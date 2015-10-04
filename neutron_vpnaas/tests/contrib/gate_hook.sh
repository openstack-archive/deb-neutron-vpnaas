#!/usr/bin/env bash

set -ex

VENV=${1:-"dsvm-functional"}
export DEVSTACK_LOCAL_CONFIG="enable_plugin neutron-vpnaas https://git.openstack.org/openstack/neutron-vpnaas"

case $VENV in
    dsvm-functional | dsvm-functional-sswan)
        # The following need to be set before sourcing
        # configure_for_func_testing.
        GATE_DEST=$BASE/new
        GATE_STACK_USER=stack
        NEUTRON_PATH=$GATE_DEST/neutron
        PROJECT_NAME=neutron-vpnaas
        NEUTRON_VPN_PATH=$GATE_DEST/$PROJECT_NAME
        DEVSTACK_PATH=$GATE_DEST/devstack
        IS_GATE=True

        source $NEUTRON_VPN_PATH/tools/configure_for_vpn_func_testing.sh

        # Make the workspace owned by the stack user
        sudo chown -R $STACK_USER:$STACK_USER $BASE

        configure_host_for_vpn_func_testing
        ;;
    api) $BASE/new/devstack-gate/devstack-vm-gate.sh ;;
esac
