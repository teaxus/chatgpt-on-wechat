# encoding:utf-8

"""
wechat channel
"""

import os
import requests
import io
from PushHelper.push_helper import PushHelper
import time
import json
from channel.chat_channel import ChatChannel
from channel.wechat.wechat_message import *
from common.singleton import singleton
from common.log import logger
from lib import itchat
from lib.itchat.content import *
from bridge.reply import *
from bridge.context import *
from concurrent.futures import ThreadPoolExecutor
from config import conf
from common.time_check import time_checker
from common.expired_dict import ExpiredDict
from plugins import *
thread_pool = ThreadPoolExecutor(max_workers=8)

def thread_pool_callback(worker):
    worker_exception = worker.exception()
    if worker_exception:
        logger.exception("Worker return exception: {}".format(worker_exception))


@itchat.msg_register(TEXT)
def handler_single_msg(msg):
    WechatChannel().handle_text(WeChatMessage(msg))
    return None

@itchat.msg_register(TEXT, isGroupChat=True)
def handler_group_msg(msg):
    WechatChannel().handle_group(WeChatMessage(msg,True))
    return None

@itchat.msg_register(VOICE)
def handler_single_voice(msg):
    WechatChannel().handle_voice(WeChatMessage(msg))
    return None
    
@itchat.msg_register(VOICE, isGroupChat=True)
def handler_group_voice(msg):
    WechatChannel().handle_group_voice(WeChatMessage(msg,True))
    return None

def _check(func):
    def wrapper(self, cmsg: ChatMessage):
        msgId = cmsg.msg_id
        if msgId in self.receivedMsgs:
            logger.info("Wechat message {} already received, ignore".format(msgId))
            return
        self.receivedMsgs[msgId] = cmsg
        create_time = cmsg.create_time            # 消息时间戳
        if conf().get('hot_reload') == True and int(create_time) < int(time.time()) - 60:  # 跳过1分钟前的历史消息
            logger.debug("[WX]history message {} skipped".format(msgId))
            return
        return func(self, cmsg)
    return wrapper

@singleton
class WechatChannel(ChatChannel):
    def __init__(self):
        self.is_login = False

    def lc(self):
        print('login')
        self.is_login = True

    def ec(self):
        PushHelper().pushMsg("ChatGPT WX Logout")
        print('exit')

    def startup(self):
        # login by scan QRCode
        itchat.auto_login(enableCmdQR=2,loginCallback=self.lc, exitCallback=self.ec)
        super().__init__()
        self.receivedMsgs = ExpiredDict(60*60*24) 

        itchat.instance.receivingRetryCount = 600  # 修改断线超时时间
        # login by scan QRCode
        hotReload = conf().get('hot_reload', False)
        try:
            itchat.auto_login(enableCmdQR=2, hotReload=hotReload)
        except Exception as e:
            if hotReload:
                logger.error("Hot reload failed, try to login without hot reload")
                itchat.logout()
                os.remove("itchat.pkl")
                itchat.auto_login(enableCmdQR=2, hotReload=hotReload)
            else:
                raise e
        self.user_id = itchat.instance.storageClass.userName
        self.name = itchat.instance.storageClass.nickName
        logger.info("Wechat login success, user_id: {}, nickname: {}".format(self.user_id, self.name))
        # start message listener
        itchat.run()

    # handle_* 系列函数处理收到的消息后构造Context，然后传入_handle函数中处理Context和发送回复
    # Context包含了消息的所有信息，包括以下属性
    #   type 消息类型, 包括TEXT、VOICE、IMAGE_CREATE
    #   content 消息内容，如果是TEXT类型，content就是文本内容，如果是VOICE类型，content就是语音文件名，如果是IMAGE_CREATE类型，content就是图片生成命令
    #   kwargs 附加参数字典，包含以下的key：
    #        session_id: 会话id
    #        isgroup: 是否是群聊
    #        receiver: 需要回复的对象
    #        msg: ChatMessage消息对象
    #        origin_ctype: 原始消息类型，语音转文字后，私聊时如果匹配前缀失败，会根据初始消息是否是语音来放宽触发规则
    #        desire_rtype: 希望回复类型，默认是文本回复，设置为ReplyType.VOICE是语音回复

    @time_checker
    @_check
    def handle_voice(self, cmsg : ChatMessage):
        if conf().get('speech_recognition') != True:
            return
        logger.debug("[WX]receive voice msg: {}".format(cmsg.content))
        context = self._compose_context(ContextType.VOICE, cmsg.content, isgroup=False, msg=cmsg)
        if context:
            thread_pool.submit(self._handle, context).add_done_callback(thread_pool_callback)

    @time_checker
    @_check
    def handle_text(self, cmsg : ChatMessage):
        logger.debug("[WX]receive text msg: {}, cmsg={}".format(json.dumps(cmsg._rawmsg, ensure_ascii=False), cmsg))
        context = self._compose_context(ContextType.TEXT, cmsg.content, isgroup=False, msg=cmsg)
        if context:
            thread_pool.submit(self._handle, context).add_done_callback(thread_pool_callback)

    @time_checker
    @_check
    def handle_group(self, cmsg : ChatMessage):
        logger.debug("[WX]receive group msg: {}, cmsg={}".format(json.dumps(cmsg._rawmsg, ensure_ascii=False), cmsg))
        context = self._compose_context(ContextType.TEXT, cmsg.content, isgroup=True, msg=cmsg)
        if context:
            thread_pool.submit(self._handle, context).add_done_callback(thread_pool_callback)
    
    @time_checker
    @_check
    def handle_group_voice(self, cmsg : ChatMessage):
        if conf().get('group_speech_recognition', False) != True:
            return
        logger.debug("[WX]receive voice for group msg: {}".format(cmsg.content))
        context = self._compose_context(ContextType.VOICE, cmsg.content, isgroup=True, msg=cmsg)
        if context:
            thread_pool.submit(self._handle, context).add_done_callback(thread_pool_callback)
    
    # 统一的发送函数，每个Channel自行实现，根据reply的type字段发送不同类型的消息
    def send(self, reply: Reply, context: Context):
        receiver = context["receiver"]
        if reply.type == ReplyType.TEXT:
            itchat.send(reply.content, toUserName=receiver)
            logger.info('[WX] sendMsg={}, receiver={}'.format(reply, receiver))
        elif reply.type == ReplyType.ERROR or reply.type == ReplyType.INFO:
            itchat.send(reply.content, toUserName=receiver)
            logger.info('[WX] sendMsg={}, receiver={}'.format(reply, receiver))
        elif reply.type == ReplyType.VOICE:
            itchat.send_file(reply.content, toUserName=receiver)
            logger.info('[WX] sendFile={}, receiver={}'.format(reply.content, receiver))
        elif reply.type == ReplyType.IMAGE_URL: # 从网络下载图片
            img_url = reply.content
            pic_res = requests.get(img_url, stream=True)
            image_storage = io.BytesIO()
            for block in pic_res.iter_content(1024):
                image_storage.write(block)
            image_storage.seek(0)
            itchat.send_image(image_storage, toUserName=receiver)
            logger.info('[WX] sendImage url={}, receiver={}'.format(img_url,receiver))
        elif reply.type == ReplyType.IMAGE: # 从文件读取图片
            image_storage = reply.content
            image_storage.seek(0)
            itchat.send_image(image_storage, toUserName=receiver)
            logger.info('[WX] sendImage, receiver={}'.format(receiver))

    def _do_send_group(self, query, msg):
        if not query:
            return
        context = dict()
        context['from_user_id'] = msg['ActualUserName']
        reply_text = super().build_reply_content(query, context)
        if reply_text:
            reply_text = '@' + msg['ActualNickName'] + ' ' + reply_text.strip()
            self.send(conf().get("group_chat_reply_prefix", "") + reply_text, msg['User']['UserName'])


    def check_prefix(self, content, prefix_list):
        for prefix in prefix_list:
            if content.startswith(prefix):
                return prefix
        return None

    def getGroupNameByGroupID(self, grounName):
        return itchat.search_chatrooms(name=grounName)[0]["UserName"]
    def sendGrounpMsg(self, msg, groupID):
        self.send(msg, groupID)

    def check_contain(self, content, keyword_list):
        if not keyword_list:
            return None
        for ky in keyword_list:
            if content.find(ky) != -1:
                return True
        return None
