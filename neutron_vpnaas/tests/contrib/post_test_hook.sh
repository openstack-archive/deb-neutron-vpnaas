#!/usr/bin/env bash

set -xe

NEUTRON_VPNAAS_DIR="$BASE/new/neutron-vpnaas"
TEMPEST_CONFIG_DIR="$BASE/new/tempest/etc"
SCRIPTS_DIR="/usr/os-testr-env/bin"

VENV=${1:-"dsvm-functional"}

function generate_testr_results {
    # Give job user rights to access tox logs
    sudo -H -u $owner chmod o+rw .
    sudo -H -u $owner chmod o+rw -R .testrepository
    if [ -f ".testrepository/0" ] ; then
        .tox/$VENV/bin/subunit-1to2 < .testrepository/0 > ./testrepository.subunit
        $SCRIPTS_DIR/subunit2html ./testrepository.subunit testr_results.html
        gzip -9 ./testrepository.subunit
        gzip -9 ./testr_results.html
        sudo mv ./*.gz /opt/stack/logs/
    fi
}

case $VENV in
    dsvm-functional | dsvm-functional-sswan)
        owner=stack
        sudo_env=
        ;;
    api)
        owner=tempest
        # Configure the api tests to use the tempest.conf set by devstack.
        sudo_env="TEMPEST_CONFIG_DIR=$TEMPEST_DIR/etc"
        ;;
esac

# Set owner permissions according to job's requirements.
cd $NEUTRON_VPNAAS_DIR
sudo chown -R $owner:stack $NEUTRON_VPNAAS_DIR

# Run tests
echo "Running neutron $VENV test suite"
set +e
sudo -H -u $owner $sudo_env tox -e $VENV
testr_exit_code=$?
set -e

echo "Dumping log from tox_install.sh"
cat /tmp/tox_install.txt

# Collect and parse results
generate_testr_results
exit $testr_exit_code
