"""LawPRE 的单元测试（标准库 unittest，依赖 jsonschema）。

运行：python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from lawpre import agent, cli  # noqa: E402
from lawpre.inputs import load_inputs  # noqa: E402
from lawpre.render import render_notes_total  # noqa: E402
from lawpre.timing import cjk_ratio, markup_lines  # noqa: E402

EXAMPLE = REPO / "inputs" / "algorithm-recommendation-pipa"


def _read(name: str) -> dict:
    return json.loads((EXAMPLE / name).read_text(encoding="utf-8"))


class TempInputs(unittest.TestCase):
    """复制示例输入到临时目录，便于逐项破坏后检查报错。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "case"
        shutil.copytree(EXAMPLE, self.dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, name: str, data: dict) -> None:
        (self.dir / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def check(self):
        inputs, report = load_inputs(self.dir)
        return inputs, report

    def assertError(self, report, fragment: str) -> None:
        self.assertTrue(
            any(fragment in e for e in report.errors),
            f"未找到包含“{fragment}”的错误；实际错误：{report.errors}",
        )


class ExampleInputs(unittest.TestCase):
    def test_example_passes_and_is_marked_draft(self):
        inputs, report = load_inputs(EXAMPLE)
        self.assertIsNotNone(inputs)
        self.assertEqual(report.errors, [])
        self.assertTrue(report.draft, "示例来源均为“部分核验”，必须标注为草稿")
        self.assertEqual(report.stats["slides"], 10)
        self.assertEqual(report.stats["planned_seconds"], 580)

    def test_example_notes_are_chinese_prose(self):
        deck = _read("deck.json")
        for slide in deck["slides"]:
            self.assertEqual(markup_lines(slide["notes_zh"]), [], slide["slide_no"])
            self.assertGreaterEqual(cjk_ratio(slide["notes_zh"]), 0.8, slide["slide_no"])


class SemanticChecks(TempInputs):
    def test_unknown_source_in_deck_is_error(self):
        deck = _read("deck.json")
        deck["slides"][2]["source_ids"] = ["S999"]
        self.write("deck.json", deck)
        _, report = self.check()
        self.assertError(report, "未登记的来源 S999")

    def test_unknown_source_in_rule_is_error(self):
        analysis = _read("analysis.json")
        analysis["issues"][0]["rules"][0]["source_id"] = "S404"
        self.write("analysis.json", analysis)
        _, report = self.check()
        self.assertError(report, "未登记的来源 S404")

    def test_not_applicable_source_cannot_back_a_rule(self):
        sources = _read("sources.json")
        sources["sources"][0]["status"] = "不适用"
        self.write("sources.json", sources)
        _, report = self.check()
        self.assertError(report, "状态为“不适用”")

    def test_slide_without_sources_is_error(self):
        deck = _read("deck.json")
        deck["slides"][4]["source_ids"] = []
        self.write("deck.json", deck)
        _, report = self.check()
        self.assertError(report, "第 5 页")

    def test_duration_outside_tolerance_is_error(self):
        deck = _read("deck.json")
        deck["slides"][1]["duration_seconds"] = 170
        self.write("deck.json", deck)
        _, report = self.check()
        self.assertError(report, "偏离目标 600 秒超过 10%")

    def test_english_notes_are_error(self):
        deck = _read("deck.json")
        deck["slides"][1]["notes_zh"] = "This slide explains the core legal issue in English. " * 3
        self.write("deck.json", deck)
        _, report = self.check()
        self.assertError(report, "不是中文正文")

    def test_markup_in_notes_is_error(self):
        deck = _read("deck.json")
        deck["slides"][1]["notes_zh"] = "- 第一点：" + "这是一段讲稿，内容足够长以通过长度检查。" * 3
        self.write("deck.json", deck)
        _, report = self.check()
        self.assertError(report, "标记行")

    def test_first_slide_must_be_cover(self):
        deck = _read("deck.json")
        deck["slides"][0]["kind"] = "issue"
        self.write("deck.json", deck)
        _, report = self.check()
        self.assertError(report, "第 1 页必须是封面")

    def test_bad_schema_stops_before_semantics(self):
        brief = _read("brief.json")
        brief["duration_minutes"] = 99
        self.write("brief.json", brief)
        inputs, report = self.check()
        self.assertIsNone(inputs)
        self.assertTrue(any("brief.json" in e for e in report.errors))

    def test_unverified_source_marks_draft(self):
        _, report = self.check()
        self.assertTrue(report.draft)

    def test_fully_verified_sources_are_not_draft(self):
        sources = _read("sources.json")
        for s in sources["sources"]:
            s["status"] = "已核验"
            s["status_note"] = "已核对"
        self.write("sources.json", sources)
        _, report = self.check()
        self.assertEqual(report.errors, [])
        self.assertFalse(report.draft)


class NotesFormat(unittest.TestCase):
    def test_total_md_matches_ppt_master_split_format(self):
        inputs, _ = load_inputs(EXAMPLE)
        text = render_notes_total(inputs)
        headings = re.findall(r"^# (\d{2})_(.+)$", text, flags=re.M)
        self.assertEqual([h[0] for h in headings], [f"{i:02d}" for i in range(1, 11)])
        self.assertEqual(text.count("\n---\n"), 9)


class AgentCommand(unittest.TestCase):
    def test_placeholders_are_substituted_per_argument(self):
        argv = agent.build_argv(
            'claude -p "阅读 {task_file} 并执行" --cwd {workdir}',
            {"task_file": "/tmp/a b/AGENT_TASK.md", "workdir": "/opt/ppt master"},
        )
        self.assertEqual(argv[0], "claude")
        self.assertEqual(argv[2], "阅读 /tmp/a b/AGENT_TASK.md 并执行")
        self.assertEqual(argv[4], "/opt/ppt master")

    def test_empty_template_gives_no_argv(self):
        self.assertEqual(agent.build_argv("   ", {}), [])


def _fake_pptx(path: Path, slides: int, with_notes: bool = True) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        for i in range(1, slides + 1):
            zf.writestr(f"ppt/slides/slide{i}.xml", "<p:sld/>")
            text = f"<a:t>第{i}页讲稿</a:t>" if with_notes else "<a:t></a:t>"
            zf.writestr(f"ppt/notesSlides/notesSlide{i}.xml", f"<p:notes>{text}</p:notes>")


class DeckVerification(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_ok_deck(self):
        p = self.dir / "deck.pptx"
        _fake_pptx(p, 10)
        check = agent.verify_deck(p, 10)
        self.assertTrue(check.ok, check.problems)
        self.assertEqual(check.slide_count, 10)
        self.assertEqual(check.notes_count, 10)

    def test_wrong_page_count(self):
        p = self.dir / "deck.pptx"
        _fake_pptx(p, 8)
        check = agent.verify_deck(p, 10)
        self.assertFalse(check.ok)
        self.assertTrue(any("页数为 8" in x for x in check.problems))

    def test_missing_notes(self):
        p = self.dir / "deck.pptx"
        _fake_pptx(p, 10, with_notes=False)
        check = agent.verify_deck(p, 10)
        self.assertFalse(check.ok)
        self.assertTrue(any("讲稿" in x for x in check.problems))

    def test_missing_and_invalid_files(self):
        self.assertFalse(agent.verify_deck(self.dir / "none.pptx", 10).ok)
        bad = self.dir / "bad.pptx"
        bad.write_text("not a zip", encoding="utf-8")
        self.assertFalse(agent.verify_deck(bad, 10).ok)


class RunCommand(unittest.TestCase):
    """端到端：用假的 ppt-master 目录与假的 agent 走完 run 的各个分支。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.pm = self.root / "ppt-master"
        (self.pm / "skills" / "ppt-master").mkdir(parents=True)
        (self.pm / "skills" / "ppt-master" / "SKILL.md").write_text("# fake", encoding="utf-8")
        self.out = self.root / "out"
        self._env = mock.patch.dict(os.environ, {"PPT_MASTER_DIR": str(self.pm)}, clear=False)
        self._env.start()
        os.environ.pop(agent.AGENT_ENV, None)

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def _run(self, *extra: str) -> int:
        return cli.main(["run", str(EXAMPLE), "--out", str(self.out), *extra])

    def test_without_agent_command_bundle_is_built_and_exit_2(self):
        self.assertEqual(self._run(), 2)
        out_dir = self.out / "algorithm-recommendation-pipa"
        self.assertTrue((out_dir / "AGENT_TASK.md").exists())
        self.assertTrue((out_dir / "notes" / "total.md").exists())

    def test_missing_ppt_master_is_exit_2(self):
        with mock.patch.dict(os.environ, {"PPT_MASTER_DIR": str(self.root / "nope")}):
            self.assertEqual(self._run(), 2)

    def test_agent_success_produces_verified_deck(self):
        script = self.root / "fake_agent.py"
        script.write_text(
            "import sys, zipfile, pathlib\n"
            "out = pathlib.Path(sys.argv[1])\n"
            "with zipfile.ZipFile(out / 'deck.pptx', 'w') as zf:\n"
            "    for i in range(1, 11):\n"
            "        zf.writestr(f'ppt/slides/slide{i}.xml', '<p/>')\n"
            "        zf.writestr(f'ppt/notesSlides/notesSlide{i}.xml', '<a:t>讲稿</a:t>')\n",
            encoding="utf-8",
        )
        cmd = f'{sys.executable} {script} {{out_dir}}'
        with mock.patch.dict(os.environ, {agent.AGENT_ENV: cmd}):
            code = self._run()
        self.assertEqual(code, 0)
        result = json.loads((self.out / "algorithm-recommendation-pipa" / "result.json").read_text(encoding="utf-8"))
        self.assertTrue(result["ok"])
        self.assertTrue(result["draft"])

    def test_agent_failure_is_exit_3(self):
        cmd = f"{sys.executable} -c 'import sys; sys.exit(7)'"
        with mock.patch.dict(os.environ, {agent.AGENT_ENV: cmd}):
            self.assertEqual(self._run(), 3)

    def test_agent_finished_without_deck_is_exit_4(self):
        cmd = f"{sys.executable} -c 'pass'"
        with mock.patch.dict(os.environ, {agent.AGENT_ENV: cmd}):
            self.assertEqual(self._run(), 4)

    def test_invalid_input_is_exit_1_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad"
            shutil.copytree(EXAMPLE, bad)
            deck = json.loads((bad / "deck.json").read_text(encoding="utf-8"))
            deck["slides"][2]["source_ids"] = ["S999"]
            (bad / "deck.json").write_text(json.dumps(deck, ensure_ascii=False), encoding="utf-8")
            code = cli.main(["run", str(bad), "--out", str(self.out)])
        self.assertEqual(code, 1)
        self.assertFalse((self.out / "algorithm-recommendation-pipa").exists())


if __name__ == "__main__":
    unittest.main()
