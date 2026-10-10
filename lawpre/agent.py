"""调用外部 agent 执行 ppt-master 技能，并验收导出的 PPTX。

agent 命令通过环境变量 LAWPRE_AGENT_CMD 配置，例如（参数以你本机 CLI 为准）：

    LAWPRE_AGENT_CMD='claude -p "请阅读并完成 {task_file} 中的任务" --permission-mode acceptEdits'

可用占位符：{task_file}（任务书绝对路径）、{workdir}（ppt-master 根目录）、{out_dir}（本次输出目录）。
命令按 shell 规则切分后直接执行（不经过 shell），因此占位符替换不会引入注入风险。
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

AGENT_ENV = "LAWPRE_AGENT_CMD"
DEFAULT_TIMEOUT = 3600


@dataclass
class AgentResult:
    returncode: int | None
    timed_out: bool = False
    argv: list[str] = field(default_factory=list)


@dataclass
class DeckCheck:
    ok: bool
    slide_count: int
    notes_count: int
    problems: list[str] = field(default_factory=list)


def build_argv(template: str, substitutions: dict[str, str]) -> list[str]:
    argv = shlex.split(template)
    out = []
    for arg in argv:
        for key, value in substitutions.items():
            arg = arg.replace("{" + key + "}", value)
        out.append(arg)
    return out


def run_agent(
    template: str,
    *,
    task_file: Path,
    workdir: Path,
    out_dir: Path,
    timeout: int = DEFAULT_TIMEOUT,
) -> AgentResult:
    argv = build_argv(
        template,
        {"task_file": str(task_file), "workdir": str(workdir), "out_dir": str(out_dir)},
    )
    if not argv:
        return AgentResult(returncode=None, argv=argv)
    log_path = out_dir / "agent.log"
    env = dict(os.environ)
    env["LAWPRE_OUT_DIR"] = str(out_dir)
    with log_path.open("w", encoding="utf-8") as log:
        log.write("$ " + " ".join(shlex.quote(a) for a in argv) + "\n\n")
        log.flush()
        try:
            proc = subprocess.run(
                argv,
                cwd=workdir,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return AgentResult(returncode=None, timed_out=True, argv=argv)
        except FileNotFoundError:
            return AgentResult(returncode=127, argv=argv)
    return AgentResult(returncode=proc.returncode, argv=argv)


_SLIDE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
_NOTE = re.compile(r"^ppt/notesSlides/notesSlide(\d+)\.xml$")
_TEXT = re.compile(r"<a:t>([^<]*)</a:t>")


def verify_deck(pptx: Path, expected_slides: int) -> DeckCheck:
    """用标准库检查 PPTX：页数、每页是否都有非空讲稿。"""
    if not pptx.exists():
        return DeckCheck(False, 0, 0, [f"未找到导出文件：{pptx}"])
    if not zipfile.is_zipfile(pptx):
        return DeckCheck(False, 0, 0, [f"导出文件不是合法的 PPTX（zip）：{pptx}"])

    problems: list[str] = []
    with zipfile.ZipFile(pptx) as zf:
        names = zf.namelist()
        slide_nums = sorted(int(m.group(1)) for n in names if (m := _SLIDE.match(n)))
        note_text_pages = 0
        for n in names:
            m = _NOTE.match(n)
            if not m:
                continue
            text = "".join(_TEXT.findall(zf.read(n).decode("utf-8", errors="replace")))
            if text.strip():
                note_text_pages += 1

    if len(slide_nums) != expected_slides:
        problems.append(f"页数为 {len(slide_nums)}，应为 {expected_slides}")
    if note_text_pages < expected_slides:
        problems.append(f"带讲稿的页数为 {note_text_pages}，应至少为 {expected_slides}")
    return DeckCheck(not problems, len(slide_nums), note_text_pages, problems)
