# Copyright 2016 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import amulet

from charmhelpers.contrib.openstack.amulet.deployment import (
    OpenStackAmuletDeployment
)

from charmhelpers.contrib.openstack.amulet.utils import (
    OpenStackAmuletUtils,
    DEBUG,
    # ERROR
)
from charmhelpers.contrib.openstack.utils import CompareOpenStackReleases

import keystoneclient
from keystoneclient.v3 import client as keystone_client_v3
from novaclient import client as nova_client
from novaclient import exceptions


class NovaOpenStackAmuletUtils(OpenStackAmuletUtils):
    """Nova based helper extending base helper for creation of flavors"""

    def create_flavor(self, nova, name, ram, vcpus, disk, flavorid="auto",
                      ephemeral=0, swap=0, rxtx_factor=1.0, is_public=True):
        """Create the specified flavor."""
        try:
            nova.flavors.find(name=name)
        except (exceptions.NotFound, exceptions.NoUniqueMatch):
            self.log.debug('Creating flavor ({})'.format(name))
            nova.flavors.create(name, ram, vcpus, disk, flavorid,
                                ephemeral, swap, rxtx_factor, is_public)


# Use DEBUG to turn on debug logging
u = NovaOpenStackAmuletUtils(DEBUG)


class NovaBasicDeployment(OpenStackAmuletDeployment):
    """Amulet tests on a basic nova compute deployment."""

    def __init__(self, series=None, openstack=None, source=None,
                 stable=False):
        """Deploy the entire test environment."""
        super(NovaBasicDeployment, self).__init__(series, openstack,
                                                  source, stable)
        self._add_services()
        self._add_relations()
        self._configure_services()
        self._deploy()

        u.log.info('Waiting on extended status checks...')
        self.exclude_services = []
        self._auto_wait_for_status(exclude_services=self.exclude_services)

        self.d.sentry.wait()
        self._initialize_tests()

    def _add_services(self):
        """Add services

           Add the services that we're testing, where nova-compute is local,
           and the rest of the service are from lp branches that are
           compatible with the local charm (e.g. stable or next).
           """
        this_service = {'name': 'nova-compute'}
        other_services = [
            {'name': 'rabbitmq-server'},
            {'name': 'nova-cloud-controller'},
            {'name': 'keystone'},
            {'name': 'glance'},
            {'name': 'percona-cluster'},
        ]
        if self._get_openstack_release() >= self.xenial_ocata:
            other_ocata_services = [
                {'name': 'neutron-gateway'},
                {'name': 'neutron-api'},
                {'name': 'neutron-openvswitch'},
            ]
            other_services += other_ocata_services

        super(NovaBasicDeployment, self)._add_services(this_service,
                                                       other_services)

    def _add_relations(self):
        """Add all of the relations for the services."""
        relations = {
            'nova-compute:image-service': 'glance:image-service',
            'nova-compute:amqp': 'rabbitmq-server:amqp',
            'nova-cloud-controller:shared-db': 'percona-cluster:shared-db',
            'nova-cloud-controller:identity-service': 'keystone:'
                                                      'identity-service',
            'nova-cloud-controller:amqp': 'rabbitmq-server:amqp',
            'nova-cloud-controller:cloud-compute': 'nova-compute:'
                                                   'cloud-compute',
            'nova-cloud-controller:image-service': 'glance:image-service',
            'keystone:shared-db': 'percona-cluster:shared-db',
            'glance:identity-service': 'keystone:identity-service',
            'glance:shared-db': 'percona-cluster:shared-db',
            'glance:amqp': 'rabbitmq-server:amqp'
        }
        if self._get_openstack_release() >= self.xenial_ocata:
            ocata_relations = {
                'neutron-gateway:amqp': 'rabbitmq-server:amqp',
                'nova-cloud-controller:quantum-network-service':
                'neutron-gateway:quantum-network-service',
                'neutron-api:shared-db': 'percona-cluster:shared-db',
                'neutron-api:amqp': 'rabbitmq-server:amqp',
                'neutron-api:neutron-api': 'nova-cloud-controller:neutron-api',
                'neutron-api:identity-service': 'keystone:identity-service',
                'nova-compute:neutron-plugin': 'neutron-openvswitch:'
                                               'neutron-plugin',
                'rabbitmq-server:amqp': 'neutron-openvswitch:amqp',
            }
            relations.update(ocata_relations)

        super(NovaBasicDeployment, self)._add_relations(relations)

    def _configure_services(self):
        """Configure all of the services."""
        u.log.debug("Running all tests in Apparmor enforce mode.")
        nova_config = {'config-flags': 'auto_assign_floating_ip=False',
                       'enable-live-migration': 'False',
                       'aa-profile-mode': 'enforce'}
        if self._get_openstack_release() > self.trusty_mitaka:
            nova_config.update({'ephemeral-device': '/dev/vdb',
                                'ephemeral-unmount': '/mnt'})
        nova_cc_config = {}
        if self._get_openstack_release() >= self.xenial_ocata:
            nova_cc_config['network-manager'] = 'Neutron'

        keystone_config = {
            'admin-password': 'openstack',
            'admin-token': 'ubuntutesting',
        }
        pxc_config = {
            'max-connections': 1000,
        }

        configs = {
            'nova-compute': nova_config,
            'keystone': keystone_config,
            'nova-cloud-controller': nova_cc_config,
            'percona-cluster': pxc_config,
        }
        super(NovaBasicDeployment, self)._configure_services(configs)

    def _initialize_tests(self):
        """Perform final initialization before tests get run."""
        # Access the sentries for inspecting service units
        self.pxc_sentry = self.d.sentry['percona-cluster'][0]
        self.keystone_sentry = self.d.sentry['keystone'][0]
        self.rabbitmq_sentry = self.d.sentry['rabbitmq-server'][0]
        self.nova_compute_sentry = self.d.sentry['nova-compute'][0]
        self.nova_cc_sentry = self.d.sentry['nova-cloud-controller'][0]
        self.glance_sentry = self.d.sentry['glance'][0]

        u.log.debug('openstack release val: {}'.format(
            self._get_openstack_release()))
        u.log.debug('openstack release str: {}'.format(
            self._get_openstack_release_string()))

        # Authenticate admin with keystone
        self.keystone_session, self.keystone = u.get_default_keystone_session(
            self.keystone_sentry,
            openstack_release=self._get_openstack_release())

        force_v1_client = False
        if self._get_openstack_release() == self.trusty_icehouse:
            # Updating image properties (such as arch or hypervisor) using the
            # v2 api in icehouse results in:
            # https://bugs.launchpad.net/python-glanceclient/+bug/1371559
            u.log.debug('Forcing glance to use v1 api')
            force_v1_client = True

        # Authenticate admin with glance endpoint
        self.glance = u.authenticate_glance_admin(
            self.keystone,
            force_v1_client=force_v1_client)

        # Authenticate admin with nova endpoint
        self.nova = nova_client.Client(2, session=self.keystone_session)

        keystone_ip = self.keystone_sentry.info['public-address']

        # Create a demo tenant/role/user
        self.demo_tenant = 'demoTenant'
        self.demo_role = 'demoRole'
        self.demo_user = 'demoUser'
        self.demo_project = 'demoProject'
        self.demo_domain = 'demoDomain'
        if self._get_openstack_release() >= self.xenial_queens:
            self.create_users_v3()
            self.demo_user_session, auth = u.get_keystone_session(
                keystone_ip,
                self.demo_user,
                'password',
                api_version=3,
                user_domain_name=self.demo_domain,
                project_domain_name=self.demo_domain,
                project_name=self.demo_project
            )
            self.keystone_demo = keystone_client_v3.Client(
                session=self.demo_user_session)
            self.nova_demo = nova_client.Client(
                2,
                session=self.demo_user_session)
        else:
            self.create_users_v2()
            # Authenticate demo user with keystone
            self.keystone_demo = \
                u.authenticate_keystone_user(
                    self.keystone, user=self.demo_user,
                    password='password',
                    tenant=self.demo_tenant)
            # Authenticate demo user with nova-api
            self.nova_demo = u.authenticate_nova_user(self.keystone,
                                                      user=self.demo_user,
                                                      password='password',
                                                      tenant=self.demo_tenant)

    def create_users_v3(self):
        try:
            self.keystone.projects.find(name=self.demo_project)
        except keystoneclient.exceptions.NotFound:
            domain = self.keystone.domains.create(
                self.demo_domain,
                description='Demo Domain',
                enabled=True
            )
            project = self.keystone.projects.create(
                self.demo_project,
                domain,
                description='Demo Project',
                enabled=True,
            )
            user = self.keystone.users.create(
                self.demo_user,
                domain=domain.id,
                project=self.demo_project,
                password='password',
                email='demov3@demo.com',
                description='Demo',
                enabled=True)
            role = self.keystone.roles.find(name='Admin')
            self.keystone.roles.grant(
                role.id,
                user=user.id,
                project=project.id)

    def create_users_v2(self):
        if not u.tenant_exists(self.keystone, self.demo_tenant):
            tenant = self.keystone.tenants.create(tenant_name=self.demo_tenant,
                                                  description='demo tenant',
                                                  enabled=True)

            self.keystone.roles.create(name=self.demo_role)
            self.keystone.users.create(name=self.demo_user,
                                       password='password',
                                       tenant_id=tenant.id,
                                       email='demo@demo.com')

    def test_100_services(self):
        """Verify the expected services are running on the corresponding
           service units."""
        u.log.debug('Checking system services on units...')

        services = {
            self.rabbitmq_sentry: ['rabbitmq-server'],
            self.nova_compute_sentry: ['nova-compute',
                                       'nova-network',
                                       'nova-api'],
            self.nova_cc_sentry: ['nova-conductor'],
            self.keystone_sentry: ['keystone'],
            self.glance_sentry: ['glance-registry',
                                 'glance-api']
        }

        if self._get_openstack_release() >= self.trusty_liberty:
            services[self.keystone_sentry] = ['apache2']

        _os_release = self._get_openstack_release_string()
        if CompareOpenStackReleases(_os_release) >= 'ocata':
            services[self.nova_compute_sentry].remove('nova-network')
            services[self.nova_compute_sentry].remove('nova-api')

        ret = u.validate_services_by_name(services)
        if ret:
            amulet.raise_status(amulet.FAIL, msg=ret)

    def test_102_service_catalog(self):
        """Verify that the service catalog endpoint data is valid."""
        u.log.debug('Checking keystone service catalog...')

        endpoint_vol = {'adminURL': u.valid_url,
                        'region': 'RegionOne',
                        'id': u.not_null,
                        'publicURL': u.valid_url,
                        'internalURL': u.valid_url}
        endpoint_id = {'adminURL': u.valid_url,
                       'region': 'RegionOne',
                       'id': u.not_null,
                       'publicURL': u.valid_url,
                       'internalURL': u.valid_url}

        if self._get_openstack_release() >= self.trusty_kilo:
            expected = {'compute': [endpoint_vol], 'identity': [endpoint_id]}
        else:
            expected = {'s3': [endpoint_vol], 'compute': [endpoint_vol],
                        'ec2': [endpoint_vol], 'identity': [endpoint_id]}
        actual = self.keystone.service_catalog.get_endpoints()

        ret = u.validate_svc_catalog_endpoint_data(
            expected,
            actual,
            openstack_release=self._get_openstack_release())
        if ret:
            amulet.raise_status(amulet.FAIL, msg=ret)

    def test_104_openstack_compute_api_endpoint(self):
        """Verify the openstack compute api (osapi) endpoint data."""
        u.log.debug('Checking compute endpoint data...')

        endpoints = self.keystone.endpoints.list()
        admin_port = internal_port = public_port = '8774'
        expected = {
            'id': u.not_null,
            'region': 'RegionOne',
            'adminurl': u.valid_url,
            'internalurl': u.valid_url,
            'publicurl': u.valid_url,
            'service_id': u.not_null
        }

        ret = u.validate_endpoint_data(
            endpoints,
            admin_port,
            internal_port,
            public_port,
            expected,
            openstack_release=self._get_openstack_release())

        if ret:
            message = 'osapi endpoint: {}'.format(ret)
            amulet.raise_status(amulet.FAIL, msg=message)

    def test_106_ec2_api_endpoint(self):
        """Verify the EC2 api endpoint data."""
        if self._get_openstack_release() >= self.trusty_kilo:
            return

        u.log.debug('Checking ec2 endpoint data...')
        endpoints = self.keystone.endpoints.list()
        admin_port = internal_port = public_port = '8773'
        expected = {
            'id': u.not_null,
            'region': 'RegionOne',
            'adminurl': u.valid_url,
            'internalurl': u.valid_url,
            'publicurl': u.valid_url,
            'service_id': u.not_null
        }

        ret = u.validate_endpoint_data(endpoints, admin_port, internal_port,
                                       public_port, expected)
        if ret:
            message = 'EC2 endpoint: {}'.format(ret)
            amulet.raise_status(amulet.FAIL, msg=message)

    def test_108_s3_api_endpoint(self):
        """Verify the S3 api endpoint data."""
        if self._get_openstack_release() >= self.trusty_kilo:
            return

        u.log.debug('Checking s3 endpoint data...')
        endpoints = self.keystone.endpoints.list()
        admin_port = internal_port = public_port = '3333'
        expected = {
            'id': u.not_null,
            'region': 'RegionOne',
            'adminurl': u.valid_url,
            'internalurl': u.valid_url,
            'publicurl': u.valid_url,
            'service_id': u.not_null
        }

        ret = u.validate_endpoint_data(endpoints, admin_port, internal_port,
                                       public_port, expected)
        if ret:
            message = 'S3 endpoint: {}'.format(ret)
            amulet.raise_status(amulet.FAIL, msg=message)

    def test_204_nova_amqp_relation(self):
        """Verify the nova-compute to rabbitmq-server amqp relation data"""
        u.log.debug('Checking n-c:rmq amqp relation data...')
        unit = self.nova_compute_sentry
        relation = ['amqp', 'rabbitmq-server:amqp']
        expected = {
            'username': 'nova',
            'private-address': u.valid_ip,
            'vhost': 'openstack'
        }

        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            message = u.relation_error('nova-compute amqp', ret)
            amulet.raise_status(amulet.FAIL, msg=message)

    def test_206_rabbitmq_amqp_relation(self):
        """Verify the rabbitmq-server to nova-compute amqp relation data"""
        u.log.debug('Checking rmq:n-c amqp relation data...')
        unit = self.rabbitmq_sentry
        relation = ['amqp', 'nova-compute:amqp']
        expected = {
            'private-address': u.valid_ip,
            'password': u.not_null,
            'hostname': u.valid_ip
        }

        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            message = u.relation_error('rabbitmq amqp', ret)
            amulet.raise_status(amulet.FAIL, msg=message)

    def test_208_nova_cloud_compute_relation(self):
        """Verify the nova-compute to nova-cc cloud-compute relation data"""
        u.log.debug('Checking n-c:n-c-c cloud-compute relation data...')
        unit = self.nova_compute_sentry
        relation = ['cloud-compute', 'nova-cloud-controller:cloud-compute']
        expected = {
            'private-address': u.valid_ip,
        }

        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            message = u.relation_error('nova-compute cloud-compute', ret)
            amulet.raise_status(amulet.FAIL, msg=message)

    def test_210_nova_cc_cloud_compute_relation(self):
        """Verify the nova-cc to nova-compute cloud-compute relation data"""
        u.log.debug('Checking n-c-c:n-c cloud-compute relation data...')
        unit = self.nova_cc_sentry
        relation = ['cloud-compute', 'nova-compute:cloud-compute']
        expected = {
            'volume_service': 'cinder',
            'network_manager': 'flatdhcpmanager',
            'ec2_host': u.valid_ip,
            'private-address': u.valid_ip,
            'restart_trigger': u.not_null
        }

        if self._get_openstack_release() >= self.xenial_ocata:
            expected['network_manager'] = 'neutron'

        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            message = u.relation_error('nova-cc cloud-compute', ret)
            amulet.raise_status(amulet.FAIL, msg=message)

    def test_300_nova_config(self):
        """Verify the data in the nova config file."""

        u.log.debug('Checking nova config file data...')
        unit = self.nova_compute_sentry
        conf = '/etc/nova/nova.conf'
        rmq_nc_rel = self.rabbitmq_sentry.relation('amqp',
                                                   'nova-compute:amqp')
        gl_nc_rel = self.glance_sentry.relation('image-service',
                                                'nova-compute:image-service')
        # Common conf across all releases
        expected = {
            'DEFAULT': {
                'dhcpbridge_flagfile': '/etc/nova/nova.conf',
                'dhcpbridge': '/usr/bin/nova-dhcpbridge',
                'logdir': '/var/log/nova',
                'state_path': '/var/lib/nova',
                'force_dhcp_release': 'True',
                'verbose': 'False',
                'use_syslog': 'False',
                'ec2_private_dns_show_ip': 'True',
                'api_paste_config': '/etc/nova/api-paste.ini',
                'enabled_apis': 'osapi_compute,metadata',
                'flat_interface': 'eth1',
                'network_manager': 'nova.network.manager.FlatDHCPManager',
                'volume_api_class': 'nova.volume.cinder.API',
                'auth_strategy': 'keystone',
            }
        }

        if self._get_openstack_release() < self.trusty_kilo:
            # Juno or earlier
            expected['DEFAULT'].update({
                'lock_path': '/var/lock/nova',
                'libvirt_use_virtio_for_bridges': 'True',
                'compute_driver': 'libvirt.LibvirtDriver',
                'rabbit_userid': 'nova',
                'rabbit_virtual_host': 'openstack',
                'rabbit_password': rmq_nc_rel['password'],
                'rabbit_host': rmq_nc_rel['hostname'],
                'glance_api_servers': gl_nc_rel['glance-api-server']
            })
        else:
            # Kilo or later
            expected.update({
                'oslo_concurrency': {
                    'lock_path': '/var/lock/nova'
                },
                'oslo_messaging_rabbit': {
                    'rabbit_userid': 'nova',
                    'rabbit_virtual_host': 'openstack',
                    'rabbit_password': rmq_nc_rel['password'],
                    'rabbit_host': rmq_nc_rel['hostname'],
                },
                'glance': {
                    'api_servers': gl_nc_rel['glance-api-server']
                }
            })

        if self._get_openstack_release() >= self.xenial_ocata:
            del expected['DEFAULT']['flat_interface']
            del expected['DEFAULT']['network_manager']
            expected['DEFAULT'].update({
                'use_neutron': 'True',
                'network_api_class': 'nova.network.neutronv2.api.API'})
            expected['neutron'] = {
                'url': u.valid_url,
                'auth_url': u.valid_url}
            # Add expected username?

        for section, pairs in expected.iteritems():
            ret = u.validate_config_data(unit, conf, section, pairs)
            if ret:
                message = "nova config error: {}".format(ret)
                amulet.raise_status(amulet.FAIL, msg=message)

    def test_400_image_instance_create(self):
        """Create an image/instance, verify they exist, and delete them."""

        u.log.debug('Checking nova instance creation...')

        image = u.create_cirros_image(self.glance, "cirros-image")
        if not image:
            amulet.raise_status(amulet.FAIL, msg="Image create failed")

        # NOTE(jamespage): ensure require flavor exists, required for >= newton
        u.create_flavor(nova=self.nova,
                        name='m1.tiny', ram=512, vcpus=1, disk=1)

        instance = u.create_instance(self.nova_demo, "cirros-image", "cirros",
                                     "m1.tiny")
        if not instance:
            amulet.raise_status(amulet.FAIL, msg="Instance create failed")

        found = False
        for instance in self.nova_demo.servers.list():
            if instance.name == 'cirros':
                found = True
                if instance.status != 'ACTIVE':
                    msg = "cirros instance is not active"
                    amulet.raise_status(amulet.FAIL, msg=msg)

        if not found:
            message = "nova cirros instance does not exist"
            amulet.raise_status(amulet.FAIL, msg=message)

        u.delete_resource(self.glance.images, image.id,
                          msg="glance image")

        u.delete_resource(self.nova_demo.servers, instance.id,
                          msg="nova instance")

    def test_500_hugepagereport_action(self):
        """Verify hugepagereport"""
        u.log.debug("Testing hugepagereport")
        sentry_unit = self.nova_compute_sentry

        action_id = u.run_action(sentry_unit, "hugepagereport")
        assert u.wait_on_action(action_id), "Hugepagereport action failed."
        data = amulet.actions.get_action_output(action_id, full_output=True)
        assert data.get(u"status") == "completed", ("Hugepagereport action"
                                                    "failed")
        report = data.get(u"results").get(u"hugepagestats")
        assert report.find('free_hugepages') != -1

    def test_900_restart_on_config_change(self):
        """Verify that the specified services are restarted when the config
           is changed."""

        sentry = self.nova_compute_sentry
        juju_service = 'nova-compute'

        # Expected default and alternate values
        set_default = {'verbose': 'False'}
        set_alternate = {'verbose': 'True'}

        # Services which are expected to restart upon config change,
        # and corresponding config files affected by the change
        conf_file = '/etc/nova/nova.conf'
        services = {'nova-compute': conf_file}

        if self._get_openstack_release() < self.xenial_ocata:
            services.update({
                'nova-api': conf_file,
                'nova-network': conf_file
            })

        # Make config change, check for service restarts
        u.log.debug('Making config change on {}...'.format(juju_service))
        mtime = u.get_sentry_time(sentry)
        self.d.configure(juju_service, set_alternate)
        self._auto_wait_for_status(exclude_services=self.exclude_services)

        sleep_time = 30
        for s, conf_file in services.iteritems():
            u.log.debug("Checking that service restarted: {}".format(s))
            if not u.validate_service_config_changed(sentry, mtime, s,
                                                     conf_file,
                                                     sleep_time=sleep_time):

                self.d.configure(juju_service, set_default)
                msg = "service {} didn't restart after config change".format(s)
                amulet.raise_status(amulet.FAIL, msg=msg)
            sleep_time = 0

        self.d.configure(juju_service, set_default)

    def test_910_pause_and_resume(self):
        """The services can be paused and resumed. """
        u.log.debug('Checking pause and resume actions...')
        sentry_unit = self.nova_compute_sentry

        assert u.status_get(sentry_unit)[0] == "active"

        action_id = u.run_action(sentry_unit, "pause")
        assert u.wait_on_action(action_id), "Pause action failed."
        assert u.status_get(sentry_unit)[0] == "maintenance"

        action_id = u.run_action(sentry_unit, "resume")
        assert u.wait_on_action(action_id), "Resume action failed."
        assert u.status_get(sentry_unit)[0] == "active"
        u.log.debug('OK')

    def test_920_change_aa_profile(self):
        """Test changing the Apparmor profile mode"""

        # Services which are expected to restart upon config change,
        # and corresponding config files affected by the change

        services = {
            'nova-compute': '/etc/apparmor.d/usr.bin.nova-compute',
        }

        if self._get_openstack_release() < self.xenial_ocata:
            services.update({
                'nova-network': '/etc/apparmor.d/usr.bin.nova-network',
                'nova-api': '/etc/apparmor.d/usr.bin.nova-api',
            })

        sentry = self.nova_compute_sentry
        juju_service = 'nova-compute'
        mtime = u.get_sentry_time(sentry)
        set_default = {'aa-profile-mode': 'enforce'}
        set_alternate = {'aa-profile-mode': 'complain'}
        sleep_time = 60

        # Change to complain mode
        self.d.configure(juju_service, set_alternate)
        self._auto_wait_for_status(exclude_services=self.exclude_services)

        for s, conf_file in services.iteritems():
            u.log.debug("Checking that service restarted: {}".format(s))
            if not u.validate_service_config_changed(sentry, mtime, s,
                                                     conf_file,
                                                     sleep_time=sleep_time):

                self.d.configure(juju_service, set_default)
                msg = "service {} didn't restart after config change".format(s)
                amulet.raise_status(amulet.FAIL, msg=msg)
            sleep_time = 0

        output, code = sentry.run('aa-status '
                                  '--complaining')
        u.log.info("Assert output of aa-status --complaining >= 3. Result: {} "
                   "Exit Code: {}".format(output, code))
        assert int(output) >= len(services)

    def test_930_check_virsh_default_network(self):
        """Verify that the default network created by libvirt was removed
           by the charm.
        """
        sentry = self.nova_compute_sentry
        output, code = sentry.run('virsh net-dumpxml default')
        u.log.info('Assert exit code of virsh net-dumpxml default != 0.'
                   'Result: {} Exit Code: {}'.format(output, code))
        assert code != 0
