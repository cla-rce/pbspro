# coding: utf-8

# Copyright (C) 1994-2018 Altair Engineering, Inc.
# For more information, contact Altair at www.altair.com.
#
# This file is part of the PBS Professional ("PBS Pro") software.
#
# Open Source License Information:
#
# PBS Pro is free software. You can redistribute it and/or modify it under the
# terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# PBS Pro is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.
# See the GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# Commercial License Information:
#
# For a copy of the commercial license terms and conditions,
# go to: (http://www.pbspro.com/UserArea/agreement.html)
# or contact the Altair Legal Department.
#
# Altair’s dual-license business model allows companies, individuals, and
# organizations to create proprietary derivative works of PBS Pro and
# distribute them - whether embedded or bundled with other software -
# under a commercial license agreement.
#
# Use of Altair’s trademarks, including but not limited to "PBS™",
# "PBS Professional®", and "PBS Pro™" and Altair’s logos is subject to Altair's
# trademark licensing policies.

import time

from tests.functional import *
from ptl.utils.pbs_snaputils import *


class TestPBSSnapshot(TestFunctional):
    """
    Test suit with unit tests for the pbs_snapshot tool
    """
    pbs_snapshot_path = None
    snapdirs = []
    snaptars = []

    def setUp(self):
        TestFunctional.setUp(self)

        # Create a custom resource called 'ngpus'
        # This will help us test parts of PBSSnapUtils which handle resources
        attr = {"type": "long", "flag": "nh"}
        self.assertTrue(self.server.manager(MGR_CMD_CREATE, RSC, attr,
                                            id="ngpus", expect=True,
                                            sudo=True))

        # Check whether pbs_snapshot is accessible
        try:
            self.pbs_snapshot_path = os.path.join(
                self.server.pbs_conf["PBS_EXEC"], "sbin", "pbs_snapshot")
            ret = self.du.run_cmd(cmd=[self.pbs_snapshot_path, "-h"])
            if ret['rc'] != 0:
                self.pbs_snapshot_path = None
        except Exception:
            self.pbs_snapshot_path = None

        # Check whether the user has root access or not
        # pbs_snapshot only supports being run as root, so skip the entire
        # testsuite if the user doesn't have root privileges
        ret = self.du.run_cmd(
            cmd=["ls", os.path.join(os.sep, "root")], sudo=True)
        if ret['rc'] != 0:
            self.skipTest("pbs_snapshot/PBSSnapUtils need root privileges")

    def setup_sc(self, sched_id, partition, port,
                 sched_priv=None, sched_log=None):
        """
        Setup a scheduler

        :param sched_id: id of the scheduler
        :type sched_id: str
        :param partition: partition name for the scheduler (e.g "P1", "P1,P2")
        :type partition: str
        :param port: The port number string for the scheduler
        :type port: str
        :param sched_priv: 'sched_priv' (full path) for the scheduler
        :type sched_priv: str
        :param sched_log: 'sched_log' (full path) for the scheduler
        :type sched_log: str
        :param log_filter: log filter value for the scheduler
        :type log_filter: int
        """
        a = {'partition': partition,
             'sched_host': self.server.hostname,
             'sched_port': port}
        if sched_priv is not None:
            a['sched_priv'] = sched_priv
        if sched_log is not None:
            a['sched_log'] = sched_log
        self.server.manager(MGR_CMD_CREATE, SCHED, a, id=sched_id)
        if 'sched_priv' in a:
            sched_dir = os.path.dirname(sched_priv)
            self.scheds[sched_id].create_scheduler(sched_dir)
            self.scheds[sched_id].start(sched_dir)
        else:
            self.scheds[sched_id].create_scheduler()
            self.scheds[sched_id].start()
        self.server.manager(MGR_CMD_SET, SCHED,
                            {'scheduling': 'True'}, id=sched_id, expect=True)

    def setup_queues_nodes(self, num_partitions):
        """
        Given a no. of partitions, create equal no. of associated queues
        and nodes

        :param num_partitions: number of partitions
        :type num_partitions: int
        :return a tuple of lists of queue and node ids:
            ([q1, q1, ..], [n1, n2, ..])
        """
        queues = []
        nodes = []
        a_q = {"queue_type": "execution",
               "started": "True",
               "enabled": "True"}
        a_n = {"resources_available.ncpus": 2}
        self.server.create_vnodes("vnode", a_n, (num_partitions + 1),
                                  self.mom)
        for i in range(num_partitions):
            partition_id = "P" + str(i + 1)

            # Create queue i + 1 with partition i + 1
            id_q = "wq" + str(i + 1)
            queues.append(id_q)
            a_q["partition"] = partition_id
            self.server.manager(MGR_CMD_CREATE, QUEUE, a_q, id=id_q)

            # Set the partition i + 1 on node i
            id_n = "vnode[" + str(i) + "]"
            nodes.append(id_n)
            a = {"partition": partition_id}
            self.server.manager(MGR_CMD_SET, NODE, a, id=id_n, expect=True)

        return (queues, nodes)

    def take_snapshot(self, parent_dir, acct_logs=None, daemon_logs=None,
                      obfuscate=None):
        """
        Take a snapshot using pbs_snapshot command

        :param parent_dir: path to the directory where snapshot will be caught
        :type parent_dir: str
        :param acct_logs: Number of accounting logs to capture
        :type acct_logs: int
        :param daemon_logs: Number of daemon logs to capture
        :type daemon_logs: int
        :param obfuscate: Obfuscate information?
        :type obfuscate: bool
        :return a tuple of name of tarball and snapshot directory captured:
            (tarfile, snapdir)
        """
        if self.pbs_snapshot_path is None:
            self.skip_test("pbs_snapshot not found")

        snap_cmd = [self.pbs_snapshot_path, "-o", parent_dir]
        if acct_logs is not None:
            snap_cmd.append("--accounting-logs=" + str(acct_logs))

        if daemon_logs is not None:
            snap_cmd.append("--daemon-logs=" + str(daemon_logs))

        if obfuscate:
            snap_cmd.append("--obfuscate")

        ret = self.du.run_cmd(cmd=snap_cmd, sudo=True)
        self.assertEquals(ret['rc'], 0)

        # Get the name of the tarball that was created
        # pbs_snapshot prints to stdout only the following:
        #     "Snapshot available at: <path to tarball>"
        self.assertTrue(len(ret['out']) > 0)
        snap_out = ret['out'][0]
        output_tar = snap_out.split(":")[1]
        output_tar = output_tar.strip()

        # Check that the output tarball was created
        self.assertTrue(os.path.isfile(output_tar),
                        "%s not found" % (output_tar))

        # Unwrap the tarball
        tar = tarfile.open(output_tar)
        tar.extractall(path=parent_dir)
        tar.close()

        # snapshot directory name = <snapshot>.tgz[:-4]
        snap_dir = output_tar[:-4]

        # Check that the directory exists
        self.assertTrue(os.path.isdir(snap_dir))

        self.snapdirs.append(snap_dir)
        self.snaptars.append(output_tar)

        return (output_tar, snap_dir)

    def test_capture_server(self):
        """
        Test the 'capture_server' interface of PBSSnapUtils
        """

        # Set something on the server so we can match it later
        job_hist_duration = "12:00:00"
        attr_list = {"job_history_enable": "True",
                     "job_history_duration": job_hist_duration}
        self.server.manager(MGR_CMD_SET, SERVER, attr_list)

        target_dir = self.du.get_tempdir()
        num_daemon_logs = 2
        num_acct_logs = 5

        with PBSSnapUtils(out_dir=target_dir, acct_logs=num_acct_logs,
                          daemon_logs=num_daemon_logs) as snap_obj:
            snap_dir = snap_obj.capture_server(True, True)

            # Go through the snapshot and perform certain checks
            # Check 1: the snapshot exists
            self.assertTrue(os.path.isdir(snap_dir))
            # Check 2: all directories except the 'server' directory have no
            # files
            svr_fullpath = os.path.join(snap_dir, "server")
            for root, _, files in os.walk(snap_dir):
                for filename in files:
                    file_fullpath = os.path.join(root, filename)
                    # Find the common paths between 'server' & the file
                    common_path = os.path.commonprefix([file_fullpath,
                                                        svr_fullpath])
                    self.assertEquals(os.path.basename(common_path), "server")
            # Check 3: qstat_Bf.out exists
            qstat_bf_out = os.path.join(snap_obj.snapdir, QSTAT_BF_PATH)
            self.assertTrue(os.path.isfile(qstat_bf_out))
            # Check 4: qstat_Bf.out has 'job_history_duration' set to 24:00:00
            with open(qstat_bf_out, "r") as fd:
                for line in fd:
                    if "job_history_duration" in line:
                        # Remove whitespaces
                        line = "".join(line.split())
                        # Split it up by '='
                        key_val = line.split("=")
                        self.assertEquals(key_val[1], job_hist_duration)

        # Cleanup
        if os.path.isdir(snap_dir):
            self.du.rm(path=snap_dir, recursive=True, force=True)

    def test_capture_all(self):
        """
        Test the 'capture_all' interface of PBSSnapUtils

        WARNING: Assumes that the test is being run on type - 1 PBS install
        """
        target_dir = self.du.get_tempdir()
        num_daemon_logs = 2
        num_acct_logs = 5

        # Check that all PBS daemons are up and running
        all_daemons_up = self.server.isUp()
        all_daemons_up = all_daemons_up and self.mom.isUp()
        all_daemons_up = all_daemons_up and self.comm.isUp()
        all_daemons_up = all_daemons_up and self.scheduler.isUp()

        if not all_daemons_up:
            # Skip the test
            self.skipTest("Type 1 installation not present or " +
                          "all daemons are not running")

        with PBSSnapUtils(out_dir=target_dir, acct_logs=num_acct_logs,
                          daemon_logs=num_daemon_logs, sudo=True) as snap_obj:
            snap_dir = snap_obj.capture_all()
            snap_obj.finalize()

            # Test that all the expected information has been captured
            # PBSSnapUtils has various dictionaries which store metadata
            # for various objects. Create a list of these dicts
            all_info = [snap_obj.server_info, snap_obj.job_info,
                        snap_obj.node_info, snap_obj.comm_info,
                        snap_obj.hook_info, snap_obj.sched_info,
                        snap_obj.resv_info, snap_obj.datastore_info,
                        snap_obj.pbs_info, snap_obj.core_info,
                        snap_obj.sys_info]
            skip_list = [ACCT_LOGS, QMGR_LPBSHOOK_OUT, "reservation", "job",
                         QMGR_PR_OUT, PG_LOGS, "core_file_bt",
                         "pbs_snapshot.log"]
            platform = self.du.get_platform()
            if not platform.startswith("linux"):
                skip_list.extend([ETC_HOSTS, ETC_NSSWITCH_CONF, LSOF_PBS_OUT,
                                  VMSTAT_OUT, DF_H_OUT, DMESG_OUT])
            for item_info in all_info:
                for key, info in item_info.iteritems():
                    info_path = info[0]
                    if info_path is None:
                        continue
                    # Check if we should skip checking this info
                    skip_item = False
                    for item in skip_list:
                        if isinstance(item, int):
                            if item == key:
                                skip_item = True
                                break
                        else:
                            if item in info_path:
                                skip_item = True
                                break
                    if skip_item:
                        continue

                    # Check if this information was captured
                    info_full_path = os.path.join(snap_dir, info_path)
                    self.assertTrue(os.path.exists(info_full_path),
                                    msg=info_full_path + " was not captured")

        # Cleanup
        if os.path.isdir(snap_dir):
            self.du.rm(path=snap_dir, recursive=True, force=True)

    def test_capture_pbs_logs(self):
        """
        Test the 'capture_pbs_logs' interface of PBSSnapUtils
        """
        target_dir = self.du.get_tempdir()
        num_daemon_logs = 2
        num_acct_logs = 5

        # Check which PBS daemons are up on this machine.
        # We'll only check for logs from the daemons which were up
        # when the snapshot was taken.
        server_up = self.server.isUp()
        mom_up = self.mom.isUp()
        comm_up = self.comm.isUp()
        sched_up = self.scheduler.isUp()

        if not (server_up or mom_up or comm_up or sched_up):
            # Skip the test
            self.skipTest("No PBSPro daemons found on the system," +
                          " skipping the test")

        with PBSSnapUtils(out_dir=target_dir, acct_logs=num_acct_logs,
                          daemon_logs=num_daemon_logs) as snap_obj:
            snap_dir = snap_obj.capture_pbs_logs()

            # Perform some checks
            # Check that the snapshot exists
            self.assertTrue(os.path.isdir(snap_dir))
            if server_up:
                # Check that 'server_logs' were captured
                log_path = os.path.join(snap_dir, SVR_LOGS_PATH)
                self.assertTrue(os.path.isdir(log_path))
                # Check that 'accounting_logs' were captured
                log_path = os.path.join(snap_dir, ACCT_LOGS_PATH)
                self.assertTrue(os.path.isdir(log_path))
            if mom_up:
                # Check that 'mom_logs' were captured
                log_path = os.path.join(snap_dir, MOM_LOGS_PATH)
                self.assertTrue(os.path.isdir(log_path))
            if comm_up:
                # Check that 'comm_logs' were captured
                log_path = os.path.join(snap_dir, COMM_LOGS_PATH)
                self.assertTrue(os.path.isdir(log_path))
            if sched_up:
                # Check that 'sched_logs' were captured
                log_path = os.path.join(snap_dir, DFLT_SCHED_LOGS_PATH)
                self.assertTrue(os.path.isdir(log_path))

        if os.path.isdir(snap_dir):
            self.du.rm(path=snap_dir, recursive=True, force=True)

    def test_snapshot_basic(self):
        """
        Test capturing a snapshot via the pbs_snapshot program
        """
        if self.pbs_snapshot_path is None:
            self.skip_test("pbs_snapshot not found")

        parent_dir = self.du.get_tempdir()
        output_tar, _ = self.take_snapshot(parent_dir)

        # Check that the output tarball was created
        self.assertTrue(os.path.isfile(output_tar))

    def test_snapshot_without_logs(self):
        """
        Test capturing a snapshot via the pbs_snapshot program
        Capture no logs
        """
        if self.pbs_snapshot_path is None:
            self.skip_test("pbs_snapshot not found")

        parent_dir = self.du.get_tempdir()
        (_, snap_dir) = self.take_snapshot(parent_dir, 0, 0)

        # Check that 'server_logs' were not captured
        log_path = os.path.join(snap_dir, SVR_LOGS_PATH)
        self.assertTrue(not os.path.isdir(log_path))
        # Check that 'mom_logs' were not captured
        log_path = os.path.join(snap_dir, MOM_LOGS_PATH)
        self.assertTrue(not os.path.isdir(log_path))
        # Check that 'comm_logs' were not captured
        log_path = os.path.join(snap_dir, COMM_LOGS_PATH)
        self.assertTrue(not os.path.isdir(log_path))
        # Check that 'sched_logs' were not captured
        log_path = os.path.join(snap_dir, DFLT_SCHED_LOGS_PATH)
        self.assertTrue(not os.path.isdir(log_path))
        # Check that 'accounting_logs' were not captured
        log_path = os.path.join(snap_dir, ACCT_LOGS_PATH)
        self.assertTrue(not os.path.isdir(log_path))

    def test_obfuscate_resv_user_groups(self):
        """
        Test obfuscation of user & group related attributes while capturing
        snapshots via pbs_snapshot
        """
        if self.pbs_snapshot_path is None:
            self.skip_test("pbs_snapshot not found")

        now = int(time.time())

        # Let's submit a reservation with Authorized_Users and
        # Authorized_Groups set
        attribs = {ATTR_auth_u: TEST_USER1, ATTR_auth_g: TSTGRP0,
                   ATTR_l + ".ncpus": 2, 'reserve_start': now + 25,
                   'reserve_end': now + 45}
        resv_obj = Reservation(attrs=attribs)
        resv_id = self.server.submit(resv_obj)
        attribs = {'reserve_state': (MATCH_RE, 'RESV_CONFIRMED|2')}
        self.server.expect(RESV, attribs, id=resv_id)

        # Now, take a snapshot with --obfuscate
        parent_dir = self.du.get_tempdir()
        (_, snap_dir) = self.take_snapshot(parent_dir, 0, 0, True)

        # Make sure that the pbs_rstat -f output captured doesn't have the
        # Authorized user and group names
        pbsrstat_path = os.path.join(snap_dir, PBS_RSTAT_F_PATH)
        self.assertTrue(os.path.isfile(pbsrstat_path))
        with open(pbsrstat_path, "r") as rstatfd:
            all_content = rstatfd.read()
            self.assertFalse(str(TEST_USER1) in all_content)
            self.assertFalse(str(TSTGRP0) in all_content)

    def test_multisched_support(self):
        """
        Test that pbs_snapshot can capture details of all schedulers
        """
        if self.pbs_snapshot_path is None:
            self.skip_test("pbs_snapshot not found")

        # Setup 3 schedulers
        sched_ids = ["sc1", "sc2", "sc3", "default"]
        self.setup_sc(sched_ids[0], "P1", "15050")
        self.setup_sc(sched_ids[1], "P2", "15051")
        # Setup scheduler at non-default location
        dir_path = os.path.join(os.sep, 'var', 'spool', 'pbs', 'sched_dir')
        if not os.path.exists(dir_path):
            self.du.mkdir(path=dir_path, sudo=True)
        sched_priv = os.path.join(dir_path, 'sched_priv_sc3')
        sched_log = os.path.join(dir_path, 'sched_logs_sc3')
        self.setup_sc(sched_ids[2], "P3", "15052", sched_priv, sched_log)

        # Add 3 partitions, each associated with a queue and a node
        (q_ids, _) = self.setup_queues_nodes(3)

        # Submit some jobs to fill the system up and get the multiple
        # schedulers busy
        for q_id in q_ids:
            for _ in range(2):
                attr = {"queue": q_id, "Resource_List.ncpus": "1"}
                j = Job(TEST_USER1, attrs=attr)
                self.server.submit(j)

        # Capture a snapshot of the system with multiple schedulers
        target_dir = self.du.get_tempdir()
        (_, snapdir) = self.take_snapshot(target_dir)

        # Check that sched priv and sched logs for all schedulers was captured
        for sched_id in sched_ids:
            if (sched_id == "default"):
                schedi_priv = os.path.join(snapdir, DFLT_SCHED_PRIV_PATH)
                schedi_logs = os.path.join(snapdir, DFLT_SCHED_LOGS_PATH)
            else:
                schedi_priv = os.path.join(snapdir, "sched_priv_" + sched_id)
                schedi_logs = os.path.join(snapdir, "sched_logs_" + sched_id)

            self.assertTrue(os.path.isdir(schedi_priv))
            self.assertTrue(os.path.isdir(schedi_logs))

            # Make sure that these directories are not empty
            self.assertTrue(len(os.listdir(schedi_priv)) > 0)
            self.assertTrue(len(os.listdir(schedi_logs)) > 0)

        # Check that qmgr -c "l sched" captured information about all scheds
        lschedpath = os.path.join(snapdir, QMGR_LSCHED_PATH)
        with open(lschedpath, "r") as fd:
            scheds_found = 0
            for line in fd:
                if line.startswith("Sched "):
                    sched_id = line.split("Sched ")[1]
                    sched_id = sched_id.strip()
                    self.assertTrue(sched_id in sched_ids)
                    scheds_found += 1
            self.assertEqual(scheds_found, 4)

    def test_snapshot_from_hook(self):
        """
        Test that pbs_snapshot can be called from inside a hook
        """
        logmsg = "pbs_snapshot was successfully run"
        hook_body = """
import pbs
import os
import subprocess
import time

pbs_snap_exec = os.path.join(pbs.pbs_conf['PBS_EXEC'], "sbin", "pbs_snapshot")
if not os.path.isfile(pbs_snap_exec):
    raise ValueError("pbs_snapshot executable not found")

ref_time = time.time()
snap_cmd = [pbs_snap_exec, "-o", "."]
assert(not subprocess.call(snap_cmd))

# Check that the snapshot was captured
snapshot_found = False
for filename in os.listdir("."):
    if filename.startswith("snapshot") and filename.endswith(".tgz"):
        # Make sure the mtime on this file is recent enough
        mtime_file = os.path.getmtime(filename)
        if mtime_file > ref_time:
            snapshot_found = True
            break
assert(snapshot_found)
pbs.logmsg(pbs.EVENT_DEBUG,"%s")
""" % (logmsg)
        hook_name = "snapshothook"
        attr = {"event": "periodic", "freq": 5}
        rv = self.server.create_import_hook(hook_name, attr, hook_body,
                                            overwrite=True)
        self.assertTrue(rv)
        self.server.log_match(logmsg)

    @classmethod
    def tearDownClass(self):
        # Delete the snapshot directories and tarballs created
        for snap_dir in self.snapdirs:
            self.du.rm(path=snap_dir, recursive=True, force=True)
        for snap_tar in self.snaptars:
            self.du.rm(path=snap_tar, sudo=True, force=True)

        TestFunctional.tearDownClass()
