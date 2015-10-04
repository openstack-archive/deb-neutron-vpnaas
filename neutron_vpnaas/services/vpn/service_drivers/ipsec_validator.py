# Copyright 2015 Awcloud Inc.  All rights reserved.
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

from neutron.common import exceptions
from oslo_log import log as logging

from neutron_vpnaas.db.vpn import vpn_validator


LOG = logging.getLogger(__name__)


class IpsecValidationFailure(exceptions.BadRequest):
    message = _("IPSec does not support %(resource)s attribute %(key)s "
                "with value '%(value)s'")


class IpsecVpnValidator(vpn_validator.VpnReferenceValidator):

    """Validator methods for the Openswan, Strongswan and Libreswan."""

    def __init__(self, service_plugin):
        self.service_plugin = service_plugin
        super(IpsecVpnValidator, self).__init__()

    def validate_ipsec_policy(self, context, ipsec_policy):
        """Restrict selecting ah-esp as IPSec Policy transform protocol.

        For those *Swan implementations, the 'ah-esp' transform protocol
        is not supported and therefore the request should be rejected.
        """
        transform_protocol = ipsec_policy.get('transform_protocol')
        if transform_protocol == "ah-esp":
            raise IpsecValidationFailure(
                resource='IPsec Policy',
                key='transform_protocol',
                value=transform_protocol)
