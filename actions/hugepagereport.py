#!/usr/bin/python
#
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

import sys

sys.path.append('hooks')

import subprocess
from charmhelpers.core import hookenv

SYSFS = '/sys'
KERNELCMD = '/proc/cmdline'


def hugepages_report():
    '''Action to return current hugepage usage and kernel cmdline for static
    hugepage allocation. Takes no params.
    '''
    outmap = {}
    try:
        devp = "{}/devices/system/node/node*/hugepages/*/*".format(SYSFS)
        outmap['hugepagestats'] = subprocess.check_output(
            "grep -H . {}".format(devp),
            shell=True).decode('UTF-8')
    except subprocess.CalledProcessError as e:
        hookenv.log(e)
        hookenv.action_fail(
            "Getting hugepages report failed: {}".format(e.message)
        )
    with open(KERNELCMD, 'rb') as cmdline:
        try:
            outmap['kernelcmd'] = cmdline.read().strip()
        except IOError as e:
            hookenv.action_fail('Could not read {}: {}'.format(KERNELCMD, e))
            return
    hookenv.action_set(outmap)

if __name__ == '__main__':
    hugepages_report()
