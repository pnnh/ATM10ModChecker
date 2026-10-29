"""从 .jar 内部读取模组声明信息（modId / 显示名 / 版本）。

不参与版本判断，仅用于界面展示，以及在网络识别失败时作为搜索关键词。
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - 3.10 及更早
    tomllib = None  # type: ignore[assignment]

_TOML_CANDIDATES = ("META-INF/neoforge.mods.toml", "META-INF/mods.toml")
_JSON_CANDIDATES = ("fabric.mod.json", "quilt.mod.json")
_PLACEHOLDER = re.compile(r"^\$\{.+\}$")


def _read_member(zf: zipfile.ZipFile, name: str, limit: int = 512 * 1024) -> str | None:
    try:
        info = zf.getinfo(name)
    except KeyError:
        return None
    if info.file_size > limit or info.is_dir():
        return None
    try:
        return zf.read(info).decode("utf-8", "replace")
    except (KeyError, OSError, zipfile.BadZipFile):
        return None


def _clean(value: object) -> str:
    text = str(value or "").strip()
    return "" if _PLACEHOLDER.match(text) else text


def _manifest_version(text: str) -> str:
    for line in text.splitlines():
        if line.lower().startswith("implementation-version:"):
            return line.split(":", 1)[1].strip()
    return ""


def read_jar_metadata(path: Path) -> dict[str, str]:
    """返回 ``{"mod_id", "name", "version"}``；读取失败时字段为空串。"""
    result = {"mod_id": "", "name": "", "version": ""}
    try:
        with zipfile.ZipFile(path) as zf:
            if tomllib is not None:
                for name in _TOML_CANDIDATES:
                    raw = _read_member(zf, name)
                    if not raw:
                        continue
                    try:
                        data = tomllib.loads(raw)
                    except Exception:  # 损坏的 TOML 不影响后续尝试
                        continue
                    mods = data.get("mods") or []
                    first = mods[0] if isinstance(mods, list) and mods else {}
                    if isinstance(first, dict):
                        result["mod_id"] = _clean(first.get("modId")) or _clean(first.get("modid"))
                        result["name"] = _clean(first.get("displayName")) or _clean(first.get("display_name"))
                        result["version"] = _clean(first.get("version"))
                    if result["mod_id"] or result["name"]:
                        break

            if not result["mod_id"]:
                for name in _JSON_CANDIDATES:
                    raw = _read_member(zf, name)
                    if not raw:
                        continue
                    try:
                        data = json.loads(raw)
                    except ValueError:
                        continue
                    result["mod_id"] = _clean(data.get("id"))
                    result["name"] = _clean(data.get("name"))
                    result["version"] = _clean(data.get("version"))
                    break

            if not result["version"]:
                manifest = _read_member(zf, "META-INF/MANIFEST.MF")
                if manifest:
                    result["version"] = _clean(_manifest_version(manifest))
    except (zipfile.BadZipFile, OSError):
        pass
    if not result["name"]:
        result["name"] = result["mod_id"]
    return result
