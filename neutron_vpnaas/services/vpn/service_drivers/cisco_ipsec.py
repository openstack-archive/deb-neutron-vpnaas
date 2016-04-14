# Copyright 2014 Cisco Systems, Inc.  All rights reserved.
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

from neutron.common import rpc as n_rpc
from oslo_log import log as logging
import oslo_messaging

from neutron_vpnaas.db.vpn import vpn_models
from neutron_vpnaas.services.vpn.common import topics
from neutron_vpnaas.services.vpn import service_drivers
from neutron_vpnaas.services.vpn.service_drivers import base_ipsec
from neutron_vpnaas.services.vpn.service_drivers \
    import cisco_csr_db as csr_id_map
from neutron_vpnaas.services.vpn.service_drivers import cisco_validator


LOG = logging.getLogger(__name__)

IPSEC = 'ipsec'
BASE_IPSEC_VERSION = '1.0'
LIFETIME_LIMITS = {'IKE Policy': {'min': 60, 'max': 86400},
                   'IPSec Policy': {'min': 120, 'max': 2592000}}
MIN_CSR_MTU = 1500
MAX_CSR_MTU = 9192
VRF_SUFFIX_LEN = 6

T2_PORT_NAME = 't2_p:'


class CiscoCsrIPsecVpnDriverCallBack(object):

    """Handler for agent to plugin RPC messaging."""

    # history
    #   1.0 Initial version

    target = oslo_messaging.Target(version=BASE_IPSEC_VERSION)

    def __init__(self, driver):
        super(CiscoCsrIPsecVpnDriverCallBack, self).__init__()
        self.driver = driver

    def create_rpc_dispatcher(self):
        return n_rpc.PluginRpcDispatcher([self])

    def get_vpn_services_using(self, context, router_id):
        query = context.session.query(vpn_models.VPNService)
        query = query.join(vpn_models.IPsecSiteConnection)
        query = query.join(vpn_models.IKEPolicy)
        query = query.join(vpn_models.IPsecPolicy)
        query = query.join(vpn_models.IPsecPeerCidr)
        query = query.filter(vpn_models.VPNService.router_id == router_id)
        return query.all()

    def get_vpn_services_on_host(self, context, host=None):
        """Returns info on the VPN services on the host."""
        routers = self.driver.l3_plugin.get_active_routers_for_host(context,
                                                                    host)
        host_vpn_services = []
        for router in routers:
            vpn_services = self.get_vpn_services_using(context, router['id'])
            for vpn_service in vpn_services:
                host_vpn_services.append(
                    self.driver.make_vpnservice_dict(context, vpn_service,
                                                     router))
        return host_vpn_services

    def update_status(self, context, status):
        """Update status of all vpnservices."""
        plugin = self.driver.service_plugin
        plugin.update_status_by_agent(context, status)


class CiscoCsrIPsecVpnAgentApi(service_drivers.BaseIPsecVpnAgentApi):

    """API and handler for Cisco IPSec plugin to agent RPC messaging."""

    target = oslo_messaging.Target(version=BASE_IPSEC_VERSION)

    def __init__(self, topic, default_version, driver):
        super(CiscoCsrIPsecVpnAgentApi, self).__init__(
            topic, default_version, driver)

    def _agent_notification(self, context, method, router_id,
                            version=None, **kwargs):
        """Notify update for the agent.

        Find the host for the router being notified and then
        dispatches a notification for the VPN device driver.
        """
        admin_context = context if context.is_admin else context.elevated()
        if not version:
            version = self.target.version
        host = self.driver.l3_plugin.get_host_for_router(admin_context,
                                                         router_id)
        LOG.debug('Notify agent at %(topic)s.%(host)s the message '
                  '%(method)s %(args)s for router %(router)s',
                  {'topic': self.topic,
                   'host': host,
                   'method': method,
                   'args': kwargs,
                   'router': router_id})
        cctxt = self.client.prepare(server=host, version=version)
        cctxt.cast(context, method, **kwargs)


class CiscoCsrIPsecVPNDriver(base_ipsec.BaseIPsecVPNDriver):

    """Cisco CSR VPN Service Driver class for IPsec."""

    def __init__(self, service_plugin):
        super(CiscoCsrIPsecVPNDriver, self).__init__(
            service_plugin,
            cisco_validator.CiscoCsrVpnValidator(service_plugin))

    def create_rpc_conn(self):
        self.endpoints = [CiscoCsrIPsecVpnDriverCallBack(self)]
        self.conn = n_rpc.create_connection()
        self.conn.create_consumer(
            topics.CISCO_IPSEC_DRIVER_TOPIC, self.endpoints, fanout=False)
        self.conn.consume_in_threads()
        self.agent_rpc = CiscoCsrIPsecVpnAgentApi(
            topics.CISCO_IPSEC_AGENT_TOPIC, BASE_IPSEC_VERSION, self)

    def create_ipsec_site_connection(self, context, ipsec_site_connection):
        vpnservice = self.service_plugin._get_vpnservice(
            context, ipsec_site_connection['vpnservice_id'])
        csr_id_map.create_tunnel_mapping(context, ipsec_site_connection)
        self.agent_rpc.vpnservice_updated(context, vpnservice['router_id'],
                                          reason='ipsec-conn-create')

    def update_ipsec_site_connection(
        self, context, old_ipsec_site_connection, ipsec_site_connection):
        vpnservice = self.service_plugin._get_vpnservice(
            context, ipsec_site_connection['vpnservice_id'])
        self.agent_rpc.vpnservice_updated(
            context, vpnservice['router_id'],
            reason='ipsec-conn-update')

    def delete_ipsec_site_connection(self, context, ipsec_site_connection):
        vpnservice = self.service_plugin._get_vpnservice(
            context, ipsec_site_connection['vpnservice_id'])
        self.agent_rpc.vpnservice_updated(context, vpnservice['router_id'],
                                          reason='ipsec-conn-delete')

    def update_vpnservice(self, context, old_vpnservice, vpnservice):
        self.agent_rpc.vpnservice_updated(context, vpnservice['router_id'],
                                          reason='vpn-service-update')

    def delete_vpnservice(self, context, vpnservice):
        self.agent_rpc.vpnservice_updated(context, vpnservice['router_id'],
                                          reason='vpn-service-delete')

    def get_cisco_connection_mappings(self, conn_id, context):
        """Obtain persisted mappings for IDs related to connection."""
        tunnel_id, ike_id, ipsec_id = csr_id_map.get_tunnel_mapping_for(
            conn_id, context.session)
        return {'site_conn_id': u'Tunnel%d' % tunnel_id,
                'ike_policy_id': u'%d' % ike_id,
                'ipsec_policy_id': u'%s' % ipsec_id}

    def _create_interface(self, interface_info):
        hosting_info = interface_info['hosting_info']
        vlan = hosting_info['segmentation_id']
        # Port name "currently" is t{1,2}_p:1, as only one router per CSR,
        # but will keep a semi-generic algorithm
        port_name = hosting_info['hosting_port_name']
        name, sep, num = port_name.partition(':')
        offset = 1 if name in T2_PORT_NAME else 0
        if_num = int(num) * 2 + offset
        return 'GigabitEthernet%d.%d' % (if_num, vlan)

    def _get_router_info(self, router_info):
        hosting_device = router_info['hosting_device']
        return {'rest_mgmt_ip': hosting_device['management_ip_address'],
                'username': hosting_device['credentials']['username'],
                'password': hosting_device['credentials']['password'],
                'inner_if_name': self._create_interface(
                    router_info['_interfaces'][0]),
                'outer_if_name': self._create_interface(
                    router_info['gw_port']),
                'vrf': 'nrouter-' + router_info['id'][:VRF_SUFFIX_LEN],
                'timeout': 30}  # Hard-coded for now

    def make_vpnservice_dict(self, context, vpnservice, router_info):
        """Collect all service info, including Cisco info for IPSec conn."""
        vpnservice_dict = dict(vpnservice)
        vpnservice_dict['ipsec_conns'] = []
        vpnservice_dict['subnet'] = dict(vpnservice.subnet)
        vpnservice_dict['router_info'] = self._get_router_info(router_info)
        for ipsec_conn in vpnservice.ipsec_site_connections:
            ipsec_conn_dict = dict(ipsec_conn)
            ipsec_conn_dict['ike_policy'] = dict(ipsec_conn.ikepolicy)
            ipsec_conn_dict['ipsec_policy'] = dict(ipsec_conn.ipsecpolicy)
            ipsec_conn_dict['peer_cidrs'] = [
                peer_cidr.cidr for peer_cidr in ipsec_conn.peer_cidrs]
            ipsec_conn_dict['cisco'] = self.get_cisco_connection_mappings(
                ipsec_conn['id'], context)
            vpnservice_dict['ipsec_conns'].append(ipsec_conn_dict)
        return vpnservice_dict
