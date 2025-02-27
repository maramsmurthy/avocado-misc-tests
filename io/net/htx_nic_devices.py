#!/usr/bin/env python

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
# See LICENSE for more details.
# Copyright: 2017 IBM
# Author: Pridhiviraj Paidipeddi <ppaidipe@linux.vnet.ibm.com>
# Author: Vaishnavi Bhat <vaishnavi@linux.vnet.ibm.com>
# this script run IO stress on nic devices for give time.

import os
import re
import time

from avocado import Test
from avocado.utils import distro
from avocado.utils import process
from avocado.utils.software_manager.manager import SoftwareManager
from avocado.utils import build
from avocado.utils import archive
from avocado.utils.process import CmdError
from avocado.utils.network.interfaces import NetworkInterface
from avocado.utils.network.hosts import LocalHost, RemoteHost
from avocado.utils.ssh import Session


class HtxNicTest(Test):

    """
    HTX [Hardware Test eXecutive] is a test tool suite. The goal of HTX is to
    stress test the system by exercising all hardware components concurrently
    in order to uncover any hardware design flaws and hardware hardware or
    hardware-software interaction issues.
    :see:https://github.com/open-power/HTX.git
    :param mdt_file: mdt file used to trigger HTX
    :params time_limit: how much time(hours) you want to run this stress.
    :param host_public_ip: Public IP address of host
    :param peer_public_ip: Public IP address of peer
    :param peer_password: password of peer for peer_user user
    :param peer_user: User name of Peer
    :param host_interfaces: Host N/W Interface's to run HTX on
    :param peer_interfaces: Peer N/W Interface's to run HTX on
    :param net_ids: Net id's of N/W Interface's
    """

    def setUp(self):
        """
        Set up
        """
        if 'ppc64' not in process.system_output('uname -a', ignore_status=True,
                                                shell=True,
                                                sudo=True).decode("utf-8"):
            self.cancel("Platform does not support HTX tests")

        self.localhost = LocalHost()
        self.parameters()
        if 'start' in str(self.name.name):
            for ipaddr, interface in zip(self.ipaddr, self.host_intfs):
                networkinterface = NetworkInterface(interface, self.localhost)
                try:
                    networkinterface.add_ipaddr(ipaddr, self.netmask)
                    networkinterface.save(ipaddr, self.netmask)
                except Exception:
                    networkinterface.save(ipaddr, self.netmask)
                networkinterface.bring_up()
        self.host_distro = distro.detect()
        self.host_distro_name = self.host_distro.name
        self.host_distro_version = self.host_distro.version
        self.session = Session(self.peer_ip, user=self.peer_user,
                               password=self.peer_password)
        if not self.session.connect():
            self.cancel("failed connecting to peer")
        self.remotehost = RemoteHost(self.peer_ip, self.peer_user,
                                     password=self.peer_password)

        self.get_peer_distro()
        self.get_peer_distro_version()
        self.htx_rpm_link = self.params.get('htx_rpm_link', default=None)

    def get_peer_distro_version(self):
        """
        Get the distro version installed on peer lpar
        """
        detected_distro = distro.detect(session=self.session)
        self.peer_distro_version = detected_distro.version

    def get_peer_distro(self):
        """
        Get the distro installed on peer lpar
        """
        detected_distro = distro.detect(session=self.session)
        if detected_distro.name == "Ubuntu":
            self.peer_distro = "Ubuntu"
        elif detected_distro.name == "rhel":
            self.peer_distro = "rhel"
        elif detected_distro.name == "SuSE":
            self.peer_distro = "SuSE"
        else:
            self.fail("Unknown peer distro type")
        self.log.info("Peer distro is %s", self.peer_distro)

    def build_htx(self):
        """
        Build 'HTX'
        """
        packages = ['git', 'gcc', 'make', 'wget']
        detected_distro = distro.detect()
        if detected_distro.name in ['centos', 'fedora', 'rhel', 'redhat']:
            packages.extend(['gcc-c++', 'ncurses-devel', 'tar'])
        elif detected_distro.name == "Ubuntu":
            packages.extend(['libncurses5', 'g++', 'ncurses-dev',
                             'libncurses-dev', 'tar', 'wget'])
        elif detected_distro.name == 'SuSE':
            packages.extend(['libncurses5', 'gcc-c++',
                            'ncurses-devel', 'tar', 'wget'])
        else:
            self.cancel("Test not supported in  %s" % detected_distro.name)

        smm = SoftwareManager()
        for pkg in packages:
            if not smm.check_installed(pkg) and not smm.install(pkg):
                self.cancel("Can not install %s" % pkg)
            cmd = "%s install %s" % (smm.backend.base_command, pkg)
            output = self.session.cmd(cmd)
            if not output.exit_status == 0:
                self.cancel(
                    "Unable to install the package %s on peer machine" % pkg)

        if self.htx_rpm_link:
            host_distro_pattern = "%s%s" % (
                                            self.host_distro_name,
                                            self.host_distro_version)
            peer_distro_pattern = "%s%s" % (
                                            self.peer_distro,
                                            self.peer_distro_version)
            patterns = [host_distro_pattern, peer_distro_pattern]
            for pattern in patterns:
                temp_string = process.getoutput(
                              "curl --silent %s" % (self.htx_rpm_link),
                              verbose=False, shell=True, ignore_status=True)
                matching_htx_versions = re.findall(
                    r"(?<=\>)htx\w*[-]\d*[-]\w*[.]\w*[.]\w*", str(temp_string))
                distro_specific_htx_versions = [htx_rpm
                                                for htx_rpm
                                                in matching_htx_versions
                                                if pattern in htx_rpm]
                distro_specific_htx_versions.sort(reverse=True)
                self.latest_htx_rpm = distro_specific_htx_versions[0]

                if pattern == host_distro_pattern:
                    if process.system('rpm -ivh --nodeps %s%s '
                                      '--force' % (
                                       self.htx_rpm_link, self.latest_htx_rpm
                                       ), shell=True, ignore_status=True):
                        self.cancel("Installion of rpm failed")

                if pattern == peer_distro_pattern:
                    cmd = ('rpm -ivh --nodeps %s%s '
                           '--force' % (self.htx_rpm_link,
                                        self.latest_htx_rpm))
                    output = self.session.cmd(cmd)
                    if not output.exit_status == 0:
                        self.cancel("Unable to install the package %s %s"
                                    " on peer machine" % (self.htx_rpm_link,
                                                          self.latest_htx_rpm))
        else:
            url = "https://github.com/open-power/HTX/archive/master.zip"
            tarball = self.fetch_asset("htx.zip", locations=[url], expire='7d')
            archive.extract(tarball, self.teststmpdir)
            htx_path = os.path.join(self.teststmpdir, "HTX-master")
            os.chdir(htx_path)

            exercisers = ["hxecapi_afu_dir", "hxecapi", "hxeocapi"]
            if not smm.check_installed('dapl-devel'):
                exercisers.append("hxedapl")
            for exerciser in exercisers:
                process.run("sed -i 's/%s//g' %s/bin/Makefile" % (exerciser,
                                                                  htx_path))
            build.make(htx_path, extra_args='all')
            build.make(htx_path, extra_args='tar')
            process.run('tar --touch -xvzf htx_package.tar.gz')
            os.chdir('htx_package')
            if process.system('./installer.sh -f'):
                self.fail("Installation of htx fails:please refer job.log")

            # Installing htx on peer
            self.session.cmd("wget %s -O /tmp/master.zip" % url)
            self.session.cmd("cd /tmp")
            self.session.cmd("unzip master.zip")
            self.session.cmd("cd HTX-master")
            for exerciser in exercisers:
                self.session.cmd("sed -i 's/%s//g' bin/Makefile" % exerciser)
            self.session.cmd("make all")
            self.session.cmd("make tar")
            self.session.cmd("tar --touch -xvzf htx_package.tar.gz")
            self.session.cmd("cd htx_package")
            self.session.cmd("./installer.sh -f")

    def parameters(self):
        self.host_intfs = []
        self.host_ip = self.params.get("host_public_ip", '*', default=None)
        self.peer_ip = self.params.get("peer_public_ip", '*', default=None)
        self.peer_user = self.params.get("peer_user", '*', default=None)
        self.peer_password = self.params.get("peer_password",
                                             '*', default=None)
        devices = self.params.get("htx_host_interfaces", '*', default=None)
        if devices:
            interfaces = os.listdir('/sys/class/net')
        for device in devices.split(" "):
            if device in interfaces:
                self.host_intfs.append(device)
            elif self.localhost.validate_mac_addr(device) and device in self.localhost.get_all_hwaddr():
                self.host_intfs.append(self.localhost.get_interface_by_hwaddr(device).name)
            else:
                self.cancel("Please check the network device")
        self.peer_intfs = self.params.get("peer_interfaces",
                                          '*', default=None).split(" ")
        self.net_ids = self.params.get("net_ids", '*', default=None).split(" ")
        self.mdt_file = self.params.get("mdt_file", '*', default="net.mdt")
        self.time_limit = int(self.params.get("time_limit",
                                              '*', default=2)) * 60
        self.query_cmd = "htxcmdline -query -mdt %s" % self.mdt_file
        self.ipaddr = self.params.get("host_ips", default="").split(" ")
        self.netmask = self.params.get("netmask", default="")
        self.peer_ips = self.params.get("peer_ips", default="").split(" ")
        self.htx_url = self.params.get("htx_rpm", default="")

    def test_start(self):
        """
        This test will be in two phases
        Phase 1: Configure all necessary pre-setup steps for both the
                 interfaces in both Host & Peer
        Phase 2: Start the HTX setup & execution of test.
        """
        self.build_htx()
        self.setup_htx_nic()
        self.run_htx()

    def test_check(self):
        self.monitor_htx_run()

    def test_stop(self):
        self.htx_cleanup()

    def setup_htx_nic(self):
        self.update_host_peer_names()
        self.generate_bpt_file()
        self.check_bpt_file_existence()
        self.update_otherids_in_bpt()
        self.update_net_ids_in_bpt()
        self.htx_configure_net()

    def update_host_peer_names(self):
        """
        Update hostname & ip of both Host & Peer in /etc/hosts file of both
        Host & Peer
        """
        host_name = process.system_output("hostname",
                                          ignore_status=True,
                                          shell=True,
                                          sudo=True).decode("utf-8")
        cmd = "hostname"
        output = self.session.cmd(cmd)
        peer_name = output.stdout.decode("utf-8")
        hosts_file = '/etc/hosts'
        self.log.info("Updating hostname of both Host & Peer in \
                      %s file", hosts_file)
        with open(hosts_file, 'r') as file:
            filedata = file.read().splitlines()
        search_str1 = "%s %s.*" % (self.host_ip, host_name)
        search_str2 = "%s %s.*" % (self.peer_ip, peer_name)
        add_str1 = "%s %s" % (self.host_ip, host_name)
        add_str2 = "%s %s" % (self.peer_ip, peer_name)

        for index, line in enumerate(filedata):
            filedata[index] = line.replace('\t', ' ')

        filedata = "\n".join(filedata)
        obj = re.search(search_str1, filedata)
        if not obj:
            filedata = "%s\n%s" % (filedata, add_str1)

        obj = re.search(search_str2, filedata)
        if not obj:
            filedata = "%s\n%s" % (filedata, add_str2)

        with open(hosts_file, 'w') as file:
            for line in filedata:
                file.write(line)

        destination = "%s:/etc" % self.peer_ip
        output = self.session.copy_files(hosts_file, destination)
        if not output:
            self.fail("unable to copy the file into peer machine")

    def generate_bpt_file(self):
        """
        Generates bpt file in both Host & Peer
        """
        self.log.info("Generating bpt file in both Host & Peer")
        cmd = "/usr/bin/build_net help n"
        self.session.cmd(cmd)
        exit_code = process.run(
            cmd, shell=True, sudo=True, ignore_status=True).exit_status
        if exit_code == 0 or exit_code == 43:
            return True
        else:
            self.fail("Command %s failed with exit status %s " %
                      (cmd, exit_code))

    def check_bpt_file_existence(self):
        """
        Verifies the bpt file existence in both Host & Peer
        """
        self.bpt_file = '/usr/lpp/htx/bpt'
        cmd = "ls %s" % self.bpt_file
        res = self.session.cmd(cmd)
        if "No such file or directory" in res.stdout.decode("utf-8"):
            self.fail("bpt file not generated in peer lpar")
        try:
            process.run(cmd, shell=True, sudo=True)
        except CmdError as details:
            msg = "Command %s failed %s, bpt file %s doesn't \
                  exist in host" % (cmd, details, self.bpt_file)
            self.fail(msg)

    def update_otherids_in_bpt(self):
        """
        Update host ip in peer bpt file & peer ip in host bpt file
        """
        # Update other id's in host lpar
        with open(self.bpt_file, 'r') as file:
            filedata = file.read()
        search_str1 = "other_ids=%s:" % self.host_ip
        replace_str1 = "%s%s" % (search_str1, self.peer_ip)

        filedata = re.sub(search_str1, replace_str1, filedata)
        with open(self.bpt_file, 'w') as file:
            for line in filedata:
                file.write(line)

        # Update other id's in peer lpar
        search_str2 = "other_ids=%s:" % self.peer_ip
        replace_str2 = "%s%s" % (search_str2, self.host_ip)
        self.session.cmd("hostname")
        filedata = self.session.cmd("cat %s" % self.bpt_file)
        filedata = filedata.stdout.decode("utf-8")
        filedata = filedata.splitlines()

        for index, line in enumerate(filedata):
            obj = re.search(search_str2, line)
            if obj:
                filedata[index] = replace_str2
                break

        else:
            self.fail("Failed to get other_ids string in peer lpar")

        filedata = "\n".join(filedata)
        self.session.cmd("echo \"%s\" > %s" % (filedata, self.bpt_file))
        self.session.cmd("cat %s" % self.bpt_file)

    def update_net_ids_in_bpt(self):
        """
        Update net id's in both Host & Peer bpt file for both N/W interfaces
        """
        # Update net id in host lpar
        with open(self.bpt_file, 'r') as file:
            filedata = file.read()
        for (host_intf, net_id) in zip(self.host_intfs, self.net_ids):
            search_str = "%s n" % host_intf
            replace_str = "%s %s" % (host_intf, net_id)
            filedata = re.sub(search_str, replace_str, filedata)
        with open(self.bpt_file, 'w') as file:
            for line in filedata:
                file.write(line)

        # Update net id in peer lpar
        filedata = self.session.cmd("cat %s" % self.bpt_file)
        filedata = filedata.stdout.decode("utf-8")
        filedata = filedata.splitlines()

        for (peer_intf, net_id) in zip(self.peer_intfs, self.net_ids):
            search_str = "%s n" % peer_intf
            replace_str = "%s %s" % (peer_intf, net_id)

            for index, line in enumerate(filedata):
                obj = re.search(search_str, line)
                if obj:
                    string = re.sub(search_str, replace_str, line)
                    filedata[index] = string
                    break

            else:
                self.fail("Failed to get %s net_id in peer bpt" % peer_intf)

        filedata = "\n".join(filedata)
        self.session.cmd("echo \"%s\" > %s" % (filedata, self.bpt_file))

    def ip_config(self):
        """
        configuring ip for host and peer interfaces
        """
        for (host_intf, net_id) in zip(self.host_intfs, self.net_ids):
            ip_addr = "%s.1.1.%s" % (net_id, self.host_ip.split('.')[-1])
            networkinterface = NetworkInterface(host_intf, self.localhost)
            try:
                networkinterface.add_ipaddr(ip_addr, self.netmask)
                networkinterface.save(ip_addr, self.netmask)
            except Exception:
                networkinterface.save(ip_addr, self.netmask)
            networkinterface.bring_up()

        for (peer_intf, net_id) in zip(self.peer_intfs, self.net_ids):
            ip_addr = "%s.1.1.%s" % (net_id, self.peer_ip.split('.')[-1])
            peer_networkinterface = NetworkInterface(
                peer_intf, self.remotehost)
            peer_networkinterface.add_ipaddr(ip_addr, self.netmask)
            peer_networkinterface.bring_up()

    def htx_configure_net(self):
        self.log.info("Starting the N/W ping test for HTX in Host")
        cmd = "build_net %s" % self.bpt_file
        output = process.system_output(cmd, ignore_status=True, shell=True,
                                       sudo=True)
        output = output.decode("utf-8")
        host_obj = re.search("All networks ping Ok", output)

        # Try up to 10 times until pingum test passes
        for count in range(11):
            if count == 0:
                try:
                    peer_output = self.session.cmd(cmd)
                    peer_output = peer_output.stdout.decode("utf-8")
                    peer_obj = re.search("All networks ping Ok", peer_output)
                except Exception:
                    self.log.info("build_net command failed in peer")
            if host_obj is not None:
                if self.peer_distro == "rhel":
                    self.session.cmd("systemctl start NetworkManager")
                else:
                    self.session.cmd("systemctl restart network")
                if self.host_distro == "rhel":
                    process.system("systemctl start NetworkManager",
                                   shell=True,
                                   ignore_status=True)
                else:
                    process.system("systemctl restart network", shell=True,
                                   ignore_status=True)
                output = process.system_output("pingum", ignore_status=True,
                                               shell=True, sudo=True)
            else:
                break
            time.sleep(30)
        else:
            self.log.info("manually configuring ip because of pingum failed.")
            self.ip_config()

        self.log.info("Starting the N/W ping test for HTX in Peer")
        for count in range(11):
            if peer_obj is not None:
                try:
                    self.session.cmd("pingum")
                except Exception:
                    self.log.info("Pingum failed on peer lpar")
            else:
                break
            time.sleep(30)

        self.log.info("N/W ping test for HTX passed in both Host & Peer")

    def run_htx(self):
        self.start_htx_deamon()
        self.shutdown_active_mdt()
        self.generate_mdt_files()
        self.select_net_mdt()
        self.query_net_devices_in_mdt()
        self.suspend_all_net_devices()
        self.activate_mdt()
        self.is_net_devices_active()
        self.start_htx_run()

    def start_htx_deamon(self):
        cmd = '/usr/lpp/htx/etc/scripts/htxd_run'
        self.log.info("Starting the HTX Deamon in Host")
        process.run(cmd, shell=True, sudo=True)

        self.log.info("Starting the HTX Deamon in Peer")
        self.session.cmd(cmd)

    def generate_mdt_files(self):
        self.log.info("Generating mdt files in Host")
        cmd = "htxcmdline -createmdt"
        process.run(cmd, shell=True, sudo=True)

        self.log.info("Generating mdt files in Peer")
        self.session.cmd(cmd)

    def select_net_mdt(self):
        self.log.info("Selecting the htx %s file in Host", self.mdt_file)
        cmd = "htxcmdline -select -mdt %s" % self.mdt_file
        process.run(cmd, shell=True, sudo=True)

        self.log.info("Selecting the htx %s file in Peer", self.mdt_file)
        self.session.cmd(cmd)

    def query_net_devices_in_mdt(self):
        self.is_net_devices_in_host_mdt()
        self.is_net_devices_in_peer_mdt()

    def is_net_devices_in_host_mdt(self):
        '''
        verifies the presence of given net devices in selected mdt file
        '''
        self.log.info("Checking host_interfaces presence in %s",
                      self.mdt_file)
        output = process.system_output(self.query_cmd, shell=True,
                                       sudo=True).decode("utf-8")
        absent_devices = []
        for intf in self.host_intfs:
            if intf not in output:
                absent_devices.append(intf)
        if absent_devices:
            self.log.info("net_devices %s are not avalable in host %s ",
                          absent_devices, self.mdt_file)
            self.fail("HTX fails to list host n/w interfaces")

        self.log.info("Given host net interfaces %s are available in %s",
                      self.host_intfs, self.mdt_file)

    def is_net_devices_in_peer_mdt(self):
        '''
        verifies the presence of given net devices in selected mdt file
        '''
        self.log.info("Checking peer_interfaces presence in %s",
                      self.mdt_file)
        output = self.session.cmd(self.query_cmd)
        output = output.stdout.decode("utf-8")
        absent_devices = []
        for intf in self.peer_intfs:
            if intf not in output:
                absent_devices.append(intf)
        if absent_devices:
            self.log.info("net_devices %s are not avalable in peer %s ",
                          absent_devices, self.mdt_file)
            self.fail("HTX fails to list peer n/w interfaces")

        self.log.info("Given peer net interfaces %s are available in %s",
                      self.peer_intfs, self.mdt_file)

    def activate_mdt(self):
        self.log.info("Activating the N/W devices with mdt %s in Host",
                      self.mdt_file)
        cmd = "htxcmdline -activate all -mdt %s" % self.mdt_file
        try:
            process.run(cmd, shell=True, sudo=True)
        except CmdError as details:
            self.log.debug("Activation of N/W devices (%s) failed in Host",
                           self.mdt_file)
            self.fail("Command %s failed %s" % (cmd, details))

        self.log.info("Activating the N/W devices with mdt %s in Peer",
                      self.mdt_file)
        try:
            self.session.cmd(cmd)
        except Exception:
            self.log.debug("Activation of N/W devices (%s) failed in Peer",
                           self.mdt_file)
            self.fail("Command %s failed" % cmd)

    def is_net_devices_active(self):
        if not self.is_net_device_active_in_host():
            self.fail("Net devices are failed to activate in Host \
                       after HTX activate")
        if not self.is_net_device_active_in_peer():
            self.fail("Net devices are failed to activate in Peer \
                       after HTX activate")

    def start_htx_run(self):
        self.log.info("Running the HTX for %s on Host", self.mdt_file)
        cmd = "htxcmdline -run -mdt %s" % self.mdt_file
        process.run(cmd, shell=True, sudo=True)

        self.log.info("Running the HTX for %s on Peer", self.mdt_file)
        self.session.cmd(cmd)

    def monitor_htx_run(self):
        for time_loop in range(0, self.time_limit, 60):
            self.log.info("Monitoring HTX Error logs in Host")
            cmd = 'htxcmdline -geterrlog'
            process.run(cmd, ignore_status=True,
                        shell=True, sudo=True)
            if os.stat('/tmp/htxerr').st_size != 0:
                self.fail("Their are errors while htx run in host")
            self.log.info("Monitoring HTX Error logs in Peer")
            self.session.cmd(cmd)
            output = self.session.cmd('test -s /tmp/htxerr')
            if not output.exit_status == 0:
                rc = False
            else:
                rc = True
            if rc:
                output = self.session.cmd("cat /tmp/htxerr")
                self.log.debug("HTX error log in peer: %s\n",
                               "\n".join(output.stdout.decode("utf-8")))
                self.fail("Their are errors while htx run in peer")
            self.log.info("Status of N/W devices after every 60 sec")
            process.system(self.query_cmd, ignore_status=True,
                           shell=True, sudo=True)

            output = self.session.cmd(self.query_cmd)
            if not output.exit_status == 0:
                self.log.info("query o/p in peer lpar\n %s", "\n".join(output))
            time.sleep(60)

    def shutdown_active_mdt(self):
        self.log.info("Shutdown active mdt in host")
        cmd = "htxcmdline -shutdown"
        process.run(cmd, timeout=120, ignore_status=True,
                    shell=True, sudo=True)
        self.log.info("Shutdown active mdt in peer")
        output = self.session.cmd(cmd)
        if not output.exit_status == 0:
            pass

    def suspend_all_net_devices(self):
        self.suspend_all_net_devices_in_host()
        self.suspend_all_net_devices_in_peer()

    def suspend_all_net_devices_in_host(self):
        '''
        Suspend the Net devices, if active.
        '''
        self.log.info("Suspending net_devices in host if any running")
        self.susp_cmd = "htxcmdline -suspend all  -mdt %s" % self.mdt_file
        process.run(self.susp_cmd, ignore_status=True, shell=True, sudo=True)

    def suspend_all_net_devices_in_peer(self):
        '''
        Suspend the Net devices, if active.
        '''
        self.log.info("Suspending net_devices in peer if any running")
        cmd = "htxcmdline -suspend all  -mdt %s" % self.mdt_file
        output = self.session.cmd(cmd)
        if not output.exit_status == 0:
            pass

    def is_net_device_active_in_host(self):
        '''
        Verifies whether the net devices are active or not in host
        '''
        self.log.info("Checking whether all net_devices are active or \
                      not in host ")
        output = process.system_output(self.query_cmd, ignore_status=True,
                                       shell=True,
                                       sudo=True).decode("utf-8").split('\n')
        active_devices = []
        for line in output:
            for intf in self.host_intfs:
                if intf in line and 'ACTIVE' in line:
                    active_devices.append(intf)
        non_active_device = list(set(self.host_intfs) - set(active_devices))
        if non_active_device:
            return False
        else:
            self.log.info("Active N/W devices in Host %s", active_devices)
            return True

    def is_net_device_active_in_peer(self):
        '''
        Verifies whether the net devices are active or not in peer
        '''
        self.log.info("Checking whether all net_devices are active or \
                      not in peer")
        output = self.session.cmd(self.query_cmd)
        if not output.exit_status == 0:
            pass
        active_devices = []
        output = output.stdout.decode("utf-8").splitlines()
        for line in output:
            for intf in self.peer_intfs:
                if intf in line and 'ACTIVE' in line:
                    active_devices.append(intf)
        non_active_device = list(set(self.peer_intfs) - set(active_devices))
        if non_active_device:
            return False
        else:
            self.log.info("Active N/W devices in Peer %s", active_devices)
            return True

    def shutdown_htx_daemon(self):
        status_cmd = '/usr/lpp/htx/etc/scripts/htx.d status'
        shutdown_cmd = '/usr/lpp/htx/etc/scripts/htxd_shutdown'
        daemon_state = process.system_output(status_cmd, ignore_status=True,
                                             shell=True,
                                             sudo=True).decode("utf-8")
        if daemon_state.split(" ")[-1] == 'running':
            process.system(shutdown_cmd, ignore_status=True,
                           shell=True, sudo=True)
        try:
            output = self.session.cmd(status_cmd)
        except Exception:
            self.log.info("Unable to get peer htxd status")
        if not output.exit_status == 0:
            pass
        line = output.stdout.decode("utf-8").splitlines()
        if 'running' in line[0]:
            self.session.cmd(shutdown_cmd)
            if not output.exit_status == 0:
                pass

    def clean_state(self):
        '''
        Reset bpt, suspend and shutdown the active mdt
        '''
        self.log.info("Resetting bpt file in both Host & Peer")
        cmd = "/usr/bin/build_net help n"
        self.session.cmd(cmd)
        exit_code = process.run(
            cmd, shell=True, sudo=True, ignore_status=True).exit_status
        if exit_code == 0 or exit_code == 43:
            return True
        else:
            self.fail("Command %s failed with exit status %s " %
                      (cmd, exit_code))

        if self.is_net_device_active_in_host():
            self.suspend_all_net_devices_in_host()
            self.log.info("Shutting down the %s in host", self.mdt_file)
            cmd = 'htxcmdline -shutdown -mdt %s' % self.mdt_file
            process.system(cmd, timeout=120, ignore_status=True,
                           shell=True, sudo=True)
        if self.is_net_device_active_in_peer():
            self.suspend_all_net_devices_in_peer()
            self.log.info("Shutting down the %s in peer", self.mdt_file)
            try:
                output = self.session.cmd(cmd)
            except Exception:
                self.log.info("Unable to shutdown the mdt")
            if not output.exit_status == 0:
                pass

        self.session.cmd("rm -rf /tmp/HTX-master")

    def ip_restore_host(self):
        '''
        restoring ip for host
        '''
        for ipaddr, interface in zip(self.ipaddr, self.host_intfs):
            cmd = "ip addr flush %s" % interface
            process.run(cmd, ignore_status=True, shell=True, sudo=True)
            networkinterface = NetworkInterface(interface, self.localhost)
            networkinterface.add_ipaddr(ipaddr, self.netmask)
            networkinterface.save(ipaddr, self.netmask)
            networkinterface.bring_up()

    def ip_restore_peer(self):
        '''
        config ip for peer
        '''
        for ip, interface in zip(self.peer_ips, self.peer_intfs):
            peer_networkinterface = NetworkInterface(
                interface, self.remotehost)
            try:
                cmd = "ip addr flush %s" % interface
                self.session.cmd(cmd)
                peer_networkinterface.add_ipaddr(ip, self.netmask)
                peer_networkinterface.save(ip, self.netmask)
            except Exception:
                peer_networkinterface.save(ip, self.netmask)
            peer_networkinterface.bring_up()

    def htx_cleanup(self):
        self.clean_state()
        self.shutdown_htx_daemon()
        self.ip_restore_host()
        self.ip_restore_peer()
        self.remotehost.remote_session.quit()
