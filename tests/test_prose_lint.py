"""Unit tests for prose_lint.

Each rule test pairs a sentence that must fire with a rewrite that must stay clean,
so a regex that gets too greedy fails here rather than in someone's README.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "prose_lint.py"

spec = importlib.util.spec_from_file_location("prose_lint", SCRIPT)
pl = importlib.util.module_from_spec(spec)
sys.modules["prose_lint"] = pl
spec.loader.exec_module(pl)


def ids(text, kind="text", doc_checks=False):
    return {f.rule for f in pl.lint_text(text, kind, doc_checks=doc_checks)}


def run(args, stdin="", env=None):
    e = dict(os.environ)
    e.pop("AI_STYLE_STRICT", None)
    e.update(env or {})
    return subprocess.run([sys.executable, str(SCRIPT), *args], input=stdin,
                          capture_output=True, text=True, env=e, cwd=ROOT)


class Punctuation(unittest.TestCase):
    def test_em_dash(self):
        self.assertIn("TYPO_EM_DASH", ids("The build failed — again."))
        self.assertNotIn("TYPO_EM_DASH", ids("The build failed, again."))

    def test_en_dash_as_sentence_dash(self):
        self.assertIn("TYPO_EN_DASH_AS_DASH", ids("The build failed – again."))
        self.assertNotIn("TYPO_EN_DASH_AS_DASH", ids("Pages 12–14 cover the parser."))

    def test_emoji_as_marker(self):
        self.assertIn("TYPO_EMOJI_MARKER", ids("- ✅ Tests pass\n"))
        self.assertNotIn("TYPO_EMOJI_MARKER", ids("- Tests pass\n"))

    def test_bold_label_bullet(self):
        self.assertIn("FMT_BOLD_LABEL_BULLET", ids("- **Speed:** the parser is faster.\n", "md"))
        self.assertIn("FMT_BOLD_LABEL_BULLET", ids("- **Speed:** the parser is faster.\n", "md"))
        self.assertNotIn("FMT_BOLD_LABEL_BULLET", ids("- The parser is faster.\n", "md"))

    def test_arrow_for_verb(self):
        self.assertIn("TYPO_ARROW_PROSE", ids("The request goes client->server."))


class RhetoricEnglish(unittest.TestCase):
    def test_not_x_its_y(self):
        self.assertIn("RHET_NOT_X_ITS_Y", ids("It's not a bug, it's a race condition."))
        self.assertNotIn("RHET_NOT_X_ITS_Y", ids("The failure is a race condition."))

    def test_not_only_but_also(self):
        self.assertIn("RHET_NOT_ONLY_EN", ids("It not only parses the file but also rewrites it."))

    def test_self_answered_question(self):
        self.assertIn("RHET_Q_REVEAL_EN", ids("The result? Two seconds saved per run."))
        self.assertNotIn("RHET_Q_REVEAL_EN", ids("Two seconds are saved per run."))

    def test_colon_reveal(self):
        self.assertIn("RHET_COLON_REVEAL_EN", ids("Here's the thing about the cache."))

    def test_whether_you_are(self):
        self.assertIn("RHET_WHETHER", ids("Whether you're a beginner or an expert, the flag helps."))

    def test_signposting(self):
        self.assertIn("RHET_SIGNPOST", ids("Let's dive in and read the parser."))

    def test_less_x_more_y(self):
        self.assertIn("RHET_LESS_MORE", ids("Less boilerplate, more shipping."))

    def test_staccato_run(self):
        self.assertIn("RHET_STACCATO", ids("Fast. Reliable. Simple."))
        self.assertNotIn("RHET_STACCATO", ids("The parser is fast and the output is stable."))


class RhetoricFrench(unittest.TestCase):
    def test_ce_nest_pas(self):
        self.assertIn("RHET_CE_NEST_PAS_FR", ids("Ce n'est pas un bug, c'est une condition de course."))
        self.assertIn("RHET_CE_NEST_PAS_FR", ids("Ce n’est pas un bug, c’est une condition de course."))

    def test_il_ne_sagit_pas(self):
        self.assertIn("RHET_IL_NE_SAGIT_PAS_FR",
                      ids("Il ne s'agit pas de vitesse, mais de fiabilité."))

    def test_non_seulement(self):
        self.assertIn("RHET_NON_SEULEMENT_FR",
                      ids("Le script non seulement analyse le fichier mais aussi le réécrit."))

    def test_question_reveal(self):
        self.assertIn("RHET_Q_REVEAL_FR", ids("Le résultat ? Deux secondes gagnées par exécution."))

    def test_colon_reveal(self):
        self.assertIn("RHET_COLON_REVEAL_FR", ids("Le hic : le cache n'est jamais invalidé."))


class Vocabulary(unittest.TestCase):
    def test_english_vocabulary(self):
        self.assertIn("VOCAB_EN", ids("Let us delve into the parser."))
        self.assertIn("VOCAB_EN", ids("The flag unlocks the full potential of the cache."))
        self.assertNotIn("VOCAB_EN", ids("This removes two manual steps."))

    def test_english_soft_vocabulary_is_a_warning(self):
        found = pl.lint_text("This is a seamless workflow.", "text", doc_checks=False)
        self.assertEqual(["VOCAB_EN_SOFT"], [f.rule for f in found])
        self.assertEqual(pl.WARN, found[0].sev)

    def test_french_vocabulary(self):
        self.assertIn("VOCAB_FR", ids("Il convient de souligner que le cache expire."))
        self.assertIn("VOCAB_FR", ids("Le script permet de tirer pleinement parti du cache."))

    def test_french_soft_vocabulary_is_a_warning(self):
        found = pl.lint_text("Il faut tirer parti de cet écosystème.", "text", doc_checks=False)
        self.assertIn("VOCAB_FR_SOFT", {f.rule for f in found})
        self.assertTrue(all(f.sev == pl.WARN for f in found))

    def test_french_calque(self):
        self.assertIn("CALQUE_FR", ids("Nous allons adresser ce problème demain."))

    def test_meta_openers_and_closers(self):
        self.assertIn("META_PRAISE", ids("Great question! The parser masks code fences."))
        self.assertIn("META_RECAP", ids("In summary, the parser masks code fences."))
        self.assertIn("META_OFFER", ids("Let me know if you want the flag documented."))


class DocumentChecks(unittest.TestCase):
    def test_uniform_sentence_length(self):
        text = "\n".join(["The parser reads the file and reports every finding once."] * 20)
        self.assertIn("RHYTHM_UNIFORM", ids(text, doc_checks=True))

    def test_title_case_heading(self):
        self.assertIn("FMT_TITLE_CASE", ids("# Installing The Prose Linter\n", "md"))
        self.assertNotIn("FMT_TITLE_CASE", ids("# Installing the prose linter\n", "md"))

    def test_summary_heading(self):
        self.assertIn("FMT_SUMMARY_HEADING", ids("## Key takeaways\n", "md"))


class Masking(unittest.TestCase):
    def test_code_fence_is_ignored(self):
        self.assertEqual(set(), ids("```\nIt's not a bug, it's a feature.\n```\n", "md"))

    def test_inline_code_is_ignored(self):
        self.assertEqual(set(), ids("Run `delve --robust` to start.\n", "md"))

    def test_url_is_ignored(self):
        self.assertEqual(set(), ids("See https://example.com/delve-into-the-tapestry for details.\n", "md"))

    def test_html_tags_are_stripped(self):
        self.assertIn("VOCAB_EN", ids("<p>Let us delve into the parser.</p>", "html"))
        self.assertEqual(set(), ids("<code>Let us delve into the parser.</code>", "html"))


class Suppression(unittest.TestCase):
    def test_ignore_single_line(self):
        self.assertEqual(set(), ids("Let us delve into the parser. <!-- ai-style: ignore -->\n", "md"))

    def test_off_on_block(self):
        text = ("<!-- ai-style: off -->\nLet us delve into the parser.\n"
                "<!-- ai-style: on -->\nThe flag removes two manual steps.\n")
        self.assertEqual(set(), ids(text, "md"))

    def test_rules_file_is_exempt(self):
        self.assertTrue(pl.is_exempt("writing-rules.md"))
        self.assertTrue(pl.is_exempt("/somewhere/else/claude-app-instructions.md"))
        self.assertFalse(pl.is_exempt("README.md"))


class Severity(unittest.TestCase):
    def test_error_fails_and_warning_does_not(self):
        self.assertEqual(1, run(["--stdin"], "It's not a bug, it's a feature.\n").returncode)
        self.assertEqual(0, run(["--stdin"], "The team ships weekly, not daily.\n").returncode)

    def test_strict_makes_warnings_fail(self):
        clean = "The team ships weekly, not daily.\n"
        self.assertEqual(1, run(["--stdin"], clean, env={"AI_STYLE_STRICT": "1"}).returncode)


class Modes(unittest.TestCase):
    def test_help_exits_zero(self):
        self.assertEqual(0, run([]).returncode)

    def test_file_mode(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "note.md"
            p.write_text("The result? Two seconds saved.\n", encoding="utf-8")
            r = run([str(p)])
            self.assertEqual(1, r.returncode)
            self.assertIn("RHET_Q_REVEAL_EN", r.stdout)

    def test_commit_msg_mode_skips_comments(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "COMMIT_EDITMSG"
            p.write_text("fix: drop the stale cache entry\n\n# It's not a bug, it's a feature.\n",
                         encoding="utf-8")
            self.assertEqual(0, run(["--commit-msg", str(p)]).returncode)

    def test_commit_msg_mode_flags_the_message(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "COMMIT_EDITMSG"
            p.write_text("feat: unlock the full potential of the cache\n", encoding="utf-8")
            r = run(["--commit-msg", str(p)])
            self.assertEqual(1, r.returncode)
            self.assertIn("VOCAB_EN", r.stderr)

    def test_hook_mode_on_write(self):
        payload = json.dumps({"tool_input": {"file_path": "/tmp/doc.md",
                                             "content": "It's not a bug, it's a feature.\n"}})
        r = run(["--hook"], payload)
        self.assertEqual(2, r.returncode)
        self.assertIn("RHET_NOT_X_ITS_Y", r.stderr)

    def test_hook_mode_ignores_non_prose(self):
        payload = json.dumps({"tool_input": {"file_path": "/tmp/main.py",
                                             "content": "# It's not a bug, it's a feature.\n"}})
        self.assertEqual(0, run(["--hook"], payload).returncode)

    def test_hook_mode_survives_broken_json(self):
        self.assertEqual(0, run(["--hook"], "not json").returncode)

    def test_git_staged_mode_reads_added_lines(self):
        with tempfile.TemporaryDirectory() as d:
            env = {"GIT_CONFIG_GLOBAL": os.path.join(d, "gitconfig"), "GIT_CONFIG_SYSTEM": "/dev/null"}
            g = dict(os.environ, **env)
            subprocess.run(["git", "init", "-q", "-b", "main", d], check=True, env=g)
            note = Path(d) / "note.md"
            note.write_text("The parser reads the file.\n", encoding="utf-8")
            subprocess.run(["git", "add", "note.md"], cwd=d, check=True, env=g)
            r = subprocess.run([sys.executable, str(SCRIPT), "--git-staged"],
                               cwd=d, capture_output=True, text=True, env=g)
            self.assertEqual(0, r.returncode, r.stderr)
            note.write_text("The parser reads the file.\nThe result? Nothing.\n", encoding="utf-8")
            subprocess.run(["git", "add", "note.md"], cwd=d, check=True, env=g)
            r = subprocess.run([sys.executable, str(SCRIPT), "--git-staged"],
                               cwd=d, capture_output=True, text=True, env=g)
            self.assertEqual(1, r.returncode)
            self.assertIn("RHET_Q_REVEAL_EN", r.stderr)


class Packaging(unittest.TestCase):
    @unittest.skipUnless(hasattr(sys, "stdlib_module_names"), "needs Python 3.10+")
    def test_no_third_party_imports(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for line in source.splitlines():
            if line.startswith(("import ", "from ")) and "__future__" not in line:
                module = line.split()[1].split(".")[0]
                self.assertIn(module, sys.stdlib_module_names, line)

    def test_every_rule_compiles_and_is_unique(self):
        seen = set()
        for rid, sev, _, hint in pl.RULES:
            self.assertNotIn(rid, seen, rid)
            seen.add(rid)
            self.assertIn(sev, (pl.ERROR, pl.WARN))
            self.assertTrue(hint.strip(), rid)
        self.assertEqual(len(pl.RULES), len(pl.COMPILED))

    def test_shipped_rules_file_stays_clean_of_its_own_examples(self):
        # writing-rules.md quotes the patterns it bans, so it must be exempt, not clean.
        self.assertTrue(pl.is_exempt(str(ROOT / "writing-rules.md")))


if __name__ == "__main__":
    unittest.main()
