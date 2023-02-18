from config import conf
from urllib import request, parse


class PushHelper(object):
    def __init__(self):
        pass

    def pushMsg(self, msg):
        if conf().get('pushToken'):
            data = parse.urlencode({ 'text': msg }).encode()
            req = request.Request("https://api.chanify.net/v1/sender/" + conf().get('pushToken'), data=data)
            request.urlopen(req)