# Copyright 2014 IBM Corp.
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
# @author: Mohammad Banikazemi, IBM Corp.

from ibmsdnve.common import constants
from neutron.openstack.common import log as logging

LOG = logging.getLogger(__name__)

HTTP_OK = 200


class FakeClient():

    '''Fake Client for SDNVE controller.'''

    def __init__(self, **kwargs):
        LOG.info(_('Fake SDNVE controller initialized'))

    def process_request(self, body):
        '''Processes requests according to requirements of controller.'''
        if self.format == 'json':
            body = dict(
                (k.replace(':', '_'), v) for k, v in body.items()
                if attributes.is_attr_set(v))
        return body

    def sdnve_list(self, resource, **_params):
        LOG.info(_('Fake SDNVE controller: list'))
        return (HTTP_OK, None)

    def sdnve_show(self, resource, specific, **_params):
        LOG.info(_('Fake SDNVE controller: show'))
        return (HTTP_OK, None)

    def sdnve_create(self, resource, body):
        LOG.info(_('Fake SDNVE controller: create'))
        return (HTTP_OK, None)

    def sdnve_update(self, resource, specific, body=None):
        LOG.info(_('Fake SDNVE controller: update'))
        return (HTTP_OK, None)

    def sdnve_delete(self, resource, specific):
        LOG.info(_('Fake SDNVE controller: delete'))
        return (HTTP_OK, None)

    def _process_update(self, request, current):
        new_request = dict(
            (k, v) for k, v in request.items()
            if v != current.get(k))

        msg = _("Original SDN-VE HTTP request: %(orig)s; New request: %(new)s")
        LOG.debug(msg, {'orig': request, 'new': new_request})
        return new_request

