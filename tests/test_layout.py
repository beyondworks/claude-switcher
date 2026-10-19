"""Sidebar layout: copies the source account's sections into the target account and leaves everything else alone."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "src"))
import cs_layout  # noqa: E402

PREFIX = "_https://claude.ai\\x00\\x01"
SEED = r"""
const { ClassicLevel } = require('classic-level');
const enc = (o) => Buffer.concat([Buffer.from([0]), Buffer.from(JSON.stringify(o), 'utf16le')]);
const P = '_https://claude.ai\x00\x01';
(async () => {
  const [dir, key, name] = process.argv.slice(1);
  const db = new ClassicLevel(dir, { keyEncoding: 'buffer', valueEncoding: 'buffer' });
  await db.open();
  await db.put(Buffer.from(P + 'LSS-persisted.dframe-code-sections', 'latin1'),
    enc({ value: { [key]: { sections: [{ id: 'cg-1', name }] } }, tabId: '', timestamp: 1 }));
  await db.put(Buffer.from(P + 'LSS-persisted.dframe-group-scopes', 'latin1'),
    enc({ value: { [key]: { groups: [{ id: 'cg-1', name }], assignments: {}, order: {} } }, tabId: '', timestamp: 1 }));
  await db.put(Buffer.from(P + 'LSS-persisted.dframe-local-slice', 'latin1'), enc({ value: { pinnedOrder: [name] } }));
  await db.put(Buffer.from(P + 'unrelated-login-entry', 'latin1'), Buffer.concat([Buffer.from([1]), Buffer.from('keep-' + name)]));
  await db.close();
})();
"""
READ = r"""
const { ClassicLevel } = require('classic-level');
const dec = (v) => (v[0] === 0 ? v.slice(1).toString('utf16le') : v.slice(1).toString('latin1'));
(async () => {
  const db = new ClassicLevel(process.argv[1], { keyEncoding: 'buffer', valueEncoding: 'buffer' });
  await db.open();
  const out = {};
  for await (const [k, v] of db.iterator()) out[k.toString('latin1').slice(20)] = dec(v);
  await db.close();
  console.log(JSON.stringify(out));
})();
"""


def have_engine():
    return bool(cs_layout.find_node()) and os.path.isdir(os.path.join(cs_layout.HERE, "node_modules", "classic-level"))


@unittest.skipUnless(have_engine(), "node + classic-level not installed")
class LayoutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["CS_STATE_DIR"] = os.path.join(self.tmp.name, "state")
        cs_layout.C.STATE_DIR = os.environ["CS_STATE_DIR"]
        self.env = dict(os.environ, NODE_PATH=os.path.join(cs_layout.HERE, "node_modules"))
        self.node = cs_layout.find_node()
        self.a, self.b = os.path.join(self.tmp.name, "A"), os.path.join(self.tmp.name, "B")
        for d, key, name in ((self.a, "acctA/orgA", "Alpha"), (self.b, "acctB/orgB", "Beta")):
            os.makedirs(os.path.join(d, "Local Storage"))
            subprocess.run([self.node, "-e", SEED, cs_layout.leveldb_dir(d), key, name], check=True, env=self.env)

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, d):
        r = subprocess.run([self.node, "-e", READ, cs_layout.leveldb_dir(d)], capture_output=True, text=True, check=True, env=self.env)
        return json.loads(r.stdout)

    def test_copies_layout_under_the_target_key_and_keeps_other_entries(self):
        ok, msg = cs_layout.copy_layout(self.a, self.b, "acctA/orgA", "acctB/orgB")
        self.assertTrue(ok, msg)
        got = self.read(self.b)
        sections = json.loads(got["LSS-persisted.dframe-code-sections"])["value"]
        self.assertEqual(sections["acctB/orgB"]["sections"][0]["name"], "Alpha")
        self.assertEqual(json.loads(got["LSS-persisted.dframe-local-slice"])["value"]["pinnedOrder"], ["Alpha"])
        self.assertEqual(got["unrelated-login-entry"], "keep-Beta")  # not touched
        self.assertTrue(os.path.isdir(os.path.join(cs_layout.C.STATE_DIR, "layout-backups")))

    def test_second_run_changes_nothing(self):
        cs_layout.copy_layout(self.a, self.b, "acctA/orgA", "acctB/orgB")
        ok, msg = cs_layout.copy_layout(self.a, self.b, "acctA/orgA", "acctB/orgB")
        self.assertTrue(ok)
        self.assertIn("already identical", msg)

    def test_korean_names_survive(self):
        subprocess.run([self.node, "-e", SEED, cs_layout.leveldb_dir(self.a), "acctA/orgA", "섹션 한글"], check=True, env=self.env)
        cs_layout.copy_layout(self.a, self.b, "acctA/orgA", "acctB/orgB")
        sections = json.loads(self.read(self.b)["LSS-persisted.dframe-code-sections"])["value"]
        self.assertEqual(sections["acctB/orgB"]["sections"][0]["name"], "섹션 한글")


class KeyTest(unittest.TestCase):
    def test_account_key_from_session_folder(self):
        d = "/x/Claude Second"
        self.assertEqual(cs_layout.account_key(d, ["/x/Claude/claude-code-sessions/a/b", d + "/claude-code-sessions/c/d"]), "c/d")
        self.assertIsNone(cs_layout.account_key("/x/Other", [d + "/claude-code-sessions/c/d"]))


if __name__ == "__main__":
    unittest.main()
