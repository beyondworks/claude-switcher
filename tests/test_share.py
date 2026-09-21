"""Shared desktop settings: every account folder ends up with the same settings files."""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import cs_share  # noqa: E402


class ShareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["CS_STATE_DIR"] = os.path.join(self.tmp.name, "state")
        self.a, self.b = os.path.join(self.tmp.name, "A"), os.path.join(self.tmp.name, "B")
        os.makedirs(self.a)
        os.makedirs(self.b)

    def tearDown(self):
        os.environ.pop("CS_STATE_DIR")
        self.tmp.cleanup()

    def put(self, d, data, name="claude_desktop_config.json", age=0):
        p = os.path.join(d, name)
        with open(p, "w") as f:
            json.dump(data, f)
        t = time.time() - age
        os.utime(p, (t, t))

    def get(self, d, name="claude_desktop_config.json"):
        with open(os.path.join(d, name)) as f:
            return json.load(f)

    def test_first_run_unions_everything(self):
        self.put(self.a, {"mcpServers": {"notion": {"command": "x"}}, "preferences": {"trusted": ["/p1"], "starred": {"s1": 1}}}, age=10)
        self.put(self.b, {"mcpServers": {}, "preferences": {"trusted": ["/p2"], "starred": {"s2": 1}}})
        cs_share.share([self.a, self.b])
        for d in (self.a, self.b):
            c = self.get(d)
            self.assertEqual(c["mcpServers"], {"notion": {"command": "x"}})
            self.assertEqual(sorted(c["preferences"]["trusted"]), ["/p1", "/p2"])
            self.assertEqual(c["preferences"]["starred"], {"s1": 1, "s2": 1})

    def test_removal_on_one_side_propagates(self):
        self.put(self.a, {"mcpServers": {"notion": {}, "figma": {}}, "list": [1, 2]})
        self.put(self.b, {"mcpServers": {"notion": {}, "figma": {}}, "list": [1, 2]})
        cs_share.share([self.a, self.b])
        self.put(self.b, {"mcpServers": {"notion": {}}, "list": [2]})  # removed figma and 1 while on B
        cs_share.share([self.a, self.b])
        self.assertEqual(self.get(self.a), {"mcpServers": {"notion": {}}, "list": [2]})

    def test_conflict_newest_file_wins(self):
        self.put(self.a, {"sidebarMode": "x"})
        self.put(self.b, {"sidebarMode": "x"})
        cs_share.share([self.a, self.b])
        self.put(self.a, {"sidebarMode": "old-change"}, age=30)
        self.put(self.b, {"sidebarMode": "new-change"})
        cs_share.share([self.a, self.b])
        self.assertEqual(self.get(self.a)["sidebarMode"], "new-change")

    def test_folder_without_the_file_receives_it(self):
        self.put(self.a, {"allowDevTools": True}, name="developer_settings.json")
        cs_share.share([self.a, self.b])
        self.assertEqual(self.get(self.b, "developer_settings.json"), {"allowDevTools": True})

    def test_login_file_is_never_touched(self):
        self.put(self.a, {"oauth:tokenCache": "A"}, name="config.json")
        self.put(self.b, {"oauth:tokenCache": "B"}, name="config.json")
        cs_share.share([self.a, self.b])
        self.assertEqual(self.get(self.b, "config.json"), {"oauth:tokenCache": "B"})


if __name__ == "__main__":
    unittest.main()
