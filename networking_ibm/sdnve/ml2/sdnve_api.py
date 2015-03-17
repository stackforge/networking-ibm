# Copyright 2015 IBM Corp.
#
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#

import contextlib
import httplib
import urllib

import httplib2
from neutron.api.v2 import attributes
from neutron.common import constants
from neutron.openstack.common import lockutils
import neutron.wsgi as wsgi
from oslo.config import cfg
from oslo_log import log as logging

LOG = logging.getLogger(__name__)

SDNVE_VERSION = '2.0'
SDNVE_ACTION_PREFIX = '/sdnve'
SDNVE_RETRIES = 0
SDNVE_RETRIY_INTERVAL = 1
SDNVE_TENANT_TYPE_OVERLAY = u'DOVE'
SDNVE_URL = 'https://%s:%s%s'


class RequestHandler(object):
    '''Handles processeing requests to and responses from controller.'''

    def __init__(self, controller_ips=None, port=None, ssl=None,
                 base_url=None, userid=None, password=None,
                 timeout=10, formats=None):
        '''Initializes the RequestHandler for communication with controller

        Following keyword arguments are used; if not specified, default
        values are used.
        :param port: Username for authentication.
        :param timeout: Time out for http requests.
        :param userid: User id for accessing controller.
        :param password: Password for accessing the controlelr.
        :param base_url: The base url for the controller.
        :param controller_ips: List of controller IP addresses.
        :param formats: Supported formats.
        '''
        self.port = port or cfg.CONF.SDNVE.port
        self.timeout = timeout
        self._s_meta = None
        self.connection = None
        self.httpclient = httplib2.Http(
            disable_ssl_certificate_validation=True)
        self.cookie = None

        userid = userid or cfg.CONF.SDNVE.userid
        password = password or cfg.CONF.SDNVE.password
        if (userid and password):
            self.httpclient.add_credentials(userid, password)

        self.base_url = base_url or cfg.CONF.SDNVE.base_url
        self.controller_ips = controller_ips or cfg.CONF.SDNVE.controller_ips

        LOG.info(_("The IP addr of available SDN-VE controllers: %s"),
                 self.controller_ips)
        self.controller_ip = self.controller_ips[0]
        LOG.info(_("The SDN-VE controller IP address: %s"),
                 self.controller_ip)

        self.new_controller = False
        self.format = formats or cfg.CONF.SDNVE.format

        self.version = SDNVE_VERSION
        self.action_prefix = SDNVE_ACTION_PREFIX
        self.retries = SDNVE_RETRIES
        self.retry_interval = SDNVE_RETRIY_INTERVAL

    def serialize(self, data):
        '''Serializes a dictionary with a single key.'''

        if isinstance(data, dict):
            return wsgi.Serializer().serialize(data, self.content_type())
        elif data:
            raise TypeError(_("unable to serialize object type: '%s'") %
                            type(data))

    def deserialize(self, data, status_code):
        '''Deserializes an xml or json string into a dictionary.'''

        # NOTE(mb): Temporary fix for backend controller requirement
        data = data.replace("router_external", "router:external")

        if status_code == httplib.NO_CONTENT:
            return data
        try:
            deserialized_data = wsgi.Serializer(
                metadata=self._s_meta).deserialize(data, self.content_type())
            deserialized_data = deserialized_data['body']
        except Exception:
            deserialized_data = data

        return deserialized_data

    def content_type(self, format=None):
        '''Returns the mime-type for either 'xml' or 'json'.'''

        return 'application/%s' % (format or self.format)

    def delete(self, url, body=None, headers=None, params=None):
        return self.do_request("DELETE", url, body=body,
                               headers=headers, params=params)

    def get(self, url, body=None, headers=None, params=None):
        return self.do_request("GET", url, body=body,
                               headers=headers, params=params)

    def post(self, url, body=None, headers=None, params=None):
        return self.do_request("POST", url, body=body,
                               headers=headers, params=params)

    def put(self, url, body=None, headers=None, params=None):
        return self.do_request("PUT", url, body=body,
                               headers=headers, params=params)

    def do_request(self, method, url, body=None, headers=None,
                   params=None, connection_type=None):

        status_code = -1
        replybody_deserialized = ''

        if body:
            body = self.serialize(body)

        self.headers = headers or {'Content-Type': self.content_type()}
        if self.cookie:
            self.headers['cookie'] = self.cookie

        if self.controller_ip != self.controller_ips[0]:
            controllers = [self.controller_ip]
        else:
            controllers = []
        controllers.extend(self.controller_ips)

        for controller_ip in controllers:
            serverurl = SDNVE_URL % (controller_ip, self.port, self.base_url)
            myurl = serverurl + url
            if params and isinstance(params, dict):
                myurl += '?' + urllib.urlencode(params, doseq=1)

            try:
                # take a lock to prevent multiple simultaneous eventlet reads
                # leading to the request failure
                with contextlib.nested(lockutils.lock('dmc-access')):
                    LOG.info(_("Sending request to SDN-VE. url: "
                               "%(myurl)s method: %(method)s body: "
                               "%(body)s header: %(header)s "),
                             {'myurl': myurl, 'method': method,
                              'body': body, 'header': self.headers})
                    resp, replybody = self.httpclient.request(
                        myurl, method=method, body=body, headers=self.headers)
                    LOG.info(("Response recd from SDN-VE. resp: %(resp)s"
                              "body: %(body)s"),
                             {'resp': resp.status, 'body': replybody})
                    status_code = resp.status

            except Exception as e:
                LOG.error(_("Error: Could not reach server: %(url)s "
                            "Exception: %(excp)s."),
                          {'url': myurl, 'excp': e})
                self.cookie = None
                continue

            if status_code not in constants.HTTP_ACCEPTABLE:
                LOG.debug(_("Error message: %(reply)s --  Status: %(status)s"),
                          {'reply': replybody, 'status': status_code})
            else:
                LOG.debug(_("Received response status: %s"), status_code)

            if resp.get('set-cookie'):
                self.cookie = resp['set-cookie']
            replybody_deserialized = self.deserialize(
                replybody,
                status_code)
            LOG.debug(_("Deserialized body: %s"), replybody_deserialized)
            if controller_ip != self.controller_ip:
                # bcast the change of controller
                self.new_controller = True
                self.controller_ip = controller_ip

            return (status_code, replybody_deserialized)

        return (httplib.REQUEST_TIMEOUT, 'Could not reach server(s)')


class Client(RequestHandler):
    '''Client for SDNVE controller.'''

    def __init__(self):
        '''Initialize a new SDNVE client.'''
        super(Client, self).__init__()

    resource_path = {
        'network': "networks",
        'subnet': "subnets",
        'port': "ports",
        'router': "routers",
        'floatingip': "floatingips",
    }

    def process_request(self, body):
        '''Processes requests according to requirements of controller.'''
        if self.format == 'json':
            body = dict(
                (k.replace(':', '_'), v) for k, v in body.items()
                if attributes.is_attr_set(v))
        return body

    def sdnve_list(self, resource, **params):
        '''Fetches a list of resources.'''

        res = self.resource_path.get(resource, None)
        if not res:
            LOG.info(_("Bad resource for forming a list request"))
            return 0, ''

        return self.get(res, params=params)

    def sdnve_show(self, resource, specific, **params):
        '''Fetches information of a certain resource.'''

        res = self.resource_path.get(resource, None)
        if not res:
            LOG.info(_("Bad resource for forming a show request"))
            return 0, ''

        return self.get(res + "/" + specific, params=params)

    def sdnve_create(self, resource, body):
        '''Creates a new resource.'''

        res = self.resource_path.get(resource, None)
        if not res:
            LOG.info(_("Bad resource for forming a create request"))
            return 0, ''

        body = self.process_request(body)
        status, data = self.post(res, body=body)
        return (status, data)

    def sdnve_update(self, resource, specific, body=None):
        '''Updates a resource.'''

        res = self.resource_path.get(resource, None)
        if not res:
            LOG.info(_("Bad resource for forming a update request"))
            return 0, ''

        body = self.process_request(body)
        return self.put(res + "/" + specific, body=body)

    def sdnve_delete(self, resource, specific):
        '''Deletes the specified resource.'''

        res = self.resource_path.get(resource, None)
        if not res:
            LOG.info(_("Bad resource for forming a delete request"))
            return 0, ''

        return self.delete(res + "/" + specific)

    def _tenant_id_conversion(self, osid):
        return osid

    def sdnve_get_tenant_byid(self, os_tenant_id):
        sdnve_tenant_id = self._tenant_id_conversion(os_tenant_id)
        resp, content = self.sdnve_show('tenant', sdnve_tenant_id)
        if resp in constants.HTTP_ACCEPTABLE:
            tenant_id = content.get('id')
            tenant_type = content.get('network_type')
            if tenant_type == SDNVE_TENANT_TYPE_OVERLAY:
                tenant_type = constants.TENANT_TYPE_OVERLAY
            return tenant_id, tenant_type
        return None, None

    def sdnve_get_controller(self):
        if self.new_controller:
            self.new_controller = False
            return self.controller_ip

    def _process_update(self, request, current):
        new_request = dict(
            (k, v) for k, v in request.items()
            if v != current.get(k))

        msg = _("Original SDN-VE HTTP request: %(orig)s; New request: %(new)s")
        LOG.debug(msg, {'orig': request, 'new': new_request})
        return new_request
