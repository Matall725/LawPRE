#!/usr/bin/env python3
"""把校验通过的 deck.json 渲染成 ppt-master 的逐页 SVG（固定版式）。

这是 LawPRE 的“固定模板”步骤：版式、配色、字体和页脚都由本脚本决定，
agent 只负责内容。输出文件命名为 NN_<kind>.svg，与 notes/total.md 的页号一一对应。

用法：
    python3 skills/lawpre/scripts/render_svg.py inputs/<slug> <ppt-master 项目>/svg_output

字体与字宽：中文 Microsoft YaHei，拉丁 Arial。字宽系数来自
`text_measure.py calibrate`（正文 22px 的 CJK 约 1.06em，保守取拉丁 0.58em）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from xml.sax.saxutils import escape

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from lawpre.inputs import load_inputs  # noqa: E402

W, H = 1280, 720
FONT = "Microsoft YaHei, Arial"
PAL = {
    "navy": "#1B2F4B",
    "gold": "#B08D2E",
    "gold_light": "#E6D9B4",
    "paper": "#F6F4EE",
    "ink": "#2A2A2A",
    "grey": "#6B6B6B",
    "white": "#FFFFFF",
}
CJK_EM = 1.06
LATIN_EM = 0.58
NO_LINE_START = set("，。、；：！？）》」”’…")
KIND_LABEL = {
    "issue": "问题",
    "rule": "规则",
    "analysis": "适用",
    "counterargument": "反方",
    "conclusion": "结论",
    "cover": "封面",
}
LH_BODY = 34  # 22px 正文的行距（约 1.55 倍）


def _char_w(ch: str, fs: float) -> float:
    cp = ord(ch)
    if 0x3000 <= cp <= 0x303F or 0x4E00 <= cp <= 0x9FFF or 0xFF00 <= cp <= 0xFFEF:
        return fs * CJK_EM
    return fs * LATIN_EM


def wrap(text: str, fs: float, max_w: float) -> list[str]:
    """按字宽逐字换行；标点不作行首；保留 5% 余量。"""
    limit = max_w * 0.95
    lines: list[str] = []
    cur = ""
    width = 0.0
    for ch in text:
        w = _char_w(ch, fs)
        if cur and width + w > limit and ch not in NO_LINE_START:
            lines.append(cur)
            cur, width = "", 0.0
        cur += ch
        width += w
    if cur:
        lines.append(cur)
    return lines


def text_el(x: float, y: float, lines: list[str], fs: int, fill: str, lh: float, anchor: str = "start") -> str:
    if not lines:
        return ""
    first = escape(lines[0])
    rest = "".join(
        f'<tspan x="{x}" dy="{lh}">{escape(line)}</tspan>' for line in lines[1:]
    )
    anchor_attr = "" if anchor == "start" else f' text-anchor="{anchor}"'
    return f'<text x="{x}" y="{y}" font-size="{fs}" fill="{fill}"{anchor_attr}>{first}{rest}</text>'


def zone(x: float, y_first: float, n_lines: int, fs: float, lh: float, width: float) -> tuple[float, float, float, float]:
    """文本区域：从第一行字顶到最后一行字底（含上升部与下降部）。"""
    top = y_first - fs - 4
    bottom = y_first + (n_lines - 1) * lh + fs * 0.35 + 6
    return (x, round(top, 1), width, round(bottom - top, 1))


def group(gid: str, bounds: tuple[float, float, float, float], body: str) -> str:
    x, y, w, h = bounds
    return f'<g id="{gid}" data-pptx-bounds="{x} {y} {w} {h}">{body}</g>'


def rect(x: float, y: float, w: float, h: float, fill: str, rx: float = 0) -> str:
    rx_attr = f' rx="{rx}"' if rx else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}"{rx_attr} fill="{fill}"/>'


def svg_root(kind_role: str, lang: str, body: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'font-family="{FONT}" lang="{lang}" data-pptx-page-role="{kind_role}">\n'
        f"{body}\n</svg>\n"
    )


def render_cover(slide: dict, brief: dict, draft: bool) -> str:
    title_lines = wrap(slide["title"], 44, 1000)
    sub_lines = wrap(slide["key_message"], 22, 1000)
    meta = f"课程：{brief['course']}　汇报人：{'、'.join(p['name'] for p in brief['presenters'])}"
    body = [rect(0, 0, W, H, PAL["navy"])]
    body.append(group("cover-accent", (90, 236, 80, 6), rect(90, 236, 80, 6, PAL["gold"])))
    title_y = 318
    body.append(group("cover-title", zone(90, title_y, len(title_lines), 44, 60, 1000),
                      text_el(90, title_y, title_lines, 44, PAL["white"], 60)))
    sub_y = title_y + 60 * (len(title_lines) - 1) + 58
    body.append(group("cover-subtitle", zone(90, sub_y, len(sub_lines), 22, LH_BODY, 1000),
                      text_el(90, sub_y, sub_lines, 22, PAL["gold_light"], LH_BODY)))
    body.append(group("cover-meta", zone(90, 620, len(wrap(meta, 16, 1100)), 16, 24, 1100),
                      text_el(90, 620, wrap(meta, 16, 1100), 16, PAL["gold_light"], 24)))
    if draft:
        banner = "草稿：法律依据部分核验中，未经人工法律审查前不得作为最终版本"
        body.append(group("cover-draft", zone(90, 670, len(wrap(banner, 16, 1100)), 16, 24, 1100),
                          text_el(90, 670, wrap(banner, 16, 1100), 16, PAL["gold"], 24)))
    return svg_root("cover", "zh-CN", "\n".join(body))


def render_content(slide: dict, total: int, brief_lang: str) -> str:
    body = [rect(0, 0, W, H, PAL["paper"])]
    kind = KIND_LABEL.get(slide["kind"], "")

    # 顶部：页面类型标签 + 标题
    tag_w = max(64, 22 * len(kind) + 28)
    tag_x = W - 60 - tag_w
    tag = (
        rect(tag_x, 44, tag_w, 30, PAL["white"], rx=15)
        + f'<rect x="{tag_x}" y="44" width="{tag_w}" height="30" rx="15" fill="none" stroke="{PAL["gold"]}" stroke-width="1.5"/>'
        + text_el(tag_x + tag_w / 2, 65, [kind], 16, PAL["gold"], 0, anchor="middle")
    )
    body.append(group("kind-tag", (tag_x, 44, tag_w, 30), tag))

    title_lines = wrap(slide["title"], 36, tag_x - 100 - 40)
    body.append(group(
        "page-title",
        zone(60, 82, len(title_lines), 36, 46, tag_x - 100),
        rect(60, 46, 6, 46, PAL["gold"]) + text_el(84, 82, title_lines, 36, PAL["navy"], 46),
    ))

    # 核心结论
    key_lines = wrap(slide["key_message"], 22, 1120)
    key_y = 82 + 46 * (len(title_lines) - 1) + 50
    body.append(group(
        "key-message",
        zone(84, key_y, len(key_lines), 22, LH_BODY, 1120),
        text_el(84, key_y, key_lines, 22, PAL["navy"], LH_BODY),
    ))
    y = key_y + LH_BODY * (len(key_lines) - 1) + 52

    # 要点
    items = []
    for text in slide["body"]:
        lines = wrap(text, 22, 1040 - 30)
        items.append(lines)
    for i, lines in enumerate(items):
        item_h = LH_BODY * len(lines)
        marker = rect(84, y - 17, 10, 10, PAL["gold"])
        text = text_el(84 + 30, y, lines, 22, PAL["ink"], LH_BODY)
        body.append(group(f"point-{i + 1}", zone(84, y, len(lines), 22, LH_BODY, 1040), marker + text))
        y += item_h + 26
    body_bottom = y - 26
    # 空白区过大时不强行填充；版式保持留白

    # 页脚：来源与页码
    src = "依据：" + "、".join(slide["source_ids"]) if slide["source_ids"] else "本页为概述，不引用法律依据"
    body.append(group("footer-source", zone(60, 672, 1, 16, 22, 1000), text_el(60, 672, [src], 16, PAL["grey"], 22)))
    body.append(group("page-number", zone(1120, 672, 1, 16, 22, 100),
                      text_el(1220, 672, [f"{slide['slide_no']:02d} / {total:02d}"], 16, PAL["grey"], 22, anchor="end")))
    if body_bottom > 640:
        raise ValueError(f"第 {slide['slide_no']} 页内容超出版式可用高度（{body_bottom:.0f}px）")
    return svg_root("content", brief_lang, "\n".join(body))


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    input_dir, out_dir = Path(argv[1]), Path(argv[2])
    inputs, report = load_inputs(input_dir)
    if inputs is None or not report.ok:
        print("输入未通过校验，不生成 SVG。请先运行 python3 -m lawpre check")
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.svg"):
        old.unlink()
    total = len(inputs.slides)
    lang = inputs.brief["language"]
    for s in inputs.slides:
        name = f"{s['slide_no']:02d}_{s['kind']}.svg"
        if s["kind"] == "cover":
            svg = render_cover(s, inputs.brief, report.draft)
        else:
            svg = render_content(s, total, lang)
        (out_dir / name).write_text(svg, encoding="utf-8")
        print(f"写入 {out_dir / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
