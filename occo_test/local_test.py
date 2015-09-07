#
# Copyright (C) 2014 MTA SZTAKI
#
# Unit tests for the SZTAKI Cloud Orchestrator
#

import unittest
from common import *
import occo.infraprocessor as ip
import occo.plugins.infraprocessor.basic_infraprocessor
import occo.plugins.infraprocessor.node_resolution.chef_cloudinit
import occo.util as util
import threading
import occo.util.factory as factory
from occo.infobroker.uds import UDS
import occo.infobroker as ib

class LocalTest(unittest.TestCase):
    def setUp(self):
        self.ib = DummyInfoBroker(main_info_broker=True)
        ib.real_main_uds = UDS.instantiate(protocol='dict')
        ib.real_main_servicecomposer = DummyServiceComposer(self.ib)
        ib.real_main_cloudhandler = DummyCloudHandler(self.ib)
    def test_create_infrastructure(self):
        infrap = ip.InfraProcessor.instantiate('basic')
        eid = uid()
        cmd = infrap.cri_create_infrastructure(eid)
        infrap.push_instructions(cmd)
        self.assertEqual(repr(self.ib), '{0}:[]'.format(eid))
    def test_create_node(self):
        infrap = ip.InfraProcessor.instantiate('basic')
        eid = uid()
        node = DummyNode(eid)
        cmd_cre = infrap.cri_create_infrastructure(eid)
        cmd_crn = infrap.cri_create_node(node)
        infrap.push_instructions(cmd_cre)
        node = infrap.push_instructions(cmd_crn)[0]
        self.assertEqual(
            repr(self.ib),
            '{0}:[{1}_True]'.format(eid, node['node_id']))
    def test_drop_node(self):
        infrap = ip.InfraProcessor.instantiate('basic')
        eid = uid()
        node = DummyNode(eid)
        cmd_cre = infrap.cri_create_infrastructure(eid)
        cmd_crn = infrap.cri_create_node(node)
        infrap.push_instructions(cmd_cre)
        node = infrap.push_instructions(cmd_crn)[0]
        cmd_rmn = infrap.cri_drop_node(node)
        infrap.push_instructions(cmd_rmn)
        self.assertEqual(repr(self.ib), '{0}:[]'.format(eid))
    def test_drop_infrastructure(self):
        infrap = ip.InfraProcessor.instantiate('basic')
        eid = uid()
        node = DummyNode(eid)
        cmd_cre = infrap.cri_create_infrastructure(eid)
        cmd_crn = infrap.cri_create_node(node)
        infrap.push_instructions(cmd_cre)
        node = infrap.push_instructions(cmd_crn)[0]
        cmd_rmn = infrap.cri_drop_node(node)
        cmd_rme = infrap.cri_drop_infrastructure(eid)
        infrap.push_instructions(cmd_rmn)
        infrap.push_instructions(cmd_rme)
        self.assertEqual(repr(self.ib), '')
    def test_create_multiple_nodes(self):
        infrap = ip.InfraProcessor.instantiate('basic')
        eid = uid()
        nodes = list(DummyNode(eid) for i in xrange(5))
        cmd_cre = infrap.cri_create_infrastructure(eid)
        cmd_crns = (infrap.cri_create_node(node) for node in nodes)
        infrap.push_instructions(cmd_cre)
        nodes = infrap.push_instructions(cmd_crns)
        self.assertEqual(len(self.ib.environments), 1)
        self.assertEqual(len(self.ib.environments.values()[0]), 5)
    def test_cancel_pending(self):
        # Coverage only
        infrap = ip.InfraProcessor.instantiate('basic')
        infrap.cancel_pending()
    def test_synchstrategies(self):
        infrap = ip.InfraProcessor.instantiate('basic')
        eid = uid()
        node_1 = DummyNode(eid)
        node_2 = DummyNode(eid, node_type='synch1')
        cmd_cre = infrap.cri_create_infrastructure(eid)
        cmd_crns = [infrap.cri_create_node(node_1),
                    infrap.cri_create_node(node_2)]
        infrap.push_instructions(cmd_cre)
        infrap.push_instructions(cmd_crns)
