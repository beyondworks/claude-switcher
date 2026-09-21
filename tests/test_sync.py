"""Tests for the sync engine and log-based folder detection. Run: python3 -m unittest discover tests"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import cs_config  # noqa: E402
import cs_sync  # noqa: E402


def write(path, text):
    with open(path, "w") as f:
        f.write(text)


def read(path):
    with open(path) as f:
        return f.read()


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.dirs = [os.path.join(root, n) for n in ("a", "b", "c")]
        for d in self.dirs:
            os.makedirs(d)
        os.environ["CS_STATE_DIR"] = os.path.join(root, "state")
        for i in range(12):
            for d in self.dirs:
                write(os.path.join(d, f"local_{i}.json"), f"s{i}")
        self.assertEqual(cs_sync.sync(self.dirs), 0)

    def tearDown(self):
        self.tmp.cleanup()

    def run_sync(self):
        return cs_sync.sync(self.dirs)

    def test_new_session_reaches_every_folder(self):
        write(os.path.join(self.dirs[2], "local_new.json"), "new")
        self.run_sync()
        for d in self.dirs:
            self.assertEqual(read(os.path.join(d, "local_new.json")), "new")

    def test_newest_edit_wins(self):
        p = os.path.join(self.dirs[1], "local_1.json")
        write(p, "archived")
        future = time.time() + 5
        os.utime(p, (future, future))
        self.run_sync()
        for d in self.dirs:
            self.assertEqual(read(os.path.join(d, "local_1.json")), "archived")

    def test_delete_propagates_to_trash_not_oblivion(self):
        os.remove(os.path.join(self.dirs[0], "local_2.json"))
        self.run_sync()
        for d in self.dirs:
            self.assertFalse(os.path.exists(os.path.join(d, "local_2.json")))
        trashed = [f for _, _, fs in os.walk(os.path.join(os.environ["CS_STATE_DIR"], "trash")) for f in fs]
        self.assertIn("local_2.json", trashed)

    def test_mass_delete_is_refused(self):
        for i in range(3, 10):
            os.remove(os.path.join(self.dirs[2], f"local_{i}.json"))
        self.assertEqual(self.run_sync(), 2)
        self.assertTrue(os.path.exists(os.path.join(self.dirs[0], "local_3.json")))

    def test_symlinked_folder_is_refused(self):
        link = os.path.join(self.tmp.name, "link")
        os.symlink(self.dirs[0], link)
        self.assertEqual(cs_sync.sync([link, self.dirs[1]]), 1)

    def test_new_folder_set_merges_without_deleting(self):
        extra = os.path.join(self.tmp.name, "d")
        os.makedirs(extra)
        write(os.path.join(extra, "local_only_here.json"), "x")
        self.assertEqual(cs_sync.sync(self.dirs + [extra]), 0)
        self.assertTrue(os.path.exists(os.path.join(self.dirs[0], "local_only_here.json")))
        self.assertTrue(os.path.exists(os.path.join(extra, "local_0.json")))


class DetectTest(unittest.TestCase):
    def test_reads_account_org_folders_from_log(self):
        with tempfile.TemporaryDirectory() as t:
            data_a, data_b = os.path.join(t, "Claude"), os.path.join(t, "Claude Second")
            acct, org = "aaaaaaaa-0000-4000-8000-000000000001", "0000000a-0000-4000-8000-00000000000a"
            acct2, org2 = "bbbbbbbb-0000-4000-8000-000000000002", "0000000b-0000-4000-8000-00000000000b"
            acct3 = "11111111-2222-3333-4444-555555555555"
            log = os.path.join(t, "main.log")
            write(log, "\n".join([
                f"2026-09-21 11:40:00 [info] Loaded 0 persisted sessions from {data_a}/claude-code-sessions/{acct}/{org2}",
                f"2026-09-21 11:48:52 [info] Loaded 151 persisted sessions from {data_a}/claude-code-sessions/{acct}/{org}",
                f"2026-09-21 11:48:51 [info] Loaded 122 persisted sessions from {data_a}/local-agent-mode-sessions/{acct}/{org}",
                f"2026-09-21 12:12:24 [info] Loaded 113 persisted sessions from {data_b}/claude-code-sessions/{acct2}/{org2}",
                f"2026-09-21 12:12:25 [info] Loaded 9 persisted sessions from /elsewhere/claude-code-sessions/{acct}/{org}",
                f"2026-09-21 12:13:00 [info] Loaded 151 persisted sessions from {data_a}/claude-code-sessions/{acct}/{org}",
                # logging out: the app briefly reads another org of the same account AFTER the real one
                f"2026-09-21 12:14:00 [info] Loaded 0 persisted sessions from {data_a}/claude-code-sessions/{acct}/{org2}",
                # a brand-new account has only ever read one empty folder
                f"2026-09-21 12:15:00 [info] Loaded 0 persisted sessions from {data_b}/claude-code-sessions/{acct3}/{org}",
            ]))
            found = cs_config.detect_session_dirs([data_a, data_b], log)
            self.assertEqual(sorted(found), sorted([
                f"{data_a}/claude-code-sessions/{acct}/{org}",
                f"{data_b}/claude-code-sessions/{acct2}/{org2}",
                f"{data_b}/claude-code-sessions/{acct3}/{org}",
            ]))


if __name__ == "__main__":
    unittest.main()
