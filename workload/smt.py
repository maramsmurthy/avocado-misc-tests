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
# Copyright: 2023 IBM
# Author: Samir A Mulani <samir@linux.vnet.ibm.com>

from avocado import Test
from avocado.utils import process, distro
from avocado.utils.software_manager.manager import SoftwareManager
import os


class smt(Test):
    """
    smt workload
    """

    def setUp(self):
        if 'ppc' not in distro.detect().arch:
            self.cancel("Processor is not powerpc")
        sm = SoftwareManager()
        self.time_in_minutes = self.params.get('time_in_minutes', default=5)
        self.detected_distro = distro.detect()
        if not sm.check_installed("powerpc-utils") and \
                not sm.install("powerpc-utils"):
            self.cancel("powerpc-utils is needed for the test to be run")
        smt_op = process.run("ppc64_cpu --smt", shell=True,
                             ignore_status=True).stderr.decode("utf-8")
        if "is not SMT capable" in smt_op:
            self.cancel("Machine is not SMT capable, skipping the test")
        distro_name = self.detected_distro.name
        distro_ver = self.detected_distro.version
        distro_rel = self.detected_distro.release
        if distro_name == "rhel":
            if (distro_ver == "7" or
                    (distro_ver == "8" and distro_rel < "4")):
                self.cancel("smtstate tool is supported only after RHEL8.4")
        elif distro_name == "SuSE":
            if (distro_ver == "12" or (distro_ver == "15" and distro_rel < 3)):
                self.cancel("smtstate tool is supported only after SLES15 SP3")
        else:
            self.cancel("Test case is supported only on RHEL and SLES")

    def test_smt_start(self):
        """
        Start the SMT Workload
        """
        relative_path = 'smt.py.data/smt.sh'
        absolute_path = os.path.abspath(relative_path)
        smt_workload = "bash " + absolute_path + " &> /tmp/smt.log &"
        process.run(
            smt_workload, ignore_status=True, sudo=True, shell=True)
        self.log.info("SMT Workload started--!!")

    def test_smt_stop(self):
        """
        Kill the SMT workload
        """
        grep_cmd = "grep -i {}".format("smt.sh")
        process_kill = 'ps aux | {} | awk "{{ print $2 }}" | \
                xargs kill'.format(grep_cmd)
        process.run(process_kill, ignore_status=True,
                    sudo=True, shell=True)
        self.log.info("SMT Workload killed successfully--!!")
