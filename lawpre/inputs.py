"""读取并校验一次 PRE 任务的四个输入文件。

校验分两层：
1. JSON Schema：字段、类型、枚举、编号格式；
2. 语义检查：引用的来源是否存在、来源状态是否允许作为依据、
   逐页来源是否齐全、总时长是否贴近目标、讲稿是否为中文口播正文。

错误（error）会阻止生成；警告（warning）会写入 QA 报告并标注草稿状态。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .timing import (
    DURATION_TOLERANCE,
    SLIDE_TOLERANCE,
    cjk_ratio,
    estimate_seconds,
    markup_lines,
)

SCHEMA_DIR = Path(__file__).parent / "schemas"

INPUT_FILES = {
    "brief": "brief.json",
    "sources": "sources.json",
    "analysis": "analysis.json",
    "deck": "deck.json",
}

PLACEHOLDER = "【待填写】"

LEGAL_KINDS = {
    "statute",
    "administrative_regulation",
    "departmental_rule",
    "judicial_interpretation",
    "guiding_case",
}
# 这些状态的来源不能被当作已确认的依据
UNVERIFIED = {"待核验", "部分核验", "存在问题"}
# 这些状态的来源不能作为规则依据（规则引用时报错）
NOT_USABLE_AS_RULE = {"不适用", "存在问题"}


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def draft(self) -> bool:
        """只要有引用的来源未完全核验，产物就只能是草稿。"""
        return bool(self.stats.get("unverified_sources"))


@dataclass
class Inputs:
    brief: dict[str, Any]
    sources: dict[str, Any]
    analysis: dict[str, Any]
    deck: dict[str, Any]
    input_dir: Path

    @property
    def source_index(self) -> dict[str, dict[str, Any]]:
        return {s["id"]: s for s in self.sources["sources"]}

    @property
    def issue_index(self) -> dict[str, dict[str, Any]]:
        return {i["id"]: i for i in self.analysis["issues"]}

    @property
    def slides(self) -> list[dict[str, Any]]:
        return self.deck["slides"]


def _schema_errors(name: str, data: Any) -> list[str]:
    schema = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    out = []
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in err.absolute_path) or "(根)"
        out.append(f"{INPUT_FILES[name]} {where}: {err.message}")
    return out


def load_inputs(input_dir: Path) -> tuple[Inputs | None, Report]:
    report = Report()
    loaded: dict[str, Any] = {}
    for key, filename in INPUT_FILES.items():
        path = input_dir / filename
        if not path.exists():
            report.errors.append(f"缺少输入文件：{path}")
            continue
        try:
            loaded[key] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            report.errors.append(f"{filename} 不是合法 JSON：{exc}")

    if report.errors:
        return None, report

    for key, filename in INPUT_FILES.items():
        raw = (input_dir / filename).read_text(encoding="utf-8")
        if PLACEHOLDER in raw:
            report.errors.append(f"{filename} 仍含未填写的占位内容（{PLACEHOLDER}），请补全后再运行")
    if report.errors:
        return None, report

    for key in INPUT_FILES:
        report.errors.extend(_schema_errors(key, loaded[key]))
    if report.errors:
        return None, report

    inputs = Inputs(
        brief=loaded["brief"],
        sources=loaded["sources"],
        analysis=loaded["analysis"],
        deck=loaded["deck"],
        input_dir=input_dir,
    )
    semantic = check_semantics(inputs)
    return inputs, semantic


def check_semantics(inputs: Inputs) -> Report:
    r = Report()
    target_seconds = inputs.brief["duration_minutes"] * 60
    sources = inputs.source_index
    issues = inputs.issue_index
    slides = inputs.slides

    # 1. 来源登记表
    if len(sources) != len(inputs.sources["sources"]):
        r.errors.append("sources.json 中存在重复的来源 id")
    for s in inputs.sources["sources"]:
        if s["kind"] in LEGAL_KINDS and not s.get("excerpt"):
            r.warnings.append(f"{s['id']} 是法律规范但缺少原文摘录（excerpt），无法核对条文")
        if s["status"] in UNVERIFIED and not s.get("status_note"):
            r.warnings.append(f"{s['id']} 状态为“{s['status']}”，但没有说明未核验的部分（status_note）")

    # 2. 分析单元
    if len(issues) != len(inputs.analysis["issues"]):
        r.errors.append("analysis.json 中存在重复的争点 id")
    for issue in inputs.analysis["issues"]:
        for rule in issue["rules"]:
            sid = rule["source_id"]
            if sid not in sources:
                r.errors.append(f"{issue['id']} 的规则引用了未登记的来源 {sid}")
            elif sources[sid]["status"] in NOT_USABLE_AS_RULE:
                r.errors.append(
                    f"{issue['id']} 的规则引用了状态为“{sources[sid]['status']}”的来源 {sid}，不能作为依据"
                )

    # 3. 逐页结构
    numbers = [s["slide_no"] for s in slides]
    if numbers != list(range(1, len(slides) + 1)):
        r.errors.append(f"slide_no 必须从 1 开始连续递增，当前为 {numbers}")
    if slides and slides[0]["kind"] != "cover":
        r.errors.append("第 1 页必须是封面（kind=cover）")
    if not 6 <= len(slides) <= 14:
        r.warnings.append(f"页数 {len(slides)} 不在 6–14 的常见范围内，请确认时长是否合适")

    total = sum(s["duration_seconds"] for s in slides)
    if abs(total - target_seconds) > DURATION_TOLERANCE * target_seconds:
        r.errors.append(
            f"逐页设定时长合计 {total} 秒，偏离目标 {target_seconds} 秒超过 "
            f"{int(DURATION_TOLERANCE * 100)}%"
        )

    referenced_sources: set[str] = set()
    referenced_issues: set[str] = set()
    est_total = 0.0
    cjk_total = 0

    for s in slides:
        n = s["slide_no"]
        ids = s["source_ids"]
        for sid in ids:
            if sid not in sources:
                r.errors.append(f"第 {n} 页引用了未登记的来源 {sid}")
        if s["kind"] != "cover" and not ids:
            r.errors.append(f"第 {n} 页（{s['kind']}）没有任何来源 id；无来源的内容不能进入 PPT")
        if "issue_id" in s:
            if s["issue_id"] not in issues:
                r.errors.append(f"第 {n} 页引用了未登记的争点 {s['issue_id']}")
            else:
                referenced_issues.add(s["issue_id"])
        referenced_sources.update(ids)

        # 讲稿
        notes = s["notes_zh"]
        if markup_lines(notes):
            r.errors.append(f"第 {n} 页讲稿含有列表、标题等标记行；讲稿必须是口语正文")
        ratio = cjk_ratio(notes)
        if ratio < 0.8:
            r.errors.append(f"第 {n} 页讲稿不是中文正文（汉字占比 {ratio:.0%}）")
        est = estimate_seconds(notes)
        est_total += est
        cjk_total += len(notes)
        if s["duration_seconds"] and abs(est - s["duration_seconds"]) > SLIDE_TOLERANCE * s["duration_seconds"]:
            r.warnings.append(
                f"第 {n} 页讲稿估算约 {est:.0f} 秒，设定为 {s['duration_seconds']} 秒，建议调整讲稿或时长"
            )

    if abs(est_total - target_seconds) > SLIDE_TOLERANCE * target_seconds:
        r.warnings.append(
            f"讲稿整体估算约 {est_total / 60:.1f} 分钟，目标 {target_seconds / 60:.0f} 分钟，"
            "请调整讲稿长度或设定时长"
        )

    for issue_id in issues:
        if issue_id not in referenced_issues:
            r.warnings.append(f"争点 {issue_id} 没有出现在任何一页中")

    # 4. 草稿状态
    unverified = sorted(
        sid for sid in referenced_sources if sid in sources and sources[sid]["status"] in UNVERIFIED
    )
    if unverified:
        r.warnings.append(
            "引用的来源未完全核验：" + "、".join(unverified) + "。产物将标注为草稿，不得宣称已审核完成"
        )

    r.stats = {
        "slides": len(slides),
        "target_seconds": target_seconds,
        "planned_seconds": total,
        "estimated_seconds": round(est_total),
        "notes_chars": cjk_total,
        "referenced_sources": sorted(referenced_sources),
        "unverified_sources": unverified,
    }
    return r
