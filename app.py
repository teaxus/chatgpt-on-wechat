# encoding:utf-8

import config
from config import conf, load_config
from channel import channel_factory
from common.log import logger
from urllib import request, parse
from channel import channel_factory
import time
import threading
import schedule
from bridge.bridge import Bridge
from bridge.context import *

from PushHelper.push_helper import PushHelper
from plugins import *

def run():
    try:
        # load config
        load_config()
        # create channel
        channel_name=conf().get('channel_type', 'wx')
        channel = channel_factory.create_channel(channel_name)
        if channel_name in ['wx','wxy']:
            PluginManager().load_plugins()

        # 建立定时任务
        def job(make_statement):
            if channel.is_login:
                groupID = channel.getGroupNameByGroupID(make_statement["group_title"])
                context = Context()
                context.type = ContextType.TEXT
                context['session_id'] = groupID
                context['receiver'] = groupID
                context.content = make_statement["make_statement"]
                msg = Bridge().fetch_reply_content(context.content, context)
                msg.content = make_statement["at_who"] + " " + msg.content
                channel.sendGrounpMsg(msg, context)
            else:
                PushHelper().pushMsg("未登录定时任务异常")

        def scheduleTask():
            while True:
                schedule.run_pending()
                time.sleep(1)

        arrSchedult = conf().get("schedule")
        for schedult_item in arrSchedult:
            if schedult_item["repet"]:
                schedule.every().day.at(schedult_item["time"]).do(job, schedult_item)
                # schedule.every(10).seconds.do(job, schedult_item)
        threading.Thread(target=scheduleTask).start()

        # startup channel
        channel.startup()
    except Exception as e:
        logger.error("App startup failed!")
        logger.exception(e)

if __name__ == '__main__':
    run()