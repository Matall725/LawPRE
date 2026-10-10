"""定位并检查 ppt-master 技能仓库。

LawPRE 不内置 ppt-master，只依赖一份本地克隆。默认位置为 ~/tools/ppt-master，
可通过环境变量 PPT_MASTER_DIR 覆盖。我们固定在已验证的版本上，升级前需要重新检查。
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PINNED_TAG = "v6.7.0"
PINNED_COMMIT = "b4efe3ddf237a97a42880164759162f8e2412f2f"
REPO_URL = "https://github.com/hugohe3/ppt-master.git"


def locate() -> Path:
    env = os.environ.get("PPT_MASTER_DIR")
    return Path(env).expanduser() if env else Path.home() / "tools" / "ppt-master"


def current_commit(root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=20, check=True,
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def doctor(root: Path | None = None) -> list[Check]:
    root = root or locate()
    checks: list[Check] = []

    skill = root / "skills" / "ppt-master" / "SKILL.md"
    checks.append(Check("ppt-master 目录", skill.exists(), f"{root}" if skill.exists() else f"未找到 {skill}"))
    if not skill.exists():
        return checks

    commit = current_commit(root)
    if commit is None:
        checks.append(Check("版本", False, "无法读取 git 版本，请确认该目录是 git 克隆"))
    elif commit == PINNED_COMMIT:
        checks.append(Check("版本", True, f"{PINNED_TAG} ({commit[:7]})"))
    else:
        checks.append(Check("版本", False, f"当前 {commit[:7]}，LawPRE 已验证的是 {PINNED_TAG} ({PINNED_COMMIT[:7]})"))

    guard = root / "skills" / "ppt-master" / "scripts" / "attribution_guard.py"
    if guard.exists():
        res = subprocess.run([sys.executable, str(guard)], capture_output=True, text=True, timeout=60, check=False)
        checks.append(Check("attribution_guard", res.returncode == 0, "通过" if res.returncode == 0 else res.stdout + res.stderr))
    else:
        checks.append(Check("attribution_guard", False, "脚本不存在"))

    for mod in ("pptx", "lxml"):
        try:
            __import__(mod)
            checks.append(Check(f"Python 包 {mod}", True, "已安装"))
        except ImportError:
            checks.append(Check(f"Python 包 {mod}", False, f"未安装；见 {root / 'skills' / 'ppt-master' / 'requirements.txt'}"))

    return checks
