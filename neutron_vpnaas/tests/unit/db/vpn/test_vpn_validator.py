# Copyright 2015, Cisco Systems Inc.
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

import mock
import socket

from neutron import context as n_ctx
from neutron.db import l3_db
from neutron.db import servicetype_db as st_db
from neutron.plugins.common import constants as nconstants
from neutron_lib import exceptions as nexception
from oslo_utils import uuidutils
from sqlalchemy.orm import query

from neutron_vpnaas.extensions import vpnaas
from neutron_vpnaas.services.vpn.common import constants as v_constants
from neutron_vpnaas.services.vpn import plugin as vpn_plugin
from neutron_vpnaas.services.vpn.service_drivers \
    import ipsec_validator as vpn_validator
from neutron_vpnaas.tests import base

_uuid = uuidutils.generate_uuid

FAKE_ROUTER_ID = _uuid()
FAKE_ROUTER = {l3_db.EXTERNAL_GW_INFO: FAKE_ROUTER_ID}
FAKE_SUBNET_ID = _uuid()
IPV4 = 4
IPV6 = 6

IPSEC_SERVICE_DRIVER = ('neutron_vpnaas.services.vpn.service_drivers.'
                        'ipsec.IPsecVPNDriver')


class TestValidatorSelection(base.BaseTestCase):

    def setUp(self):
        super(TestValidatorSelection, self).setUp()
        vpnaas_provider = [{
            'service_type': nconstants.VPN,
            'name': 'vpnaas',
            'driver': IPSEC_SERVICE_DRIVER,
            'default': True
        }]
        # override the default service provider
        self.service_providers = (
            mock.patch.object(st_db.ServiceTypeManager,
                              'get_service_providers').start())
        self.service_providers.return_value = vpnaas_provider
        mock.patch('neutron.common.rpc.create_connection').start()
        stm = st_db.ServiceTypeManager()
        mock.patch('neutron.db.servicetype_db.ServiceTypeManager.get_instance',
                   return_value=stm).start()
        self.vpn_plugin = vpn_plugin.VPNDriverPlugin()

    def test_reference_driver_used(self):
        self.assertIsInstance(self.vpn_plugin._get_validator(),
                              vpn_validator.IpsecVpnValidator)


class TestIPsecDriverValidation(base.BaseTestCase):

    def setUp(self):
        super(TestIPsecDriverValidation, self).setUp()
        self.l3_plugin = mock.Mock()
        mock.patch(
            'neutron.manager.NeutronManager.get_service_plugins',
            return_value={nconstants.L3_ROUTER_NAT: self.l3_plugin}).start()
        self.core_plugin = mock.Mock()
        mock.patch('neutron.manager.NeutronManager.get_plugin',
                   return_value=self.core_plugin).start()
        self.context = n_ctx.Context('some_user', 'some_tenant')
        self.service_plugin = mock.Mock()
        self.validator = vpn_validator.IpsecVpnValidator(self.service_plugin)
        self.router = mock.Mock()
        self.router.gw_port = {'fixed_ips': [{'ip_address': '10.0.0.99'}]}

    def test_non_public_router_for_vpn_service(self):
        """Failure test of service validate, when router missing ext. I/F."""
        self.l3_plugin.get_router.return_value = {}  # No external gateway
        vpnservice = {'router_id': 123, 'subnet_id': 456}
        self.assertRaises(vpnaas.RouterIsNotExternal,
                          self.validator.validate_vpnservice,
                          self.context, vpnservice)

    def test_subnet_not_connected_for_vpn_service(self):
        """Failure test of service validate, when subnet not on router."""
        self.l3_plugin.get_router.return_value = FAKE_ROUTER
        self.core_plugin.get_ports.return_value = None
        vpnservice = {'router_id': FAKE_ROUTER_ID, 'subnet_id': FAKE_SUBNET_ID}
        self.assertRaises(vpnaas.SubnetIsNotConnectedToRouter,
                          self.validator.validate_vpnservice,
                          self.context, vpnservice)

    def test_defaults_for_ipsec_site_connections_on_create(self):
        """Check that defaults are applied correctly.

        MTU has a default and will always be present on create.
        However, the DPD settings do not have a default, so
        database create method will assign default values for any
        missing. In addition, the DPD dict will be flattened
        for storage into the database, so we'll do it as part of
        assigning defaults.
        """
        ipsec_sitecon = {}
        self.validator.assign_sensible_ipsec_sitecon_defaults(ipsec_sitecon)
        expected = {
            'dpd_action': 'hold',
            'dpd_timeout': 120,
            'dpd_interval': 30
        }
        self.assertEqual(expected, ipsec_sitecon)

        ipsec_sitecon = {'dpd': {'interval': 50}}
        self.validator.assign_sensible_ipsec_sitecon_defaults(ipsec_sitecon)
        expected = {
            'dpd': {'interval': 50},
            'dpd_action': 'hold',
            'dpd_timeout': 120,
            'dpd_interval': 50
        }
        self.assertEqual(expected, ipsec_sitecon)

    def test_resolve_peer_address_with_ipaddress(self):
        ipsec_sitecon = {'peer_address': '10.0.0.9'}
        self.validator._validate_peer_address = mock.Mock()
        self.validator.resolve_peer_address(ipsec_sitecon, self.router)
        self.assertEqual('10.0.0.9', ipsec_sitecon['peer_address'])
        self.validator._validate_peer_address.assert_called_once_with(
            IPV4, self.router)

    def test_resolve_peer_address_with_fqdn(self):
        with mock.patch.object(socket, 'getaddrinfo') as mock_getaddr_info:
            mock_getaddr_info.return_value = [(2, 1, 6, '',
                                              ('10.0.0.9', 0))]
            ipsec_sitecon = {'peer_address': 'fqdn.peer.addr'}
            self.validator._validate_peer_address = mock.Mock()
            self.validator.resolve_peer_address(ipsec_sitecon, self.router)
            self.assertEqual('10.0.0.9', ipsec_sitecon['peer_address'])
            self.validator._validate_peer_address.assert_called_once_with(
                IPV4, self.router)

    def test_resolve_peer_address_with_invalid_fqdn(self):
        with mock.patch.object(socket, 'getaddrinfo') as mock_getaddr_info:
            def getaddr_info_failer(*args, **kwargs):
                raise socket.gaierror()
            mock_getaddr_info.side_effect = getaddr_info_failer
            ipsec_sitecon = {'peer_address': 'fqdn.invalid'}
            self.assertRaises(vpnaas.VPNPeerAddressNotResolved,
                              self.validator.resolve_peer_address,
                              ipsec_sitecon, self.router)

    def helper_validate_peer_address(self, fixed_ips, ip_version,
                                     expected_exception=False):
        self.router.id = FAKE_ROUTER_ID
        self.router.gw_port = {'fixed_ips': fixed_ips}
        try:
            self.validator._validate_peer_address(ip_version, self.router)
            if expected_exception:
                self.fail("No exception raised for invalid peer address")
        except vpnaas.ExternalNetworkHasNoSubnet:
            if not expected_exception:
                self.fail("exception for valid peer address raised")

    def test_validate_peer_address(self):
        # validate ipv4 peer_address with ipv4 gateway
        fixed_ips = [{'ip_address': '10.0.0.99'}]
        self.helper_validate_peer_address(fixed_ips, IPV4)

        # validate ipv6 peer_address with ipv6 gateway
        fixed_ips = [{'ip_address': '2001::1'}]
        self.helper_validate_peer_address(fixed_ips, IPV6)

        # validate ipv6 peer_address with both ipv4 and ipv6 gateways
        fixed_ips = [{'ip_address': '2001::1'}, {'ip_address': '10.0.0.99'}]
        self.helper_validate_peer_address(fixed_ips, IPV6)

        # validate ipv4 peer_address with both ipv4 and ipv6 gateways
        fixed_ips = [{'ip_address': '2001::1'}, {'ip_address': '10.0.0.99'}]
        self.helper_validate_peer_address(fixed_ips, IPV4)

        # validate ipv4 peer_address with ipv6 gateway
        fixed_ips = [{'ip_address': '2001::1'}]
        self.helper_validate_peer_address(fixed_ips, IPV4,
                                          expected_exception=True)

        # validate ipv6 peer_address with ipv4 gateway
        fixed_ips = [{'ip_address': '10.0.0.99'}]
        self.helper_validate_peer_address(fixed_ips, IPV6,
                                          expected_exception=True)

    def test_validate_ipsec_policy(self):
        ipsec_policy = {'transform_protocol': 'ah-esp'}
        self.assertRaises(vpn_validator.IpsecValidationFailure,
                          self.validator.validate_ipsec_policy,
                          self.context, ipsec_policy)

    def test_defaults_for_ipsec_site_connections_on_update(self):
        """Check that defaults are used for any values not specified."""
        ipsec_sitecon = {}
        prev_connection = {'peer_cidrs': [{'cidr': '10.0.0.0/24'},
                                          {'cidr': '20.0.0.0/24'}],
                           'local_ep_group_id': None,
                           'peer_ep_group_id': None,
                           'dpd_action': 'clear',
                           'dpd_timeout': 500,
                           'dpd_interval': 250}
        self.validator.assign_sensible_ipsec_sitecon_defaults(ipsec_sitecon,
                                                              prev_connection)
        expected = {
            'peer_cidrs': ['10.0.0.0/24', '20.0.0.0/24'],
            'local_ep_group_id': None,
            'peer_ep_group_id': None,
            'dpd_action': 'clear',
            'dpd_timeout': 500,
            'dpd_interval': 250
        }
        self.assertEqual(expected, ipsec_sitecon)

        ipsec_sitecon = {'dpd': {'timeout': 200}}
        local_epg_id = _uuid()
        peer_epg_id = _uuid()
        prev_connection = {'peer_cidrs': [],
                           'local_ep_group_id': local_epg_id,
                           'peer_ep_group_id': peer_epg_id,
                           'dpd_action': 'clear',
                           'dpd_timeout': 500,
                           'dpd_interval': 100}
        self.validator.assign_sensible_ipsec_sitecon_defaults(ipsec_sitecon,
                                                              prev_connection)
        expected = {
            'peer_cidrs': [],
            'local_ep_group_id': local_epg_id,
            'peer_ep_group_id': peer_epg_id,
            'dpd': {'timeout': 200},
            'dpd_action': 'clear',
            'dpd_timeout': 200,
            'dpd_interval': 100
        }
        self.assertEqual(expected, ipsec_sitecon)

    def test_bad_dpd_settings_on_create(self):
        """Failure tests of DPD settings for IPSec conn during create."""
        ipsec_sitecon = {'dpd_action': 'hold', 'dpd_interval': 100,
                         'dpd_timeout': 100}
        self.assertRaises(vpnaas.IPsecSiteConnectionDpdIntervalValueError,
                          self.validator._check_dpd, ipsec_sitecon)
        ipsec_sitecon = {'dpd_action': 'hold', 'dpd_interval': 100,
                         'dpd_timeout': 99}
        self.assertRaises(vpnaas.IPsecSiteConnectionDpdIntervalValueError,
                          self.validator._check_dpd, ipsec_sitecon)

    def test_bad_mtu_for_ipsec_connection(self):
        """Failure test of invalid MTU values for IPSec conn create/update."""
        ip_version_limits = vpn_validator.IpsecVpnValidator.IP_MIN_MTU
        for version, limit in ip_version_limits.items():
            ipsec_sitecon = {'mtu': limit - 1}
            self.assertRaises(
                vpnaas.IPsecSiteConnectionMtuError,
                self.validator._check_mtu,
                self.context, ipsec_sitecon['mtu'], version)

    def test_endpoints_all_cidrs_in_endpoint_group(self):
        """All endpoints in the endpoint group are valid CIDRs."""
        endpoint_group = {'type': v_constants.CIDR_ENDPOINT,
                          'endpoints': ['10.10.10.0/24', '20.20.20.0/24']}
        try:
            self.validator.validate_endpoint_group(self.context,
                                                   endpoint_group)
        except Exception:
            self.fail("All CIDRs in endpoint_group should be valid")

    def test_endpoints_all_subnets_in_endpoint_group(self):
        """All endpoints in the endpoint group are valid subnets."""
        endpoint_group = {'type': v_constants.SUBNET_ENDPOINT,
                          'endpoints': [_uuid(), _uuid()]}
        try:
            self.validator.validate_endpoint_group(self.context,
                                                   endpoint_group)
        except Exception:
            self.fail("All subnets in endpoint_group should be valid")

    def test_mixed_endpoint_types_in_endpoint_group(self):
        """Fail when mixing types of endpoints in endpoint group."""
        endpoint_group = {'type': v_constants.CIDR_ENDPOINT,
                          'endpoints': ['10.10.10.0/24', _uuid()]}
        self.assertRaises(vpnaas.InvalidEndpointInEndpointGroup,
                          self.validator.validate_endpoint_group,
                          self.context, endpoint_group)
        endpoint_group = {'type': v_constants.SUBNET_ENDPOINT,
                          'endpoints': [_uuid(), '10.10.10.0/24']}
        self.assertRaises(vpnaas.InvalidEndpointInEndpointGroup,
                          self.validator.validate_endpoint_group,
                          self.context, endpoint_group)

    def test_missing_endpoints_for_endpoint_group(self):
        endpoint_group = {'type': v_constants.CIDR_ENDPOINT,
                          'endpoints': []}
        self.assertRaises(vpnaas.MissingEndpointForEndpointGroup,
                          self.validator.validate_endpoint_group,
                          self.context, endpoint_group)

    def test_fail_bad_cidr_in_endpoint_group(self):
        """Testing catches bad CIDR.

        Just check one case, as CIDR validator used has good test coverage.
        """
        endpoint_group = {'type': v_constants.CIDR_ENDPOINT,
                          'endpoints': ['10.10.10.10/24', '20.20.20.1']}
        self.assertRaises(vpnaas.InvalidEndpointInEndpointGroup,
                          self.validator.validate_endpoint_group,
                          self.context, endpoint_group)

    def test_unknown_subnet_in_endpoint_group(self):
        subnet_id = _uuid()
        self.core_plugin.get_subnet.side_effect = nexception.SubnetNotFound(
            subnet_id=subnet_id)
        endpoint_group = {'type': v_constants.SUBNET_ENDPOINT,
                          'endpoints': [subnet_id]}
        self.assertRaises(vpnaas.NonExistingSubnetInEndpointGroup,
                          self.validator.validate_endpoint_group,
                          self.context, endpoint_group)

    def test_fail_subnets_not_on_same_router_for_endpoint_group(self):
        """Detect when local endpoints not on the same router."""
        subnet1 = {'id': _uuid(), 'ip_version': 4}
        subnet2 = {'id': _uuid(), 'ip_version': 4}
        router = _uuid()
        multiple_subnets = [subnet1, subnet2]
        port_mock = mock.patch.object(self.core_plugin, "get_ports").start()
        port_mock.side_effect = ['dummy info', None]
        self.assertRaises(vpnaas.SubnetIsNotConnectedToRouter,
                          self.validator._check_local_subnets_on_router,
                          self.context, router, multiple_subnets)

    def test_ipsec_conn_local_endpoints_same_ip_version(self):
        """Check local endpoint subnets all have same IP version."""
        endpoint_group_id = _uuid()
        subnet1 = {'ip_version': 4}
        subnet2 = {'ip_version': 4}
        single_subnet = [subnet1]
        version = self.validator._check_local_endpoint_ip_versions(
            endpoint_group_id, single_subnet)
        self.assertEqual(4, version)
        multiple_subnets = [subnet1, subnet2]
        version = self.validator._check_local_endpoint_ip_versions(
            endpoint_group_id, multiple_subnets)
        self.assertEqual(4, version)

    def test_fail_ipsec_conn_local_endpoints_mixed_ip_version(self):
        """Fail when mixed IP versions in local endpoints."""
        endpoint_group_id = _uuid()
        subnet1 = {'ip_version': 6}
        subnet2 = {'ip_version': 4}
        mixed_subnets = [subnet1, subnet2]
        self.assertRaises(vpnaas.MixedIPVersionsForIPSecEndpoints,
                          self.validator._check_local_endpoint_ip_versions,
                          endpoint_group_id, mixed_subnets)

    def test_ipsec_conn_peer_endpoints_same_ip_version(self):
        """Check all CIDRs have the same IP version."""
        endpoint_group_id = _uuid()
        one_cidr = ['2002:0a00::/48']
        version = self.validator._check_peer_endpoint_ip_versions(
            endpoint_group_id, one_cidr)
        self.assertEqual(6, version)
        multiple_cidr = ['10.10.10.0/24', '20.20.20.0/24']
        version = self.validator._check_peer_endpoint_ip_versions(
            endpoint_group_id, multiple_cidr)
        self.assertEqual(4, version)

    def test_fail_ipsec_conn_peer_endpoints_mixed_ip_version(self):
        """Fail when mixed IP versions in peer endpoints."""
        endpoint_group_id = _uuid()
        mixed_cidrs = ['10.10.10.0/24', '2002:1400::/48']
        self.assertRaises(vpnaas.MixedIPVersionsForIPSecEndpoints,
                          self.validator._check_peer_endpoint_ip_versions,
                          endpoint_group_id, mixed_cidrs)

    def test_fail_ipsec_conn_locals_and_peers_different_ip_version(self):
        """Ensure catch when local and peer IP versions are not the same."""
        self.assertRaises(vpnaas.MixedIPVersionsForIPSecConnection,
                          self.validator._validate_compatible_ip_versions,
                          4, 6)

    def test_fail_ipsec_conn_no_subnet_requiring_endpoint_groups(self):
        """When no subnet, connection must use endpoints.

        This means both endpoint groups must be present, and peer_cidrs
        cannot be used.
        """
        subnet = None
        ipsec_sitecon = {'peer_cidrs': ['10.0.0.0/24'],
                         'local_ep_group_id': 'local-epg-id',
                         'peer_ep_group_id': 'peer-epg-id'}
        self.assertRaises(vpnaas.PeerCidrsInvalid,
                          self.validator.validate_ipsec_conn_optional_args,
                          ipsec_sitecon, subnet)

        ipsec_sitecon = {'peer_cidrs': [],
                         'local_ep_group_id': None,
                         'peer_ep_group_id': 'peer-epg-id'}
        self.assertRaises(vpnaas.MissingRequiredEndpointGroup,
                          self.validator.validate_ipsec_conn_optional_args,
                          ipsec_sitecon, subnet)

        ipsec_sitecon = {'peer_cidrs': [],
                         'local_ep_group_id': 'local-epg-id',
                         'peer_ep_group_id': None}
        self.assertRaises(vpnaas.MissingRequiredEndpointGroup,
                          self.validator.validate_ipsec_conn_optional_args,
                          ipsec_sitecon, subnet)

        ipsec_sitecon = {'peer_cidrs': [],
                         'local_ep_group_id': None,
                         'peer_ep_group_id': None}
        self.assertRaises(vpnaas.MissingRequiredEndpointGroup,
                          self.validator.validate_ipsec_conn_optional_args,
                          ipsec_sitecon, subnet)

    def test_fail_ipsec_conn_subnet_requiring_peer_cidrs(self):
        """When legacy mode, no endpoint groups.

        This means neither endpoint group can be specified, and the peer_cidrs
        must be present.
        """
        subnet = {'id': FAKE_SUBNET_ID}
        ipsec_sitecon = {'peer_cidrs': [],
                         'local_ep_group_id': None,
                         'peer_ep_group_id': None}
        self.assertRaises(vpnaas.MissingPeerCidrs,
                          self.validator.validate_ipsec_conn_optional_args,
                          ipsec_sitecon, subnet)

        ipsec_sitecon = {'peer_cidrs': ['10.0.0.0/24'],
                         'local_ep_group_id': 'local-epg-id',
                         'peer_ep_group_id': None}
        self.assertRaises(vpnaas.InvalidEndpointGroup,
                          self.validator.validate_ipsec_conn_optional_args,
                          ipsec_sitecon, subnet)

        ipsec_sitecon = {'peer_cidrs': ['10.0.0.0/24'],
                         'local_ep_group_id': None,
                         'peer_ep_group_id': 'peer-epg-id'}
        self.assertRaises(vpnaas.InvalidEndpointGroup,
                          self.validator.validate_ipsec_conn_optional_args,
                          ipsec_sitecon, subnet)

        ipsec_sitecon = {'peer_cidrs': ['10.0.0.0/24'],
                         'local_ep_group_id': 'local-epg-id',
                         'peer_ep_group_id': 'peer-epg-id'}
        self.assertRaises(vpnaas.InvalidEndpointGroup,
                          self.validator.validate_ipsec_conn_optional_args,
                          ipsec_sitecon, subnet)

    def test_ipsec_conn_get_local_subnets(self):
        subnet1 = _uuid()
        subnet2 = _uuid()
        expected_subnets = [subnet1, subnet2]
        local_epg = {'id': _uuid(),
                    'type': v_constants.SUBNET_ENDPOINT,
                     'endpoints': expected_subnets}
        query_mock = mock.patch.object(query.Query, 'all').start()
        query_mock.return_value = expected_subnets
        subnets = self.validator._get_local_subnets(self.context, local_epg)
        self.assertEqual(expected_subnets, subnets)

    def test_ipsec_conn_get_peer_cidrs(self):
        expected_cidrs = ['10.10.10.10/24', '20.20.20.20/24']
        peer_epg = {'id': 'should-be-cidrs',
                    'type': v_constants.CIDR_ENDPOINT,
                    'endpoints': expected_cidrs}
        cidrs = self.validator._get_peer_cidrs(peer_epg)
        self.assertEqual(expected_cidrs, cidrs)

    def test_fail_ipsec_conn_endpoint_group_types(self):
        local_epg = {'id': 'should-be-subnets',
                     'type': v_constants.CIDR_ENDPOINT,
                     'endpoints': ['10.10.10.10/24', '20.20.20.20/24']}
        self.assertRaises(vpnaas.WrongEndpointGroupType,
                          self.validator._get_local_subnets,
                          self.context, local_epg)
        peer_epg = {'id': 'should-be-cidrs',
                    'type': v_constants.SUBNET_ENDPOINT,
                    'endpoints': [_uuid(), _uuid()]}
        self.assertRaises(vpnaas.WrongEndpointGroupType,
                          self.validator._get_peer_cidrs,
                          peer_epg)

    def test_validate_ipsec_conn_for_endpoints(self):
        """Check upper-level validation method for endpoint groups.

        Tests the happy path for doing general validation of the IPSec
        connection, calling all the sub-checks for an endpoint group case.
        """
        subnet1 = {'id': _uuid(), 'ip_version': 4}
        subnet2 = {'id': _uuid(), 'ip_version': 4}
        local_subnets = [subnet1, subnet2]
        local_epg_id = _uuid()
        local_epg = {'id': local_epg_id,
                     'type': v_constants.SUBNET_ENDPOINT,
                     'endpoints': local_subnets}
        # Mock getting the subnets from the IDs
        query_mock = mock.patch.object(query.Query, 'all').start()
        query_mock.return_value = local_subnets
        # Mock that subnet is on router
        port_mock = mock.patch.object(self.core_plugin, "get_ports").start()
        port_mock.side_effect = ['dummy info', 'more dummy info']

        peer_epg_id = _uuid()
        peer_cidrs = ['10.10.10.10/24', '20.20.20.20/24']
        peer_epg = {'id': peer_epg_id,
                    'type': v_constants.CIDR_ENDPOINT,
                    'endpoints': peer_cidrs}

        ipsec_sitecon = {'local_ep_group_id': local_epg_id,
                         'local_epg_subnets': local_epg,
                         'peer_ep_group_id': peer_epg_id,
                         'peer_epg_cidrs': peer_epg,
                         'mtu': 2000,
                         'dpd_action': 'hold',
                         'dpd_interval': 30,
                         'dpd_timeout': 120}
        local_version = None
        vpnservice = {'router_id': _uuid()}
        self.validator.validate_ipsec_site_connection(
            self.context, ipsec_sitecon, local_version, vpnservice)

    # NOTE: Following are tests for the older API, providing some additional
    # coverage.

    def test_ipsec_conn_peer_cidrs_same_ip_version(self):
        """Check legacy peer_cidrs have same IP version."""
        one_cidr = ['2002:0a00::/48']
        version = self.validator._check_peer_cidrs_ip_versions(one_cidr)
        self.assertEqual(6, version)
        multiple_cidrs = ['10.10.10.0/24', '20.20.20.0/24']
        version = self.validator._check_peer_cidrs_ip_versions(multiple_cidrs)
        self.assertEqual(4, version)

    def test_fail_ipsec_conn_peer_cidrs_mixed_ip_version(self):
        mixed_cidrs = ['2002:0a00::/48', '20.20.20.0/24']
        self.assertRaises(vpnaas.MixedIPVersionsForPeerCidrs,
                          self.validator._check_peer_cidrs_ip_versions,
                          mixed_cidrs)
