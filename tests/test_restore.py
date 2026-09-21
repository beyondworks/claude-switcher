"""Tests for "open the account used last" (claude-switch restore)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import cs_config as C  # noqa: E402
import claude_switch as cs  # noqa: E402


class RestoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        b = os.path.join(self.tmp.name, "Claude Second")
        os.makedirs(b)
        self.conf = {"profiles": {"a": {"label": "A", "data_dir": C.PRIMARY_DATA},
                                  "b": {"label": "B", "data_dir": b}}, "sync_dirs": []}
        self.switched = []
        patches = [
            mock.patch.object(cs, "LAST", os.path.join(self.tmp.name, "last.json")),
            mock.patch.object(cs, "cmd_switch", lambda conf, t, yes, dry: self.switched.append((t, yes)) or 0),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        os.makedirs(C.STATE_DIR, exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()

    def restore_with(self, running, last):
        if last:
            cs.remember(last)
        with mock.patch.object(cs, "current", return_value=running):
            return cs.cmd_restore(self.conf)

    def test_default_opened_but_last_was_b(self):
        self.restore_with("a", "b")
        self.assertEqual(self.switched, [("b", True)])  # no busy prompt for a freshly opened app

    def test_last_was_a(self):
        self.restore_with("a", "a")
        self.assertEqual(self.switched, [])

    def test_disabled_in_config(self):
        self.conf["restore_last"] = False
        self.restore_with("a", "b")
        self.assertEqual(self.switched, [])

    def test_b_already_running(self):
        self.restore_with("b", "b")
        self.assertEqual(self.switched, [])

    def test_nothing_recorded(self):
        self.restore_with("a", None)
        self.assertEqual(self.switched, [])


if __name__ == "__main__":
    unittest.main()
