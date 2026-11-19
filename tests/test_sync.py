"""Tests for the sync engine and log-based folder detection. Run: python3 -m unittest discover tests"""
import json
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


class RemoteControlIdsTest(unittest.TestCase):
    """bridgeSessionIds name claude.ai sessions of the account that created them. The app reuses the
    last one; another account's cannot be reused, so the app opens a new claude.ai session that lacks
    the session's title. Each account must keep its own."""

    NAME = "local_s.json"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.a, self.b = (os.path.join(self.tmp.name, n) for n in ("a", "b"))
        for d in (self.a, self.b):
            os.makedirs(d)
        os.environ["CS_STATE_DIR"] = os.path.join(self.tmp.name, "state")

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, d, session, age=0):
        p = os.path.join(d, self.NAME)
        write(p, json.dumps(session, ensure_ascii=False, separators=(",", ":")))
        t = time.time() + age
        os.utime(p, (t, t))
        return p

    def load(self, d):
        return json.loads(read(os.path.join(d, self.NAME)))

    def test_edit_keeps_the_receiving_accounts_ids(self):
        for b_ids in (["session_b1"], None):
            with self.subTest(b_ids=b_ids):
                b = {"title": "Old", "isArchived": False}
                if b_ids is not None:
                    b["bridgeSessionIds"] = b_ids
                self.put(self.b, b)
                self.put(self.a, {"title": "New", "bridgeSessionIds": ["session_a1", "session_a2"], "isArchived": True}, age=5)
                self.assertEqual(cs_sync.sync([self.a, self.b]), 0)
                got = self.load(self.b)
                self.assertEqual((got["title"], got["isArchived"]), ("New", True))
                self.assertEqual(got.get("bridgeSessionIds"), b_ids)
                self.assertEqual(self.load(self.a)["bridgeSessionIds"], ["session_a1", "session_a2"])

    def test_new_session_reaches_other_account_without_ids(self):
        self.put(self.a, {"title": "Fresh", "bridgeSessionIds": ["session_a1"]})
        cs_sync.sync([self.a, self.b])
        self.assertEqual(self.load(self.b), {"title": "Fresh"})

    def test_ids_alone_never_count_as_a_change(self):
        """Copies that differ only in their own ids are in sync: nothing is copied either way,
        including when the app appends an id on one account."""
        self.put(self.a, {"title": "T", "bridgeSessionIds": ["session_a1"]})
        self.put(self.b, {"title": "T", "bridgeSessionIds": ["session_b1"]}, age=-5)
        cs_sync.sync([self.a, self.b])
        self.put(self.b, {"title": "T", "bridgeSessionIds": ["session_b1", "session_b2"]}, age=5)
        before = {d: os.path.getmtime(os.path.join(d, self.NAME)) for d in (self.a, self.b)}
        cs_sync.sync([self.a, self.b])
        self.assertEqual(self.load(self.a)["bridgeSessionIds"], ["session_a1"])
        self.assertEqual(self.load(self.b)["bridgeSessionIds"], ["session_b1", "session_b2"])
        self.assertEqual({d: os.path.getmtime(os.path.join(d, self.NAME)) for d in (self.a, self.b)}, before)

    def test_written_like_the_app_and_dated_like_the_source(self):
        """Compact UTF-8 JSON, as the app writes it, with the source's modification time, so the
        newest-wins rule does not bounce the merged copy back on the next run."""
        self.put(self.b, {"title": "x", "bridgeSessionIds": ["session_b1"]})
        src = self.put(self.a, {"title": "새 이름", "n": 1}, age=5)
        cs_sync.sync([self.a, self.b])
        dst = os.path.join(self.b, self.NAME)
        self.assertEqual(read(dst), '{"title":"새 이름","n":1,"bridgeSessionIds":["session_b1"]}')
        self.assertEqual(os.path.getmtime(dst), os.path.getmtime(src))

    def test_other_files_are_copied_byte_for_byte(self):
        text = '{\n  "bridgeSessionIds": ["session_a1"]\n}\n'
        write(os.path.join(self.a, "scheduled-tasks.json"), text)
        cs_sync.sync([self.a, self.b])
        self.assertEqual(read(os.path.join(self.b, "scheduled-tasks.json")), text)


class DetectTest(unittest.TestCase):
    def test_reads_account_org_folders_from_log(self):
        J = os.path.join
        with tempfile.TemporaryDirectory() as t:
            data_a, data_b = os.path.join(t, "Claude"), os.path.join(t, "Claude Second")
            acct, org = "aaaaaaaa-0000-4000-8000-000000000001", "0000000a-0000-4000-8000-00000000000a"
            acct2, org2 = "bbbbbbbb-0000-4000-8000-000000000002", "0000000b-0000-4000-8000-00000000000b"
            acct3 = "11111111-2222-3333-4444-555555555555"
            log = os.path.join(t, "main.log")
            write(log, "\n".join([
                f"2026-09-21 11:40:00 [info] Loaded 0 persisted sessions from {J(data_a, "claude-code-sessions", acct, org2)}",
                f"2026-09-21 11:48:52 [info] Loaded 151 persisted sessions from {J(data_a, "claude-code-sessions", acct, org)}",
                f"2026-09-21 11:48:51 [info] Loaded 122 persisted sessions from {J(data_a, "local-agent-mode-sessions", acct, org)}",
                f"2026-09-21 12:12:24 [info] Loaded 113 persisted sessions from {J(data_b, "claude-code-sessions", acct2, org2)}",
                f"2026-09-21 12:12:25 [info] Loaded 9 persisted sessions from /elsewhere/claude-code-sessions/{acct}/{org}",
                f"2026-09-21 12:13:00 [info] Loaded 151 persisted sessions from {J(data_a, "claude-code-sessions", acct, org)}",
                # logging out: the app briefly reads another org of the same account AFTER the real one
                f"2026-09-21 12:14:00 [info] Loaded 0 persisted sessions from {J(data_a, "claude-code-sessions", acct, org2)}",
                # a brand-new account has only ever read one empty folder
                f"2026-09-21 12:15:00 [info] Loaded 0 persisted sessions from {J(data_b, "claude-code-sessions", acct3, org)}",
            ]))
            found = cs_config.detect_session_dirs([data_a, data_b], log)
            self.assertEqual(sorted(found), sorted([
                J(data_a, "claude-code-sessions", acct, org),
                J(data_b, "claude-code-sessions", acct2, org2),
                J(data_b, "claude-code-sessions", acct3, org),
            ]))


    def test_falls_back_to_folders_on_disk(self):
        """A data folder the log says nothing about: per account, the org folder with the most sessions."""
        with tempfile.TemporaryDirectory() as t:
            root = os.path.join(t, "Claude C", "claude-code-sessions", "cccccccc-0000-4000-8000-000000000003")
            busy, empty = os.path.join(root, "0000000c-0000-4000-8000-00000000000c"), os.path.join(root, "0000000d-0000-4000-8000-00000000000d")
            os.makedirs(busy)
            for n in range(3):
                write(os.path.join(busy, f"local_{n}.json"), "{}")
            os.makedirs(empty)
            self.assertEqual(cs_config.detect_session_dirs([os.path.join(t, "Claude C")], os.path.join(t, "none.log")), [busy])


if __name__ == "__main__":
    unittest.main()
