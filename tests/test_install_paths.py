"""The CLI is installed as a symlink (~/.local/bin/claude-switch). The sync agent must still point at the
real cs_sync.py — v0.1.0 pointed launchd at <symlink dir>/cs_sync.py, which does not exist."""
import os
import subprocess
import sys
import tempfile
import unittest

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")


class InstallPathTest(unittest.TestCase):
    def test_sync_script_resolves_through_symlink(self):
        with tempfile.TemporaryDirectory() as bindir:
            link = os.path.join(bindir, "claude-switch")
            os.symlink(os.path.realpath(os.path.join(SRC, "claude_switch.py")), link)
            out = subprocess.run([sys.executable, link, "_sync-script"], capture_output=True, text=True, check=True).stdout.strip()
            self.assertTrue(os.path.isfile(out), out)
            self.assertFalse(out.startswith(bindir), out)


if __name__ == "__main__":
    unittest.main()
