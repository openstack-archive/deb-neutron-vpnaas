====================
VPNaaS Tempest Tests
====================

This contains the tempest test codes for the Neutron VPN as a Service (VPNaaS) service. The tests
currently require tempest to be installed via devstack or standalone. It is assumed that you
also have Neutron with the Neutron VPNaaS service installed. These tests could also be run against
a multinode openstack.

Please see /neutron-vpnaas/devstack/README.md for the required devstack configuration settings
for Neutron-VPNaaS.

How to test:
============

As a tempest plugin, the steps to run tests by hands are:

1. Setup a local working environment for running tempest
    ::

        tempest init ${your_tempest_dir}

2. Enter ${your_tempest_dir}
    ::

        cd ${your_tempest_dir}

3. Check neutron_vpnaas_tests exist in tempest plugins:
    ::

        tempest list-plugins

    +----------------------+--------------------------------------------------------+
    |         Name         |                       EntryPoint                       |
    +----------------------+--------------------------------------------------------+
    | neutron_tests        |   neutron.tests.tempest.plugin:NeutronTempestPlugin    |
    | neutron_vpnaas_tests |   neutron_vpnaas.tests.tempest.plugin:VPNTempestPlugin |
    +----------------------+--------------------------------------------------------+


4. Run neutron_vpnaas tests:
    ::

        tempest run --regex "^neutron_vpnaas.tests.tempest.api\."

Usage in gate:
==============

In the jenkins gate, devstack-gate/devstack-vm-gate-wrap.sh will invoke tempest with proper
configurations, such as:

    ::

        DEVSTACK_GATE_TEMPEST=1
        DEVSTACK_GATE_TEMPEST_ALL_PLUGINS=1
        DEVSTACK_GATE_TEMPEST_REGEX="^neutron_vpnaas.tests.tempest.api\."

The actual raw command in gate running under the tempest code directory is:

    ::

        tox -eall-plugin -- "^neutron_vpnaas.tests.tempest.api\."


External Resources:
===================

For more information on the tempest, see: <http://docs.openstack.org/developer/tempest/>
