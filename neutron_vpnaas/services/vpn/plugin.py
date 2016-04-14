
#    (c) Copyright 2013 Hewlett-Packard Development Company, L.P.
#    All Rights Reserved.
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

from neutron.db import servicetype_db as st_db
from neutron.plugins.common import constants
from neutron.services import provider_configuration as pconf
from neutron.services import service_base
from oslo_log import log as logging

from neutron_vpnaas._i18n import _LI
from neutron_vpnaas.db.vpn import vpn_db

LOG = logging.getLogger(__name__)


def add_provider_configuration(type_manager, service_type):
    type_manager.add_provider_configuration(
        service_type,
        pconf.ProviderConfiguration('neutron_vpnaas'))


class VPNPlugin(vpn_db.VPNPluginDb):

    """Implementation of the VPN Service Plugin.

    This class manages the workflow of VPNaaS request/response.
    Most DB related works are implemented in class
    vpn_db.VPNPluginDb.
    """
    supported_extension_aliases = ["vpnaas",
                                   "vpn-endpoint-groups",
                                   "service-type"]
    path_prefix = "/vpn"


class VPNDriverPlugin(VPNPlugin, vpn_db.VPNPluginRpcDbMixin):
    """VpnPlugin which supports VPN Service Drivers."""
    #TODO(nati) handle ikepolicy and ipsecpolicy update usecase
    def __init__(self):
        super(VPNDriverPlugin, self).__init__()
        self.service_type_manager = st_db.ServiceTypeManager.get_instance()
        add_provider_configuration(self.service_type_manager, constants.VPN)
        # Load the service driver from neutron.conf.
        drivers, default_provider = service_base.load_drivers(
            constants.VPN, self)
        LOG.info(_LI("VPN plugin using service driver: %s"), default_provider)
        self.ipsec_driver = drivers[default_provider]
        vpn_db.subscribe()

    def _get_driver_for_vpnservice(self, vpnservice):
        return self.ipsec_driver

    def _get_driver_for_ipsec_site_connection(self, context,
                                              ipsec_site_connection):
        #TODO(nati) get vpnservice when we support service type framework
        vpnservice = None
        return self._get_driver_for_vpnservice(vpnservice)

    def _get_validator(self):
        return self.ipsec_driver.validator

    def create_ipsec_site_connection(self, context, ipsec_site_connection):
        ipsec_site_connection = super(
            VPNDriverPlugin, self).create_ipsec_site_connection(
                context, ipsec_site_connection)
        driver = self._get_driver_for_ipsec_site_connection(
            context, ipsec_site_connection)
        driver.create_ipsec_site_connection(context, ipsec_site_connection)
        return ipsec_site_connection

    def delete_ipsec_site_connection(self, context, ipsec_conn_id):
        ipsec_site_connection = self.get_ipsec_site_connection(
            context, ipsec_conn_id)
        super(VPNDriverPlugin, self).delete_ipsec_site_connection(
            context, ipsec_conn_id)
        driver = self._get_driver_for_ipsec_site_connection(
            context, ipsec_site_connection)
        driver.delete_ipsec_site_connection(context, ipsec_site_connection)

    def update_ipsec_site_connection(
            self, context,
            ipsec_conn_id, ipsec_site_connection):
        old_ipsec_site_connection = self.get_ipsec_site_connection(
            context, ipsec_conn_id)
        ipsec_site_connection = super(
            VPNDriverPlugin, self).update_ipsec_site_connection(
                context,
                ipsec_conn_id,
                ipsec_site_connection)
        driver = self._get_driver_for_ipsec_site_connection(
            context, ipsec_site_connection)
        driver.update_ipsec_site_connection(
            context, old_ipsec_site_connection, ipsec_site_connection)
        return ipsec_site_connection

    def create_vpnservice(self, context, vpnservice):
        vpnservice = super(
            VPNDriverPlugin, self).create_vpnservice(context, vpnservice)
        driver = self._get_driver_for_vpnservice(vpnservice)
        driver.create_vpnservice(context, vpnservice)
        return vpnservice

    def update_vpnservice(self, context, vpnservice_id, vpnservice):
        old_vpn_service = self.get_vpnservice(context, vpnservice_id)
        new_vpn_service = super(
            VPNDriverPlugin, self).update_vpnservice(context, vpnservice_id,
                                                     vpnservice)
        driver = self._get_driver_for_vpnservice(old_vpn_service)
        driver.update_vpnservice(context, old_vpn_service, new_vpn_service)
        return new_vpn_service

    def delete_vpnservice(self, context, vpnservice_id):
        vpnservice = self._get_vpnservice(context, vpnservice_id)
        super(VPNDriverPlugin, self).delete_vpnservice(context, vpnservice_id)
        driver = self._get_driver_for_vpnservice(vpnservice)
        driver.delete_vpnservice(context, vpnservice)
