"""讲稿字数与口播时长估算。

中文口头汇报的常见语速约每分钟 240–280 个汉字。这里取 260 作为估算值，
只用于发出警告，不作为硬性失败条件；最终以排练时长为准。
"""

from __future__ import annotations

import re

CHARS_PER_MINUTE = 260
DURATION_TOLERANCE = 0.10  # 总时长相对目标允许的偏差（硬性）
SLIDE_TOLERANCE = 0.25  # 单页估算时长相对设定值允许的偏差（警告）

_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_LETTER = re.compile(r"[A-Za-z]")
_MARKUP_LINE = re.compile(r"^\s*(#|[-*+>|]\s|\d+[.、]\s|```)")


def cjk_count(text: str) -> int:
    return len(_CJK.findall(text))


def cjk_ratio(text: str) -> float:
    """汉字占（汉字 + 拉丁字母）的比例；不含标点与数字。"""
    cjk = cjk_count(text)
    letters = len(_LETTER.findall(text))
    total = cjk + letters
    return cjk / total if total else 0.0


def estimate_seconds(text: str) -> float:
    return cjk_count(text) / CHARS_PER_MINUTE * 60


def markup_lines(text: str) -> list[str]:
    """讲稿中不允许出现的列表、标题、引用等标记行。"""
    return [line for line in text.splitlines() if _MARKUP_LINE.match(line)]
