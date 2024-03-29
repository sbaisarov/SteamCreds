import requests
import re
import time
import json
import logging

class OnlineSimError(Exception): pass
class SmsActivateError(Exception): pass


logger = logging.getLogger('__main__')


class OnlineSimApi:

    COUNTRIES = {
        "Россия": "7",
        "Китай": "86",
        "Нигерия": "234",
        "Кот д'ивуар": "225",
        "Украина": "380",
        "Казахстан": "77",
        "Египет": "20"
    }

    def __init__(self, api_key, host):
        self.api_key = api_key
        if not host:
            host = "onlinesim.ru"
        else:
            host = re.search(r"(?:https?://)?(.+)/?", host).group(1).rstrip("/")
        self.base_url = "http://" + host + "/%s"
        self.number_country = self.COUNTRIES

    def _request_new_number(self, country):
        url = self.base_url % 'api/getNum.php'
        data = {
            'service': 'Steam',
            'apikey': self.api_key,
            'form': '1',
            'country': country
        }
        resp = self._send_request(url, data)
        while True:
            try:
                tzid = resp['tzid']
                break
            except KeyError:
                raise OnlineSimError("Ошибка от сервиса sim %s" % resp['response'])
        return tzid

    def get_number(self, country='7'):
        tzid = self._request_new_number(country)
        url = self.base_url % 'api/getState.php'
        data = {'message_to_code': 1, 'tzid': tzid, 'apikey': self.api_key}
        while True:
            resp = self._send_request(url, data)
            try:
                return tzid, resp[0]['number']
            except (KeyError, IndexError):
                if resp[0]['response'] == 'TZ_INPOOL':
                    time.sleep(3)
                    continue
                raise OnlineSimError(resp['response'])

    def get_sms_code(self, tzid):
        url = self.base_url % 'api/getState.php'
        data = {'message_to_code': 1, 'tzid': tzid, 'apikey': self.api_key}
        resp = self._send_request(url, data)
        try:
            sms_code = resp[0].get('msg', None)
            time_left = resp[0].get('time', None)
        except IndexError:
            raise OnlineSimError(resp.text)
        if not time_left:
            raise OnlineSimError(resp[0])
        return sms_code, time_left

    def set_operation_ok(self, tzid, time_start):
        now = int(time.time())
        if now - time_start < 125:
            time.sleep(125 - (now - time_start))
        url = self.base_url % 'api/setOperationOk.php'
        data = {'tzid': tzid, 'apikey': self.api_key}
        self._send_request(url, data)

    def request_repeated_number_usage(self, tzid):
        url = self.base_url % 'api/setOperationRevise.php'
        data = {'tzid': tzid, 'apikey': self.api_key}
        self._send_request(url, data)

    def get_balance(self):
        url = self.base_url % 'api/getBalance.php'
        data = {'apikey': self.api_key}
        resp = self._send_request(url, data)
        try:
            return resp["balance"]
        except KeyError:
            raise OnlineSimError(resp["response"])

    @staticmethod
    def _send_request(url, data):
        while True:
            try:
                resp = requests.post(url, data=data, timeout=5)
                resp = resp.json()
                break
            except json.decoder.JSONDecodeError:
                logger.error('Сработала CloudFlare защита: %s. Код ошибки: %s', url, resp.status_code)
                time.sleep(3)
            except requests.exceptions.Timeout:
                logger.error('Не удалось получить ответ от: %s', url)

        logger.info(resp)
        return resp


class SmsActivateApi:

    countries = "0 - Россия, 1 - Украина, 2 - Казахстан, 3 - Китай, 4 - Филиппины, 5 - Мьянма, " \
        "6 - Индонезия, 7 - Малайзия, 8 - Кения, 9 - Танзания, 10 - Вьетнам, 11 - Кыргызстан," \
        " 12 - США, 13 - Израиль, 14 - Гонконг, 15 - Польша, 16 - Великобритания, " \
        "17 - Мадагаскар, 18 - Конго, 19 - Нигерия, 20 - Макао, 21 - Египет, 23 - Ирландия, " \
        "24 - Камбоджа"

    def __init__(self, api_key, host):
        self.api_key = api_key
        if not host:
            host = "sms-activate.ru"
        else:
            host = re.search(r"(?:https?://)?(.+)/?", host).group(1).rstrip("/")
        self.base_url = "http://" + host + "/stubs/handler_api.php"
        
        string_handler = {}
        for item in self.countries.split(", "):
            value, delimiter, country = item.partition(" - ")
            string_handler[country] = value
        self.number_country = string_handler

    def get_number_status(self):
        """Get number of numbers available"""
        resp = requests.get(self.base_url, params={'api_key': self.api_key,
                                                   'action': 'getNumbersStatus'}, timeout=10)
        if 'BAD_KEY' in resp.text:
            raise SmsActivateError('Неверный API ключ')

        if not resp.json()['ot_0']:
            raise SmsActivateError('Закончились номера')

    def get_balance(self):
        resp = requests.get(self.base_url, params={'api_key': self.api_key,
                                                   'action': 'getBalance'}, timeout=10)
        logger.info(resp.text)
        if float(resp.text.partition(':')[2]) < 2:
            raise SmsActivateError('Недостаточно баланса для заказа номера')
        return resp.text

    def get_number(self, country='0'):
        resp = requests.get(self.base_url, params={'api_key': self.api_key,
                                                   'action': 'getNumber',
                                                   'service': 'mt',
                                                   'operator': 'any',
                                                   'country': country}, timeout=10)
        logger.info('Ответ от sms-activate на запрос получить новый номер: ' + resp.text)
        if "ACCESS_NUMBER" not in resp.text:
            raise SmsActivateError(resp.text)

        id, number = resp.text.split(':')[1:]
        number = '+' + number
        return id, number

    def set_operation_ok(self, id, time_start):
        self._set_status(id, 8)

    def request_repeated_number_usage(self, id):
        self._set_status(id, 3)

    def _set_status(self, id, status):
        """
        :param id: activation id
        :param status: 1 - number is ready, 3 - request number again, 6 - complete activation
        :return: None
        """
        set_status_params = {'api_key': self.api_key, 'action': 'setStatus', 'id': id, 'status': status}
        resp = requests.get(self.base_url, params=set_status_params, timeout=10)
        logger.info('Ответ от sms-activate на запрос установить статус: ' + resp.text)

    def get_sms_code(self, id):
        resp = requests.get(self.base_url, params={'api_key': self.api_key,
                                                   'action': 'getStatus',
                                                   'id': id}, timeout=10)
        logger.info('Ответ от sms-activate на запрос получить статус: ' + resp.text)
        try:
            status, delimeter, smscode_msg = resp.text.partition(':')
            sms_code = re.search(r'\d+', smscode_msg).group()
        except AttributeError:
            sms_code = ''

        return sms_code, None
        