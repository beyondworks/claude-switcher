"""Account unify: after the merge, the base account's account-keyed values are copied onto the other accounts."""
import glob
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import cs_share  # noqa: E402

A, B, C = "aaaaaaaa-0000-0000-0000-000000000000", "bbbbbbbb-0000-0000-0000-000000000000", "cccccccc-0000-0000-0000-000000000000"


def config(sections, groups, modes, gate, extra=None):
    epi = {"dframe-code-sections": sections, "dframe-group-scopes": groups, **modes, "starred-local-code-sessions": ["local_1"]}
    return {"preferences": {"epitaxyPrefs": epi, "bypassPermissionsGateByAccount": gate, "sidebarMode": "code", **(extra or {})}}


class UnifyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["CS_STATE_DIR"] = os.path.join(self.tmp.name, "state")
        self.dirs = []
        for n in ("Claude", "Claude Second", "Claude C"):
            d = os.path.join(self.tmp.name, n)
            os.makedirs(d)
            self.dirs.append(d)

    def tearDown(self):
        os.environ.pop("CS_STATE_DIR")
        self.tmp.cleanup()

    def put(self, d, data, name="claude_desktop_config.json"):
        with open(os.path.join(d, name), "w") as f:
            json.dump(data, f)

    def get(self, d, name="claude_desktop_config.json"):
        with open(os.path.join(d, name)) as f:
            return json.load(f)

    def test_base_values_reach_every_account_and_files_match(self):
        sections = {f"{A}/o1": [{"id": "s-old"}], f"{B}/o2": [{"id": "s1"}, {"id": "s2"}], f"{C}/o3": [{"id": "s3"}], "dddddddd-x/o4": [{"id": "other"}]}
        groups = {f"{A}/o1": {"local_1": "s-old"}, f"{B}/o2": {"local_1": "s1", "local_2": "s2"}, f"{C}/o3": {}}
        modes = {f"epitaxy-folder-permission-mode-v2.{B}": {"/p": "bypassPermissions"}, f"epitaxy-folder-permission-mode-v2.{C}": {"/q": "auto"}}
        gate = {A: False, B: True, C: True}
        for d in self.dirs:
            self.put(d, config(sections, groups, modes, gate))
            self.put(d, {"v": 1, "owners": {A: {"x": False}, B: {"x": True, "y": True}, C: {}}}, "mcp-user-tool-toggles.json")
        changed = cs_share.share(self.dirs, unify_from=B, unify_to=[A, C])
        self.assertIn("claude_desktop_config.json", changed)
        got = [self.get(d) for d in self.dirs]
        self.assertTrue(all(g == got[0] for g in got))
        epi = got[0]["preferences"]["epitaxyPrefs"]
        for acc, org in ((A, "o1"), (C, "o3")):
            self.assertEqual(epi["dframe-code-sections"][f"{acc}/{org}"], [{"id": "s1"}, {"id": "s2"}])
            self.assertEqual(epi["dframe-group-scopes"][f"{acc}/{org}"], {"local_1": "s1", "local_2": "s2"})
            self.assertEqual(epi[f"epitaxy-folder-permission-mode-v2.{acc}"], {"/p": "bypassPermissions"})
            self.assertTrue(got[0]["preferences"]["bypassPermissionsGateByAccount"][acc])
        self.assertEqual(epi["dframe-code-sections"]["dddddddd-x/o4"], [{"id": "other"}])  # an account not listed is left alone
        tog = [self.get(d, "mcp-user-tool-toggles.json") for d in self.dirs]
        self.assertTrue(all(t == tog[0] for t in tog))
        self.assertEqual(tog[0]["owners"][A], {"x": True, "y": True})
        backups = glob.glob(os.path.join(self.tmp.name, "state", "unify-backups.noindex", "*", "*", "*.json"))
        self.assertEqual(len(backups), 6)  # 2 files x 3 folders, the versions from before the unify
        old = json.load(open([b for b in backups if b.endswith(os.path.join("Claude", "claude_desktop_config.json"))][0]))
        self.assertEqual(old["preferences"]["epitaxyPrefs"]["dframe-code-sections"][f"{A}/o1"], [{"id": "s-old"}])
        # second run: nothing left to change, no new backup
        self.assertEqual(cs_share.share(self.dirs, unify_from=B, unify_to=[A, C]), [])
        self.assertEqual(len(glob.glob(os.path.join(self.tmp.name, "state", "unify-backups.noindex", "*"))), 1)

    def test_missing_or_odd_keys_are_skipped_and_logged(self):
        data = {"preferences": {"epitaxyPrefs": {"dframe-code-sections": "not-a-dict"}, "bypassPermissionsGateByAccount": {A: False}}}
        for d in self.dirs:
            self.put(d, data)
        cs_share.share(self.dirs, unify_from=B, unify_to=[A, C])
        for d in self.dirs:
            self.assertEqual(self.get(d), data)  # nothing to copy from: files untouched and still valid JSON
        log = open(os.path.join(self.tmp.name, "state", "sync.log")).read()
        self.assertIn("account unify: claude_desktop_config.json: dframe-code-sections missing", log)
        self.assertIn("no value for the base account", log)
        cs_share.share(self.dirs, unify_from=B, unify_to=[A, C])  # same notes again: not logged twice
        self.assertEqual(open(os.path.join(self.tmp.name, "state", "sync.log")).read(), log)

    def test_target_without_its_own_key_is_skipped(self):
        sections = {f"{B}/o2": [{"id": "s1"}], f"{A}/o1": [{"id": "a"}]}  # C never opened the sidebar
        for d in self.dirs:
            self.put(d, config(sections, {f"{B}/o2": {}}, {}, {B: True}))
        cs_share.share(self.dirs, unify_from=B, unify_to=[A, C])
        epi = self.get(self.dirs[0])["preferences"]["epitaxyPrefs"]
        self.assertEqual(epi["dframe-code-sections"][f"{A}/o1"], [{"id": "s1"}])
        self.assertNotIn(f"{C}/o3", epi["dframe-code-sections"])

    def test_no_unify_setting_keeps_old_behaviour(self):
        for d in self.dirs:
            self.put(d, config({f"{A}/o1": [1], f"{B}/o2": [2]}, {}, {}, {A: False, B: True}))
        cs_share.share(self.dirs, unify_from=None, unify_to=[])
        self.assertEqual(self.get(self.dirs[0])["preferences"]["epitaxyPrefs"]["dframe-code-sections"][f"{A}/o1"], [1])

    def test_base_order_from_its_own_folder_survives_the_merge(self):
        # B reordered its sections while open; the merge's list union would keep the old order
        old = {f"{A}/o1": {"sections": [{"id": "x"}, {"id": "y"}]}, f"{B}/o2": {"sections": [{"id": "x"}, {"id": "y"}]}}
        for d in self.dirs:
            self.put(d, config(old, {}, {}, {B: True}))
        cs_share.share(self.dirs, unify_from=B, unify_to=[A, C])
        os.makedirs(os.path.join(self.dirs[1], "claude-code-sessions", B))  # B lives in "Claude Second"
        os.makedirs(os.path.join(self.dirs[0], "claude-code-sessions", A))
        os.makedirs(os.path.join(self.dirs[0], "claude-code-sessions", B))  # a stale B folder in A's data folder
        open(os.path.join(self.dirs[1], "claude-code-sessions", ".DS_Store"), "w").close()
        new = {f"{A}/o1": old[f"{A}/o1"], f"{B}/o2": {"sections": [{"id": "y"}, {"id": "x"}]}}
        self.put(self.dirs[1], config(new, {}, {}, {B: True}))
        cs_share.share(self.dirs, unify_from=B, unify_to=[A, C])
        for d in self.dirs:
            secs = self.get(d)["preferences"]["epitaxyPrefs"]["dframe-code-sections"]
            self.assertEqual(secs[f"{B}/o2"]["sections"], [{"id": "y"}, {"id": "x"}])
            self.assertEqual(secs[f"{A}/o1"]["sections"], [{"id": "y"}, {"id": "x"}])

    def test_permission_acks_and_org_account_choice_follow(self):
        modes = {f"epitaxy-folder-permission-mode-v2.{B}": {"/p": "bypassPermissions"}, f"epitaxy-perm-mode-acks-v2.{B}": ["/p:bypassPermissions"]}
        data = config({f"{A}/o1": [], f"{B}/o2": [1], f"{C}/o3": []}, {f"{A}/o1": {}, f"{B}/o2": {}, f"{C}/o3": {}}, modes, {B: True},
                      {"chicagoChoiceByOrgAccount": {f"o2:{B}": {"choice": "on"}}, "bypassPermissionsOptInByAccount": {B: True}})
        for d in self.dirs:
            self.put(d, data)
        cs_share.share(self.dirs, unify_from=B, unify_to=[A, C])
        p = self.get(self.dirs[0])["preferences"]
        for acc, org in ((A, "o1"), (C, "o3")):
            self.assertEqual(p["epitaxyPrefs"][f"epitaxy-perm-mode-acks-v2.{acc}"], ["/p:bypassPermissions"])
            self.assertEqual(p["chicagoChoiceByOrgAccount"][f"{org}:{acc}"], {"choice": "on"})
            self.assertTrue(p["bypassPermissionsOptInByAccount"][acc])

    @unittest.skipUnless(cs_share._node() and os.path.isdir(os.path.join(os.path.dirname(cs_share.LS_WRITER), "node_modules", "classic-level")), "node + classic-level needed")
    def test_local_storage_gets_the_unified_values(self):
        import subprocess
        node = cs_share._node()
        mk = os.path.join(self.tmp.name, "mk.mjs")
        with open(mk, "w") as f:
            f.write("import { ClassicLevel } from 'classic-level'; const db = new ClassicLevel(process.argv[2]); await db.open(); await db.put('x', 'y'); await db.close()\n")
        env = dict(os.environ, NODE_PATH=os.path.join(os.path.dirname(cs_share.LS_WRITER), "node_modules"))
        for d in self.dirs:
            ldb = os.path.join(d, "Local Storage", "leveldb")
            os.makedirs(os.path.dirname(ldb))
            shutil_mk = os.path.join(os.path.dirname(cs_share.LS_WRITER), "_mk_test.mjs")
            with open(shutil_mk, "w") as f:
                f.write(open(mk).read())
            try:
                subprocess.run([node, shutil_mk, ldb], check=True, env=env, capture_output=True)
            finally:
                os.unlink(shutil_mk)
        groups = {f"{A}/o1": {"groups": []}, f"{B}/o2": {"groups": [{"id": "g1"}]}, f"{C}/o3": {"groups": []}}
        for d in self.dirs:
            self.put(d, config({f"{A}/o1": [], f"{B}/o2": [1], f"{C}/o3": []}, groups, {}, {B: True}))
        cs_share.share(self.dirs, unify_from=B, unify_to=[A, C])
        rd = os.path.join(os.path.dirname(cs_share.LS_WRITER), "_rd_test.mjs")
        with open(rd, "w") as f:
            f.write("import { ClassicLevel } from 'classic-level'; const db = new ClassicLevel(process.argv[2], {keyEncoding:'buffer', valueEncoding:'buffer'}); "
                    "const v = await db.get(Buffer.from('_https://claude.ai\\u0000\\u0001LSS-persisted.dframe-group-scopes', 'latin1')); "
                    "const s = v[0] === 0 ? v.subarray(1).toString('utf16le') : v.subarray(1).toString('latin1'); console.log(s); await db.close()\n")
        try:
            for d in self.dirs:
                out = subprocess.run([node, rd, os.path.join(d, "Local Storage", "leveldb")], check=True, capture_output=True, text=True).stdout
                val = json.loads(out)["value"]
                self.assertEqual(val[f"{A}/o1"], {"groups": [{"id": "g1"}]})
        finally:
            os.unlink(rd)
        self.assertTrue(glob.glob(os.path.join(self.tmp.name, "state", "unify-backups.noindex", "*", "*", "Local Storage-leveldb")))


if __name__ == "__main__":
    unittest.main()
