# encoding:utf-8

import config
from common.log import logger
from urllib import request, parse
from channel import channel_factory

import threading
import schedule
from bridge.bridge import Bridge

if __name__ == '__main__':
    try:
        # load config
        config.load_config()

        # create channel
        channel = channel_factory.create_channel("wx")

        # 建立定时任务
        def job(make_statement):
            if channel.is_login:
                groupID = channel.getGroupNameByGroupID("xxx")
                msg = Bridge().fetch_reply_content(make_statement["make_statement"], {"from_user_id":groupID,"type":"TEXT"})
                channel.sendGrounpMsg(make_statement["at_who"] + " " +msg, groupID)

        def scheduleTask():
            while True:
                schedule.run_pending()

        arrSchedult = config.conf().get("schedule")
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
