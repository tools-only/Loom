import unittest

from loom.timing_stats import compute_stages


class TimingStatsTests(unittest.TestCase):
    def test_flattens_main_stages_and_server_timings(self):
        result = compute_stages({
            "t0_click": 0,
            "t1_built": 2,
            "t2_sent": 3,
            "t3_ack": 8,
            "t4_thinking": 10,
            "t5_patch": 120,
            "t6_dom": 125,
            "server": {
                "ms_hand_agent": 40,
                "ms_loom_agent": 70,
                "ms_broadcast": 1,
            },
        })

        self.assertEqual(
            [stage["name"] for stage in result["stages"]],
            [
                "Build Envelope",
                "WS -> Server ACK",
                "ACK -> Thinking",
                "Hand Agent",
                "Loom Agent -> Browser",
                "broadcast patches",
                "Patch -> DOM Done",
            ],
        )
        self.assertEqual(result["server_timings"], [])

    def test_keeps_legacy_server_timings_when_no_hand_agent(self):
        result = compute_stages({
            "t0_click": 0,
            "t1_built": 2,
            "t2_sent": 3,
            "t3_ack": 8,
            "t4_thinking": 10,
            "t5_patch": 120,
            "t6_dom": 125,
            "server": {
                "ms_claude_gen": 55,
                "ms_op_to_resolve": 7,
                "ms_broadcast": 2,
            },
        })

        self.assertEqual(
            [stage["name"] for stage in result["stages"]],
            [
                "Build Envelope",
                "WS -> Server ACK",
                "ACK -> Thinking",
                "op recv -> CC dispatched",
                "CC dispatch -> anchor_patch",
                "broadcast patches",
                "Patch -> DOM Done",
            ],
        )
        self.assertEqual(result["server_timings"], [])


if __name__ == "__main__":
    unittest.main()
