#!/usr/bin/env python

import random
import time
import unittest
from queue import Queue
from unittest.mock import patch

from netils import build_byte_string

from tests.unit.faucet.test_valve import ValveTestBases

DOT1X_DP1_CONFIG = """
        dp_id: 1
        dot1x:
            nfv_intf: lo
            radius_ip: 127.0.0.1
            radius_port: 1812
            radius_secret: SECRET"""

DOT1X_CONFIG = """
acls:
    eapol_to_nfv:
        - rule:
            dl_type: 0x888e
            actions:
                output:
                    # set_fields:
                        # - eth_dst: NFV_MAC
                    port: p2
        - rule:
            eth_src: ff:ff:ff:ff:ff:ff
            actions:
                allow: 0
        - rule:
            actions:
                allow: 0
    eapol_from_nfv:
        - rule:
            dl_type: 0x888e
            # eth_dst: NFV_MAC
            actions:
                output:
                    # set_fields:
                        # - eth_dst: 01:80:c2:00:00:03
                    port: p1
        - rule:
            actions:
                allow: 0
    allowall:
        - rule:
            actions:
                allow: 1
dps:
    s1:
        hardware: 'GenericTFM'
%s
        interfaces:
            p1:
                number: 1
                native_vlan: v100
                dot1x: True
                acl_in: eapol_to_nfv
            p2:
                number: 2
                native_vlan: v100
                acl_in: eapol_from_nfv
            p3:
                number: 3
                native_vlan: v100
                acl_in: allowall
vlans:
    v100:
        vid: 0x100
""" % DOT1X_DP1_CONFIG

FROM_SUPPLICANT = Queue()
TO_SUPPLICANT = Queue()
FROM_RADIUS = Queue()
TO_RADIUS = Queue()


def supplicant_replies():
    header = "0000000000010242ac17006f888e"
    replies = [build_byte_string(header + "01000009027400090175736572"),
               build_byte_string(header + "010000160275001604103abcadc86714b2d75d09dd7ff53edf6b")]

    for r in replies:
        yield r


def radius_replies():
    replies = [build_byte_string("0b040050e5e40d846576a2310755e906c4b2b5064f180175001604101a16a3baa37a0238f33384f6c11067425012ce61ba97026b7a05b194a930a922405218126aa866456add628e3a55a4737872cad6"),
               build_byte_string("02050032fb4c4926caa21a02f74501a65c96f9c74f06037500045012c060ca6a19c47d0998c7b20fd4d771c1010675736572")]
    for r in replies:
        yield r


def urandom():
    _list = [b'\x87\xf5[\xa71\xeeOA;}\\t\xde\xd7.=',
             b'\xf7\xe0\xaf\xc7Q!\xa2\xa9\xa3\x8d\xf7\xc6\x85\xa8k\x06']
    for l in _list:
        yield l


URANDOM_GENERATOR = urandom()


def urandom_helper(size):
    return next(URANDOM_GENERATOR)


SUPPLICANT_REPLY_GENERATOR = supplicant_replies()
RADIUS_REPLY_GENERATOR = radius_replies()


def eap_receive(chewie):
    return FROM_SUPPLICANT.get()


def eap_send(chewie, data):
    TO_SUPPLICANT.put(data)
    try:
        n = next(SUPPLICANT_REPLY_GENERATOR)
    except StopIteration:
        return
    if n:
        FROM_SUPPLICANT.put(n)


def radius_receive(chewie):
    return FROM_RADIUS.get()


def radius_send(chewie, data):
    TO_RADIUS.put(data)
    try:
        n = next(RADIUS_REPLY_GENERATOR)
    except StopIteration:
        return
    if n:
        FROM_RADIUS.put(n)


def nextId(eap_sm):  # pylint: disable=invalid-name
    """Determines the next identifier value to use, based on the previous one.
    Returns:
        integer"""
    if eap_sm.currentId is None:
        # I'm assuming we cant have ids wrap around in the same series.
        #  so the 200 provides a large buffer.
        return 116
    _id = eap_sm.currentId + 1
    if _id > 255:
        return random.randint(0, 200)
    return _id


def get_next_radius_packet_id(chewie):
    """Calulate the next RADIUS Packet ID
    Returns:
        int
    """
    if chewie.radius_id == -1:
        chewie.radius_id = 4
        return chewie.radius_id
    chewie.radius_id += 1
    if chewie.radius_id > 255:
        chewie.radius_id = 0
    return chewie.radius_id


class FaucetDot1XTest(ValveTestBases.ValveTestSmall):
    """Test chewie api"""

    def setUp(self):
        self.setup_valve(DOT1X_CONFIG)

    @patch('faucet.faucet_dot1x.chewie.os.urandom', urandom_helper)
    @patch('faucet.faucet_dot1x.chewie.FullEAPStateMachine.nextId', nextId)
    @patch('faucet.faucet_dot1x.chewie.Chewie.get_next_radius_packet_id', get_next_radius_packet_id)
    @patch('faucet.faucet_dot1x.chewie.Chewie.radius_send', radius_send)
    @patch('faucet.faucet_dot1x.chewie.Chewie.radius_receive', radius_receive)
    @patch('faucet.faucet_dot1x.chewie.Chewie.eap_send', eap_send)
    @patch('faucet.faucet_dot1x.chewie.Chewie.eap_receive', eap_receive)
    def test_success_dot1x(self):
        """Test success api"""
        self.dot1x.reset(valves=self.valves_manager.valves)

        FROM_SUPPLICANT.put(build_byte_string("0000000000010242ac17006f888e01010000"))
        time.sleep(5)
        with open('%s/faucet.log' % self.tmpdir, 'r') as log:
            for l in log.readlines():
                if 'Successful auth' in l:
                    break
            else:
                self.fail('Cannot find "Successful auth" string in faucet.log')
        self.assertEqual(2,
                         len(self.last_flows_to_dp[1]))


if __name__ == "__main__":
    unittest.main()  # pytype: disable=module-attr