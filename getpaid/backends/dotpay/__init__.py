import datetime
from decimal import Decimal
import hashlib
import logging
import urllib
import urllib2
from xml.dom.minidom import parseString, Node
from django.template.base import Template
from django.template.context import Context
from django.utils.timezone import utc
from django.utils.translation import ugettext_lazy as _
import time
from getpaid.backends import PaymentProcessorBase
from getpaid.backends.payu.tasks import get_payment_status_task

logger = logging.getLogger('getpaid.backends.dotpay')


class DotpayTransactionStatus:
    NEW = 1
    CANCELED = 2
    REJECTED = 3
    STARTED = 4
    AWAITING = 5
    REJECTED_AFTER_CANCEL = 7
    FINISHED = 99
    ERROR = 888

class PaymentProcessor(PaymentProcessorBase):
    BACKEND = 'getpaid.backends.dotpay'
    BACKEND_NAME = _('Dotpay')
    BACKEND_ACCEPTED_CURRENCY = ('PLN', 'EUR', 'USD', 'GBP', 'JPY', 'CZK', 'SEK' )

    _GATEWAY_URL = 'https://ssl.dotpay.eu/'
#
#    _REQUEST_SIG_FIELDS = ('pos_id', 'pay_type', 'session_id', 'pos_auth_key',
#                           'amount', 'desc', 'desc2', 'trsDesc', 'order_id', 'first_name', 'last_name',
#                           'payback_login', 'street', 'street_hn', 'street_an', 'city', 'post_code',
#                           'country', 'email', 'phone', 'language', 'client_ip', 'ts' )
#    _ONLINE_SIG_FIELDS = ('pos_id', 'session_id', 'ts',)
#    _GET_SIG_FIELDS =  ('pos_id', 'session_id', 'ts',)
#    _GET_RESPONSE_SIG_FIELDS =  ('pos_id', 'session_id', 'order_id', 'status', 'amount', 'desc', 'ts',)

#    @staticmethod
#    def compute_sig(params, fields, key):
#        text = ''
#        for field in fields:
#            text += unicode(params.get(field, '')).encode('utf-8')
#        text += key
#        return hashlib.md5(text).hexdigest()

#    @staticmethod
#    def online(pos_id, session_id, ts, sig):
#        params = {'pos_id' : pos_id, 'session_id': session_id, 'ts': ts, 'sig': sig}
#
#
#        key2 = PaymentProcessor.get_backend_setting('key2')
#        if sig != PaymentProcessor.compute_sig(params, PaymentProcessor._ONLINE_SIG_FIELDS, key2):
#            logger.warning('Got message with wrong sig, %s' % str(params))
#            return 'SIG ERR'
#
#        try:
#            params['pos_id'] = int(params['pos_id'])
#        except ValueError:
#            return 'POS_ID ERR'
#        if params['pos_id'] != int(PaymentProcessor.get_backend_setting('pos_id')):
#            return 'POS_ID ERR'
#
#        try:
#            payment_id , session = session_id.split(':')
#        except ValueError:
#            logger.warning('Got message with wrong session_id, %s' % str(params))
#            return 'SESSION_ID ERR'
#
#        get_payment_status_task.delay(payment_id, session_id)
#        return 'OK'

    def get_gateway_url(self, request):
        """
        Routes a payment to Gateway, should return URL for redirection.

        """
        params = {'pos_id': PaymentProcessor.get_backend_setting('pos_id'),
                  'pos_auth_key': PaymentProcessor.get_backend_setting('pos_auth_key'),
                  'desc': PaymentProcessor.get_backend_setting('description', '')}
        if not params['desc']:
            params['desc'] = unicode(self.payment.order)
        else:
            params['desc'] = Template(params['desc']).render(Context({"payment": self.payment, "order": self.payment.order}))

        key1 = PaymentProcessor.get_backend_setting('key1')

        signing = PaymentProcessor.get_backend_setting('signing', True)
        testing = PaymentProcessor.get_backend_setting('testing', False)

        if testing:
            # Switch to testing mode, where payment method is set to "test payment"->"t"
            # Warning: testing mode need to be enabled also in payu.pl system for this POS
            params['pay_type'] = 't'

        # Here we put payment.pk as we can get order through payment model
        params['order_id'] = self.payment.pk

        # amount is number of Grosz, not PLN
        params['amount'] = int(self.payment.amount * 100)

        params['session_id'] = "%d:%s" % (self.payment.pk, str(time.time()))

        #Warning: please make sure that this header actually has client IP
        #         rather then web server proxy IP in your WSGI environment
        params['client_ip'] = request.META['REMOTE_ADDR']


        if signing:
            params['ts'] = time.time()
            params['sig'] = PaymentProcessor.compute_sig(params, self._REQUEST_SIG_FIELDS, key1)

        for key in params.keys():
            params[key] = unicode(params[key]).encode('utf-8')

        gateway_url = self._GATEWAY_URL + 'UTF/NewPayment?' + urllib.urlencode(params)
        return gateway_url

#    def get_payment_status(self, session_id):
#        params = {'pos_id': PaymentProcessor.get_backend_setting('pos_id'), 'session_id': session_id, 'ts': time.time()}
#        key1 = PaymentProcessor.get_backend_setting('key1')
#        key2 = PaymentProcessor.get_backend_setting('key2')
#
#        params['sig'] = PaymentProcessor.compute_sig(params, self._GET_SIG_FIELDS, key1)
#
#        for key in params.keys():
#            params[key] = unicode(params[key]).encode('utf-8')
#
#        data = urllib.urlencode(params)
#        url = self._GATEWAY_URL + 'UTF/Payment/get/xml'
#        request = urllib2.Request(url, data)
#        response = urllib2.urlopen(request)
#        xml_response = response.read()
#        xml_dom = parseString(xml_response)
#        tag_response = xml_dom.getElementsByTagName('trans')[0]
#        response_params={}
#        for tag in tag_response.childNodes:
#            if tag.nodeType == Node.ELEMENT_NODE:
#                response_params[tag.nodeName] = reduce(lambda x,y: x + y.nodeValue, tag.childNodes, u"")
#        if PaymentProcessor.compute_sig(response_params, self._GET_RESPONSE_SIG_FIELDS, key2) == response_params['sig']:
#
#            if not (int(response_params['pos_id']) == params['pos_id'] or int(response_params['order_id']) == self.payment.pk):
#                logger.error('Wrong pos_id and/or payment for Payment/get response data %s' % str(response_params))
#                return
#
#            status = int(response_params['status'])
#            if status == PayUTransactionStatus.FINISHED:
#                self.payment.amount_paid = Decimal(response_params['amount']) / Decimal('100')
#                self.payment.paid_on = datetime.datetime.utcnow().replace(tzinfo=utc)
#                if Decimal(response_params['amount']) / Decimal('100') >= self.payment.amount:
#                    self.payment.change_status('paid')
#                else:
#                    self.payment.change_status('partially_paid')
#            elif status in (    PayUTransactionStatus.CANCELED,
#                                PayUTransactionStatus.ERROR,
#                                PayUTransactionStatus.REJECTED,
#                                PayUTransactionStatus.REJECTED_AFTER_CANCEL):
#                self.payment.change_status('failed')
#
#
#        else:
#            logger.error('Wrong signature for Payment/get response data %s' % str(response_params))