"""Sidebar layout: the account being left hands its layout to the account being entered, and the shared-settings
merge cannot mix the two accounts' section lists together."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import cs_layout  # noqa: E402
import cs_share  # noqa: E402

KA, KB = "acctA/orgA", "acctB/orgB"


def cfg(key, names, pinned, other=None):
    sections = [{"id": "cg-" + n, "kind": "manual", "name": n} for n in names]
    return {"preferences": {
        "sidebarMode": "epitaxy",
        "menuBarEnabled": True,
        "epitaxyPrefs": {
            "dframe-code-sections": {key: {"sections": sections}, **(other or {})},
            "dframe-group-scopes": {key: {"groups": [{"id": "cg-" + n, "name": n} for n in names], "assignments": {}, "order": {}}},
            "dframe-local-slice": {"pinnedOrder": pinned},
            "starred-local-code-sessions": [],
            "keep-me": {"x": 1},
        }}}


class LayoutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        cs_layout.C.STATE_DIR = os.path.join(self.tmp.name, "state")
        os.environ["CS_STATE_DIR"] = cs_layout.C.STATE_DIR
        self.a, self.b = os.path.join(self.tmp.name, "A"), os.path.join(self.tmp.name, "B")
        os.makedirs(os.path.join(self.a, "claude-code-sessions", *KA.split("/")))
        os.makedirs(os.path.join(self.b, "claude-code-sessions", *KB.split("/")))
        self.conf = {"profiles": {"a": {"label": "A", "data_dir": self.a}, "b": {"label": "B", "data_dir": self.b}},
                     "sync_dirs": [os.path.join(self.a, "claude-code-sessions", *KA.split("/")),
                                   os.path.join(self.b, "claude-code-sessions", *KB.split("/"))]}

    def tearDown(self):
        os.environ.pop("CS_STATE_DIR", None)
        self.tmp.cleanup()

    def put(self, d, data):
        with open(os.path.join(d, cs_layout.CONFIG), "w") as f:
            json.dump(data, f, ensure_ascii=False)

    def get(self, d):
        with open(os.path.join(d, cs_layout.CONFIG)) as f:
            return json.load(f)["preferences"]["epitaxyPrefs"]

    def names(self, d, key):
        return [s["name"] for s in self.get(d)["dframe-code-sections"][key]["sections"]]

    def test_account_key(self):
        self.assertEqual(cs_layout.account_key(self.a, self.conf["sync_dirs"]), KA)
        self.assertIsNone(cs_layout.account_key("/nowhere", self.conf["sync_dirs"]))

    def test_switch_hands_layout_over_and_survives_the_merge(self):
        self.put(self.a, cfg(KA, ["옛 A 섹션 1", "옛 A 섹션 2"], ["old"]))
        self.put(self.b, cfg(KB, ["섹션 가", "섹션 나", "섹션 다"], ["p1", "p2"]))
        snap = cs_layout.before_share(self.conf, "b", "a")
        cs_share.share([self.a, self.b])  # the shared-settings merge, which unions list items
        msg = cs_layout.after_share(self.conf, "b", "a", snap)
        self.assertIn("synced", msg)
        self.assertEqual(self.names(self.a, KA), ["섹션 가", "섹션 나", "섹션 다"])  # entered account has B's layout
        self.assertEqual(self.names(self.b, KB), ["섹션 가", "섹션 나", "섹션 다"])  # left account is not mixed
        self.assertEqual(self.get(self.a)["dframe-local-slice"]["pinnedOrder"], ["p1", "p2"])
        self.assertEqual(self.get(self.a)["keep-me"], {"x": 1})  # unrelated entries stay

    def test_second_run_changes_nothing(self):
        self.put(self.a, cfg(KA, ["x"], ["o"]))
        self.put(self.b, cfg(KB, ["y"], ["p"]))
        snap = cs_layout.before_share(self.conf, "b", "a")
        cs_layout.after_share(self.conf, "b", "a", snap)
        snap = cs_layout.before_share(self.conf, "b", "a")
        self.assertIn("identical", cs_layout.after_share(self.conf, "b", "a", snap))

    def test_missing_layout_is_reported_not_raised(self):
        self.put(self.a, {"preferences": {}})
        self.put(self.b, {"preferences": {}})
        self.assertIsNone(cs_layout.before_share(self.conf, "b", "a"))
        self.assertIsNone(cs_layout.after_share(self.conf, "b", "a", None))

    def test_backup_is_kept_and_trimmed(self):
        self.put(self.a, cfg(KA, ["x"], ["o"]))
        self.put(self.b, cfg(KB, ["y"], ["p"]))
        for i in range(8):
            self.put(self.b, cfg(KB, ["y" + str(i)], ["p"]))
            cs_layout.after_share(self.conf, "b", "a", cs_layout.before_share(self.conf, "b", "a"))
        self.assertLessEqual(len(os.listdir(os.path.join(cs_layout.C.STATE_DIR, "layout-backups"))), cs_layout.KEEP_BACKUPS)


if __name__ == "__main__":
    unittest.main()
