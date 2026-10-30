"""版本号比较。

Minecraft 生态里的版本字符串极度不规范（``1.21.1-1.15.46``、
``neoforge-1.21.1-4.1.0``、``3.8.2+1.21.1-neoforge``、``0.5.3``……），
因此“是否有新版本”以**发布时间**为主判据，版本号比较只用于展示排序与兜底。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from modchecker.models import ChangeLevel

_NUM_RE = re.compile(r"\d+")
_TOKEN_RE = re.compile(r"[0-9]+|[a-zA-Z]+")

# 文件名 / 版本号里的预发布标记：alpha、beta、snapshot、preview、rc1、pre233、-dev 等
_PRERELEASE_RE = re.compile(
    r"(?i)(?:^|[^a-z0-9])(?:alpha|beta|snapshot|preview|experimental|rc|pre|dev)(?=\d|[^a-z]|$)")

# 预发布阶段权重：键值越大越“新”
_STAGE_WEIGHTS = {
    "snapshot": -4,
    "dev": -3,
    "alpha": -2,
    "beta": -1,
    "pre": -1,
    "preview": -1,
    "test": -1,
    "rc": 0,
}
_RELEASE_WEIGHT = 1

# 出现在版本号里但不代表阶段的关键词（如加载器名）
_NOISE = {"neoforge", "forge", "fabric", "quilt", "mc", "java", "release"}


def parse_iso(value: str | None) -> datetime | None:
    """解析 ISO 时间串（CurseForge 的时间常带 1-2 位小数秒）。"""
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # 归一化小数位：2026-10-25T14:13:32.66Z -> .660000
    text = re.sub(r"\.(\d+)", lambda m: "." + (m.group(1) + "000000")[:6], text, count=1)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def version_key(version: str) -> tuple[tuple[int, ...], int]:
    """把版本串转换为可排序的键：(数字序列, 阶段权重)。"""
    if not version:
        return ((), _RELEASE_WEIGHT)
    numbers = tuple(int(x) for x in _NUM_RE.findall(version))
    stage = _RELEASE_WEIGHT
    for token in _TOKEN_RE.findall(version.lower()):
        if token.isdigit() or token in _NOISE:
            continue
        if token in _STAGE_WEIGHTS:
            stage = min(stage, _STAGE_WEIGHTS[token])
    return (numbers, stage)


def compare(a: str, b: str) -> int:
    """返回 -1/0/1。数字段逐位比较，缺位补 0；数字相同再比较阶段。"""
    nums_a, stage_a = version_key(a)
    nums_b, stage_b = version_key(b)
    length = max(len(nums_a), len(nums_b))
    padded_a = nums_a + (0,) * (length - len(nums_a))
    padded_b = nums_b + (0,) * (length - len(nums_b))
    if padded_a != padded_b:
        return -1 if padded_a < padded_b else 1
    if stage_a != stage_b:
        return -1 if stage_a < stage_b else 1
    return 0


def _strip_noise(text: str, mc_version: str, loader: str) -> str:
    """去掉版本串中与“模组自身版本”无关的部分（MC 版本、加载器名）。

    ``ars_elemental-1.21.1-0.7.1`` 与 ``0.7.1`` 应视为同一版本。
    """
    result = text or ""
    parts = [p for p in (mc_version or "").split(".") if p]
    if parts:
        result = re.sub(rf"\b{re.escape(mc_version)}\b", " ", result, flags=re.IGNORECASE)
        if len(parts) >= 2:
            family = re.escape(".".join(parts[:2]))
            result = re.sub(rf"\b{family}(?:\.\d+)?\b", " ", result, flags=re.IGNORECASE)
    for noise in ("neoforge", "forge", "fabric", "quilt", "mc", "marker"):
        result = re.sub(rf"(?i)\b{noise}\b", " ", result)
    if loader:
        result = re.sub(re.escape(loader), " ", result, flags=re.IGNORECASE)
    return result


def comparable_compare(a: str, b: str, mc_version: str = "", loader: str = "") -> int:
    """忽略 MC 版本/加载器噪声后的版本比较。"""
    return compare(_strip_noise(a, mc_version, loader), _strip_noise(b, mc_version, loader))


def decide(installed: str, latest: str,
           installed_date: datetime | None = None,
           latest_date: datetime | None = None,
           mc_version: str = "",
           loader: str = "") -> bool | None:
    """综合发布时间与（去噪声后的）版本号，判断 latest 是否真的更新。

    两个数据源的版本命名习惯不一致时（例如文件名风格 vs 纯版本号），
    发布时间的差异会误报，因此版本号等价时以“不更新”为准。
    """
    by_date: bool | None = None
    if installed_date and latest_date:
        by_date = latest_date != installed_date and latest_date > installed_date

    cmp: int | None = None
    if installed and latest:
        # 结果含义：latest 相对 installed 的排序（>0 表示 latest 更新）
        cmp = comparable_compare(latest, installed, mc_version, loader)

    if by_date is True:
        return False if cmp == 0 else True
    if by_date is False:
        return False
    if cmp is not None:
        return cmp > 0
    return None


def is_prerelease(*texts: str) -> bool:
    """文本（通常是 jar 文件名或 jar 内版本号）是否带 beta/alpha 等预发布标记。"""
    return any(_PRERELEASE_RE.search(text) for text in texts if text)


def _semantic_numbers(text: str, mc_version: str, loader: str) -> tuple[int, ...]:
    return tuple(int(x) for x in _NUM_RE.findall(_strip_noise(text, mc_version, loader)))


def change_level(installed: str, latest: str, mc_version: str = "", loader: str = "",
                 prerelease: bool = False) -> ChangeLevel:
    """按语义化版本号判断这次更新的量级。

    只比较去掉 MC 版本 / 加载器噪声后的数字段：第一段变化为主版本，
    第二段为次版本，第三段为修订（通常是 bug 修复），更靠后的为构建号。
    本地走 beta/alpha 通道时不做细分，直接归为预发布更新。
    """
    if prerelease:
        return ChangeLevel.PRERELEASE
    before = _semantic_numbers(installed, mc_version, loader)
    after = _semantic_numbers(latest, mc_version, loader)
    if not before or not after:
        return ChangeLevel.UNKNOWN
    for position, level in ((0, ChangeLevel.MAJOR), (1, ChangeLevel.MINOR),
                            (2, ChangeLevel.PATCH)):
        left = before[position] if position < len(before) else 0
        right = after[position] if position < len(after) else 0
        if left != right:
            return level
    if before[3:] != after[3:]:
        return ChangeLevel.BUILD
    return ChangeLevel.UNKNOWN
