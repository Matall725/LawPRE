"""命令行入口。

    python3 -m lawpre init   <slug>                    # 生成输入模板（含待填写占位）
    python3 -m lawpre check  inputs/<slug>             # 只校验输入
    python3 -m lawpre build  inputs/<slug>             # 校验并生成内容包与 AGENT_TASK.md
    python3 -m lawpre run    inputs/<slug>             # 生成后调用 agent（需设置 LAWPRE_AGENT_CMD）
    python3 -m lawpre doctor                            # 检查 ppt-master 环境

退出码：
    0  成功（run：PPTX 已导出并通过验收）
    1  输入校验未通过
    2  环境未就绪（ppt-master 缺失，或未配置 LAWPRE_AGENT_CMD；内容包仍已生成）
    3  agent 执行失败或超时
    4  agent 结束但 PPTX 验收未通过
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from . import agent, ppt_master
from .inputs import PLACEHOLDER, load_inputs
from .render import build_outputs

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "out"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,60}$")


def _print_report(report) -> None:
    for e in report.errors:
        print(f"[错误] {e}")
    for w in report.warnings:
        print(f"[警告] {w}")
    st = report.stats
    if st:
        print(
            f"页数 {st['slides']}；设定时长 {st['planned_seconds']}s / 目标 {st['target_seconds']}s；"
            f"讲稿估算 {st['estimated_seconds']}s；草稿状态：{'是' if report.draft else '否'}"
        )


def _load_or_exit(input_dir: Path):
    inputs, report = load_inputs(input_dir)
    _print_report(report)
    if inputs is None or not report.ok:
        print("校验未通过，已停止。")
        return None, report
    return inputs, report


def cmd_check(args) -> int:
    inputs, report = _load_or_exit(Path(args.input_dir))
    if inputs is None:
        return 1
    print("校验通过。")
    return 0


def cmd_build(args) -> int:
    input_dir = Path(args.input_dir)
    inputs, report = _load_or_exit(input_dir)
    if inputs is None:
        return 1
    out_dir = Path(args.out or DEFAULT_OUT) / inputs.brief["slug"]
    out_dir.mkdir(parents=True, exist_ok=True)
    pm_root = ppt_master.locate()
    files = build_outputs(inputs, report, out_dir, pm_root, ppt_master.current_commit(pm_root))
    print(f"内容包已生成：{out_dir}")
    for key in ("content", "notes", "script", "qa", "agent_task"):
        print(f"  {key}: {files[key].relative_to(out_dir)}")
    return 0


def cmd_run(args) -> int:
    input_dir = Path(args.input_dir)
    inputs, report = _load_or_exit(input_dir)
    if inputs is None:
        return 1

    out_dir = Path(args.out or DEFAULT_OUT) / inputs.brief["slug"]
    out_dir.mkdir(parents=True, exist_ok=True)
    pm_root = ppt_master.locate()
    if not (pm_root / "skills" / "ppt-master" / "SKILL.md").exists():
        print(f"未找到 ppt-master：{pm_root}。请先运行 scripts/setup_ppt_master.sh 或设置 PPT_MASTER_DIR。")
        return 2

    files = build_outputs(inputs, report, out_dir, pm_root, ppt_master.current_commit(pm_root))
    print(f"内容包已生成：{out_dir}")

    template = os.environ.get(agent.AGENT_ENV, "").strip()
    if not template:
        print(
            f"未设置 {agent.AGENT_ENV}，跳过 agent 步骤。\n"
            f"任务书：{files['agent_task']}\n"
            "请设置该变量（参见 README），或把任务书交给任意 agent 执行后，再运行：\n"
            f"    python3 -m lawpre verify {input_dir}"
        )
        return 2

    timeout = args.timeout or agent.DEFAULT_TIMEOUT
    print(f"调用 agent（超时 {timeout}s），日志：{out_dir / 'agent.log'}")
    result = agent.run_agent(
        template,
        task_file=files["agent_task"],
        workdir=pm_root,
        out_dir=out_dir,
        timeout=timeout,
    )
    if result.timed_out:
        print("agent 超时。")
        return 3
    if result.returncode != 0:
        print(f"agent 退出码 {result.returncode}，详见 agent.log。")
        return 3

    return _verify(inputs, out_dir)


def _verify(inputs, out_dir: Path) -> int:
    check = agent.verify_deck(out_dir / "deck.pptx", len(inputs.slides))
    result = {
        "ok": check.ok,
        "slides": check.slide_count,
        "pages_with_notes": check.notes_count,
        "problems": check.problems,
        "draft": _is_draft(out_dir),
    }
    (out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if not check.ok:
        print("PPTX 验收未通过：")
        for p in check.problems:
            print(f"  - {p}")
        return 4
    print(f"PPTX 验收通过：{out_dir / 'deck.pptx'}（{check.slide_count} 页，{check.notes_count} 页有讲稿）")
    return 0


def _is_draft(out_dir: Path) -> bool:
    try:
        return bool(json.loads((out_dir / "manifest.json").read_text(encoding="utf-8")).get("draft"))
    except (OSError, json.JSONDecodeError):
        return True


def cmd_verify(args) -> int:
    inputs, report = _load_or_exit(Path(args.input_dir))
    if inputs is None:
        return 1
    out_dir = Path(args.out or DEFAULT_OUT) / inputs.brief["slug"]
    return _verify(inputs, out_dir)


def _templates(slug: str) -> dict[str, dict]:
    ph = PLACEHOLDER
    return {
        "brief.json": {
            "slug": slug,
            "course": ph,
            "title": ph,
            "template_type": "doctrine_analysis",
            "duration_minutes": 10,
            "language": "zh-CN",
            "canvas": "ppt169",
            "presenters": [{"name": ph}],
        },
        "sources.json": {
            "sources": [
                {
                    "id": "S001",
                    "title": ph,
                    "kind": "statute",
                    "issuer": ph,
                    "status": "待核验",
                    "locator": ph,
                }
            ]
        },
        "analysis.json": {
            "issues": [
                {
                    "id": "I01",
                    "issue": ph,
                    "rules": [{"source_id": "S001", "legal_proposition": ph}],
                    "application": [ph],
                    "counterargument": ph,
                    "conclusion": ph,
                    "uncertainties": [],
                }
            ]
        },
        "deck.json": {
            "slides": [
                {
                    "slide_no": i + 1,
                    "kind": kind,
                    "title": ph,
                    "key_message": ph,
                    "body": [],
                    "source_ids": [] if kind == "cover" else ["S001"],
                    "notes_zh": ph,
                    "duration_seconds": 60,
                }
                for i, kind in enumerate(["cover", "issue", "conclusion"])
            ]
        },
    }


def cmd_init(args) -> int:
    slug = args.slug
    if not SLUG_RE.match(slug):
        print("slug 只能包含小写字母、数字和连字符，长度 3–61。")
        return 1
    target = Path(args.root or REPO_ROOT / "inputs") / slug
    if target.exists() and any(target.iterdir()) and not args.force:
        print(f"{target} 已存在且非空；如需覆盖请加 --force。")
        return 1
    target.mkdir(parents=True, exist_ok=True)
    for name, data in _templates(slug).items():
        (target / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已生成模板：{target}")
    print(f"请把所有 {PLACEHOLDER} 替换为实际内容，然后运行：python3 -m lawpre check {target}")
    return 0


def cmd_doctor(args) -> int:
    checks = ppt_master.doctor(Path(args.root) if args.root else None)
    bad = 0
    for c in checks:
        mark = "OK " if c.ok else "FAIL"
        print(f"[{mark}] {c.name}: {c.detail}")
        bad += 0 if c.ok else 1
    return 0 if bad == 0 else 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lawpre", description="LawPRE：法律课程汇报生成流程")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_input(sp):
        sp.add_argument("input_dir", help="输入目录，如 inputs/<slug>")
        sp.add_argument("--out", help=f"输出根目录（默认 {DEFAULT_OUT}）")

    add_input(sub.add_parser("check", help="只校验输入"))
    sp = sub.add_parser("init", help="生成 inputs/<slug>/ 的模板文件")
    sp.add_argument("slug")
    sp.add_argument("--root", help="输入根目录（默认 inputs/）")
    sp.add_argument("--force", action="store_true", help="覆盖已有非空目录")
    sp = sub.add_parser("build", help="校验并生成内容包")
    add_input(sp)
    sp = sub.add_parser("run", help="生成内容包并调用 agent 制作 PPTX")
    add_input(sp)
    sp.add_argument("--timeout", type=int, help="agent 超时秒数")
    add_input(sub.add_parser("verify", help="验收已有的 deck.pptx"))
    sp = sub.add_parser("doctor", help="检查 ppt-master 环境")
    sp.add_argument("--root", help="ppt-master 根目录（默认读取 PPT_MASTER_DIR）")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {
        "init": cmd_init,
        "check": cmd_check,
        "build": cmd_build,
        "run": cmd_run,
        "verify": cmd_verify,
        "doctor": cmd_doctor,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
