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

    def test_first_merge_keeps_the_first_accounts_values(self):
        # B was just added: its fresh defaults are the newest file, but they are not changes
        self.put(self.a, {"preferences": {"sidebarMode": "custom", "keepAwakeEnabled": True}}, age=30)
        self.put(self.b, {"preferences": {"sidebarMode": "default", "keepAwakeEnabled": False, "onlyB": 1}})
        cs_share.share([self.a, self.b])
        for d in (self.a, self.b):
            self.assertEqual(self.get(d), {"preferences": {"sidebarMode": "custom", "keepAwakeEnabled": True, "onlyB": 1}})

    def test_joining_account_adds_but_never_overrides(self):
        c = os.path.join(self.tmp.name, "C")
        os.makedirs(c)
        self.put(self.a, {"sidebarMode": "custom", "trusted": ["/p1"]}, age=30)
        self.put(self.b, {"sidebarMode": "custom", "trusted": ["/p1"]}, age=30)
        cs_share.share([self.a, self.b])
        self.put(c, {"sidebarMode": "default", "trusted": ["/p3"], "onlyC": 1})
        cs_share.share([self.a, self.b, c])
        for d in (self.a, self.b, c):
            self.assertEqual(self.get(d), {"sidebarMode": "custom", "trusted": ["/p1", "/p3"], "onlyC": 1})
        self.put(c, {"sidebarMode": "changed-on-c", "trusted": ["/p1", "/p3"], "onlyC": 1})  # once merged, C's edits count
        cs_share.share([self.a, self.b, c])
        self.assertEqual(self.get(self.a)["sidebarMode"], "changed-on-c")

    def test_base_without_folder_record_counts_every_folder_as_merged(self):
        os.makedirs(cs_share._base_dir())
        self.put(cs_share._base_dir(), {"sidebarMode": "x"})
        self.put(self.a, {"sidebarMode": "old-change"}, age=30)
        self.put(self.b, {"sidebarMode": "new-change"})
        cs_share.share([self.a, self.b])
        self.assertEqual(self.get(self.a)["sidebarMode"], "new-change")

    def test_account_added_before_first_merge_after_upgrade_never_overrides(self):
        self.put(self.a, {"mcpServers": {"notion": {}}}, age=30)
        self.put(self.b, {"mcpServers": {"notion": {}}}, age=30)
        cs_share.share([self.a, self.b])
        os.remove(os.path.join(cs_share._base_dir(), cs_share.MERGED_DIRS))  # a base from a version without the record
        time.sleep(0.05)
        c = os.path.join(self.tmp.name, "C")  # created after that base was written
        os.makedirs(c)
        self.put(c, {"mcpServers": {}})
        cs_share.share([self.a, self.b, c])
        self.assertEqual(self.get(self.a), {"mcpServers": {"notion": {}}})

    def test_file_that_appears_after_first_merge_keeps_the_first_accounts_values(self):
        self.put(self.a, {"x": 1}, age=60)
        self.put(self.b, {"x": 1}, age=60)
        cs_share.share([self.a, self.b])
        self.put(self.a, {"allowDevTools": True}, name="developer_settings.json", age=30)
        self.put(self.b, {"allowDevTools": False}, name="developer_settings.json")  # the app's default, written later
        cs_share.share([self.a, self.b])
        self.assertEqual(self.get(self.a, "developer_settings.json"), {"allowDevTools": True})

    def test_same_folder_spelled_differently_is_still_merged(self):
        self.put(self.a, {"x": 1}, age=60)
        self.put(self.b, {"x": 1}, age=60)
        cs_share.share([self.a, self.b])
        self.put(self.a, {"x": 2})
        cs_share.share([self.a + os.sep, self.b])
        self.assertEqual(self.get(self.b), {"x": 2})

    def test_file_that_is_not_a_json_object_counts_as_unreadable(self):
        self.put(self.a, None, age=30)
        self.put(self.b, {"mcpServers": {"x": {}}})
        cs_share.share([self.a, self.b])
        self.assertEqual(self.get(self.a), {"mcpServers": {"x": {}}})

    def test_corrupt_folder_record_is_ignored(self):
        for raw in ("null", '"text"', '{"claude_desktop_config.json": [null, 3]}'):
            with self.subTest(record=raw):
                self.put(self.a, {"x": 1}, age=60)
                self.put(self.b, {"x": 1}, age=60)
                cs_share.share([self.a, self.b])
                with open(os.path.join(cs_share._base_dir(), cs_share.MERGED_DIRS), "w") as f:
                    f.write(raw)
                self.put(self.a, {"x": 2})
                cs_share.share([self.a, self.b])
                self.assertEqual(self.get(self.b), {"x": 2})

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
