"""把校验通过的输入渲染成 ppt-master 需要的内容文件和交付文档。

输出目录结构（out/<slug>/）：
    source/content.md       ppt-master 的逐页内容（Quick 路线的唯一内容来源）
    source/references.md    引用资料表（不进入 PPT 页面，单独交付）
    notes/total.md          完整中文讲稿，ppt-master 的 notes 分页格式
    SCRIPT_zh.md            给人阅读的讲稿与时间表
    QA_REPORT.md            校验结果与草稿状态
    AGENT_TASK.md           交给 agent 的任务书
    manifest.json           输入指纹与生成记录
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .inputs import Inputs, Report

REPO_ROOT = Path(__file__).resolve().parents[1]

DRAFT_BANNER = "草稿：含未完全核验的法律依据，未经人工法律审查前不得作为最终版本"


def _fmt_seconds(seconds: int) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}分{s:02d}秒"


def _source_line(src: dict[str, Any]) -> str:
    return f"[{src['id']}] {src['title']}（{src['issuer']}，{src['locator']}，状态：{src['status']}）"


def _input_fingerprint(input_dir: Path) -> dict[str, str]:
    out = {}
    for path in sorted(input_dir.glob("*.json")):
        out[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def render_content_md(inputs: Inputs, report: Report) -> str:
    brief = inputs.brief
    sources = inputs.source_index
    lines = [
        f"# {brief['title']}",
        "",
        f"课程：{brief['course']}  ",
        f"汇报人：{'、'.join(p['name'] for p in brief['presenters'])}  ",
        f"目标时长：约 {brief['duration_minutes']} 分钟，共 {len(inputs.slides)} 页  ",
        "画布：16:9（ppt169），语言：中文",
        "",
    ]
    if report.draft:
        lines += [f"> {DRAFT_BANNER}", ""]
    for s in inputs.slides:
        lines += [
            f"## 第 {s['slide_no']} 页｜{s['title']}",
            "",
            f"- 页面类型：{s['kind']}",
            f"- 核心结论：{s['key_message']}",
        ]
        if s.get("issue_id"):
            lines.append(f"- 对应争点：{s['issue_id']}")
        if s["body"]:
            lines.append("- 页面要点：")
            lines += [f"  - {item}" for item in s["body"]]
        if s["source_ids"]:
            lines.append("- 页面来源：" + "；".join(f"{sid}" for sid in s["source_ids"]))
            for sid in s["source_ids"]:
                lines.append(f"  - {_source_line(sources[sid])}")
        lines.append(f"- 预计用时：{s['duration_seconds']} 秒")
        lines.append("")
    return "\n".join(lines)


def render_references_md(inputs: Inputs) -> str:
    lines = [
        f"# 引用资料表：{inputs.brief['title']}",
        "",
        "| 编号 | 名称 | 类型 | 发布主体 | 公布/施行 | 原文定位 | 状态 | 说明 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in inputs.sources["sources"]:
        dates = " / ".join(filter(None, [s.get("date_published"), s.get("date_effective")])) or "—"
        note = s.get("status_note", "").replace("|", "\\|") or "—"
        lines.append(
            f"| {s['id']} | {s['title']} | {s['kind']} | {s['issuer']} | {dates} | "
            f"{s['locator']} | {s['status']} | {note} |"
        )
    lines.append("")
    lines.append("## 原文摘录")
    lines.append("")
    for s in inputs.sources["sources"]:
        if s.get("excerpt"):
            lines += [f"**{s['id']} {s['title']} {s['locator']}**", "", f"> {s['excerpt']}", ""]
    if inputs.sources["sources"] and any(s.get("url") for s in inputs.sources["sources"]):
        lines += ["## 链接", ""]
        lines += [f"- {s['id']}：{s['url']}" for s in inputs.sources["sources"] if s.get("url")]
        lines.append("")
    return "\n".join(lines)


def render_notes_total(inputs: Inputs) -> str:
    """ppt-master 的 notes/total.md：`# NN_标题` 分页，`---` 分隔，正文只能是口语。"""
    parts = []
    for s in inputs.slides:
        parts.append(f"# {s['slide_no']:02d}_{s['title']}\n\n{s['notes_zh'].strip()}\n")
    return "\n---\n\n".join(parts)


def render_script_md(inputs: Inputs, report: Report) -> str:
    brief = inputs.brief
    sources = inputs.source_index
    stats = report.stats
    lines = [
        f"# 讲稿：{brief['title']}",
        "",
        f"- 课程：{brief['course']}",
        f"- 汇报人：{'、'.join(p['name'] for p in brief['presenters'])}",
        f"- 目标时长：{_fmt_seconds(stats['target_seconds'])}；逐页设定合计 {_fmt_seconds(stats['planned_seconds'])}；"
        f"按 260 字/分钟估算约 {_fmt_seconds(stats['estimated_seconds'])}",
        f"- 状态：{DRAFT_BANNER if report.draft else '无未核验来源（仍需人工审查）'}",
        "",
    ]
    for s in inputs.slides:
        lines += [
            f"## {s['slide_no']:02d}. {s['title']}",
            "",
            f"*约 {s['duration_seconds']} 秒｜{s['kind']}｜{s['key_message']}*",
            "",
            s["notes_zh"].strip(),
            "",
        ]
        if s["source_ids"]:
            lines.append("本页依据：" + "；".join(
                f"{sid}《{sources[sid]['title']}》{sources[sid]['locator']}" for sid in s["source_ids"]
            ))
            lines.append("")
    return "\n".join(lines)


def render_qa_md(inputs: Inputs, report: Report) -> str:
    stats = report.stats
    status = (
        "存在未完全核验的依据（草稿）" if report.draft
        else "未发现未核验依据；仍需人工法律审查后才可宣称审核完成"
    )
    lines = [
        f"# 质量检查报告：{inputs.brief['title']}",
        "",
        f"- 结果：{'通过校验' if report.ok else '未通过校验（见错误）'}",
        f"- 草稿状态：{status}",
        f"- 页数：{stats.get('slides', 0)}",
        f"- 逐页设定时长：{stats.get('planned_seconds', 0)} 秒（目标 {stats.get('target_seconds', 0)} 秒）",
        f"- 讲稿估算时长：{stats.get('estimated_seconds', 0)} 秒",
        f"- 讲稿字数（含标点）：{stats.get('notes_chars', 0)}",
        f"- 引用来源：{'、'.join(stats.get('referenced_sources', [])) or '无'}",
        f"- 未完全核验的来源：{'、'.join(stats.get('unverified_sources', [])) or '无'}",
        "",
        "## 错误",
        "",
    ]
    lines += [f"- {e}" for e in report.errors] or ["无"]
    lines += ["", "## 警告", ""]
    lines += [f"- {w}" for w in report.warnings] or ["无"]
    lines += [
        "",
        "## 人工确认项（不由程序完成）",
        "",
        "- [ ] 逐条核对法律依据的现行效力（国家法律法规数据库）",
        "- [ ] 核对每条规则的原文定位与引用是否支持所述结论",
        "- [ ] 确认反方观点与“待补充”事项是否已处理",
        "- [ ] 排练一遍，确认实际时长在目标范围内",
        "",
    ]
    return "\n".join(lines)


def render_agent_task(
    inputs: Inputs,
    report: Report,
    out_dir: Path,
    ppt_master_dir: Path,
) -> str:
    brief = inputs.brief
    slides = len(inputs.slides)
    py = sys.executable  # 运行 LawPRE 的解释器（doctor 已检查其 ppt-master 依赖）
    draft_line = (
        f"**草稿标注（必须）**：在封面页底部小字注明“{DRAFT_BANNER}”。"
        if report.draft else "本次依据均已核验；仍请在封面注明“待人工审查”。"
    )
    return f"""# 任务：用 ppt-master 技能生成一份中文 PPTX 课堂汇报

你是一个在 LawPRE 流程中工作的 agent。下面是完整任务书。除非遇到无法继续的阻塞问题，请直接完成；
无法完成的部分写入 `{out_dir / 'AGENT_REPORT.md'}` 并说明原因。

## 1. 必读的技能入口（路径固定）

- 技能目录：`{ppt_master_dir / 'skills' / 'ppt-master'}`
- 先阅读 `SKILL.md`，然后按其中的路由表选择路线。
- **本任务明确要求 Quick（无交互）路线**，对应
  `workflows/profiles/quick-generate.md`。不要进入 Default 路线，不要生成 Strategist、确认页或 design_spec/spec_lock。
- 仓库的 `AGENTS.md` 中的 Command Quick Reference 给出了全部命令，请用绝对路径调用。

## 2. 输入（只读，不要修改）

- 逐页内容：`{out_dir / 'source' / 'content.md'}`（页数严格为 **{slides} 页**，顺序不变，不新增、不合并、不删除页面）
- 完整讲稿（最终口播稿）：`{out_dir / 'notes' / 'total.md'}`
- 引用资料表：`{out_dir / 'source' / 'references.md'}`（不进入 PPT 页面，仅供核对）

## 3. 内容规则（硬性）

1. 所有事实、条文、数字只能来自 `content.md` 和 `references.md`。发现缺口时，在该页标注“待核验”，**不得**自行补充法条、案例或数据。
2. 页面上的文字以 `content.md` 为准；页面标题、要点可精简排版，但不得改变含义。
3. 讲稿 `notes/total.md` 是已定稿的口播稿：按 notes 的 pre-SVG narration 分支**校验并原样保留**，不得改写或润色。
4. 画布：16:9（`ppt169`，1280x720）。所有页面使用简体中文；字体要保证中文可读。
5. {draft_line}
6. 页脚或来源标注使用 content.md 中的编号（如 S001），便于核对。

## 4. 执行步骤

1. 按 SKILL.md 与 Quick 路线完成 Plan（§2）与逐页 SVG 编写（§3）。
   - 可选：`{py} {REPO_ROOT / 'skills' / 'lawpre' / 'scripts' / 'render_svg.py'} {REPO_ROOT / 'inputs' / brief['slug']} <project_path>/svg_output` 生成固定版式的逐页 SVG（已通过 Quick 质检），之后按需调整。
2. 把 `{out_dir / 'notes' / 'total.md'}` 复制到项目的 `notes/total.md`，然后依次运行：
   - `{py} {ppt_master_dir / 'skills/ppt-master/scripts/total_md_split.py'} <project_path>`（按页拆分讲稿）
   - `{py} {ppt_master_dir / 'skills/ppt-master/scripts/svg_quality_checker.py'} <project_path> --quick-generate --canonical-authoring --stage final --json`，直到通过
   - `{py} {ppt_master_dir / 'skills/ppt-master/scripts/svg_to_pptx.py'} <project_path> --quick-generate --with-notes -o {out_dir / 'deck.pptx'}`
   - 以上命令必须使用 `{py}`（已安装 python-pptx 与 lxml 的解释器）。系统 `python3` 通常没有这些依赖，会直接失败。
3. 导出后检查：
   - `{out_dir / 'deck.pptx'}` 存在，且页数为 **{slides}**；
   - 每页都有讲稿（备注）；
   - 没有残留的 `design_spec.md`、`spec_lock.md`、`finalize_svg.py` 产物。
4. 把以下内容写入 `{out_dir / 'AGENT_REPORT.md'}`：导出路径、页数、讲稿页数、质检结果、
   任何与本任务书不一致之处、以及仍需人工核对的页面。

## 5. 任务参数（供参考）

- 课程：{brief['course']}
- 题目：{brief['title']}
- 目标时长：{brief['duration_minutes']} 分钟
- 建议项目名：`lawpre_{brief['slug'].replace('-', '_')}`
- 项目根目录：`{ppt_master_dir}`（在其 `projects/` 下创建项目）

## 6. 禁止事项

- 不要修改 LawPRE 仓库中的任何文件。
- 不要访问或修改 ppt-master 仓库之外的路径。
- 不要删除 `{out_dir}` 下已有的文件。
"""


def build_outputs(
    inputs: Inputs,
    report: Report,
    out_dir: Path,
    ppt_master_dir: Path,
    ppt_master_commit: str | None,
) -> dict[str, Path]:
    (out_dir / "source").mkdir(parents=True, exist_ok=True)
    (out_dir / "notes").mkdir(parents=True, exist_ok=True)

    files = {
        "content": out_dir / "source" / "content.md",
        "references": out_dir / "source" / "references.md",
        "notes": out_dir / "notes" / "total.md",
        "script": out_dir / "SCRIPT_zh.md",
        "qa": out_dir / "QA_REPORT.md",
        "agent_task": out_dir / "AGENT_TASK.md",
        "manifest": out_dir / "manifest.json",
    }
    files["content"].write_text(render_content_md(inputs, report), encoding="utf-8")
    files["references"].write_text(render_references_md(inputs), encoding="utf-8")
    files["notes"].write_text(render_notes_total(inputs), encoding="utf-8")
    files["script"].write_text(render_script_md(inputs, report), encoding="utf-8")
    files["qa"].write_text(render_qa_md(inputs, report), encoding="utf-8")
    files["agent_task"].write_text(
        render_agent_task(inputs, report, out_dir, ppt_master_dir), encoding="utf-8"
    )
    manifest = {
        "slug": inputs.brief["slug"],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input_sha256": _input_fingerprint(inputs.input_dir),
        "ppt_master_dir": str(ppt_master_dir),
        "ppt_master_commit": ppt_master_commit,
        "draft": report.draft,
        "slides": len(inputs.slides),
        "warnings": len(report.warnings),
    }
    files["manifest"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return files
