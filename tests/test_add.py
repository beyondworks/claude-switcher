"""`claude-switch add` names new accounts C, D, … and gives each its own data folder."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import cs_config as C  # noqa: E402
import claude_switch as cs  # noqa: E402


class AddTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.saved = {}
        for p in [mock.patch.object(C, "APP_SUPPORT", t),
                  mock.patch.object(C, "save", lambda c: self.saved.update(c)),
                  mock.patch.object(C, "STATE_DIR", os.path.join(t, "state")),
                  mock.patch.object(cs, "PENDING", os.path.join(t, "state", "pending-setup")),
                  mock.patch.object(cs.subprocess, "run")]:  # do not open a real Claude window
            p.start()
            self.addCleanup(p.stop)
        os.makedirs(os.path.join(t, "Claude Second"))
        self.conf = {"profiles": {"a": {"label": "A", "data_dir": C.PRIMARY_DATA},
                                  "b": {"label": "B", "data_dir": os.path.join(t, "Claude Second")}},
                     "sync_dirs": []}

    def tearDown(self):
        self.tmp.cleanup()

    def test_next_accounts_are_c_then_d(self):
        cs.cmd_add(self.conf, "Team")
        self.assertEqual(self.conf["profiles"]["c"]["label"], "Team")
        self.assertTrue(os.path.isdir(os.path.join(self.tmp.name, "Claude C")))
        cs.cmd_add(self.conf, "")
        self.assertEqual(self.conf["profiles"]["d"]["label"], "D")
        self.assertTrue(os.path.isdir(os.path.join(self.tmp.name, "Claude D")))
        # the window is opened with the new account's own data folder
        args = cs.subprocess.run.call_args[0][0]
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "state", "pending-setup")))
        self.assertIn(f"--user-data-dir={os.path.join(self.tmp.name, 'Claude D')}", args)

    def test_unfinished_b_is_reused_before_adding_c(self):
        os.rmdir(os.path.join(self.tmp.name, "Claude Second"))
        cs.cmd_add(self.conf, "Personal")
        self.assertNotIn("c", self.conf["profiles"])
        self.assertEqual(self.conf["profiles"]["b"]["label"], "Personal")


if __name__ == "__main__":
    unittest.main()
