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

import netaddr
from neutron.common import exceptions as exc
from neutron import context as ctx
from neutron.db import models_v2
from neutron import manager
from neutron.plugins.common import constants as p_const
from neutron.plugins.ml2 import driver_api as api
from oslo.config import cfg
from oslo_log import log as logging

from networking_ibm.sdnve.common import constants
from networking_ibm.sdnve.common import exceptions as sdnve_exc
from networking_ibm.sdnve.ml2 import sdnve_api as sdnve
from networking_ibm.sdnve.ml2 import sdnve_api_fake as sdnve_fake

LOG = logging.getLogger(__name__)


class SdnveDriver(object):
    """Driver for IBM SDNVE Controller."""
    def __init__(self):
        if cfg.CONF.SDNVE.use_fake_controller:
            self.sdnve_client = sdnve_fake.FakeClient()
        else:
            self.sdnve_client = sdnve.Client()

    def _check_segment(self, segment):
        network_type = segment[api.NETWORK_TYPE]
        return network_type in [p_const.TYPE_LOCAL, p_const.TYPE_GRE,
                                p_const.TYPE_VXLAN, p_const.TYPE_FLAT]

    def _pre_create_network(self, context):
        network = context.current
        LOG.debug(_("Pre create network in progress: %r"), network)
        if not network.get('tenant_id'):
            self.handleEmptyTenant(context, network, 'network')

    def _create_network(self, context):
        network = context.current
        processed_request = {}
        processed_request['network'] = network
        LOG.debug(_("Create network in progress: %r"),
                  processed_request)
        (res, data) = self.sdnve_client.sdnve_create('network',
                                                     processed_request)

        if res not in constants.HTTP_ACCEPTABLE:
            raise sdnve_exc.SdnveException(
                msg=(_('Create net failed in SDN-VE: %s') % data))

    def _pre_update_network(self, context):
        network = context.current
        LOG.debug(_("Pre Update network in progress: %r"), network)
        sdnve_net = self.sdnve_client._process_update(
            context.current, context.original)
        self._filter_update_request(sdnve_net, 'network')

    def _update_network(self, context):
        id = context.current['id']
        LOG.debug(_("Update network in progress: %r"), id)
        processed_request = {}
        processed_request['network'] = self.sdnve_client._process_update(
            context.current, context.original)
        if processed_request['network']:
            (res, data) = self.sdnve_client.sdnve_update('network',
                                                         id,
                                                         processed_request)
            if res not in constants.HTTP_ACCEPTABLE:
                raise sdnve_exc.SdnveException(msg=(_('Update net failed '
                                                    'in SDN-VE: %s') % data))

    def _delete_network(self, context):
        id = context.current['id']
        LOG.debug(_("Delete network in progress: %s"), id)
        (res, data) = self.sdnve_client.sdnve_delete('network', id)
        if res not in constants.HTTP_ACCEPTABLE:
            LOG.error(
                _("Delete net failed after deleting the network in DB: %s"),
                data)

    def _pre_create_port(self, context):
        port = context.current
        LOG.debug(_("Pre create port in progress: %r"), context.current)
        if context._binding.host is None or context._binding.host == '':
            context._binding.host = ' '
        if not port.get('tenant_id'):
            self.handleEmptyTenant(context, port, 'port')

    def _create_port(self, context):
        port = context.current
        LOG.debug(_("Create port in progress: %r"), port)
        processed_request = {}
        processed_request['port'] = port
        (res, data) = self.sdnve_client.sdnve_create('port', processed_request)
        if res not in constants.HTTP_ACCEPTABLE:
            raise sdnve_exc.SdnveException(
                msg=(_('Create port failed in SDN-VE: %s') % data))

    def _update_port(self, context):
        port = context.current
        LOG.debug(_("Update port in progress: %r"), port)
        processed_request = {}
        update_sg = context._plugin.is_security_group_member_updated(
            context._plugin_context, context.original, context.current)
        LOG.debug(_("is sg_member_updated %s"), str(update_sg))
        # there is a bug in ml2 base driver in update_port
        # it is supposed to notify on sg member update as done below
        # but it doesnt, until  that gets fixed upstream, we have this here
        if update_sg:
            LOG.debug(_("calling sg member update on orig port"))
            context._plugin.notify_security_groups_member_updated(
                context._plugin_context, context.original)
            LOG.debug(_("calling sg member update on new port"))
            context._plugin.notify_security_groups_member_updated(
                context._plugin_context, context.current)

        processed_request['port'] = self.filter_update_port_attributes(
            self.sdnve_client._process_update(context.current,
                                              context.original))
        LOG.debug(_("Updated port request: %r"), processed_request['port'])
        if processed_request['port']:
            (res, data) = self.sdnve_client.sdnve_update(
                'port', context.current['id'], processed_request)
            if res not in constants.HTTP_ACCEPTABLE:
                raise sdnve_exc.SdnveException(
                    msg=(_('Update port failed in SDN-VE: %s') % data))

    def _pre_delete_port(self, context):
        LOG.debug(_("Pre delete port in progress: %r"), context.current)
        self._clear_floating_ip(context)

    def _delete_port(self, context):
        id = context.current['id']

        LOG.debug(_("Delete port in progress: %s"), id)
        (res, data) = self.sdnve_client.sdnve_delete('port', id)
        if res not in constants.HTTP_ACCEPTABLE:
            LOG.error(
                _("Delete port operation failed in SDN-VE "
                  "after deleting the port from DB: %s"), data)

    def _pre_create_subnet(self, context):
        subnet = context.current
        LOG.debug(_("Pre create subnet in progress: %r"), subnet)
        if not subnet.get('tenant_id'):
            self.handleEmptyTenant(context, subnet, 'subnet')

    def _create_subnet(self, context):
        subnet = context.current
        LOG.debug(_("Create subnet in progress: %r"), subnet)
        self._check_subnet_create(context, subnet)
        sdnve_subnet = subnet.copy()
        if subnet.get('gateway_ip') is None:
            sdnve_subnet['gateway_ip'] = 'null'
        processed_request = {}
        processed_request['subnet'] = sdnve_subnet
        LOG.debug(_("Create subnet in progress: %r"), processed_request)
        (res, data) = self.sdnve_client.sdnve_create('subnet',
                                                     processed_request)
        if res not in constants.HTTP_ACCEPTABLE:
            raise sdnve_exc.SdnveException(
                msg=(_('Create subnet failed in SDN-VE: %s') % data))

    def _pre_update_subnet(self, context):
        subnet = context.current
        LOG.debug(_("Pre Update subnet in progress: %r"), subnet)
        sdnve_subnet = self.sdnve_client._process_update(
            context.current, context.original)
        self._filter_update_request(sdnve_subnet, 'subnet')

    def _update_subnet(self, context):
        subnet = context.current
        LOG.debug(_("Update subnet in progress: %r"), subnet)
        processed_request = {}
        processed_request['subnet'] = self.sdnve_client._process_update(
            context.current, context.original)
        if processed_request['subnet']:
            if 'gateway_ip' in processed_request['subnet']:
                if processed_request['subnet'].get('gateway_ip') is None:
                    processed_request['subnet']['gateway_ip'] = 'null'
            (res, data) = self.sdnve_client.sdnve_update('subnet',
                                                         context.current['id'],
                                                         processed_request)
            if res not in constants.HTTP_ACCEPTABLE:
                raise sdnve_exc.SdnveException(
                    msg=(_('Update subnet failed in SDN-VE: %s') % data))

    def _delete_subnet(self, context):
        id = context.current['id']
        LOG.debug(_("Delete subnet in progress: %s"), id)
        (res, data) = self.sdnve_client.sdnve_delete('subnet', id)
        if res not in constants.HTTP_ACCEPTABLE:
            LOG.error(_("Delete subnet operation failed in SDN-VE after "
                        "deleting the subnet from DB: %s"), data)

    def check_ip_pool_overlap(self, context, subnet):
        # get all subnets,
        # for each subnet, check if ip addr pool collides with this subnet
        dbcontext = context._plugin_context
        adminctx = ctx.get_admin_context()
        new_network = context._plugin.get_network(dbcontext,
                                                  subnet["network_id"])
        new_shared_internal = new_network['shared'] and not (
            new_network['router:external'])
        new_external = new_network['router:external']
        if not new_shared_internal and not new_external:
            return False, None

        pool_qry = dbcontext.session.query(models_v2.IPAllocationPool)
        allocation_pools = pool_qry.filter_by(subnet_id=subnet['id'])
        allocations = netaddr.IPSet()
        for pool in allocation_pools:
            allocations = allocations | netaddr.IPSet(
                netaddr.IPRange(pool['first_ip'], pool['last_ip']))

        subnets = context._plugin._get_all_subnets(dbcontext)

        for sub in subnets:
            network = context._plugin.get_network(adminctx, sub["network_id"])
            if network["id"] == new_network["id"]:
                continue
            old_shared_internal = network['shared'] and not (
                network['router:external'])
            old_external = network['router:external']
            if (new_shared_internal and old_external) or (
                    new_external and old_shared_internal):
                pool_qry = dbcontext.session.query(models_v2.IPAllocationPool)
                for pool in pool_qry.filter_by(subnet_id=sub['id']):
                    # Create a set of all addresses in the pool
                    poolset = netaddr.IPSet(netaddr.iter_iprange(
                        pool['first_ip'], pool['last_ip']))
                    # Use set difference for overlap
                    diff = allocations & poolset
                    if len(diff):
                        LOG.info("external subnet %s pool "
                                 "overlap with %s", subnet)
                        return (True, sub["id"])
        return (False, None)

    def _check_subnet_create(self, context, subnet):
        # check allocation pool overlaps
        ret, subid = self.check_ip_pool_overlap(context, subnet)
        if ret:
            raise sdnve_exc.SdnveException(
                msg=(_('Create subnet failed in SDN-VE, '
                       'IP pool overlap with subnet %s') % subid))
        # check cidr overlaps
        ret, subid = self.check_subnet_cidr_overlap(context, subnet)
        if ret:
            raise sdnve_exc.SdnveException(
                msg=(_('Create subnet failed in SDN-VE, '
                       'CIDR overlap with subnet %s') % subid))

    def check_subnet_cidr_overlap(self, context, subnet):
        # get all subnets,
        # for each subnet, check if cidr collides
        dbcontext = context._plugin_context
        adminctx = ctx.get_admin_context()

        new_network = context._plugin.get_network(dbcontext,
                                                  subnet["network_id"])
        new_subnet_ipset = netaddr.IPSet([subnet['cidr']])
        subnet_list = context._plugin._get_all_subnets(adminctx)
        for sub in subnet_list:
            network = context._plugin.get_network(adminctx,
                                                  sub["network_id"])
            if network["id"] == new_network["id"]:
                continue
            if new_network['shared'] and network['shared']:
                if (netaddr.IPSet([sub.cidr]) & new_subnet_ipset):
                    # collision
                    return (True, sub["id"])
            if new_network['shared'] and not network['router:external']:
                if (netaddr.IPSet([sub.cidr]) & new_subnet_ipset):
                    # collision
                    return (True, sub["id"])
            if network['shared'] and not new_network['router:external']:
                if (netaddr.IPSet([sub.cidr]) & new_subnet_ipset):
                    # collision
                    return (True, sub["id"])
        return (False, None)

    def _filter_update_request(self, resource, type):
        restricted_values = {}
        if type == 'subnet':
            restricted_values = self.restrict_update_subnet
        elif type == 'network':
            restricted_values = self.restrict_update_network
        for key, value in resource.items():
            if key in restricted_values:
                msg = _("Update of %s is not supported "
                        "by SDNVE Controller") % key
                raise exc.InvalidInput(error_message=msg)

    def _clear_floating_ip(self, context):
        l3plugin = manager.NeutronManager.get_service_plugins().get(
            p_const.L3_ROUTER_NAT)
        if l3plugin:
            dbcontext = context._plugin_context
            floatingip_filter = {'port_id': [context.current['id']]}
            floatingip_list = l3plugin.get_floatingips(dbcontext,
                                                       floatingip_filter)
            for floatingip in floatingip_list:
                LOG.debug(_("Updating floating IP before port delete %r"),
                          floatingip)
                floatingip_id = floatingip.get('id')
                if floatingip_id:
                    (res, data) = self.sdnve_client.sdnve_update(
                        'floatingip', floatingip_id, {'floatingip': {}})
                    if res not in constants.HTTP_ACCEPTABLE:
                        LOG.error(_("Floating ip disassociate failed in "
                                    "SDN-VE : %s"), data)

    def filter_update_port_attributes(self, port):
        self.try_del(port, ['security_groups', 'status',
                            'fixed_ips', 'admin_state_up'])
        return port

    def try_del(self, d, keys):
        """Ignore key errors when deleting from a dictionary."""
        for key in keys:
            try:
                del d[key]
            except KeyError:
                pass

    def handleEmptyTenant(self, context, resource, type):
        new_tenant_id = ""
        dbcontext = context._plugin_context
        tenant_token = "HA " + type + " tenant"
        resource_name = resource.get('name')

        if type == 'port':
            network_id = resource.get('network_id')
            if network_id:
                network_info = (
                    context._plugin.get_network(dbcontext, network_id))
                if network_info.get('tenant_id'):
                    new_tenant_id = network_info.get('tenant_id')
        if not new_tenant_id:
            if resource_name and tenant_token in resource_name:
                tokens = resource_name.rpartition(" ")
                new_tenant_id = tokens[2]
        if not new_tenant_id:
            raise exc.InvalidInput(error_message="Tenant cannot be empty!")
        else:
            context.current['tenant_id'] = new_tenant_id
