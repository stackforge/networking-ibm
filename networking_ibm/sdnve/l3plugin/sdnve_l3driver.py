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

from oslo.config import cfg
from oslo_log import log as logging

from networking_ibm.sdnve.common import constants
from networking_ibm.sdnve.common import exceptions as sdnve_exc
from networking_ibm.sdnve.ml2 import sdnve_api as sdnve
from networking_ibm.sdnve.ml2 import sdnve_api_fake as sdnve_fake

LOG = logging.getLogger(__name__)


class SdnveL3Driver(object):
    def __init__(self):

        if cfg.CONF.SDNVE.use_fake_controller:
            self.sdnve_client = sdnve_fake.FakeClient()
        else:
            self.sdnve_client = sdnve.Client()

    def create_router(self, context, router):
        egw = router.get('external_gateway_info')
        if egw is None:
            router['external_gateway_info'] = {'network_id': ''}
        processed_request = {}
        processed_request['router'] = router
        (res, data) = self.sdnve_client.sdnve_create('router',
                                                     processed_request)
        if res not in constants.HTTP_ACCEPTABLE:
            raise sdnve_exc.SdnveException(
                msg=(_('Create router failed in SDN-VE: %s') % res))

    def update_router(self, context, id, original_router, router):
        processed_request = {}
        processed_request['router'] = self.sdnve_client._process_update(
            router['router'], original_router)
        if processed_request['router']:
            egw = processed_request['router'].get('external_gateway_info')
            if egw == {}:
                network_clear = None
                processed_request['router']['external_gateway_info'] = {
                    'network_id': network_clear}
            (res, data) = self.sdnve_client.sdnve_update(
                'router', id, processed_request)
            if res not in constants.HTTP_ACCEPTABLE:
                raise sdnve_exc.SdnveException(
                    msg=(_('Update router failed in SDN-VE: %s') % res))

    def delete_router(self, context, id):
        (res, data) = self.sdnve_client.sdnve_delete('router', id)
        if res not in constants.HTTP_ACCEPTABLE:
            LOG.error(
                _("Delete router operation failed in SDN-VE after "
                  "deleting the router in DB: %s"), res)

    def add_router_interface(self, context, router_id, interface_info):

        (res, data) = self.sdnve_client.sdnve_update(
            'router', router_id + '/add_router_interface', interface_info)
        if res not in constants.HTTP_ACCEPTABLE:
            raise sdnve_exc.SdnveException(
                msg=(_('Update router-add-interface failed in SDN-VE: %s') %
                     res))

    def _add_router_interface_only(self, context, router_id, interface_info):

        port_id = interface_info.get('port_id')
        if port_id:
            (res, data) = self.sdnve_client.sdnve_update(
                'router', router_id + '/add_router_interface', interface_info)
            if res not in constants.HTTP_ACCEPTABLE:
                LOG.error(_("_add_router_interface_only: "
                            "failed to add the interface in the roll back."
                            " of a remove_router_interface operation"))

    def remove_router_interface(self, context, router_id, interface_info):

        (res, data) = self.sdnve_client.sdnve_update(
            'router', router_id + '/remove_router_interface', interface_info)
        if res not in constants.HTTP_ACCEPTABLE:
            LOG.error(_("Update router-remove-interface"
                        " failed SDN-VE: %s"), res)

    def create_floatingip(self, context, floatingip):
        sdnve_floatingip = floatingip.copy()
        self.try_del(sdnve_floatingip, ['status', 'port_id',
                                        'router_id', 'fixed_ip_address'])
        (res, data) = self.sdnve_client.sdnve_create(
            'floatingip', {'floatingip': sdnve_floatingip})
        if res not in constants.HTTP_ACCEPTABLE:
            raise sdnve_exc.SdnveException(
                msg=(_('Creating floating ip operation failed '
                       'in SDN-VE controller: %s') % res))

    def update_floatingip(self, context, id, original_floatingip, floatingip):
        processed_request = {}
        processed_request['floatingip'] = self.sdnve_client._process_update(
            floatingip['floatingip'], original_floatingip)
        if processed_request['floatingip']:
            new_processed_request = processed_request['floatingip']
            if new_processed_request.get('port_id') is None:
                new_processed_request = {}
            elif new_processed_request.get('fixed_ip_address'):
                fip_addr = new_processed_request.get('fixed_ip_address')
                new_processed_request.pop('fixed_ip_address', fip_addr)
            (res, data) = self.sdnve_client.sdnve_update(
                'floatingip', id,
                {'floatingip': new_processed_request})
            if res not in constants.HTTP_ACCEPTABLE:
                raise sdnve_exc.SdnveException(
                    msg=(_('Update floating ip failed in SDN-VE: %s') % res))

    def delete_floatingip(self, context, id):
        (res, data) = self.sdnve_client.sdnve_delete('floatingip', id)
        if res not in constants.HTTP_ACCEPTABLE:
            raise sdnve_exc.SdnveException(
                msg=(_("Delete floatingip failed in SDN-VE: %s"), res))

    def try_del(self, d, keys):
        for key in keys:
            try:
                del d[key]
            except KeyError:
                pass
