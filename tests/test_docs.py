"""The skill package itself: valid frontmatter, docs in sync with the code, portable Python."""
import re
import subprocess
import sys
import unittest

import helpers

SKILL_MD = helpers.SKILL / "SKILL.md"


class SkillPackageTests(unittest.TestCase):
    def test_frontmatter(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        self.assertIsNotNone(m)
        fm = m.group(1)
        name = re.search(r"^name:\s*(.+)$", fm, re.M).group(1).strip()
        desc = re.search(r"^description:\s*(.+)$", fm, re.M).group(1).strip()
        self.assertRegex(name, r"^[a-z0-9]+(-[a-z0-9]+)*$")
        self.assertLessEqual(len(desc), 1024)
        self.assertNotRegex(desc, r"[<>]")
        self.assertLess(len(text.splitlines()), 500)

    def test_referenced_files_exist(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        for ref in set(re.findall(r"`(references/[\w./-]+)`", text)):
            self.assertTrue((helpers.SKILL / ref).exists(), ref)
        for subject in ("general", "math-physics", "chemistry", "biology-medicine", "history-social", "law",
                        "computer-science", "economics-business", "languages"):
            self.assertTrue((helpers.SKILL / "references" / "subjects" / f"{subject}.md").exists(), subject)

    def test_format_doc_in_sync(self):
        r = subprocess.run([sys.executable, str(helpers.ROOT / "tools" / "gen_format_doc.py"), "--check"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_portable_python(self):
        if sys.version_info < (3, 12):
            self.skipTest("checker needs Python 3.12 tokens")
        r = subprocess.run([sys.executable, str(helpers.ROOT / "tools" / "check_portability.py"),
                            str(helpers.SKILL / "scripts")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_cli_help_and_doctor(self):
        cli = helpers.SKILL / "scripts" / "examscribe.py"
        r = subprocess.run([sys.executable, str(cli), "help"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0)
        self.assertIn("next", r.stdout)
        r = subprocess.run([sys.executable, str(cli), "format", "concept"], capture_output=True, text=True,
                           encoding="utf-8")
        self.assertIn("definition:", r.stdout)


if __name__ == "__main__":
    unittest.main()
