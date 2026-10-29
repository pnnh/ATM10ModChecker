"""解析本地整合包元数据（CurseForge manifest / 启动器实例文件 / modlist.html）。

三种文件的可用信息不同：
* ``manifest.json``（CurseForge 整合包）——只有 projectID + fileID，没有文件名；
* ``minecraftinstance.json``（CurseForge 客户端）——有安装时使用的 fileName；
* ``modlist.html``（部分整合包随包分发）——正文形如 ``名称 (文件名.jar)``，最理想。
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

_METADATA_FILES = ("manifest.json", "minecraftinstance.json", "modlist.html",
                   "mmc-pack.json", "instance.cfg")

_PACK_VERSION_RE = re.compile(
    r"(?:ServerFiles|All[\s_-]*the[\s_-]*Mods[\s_-]*10|ATM10|ATM-10)[\s_-]*v?(\d+(?:\.\d+){1,2})",
    re.IGNORECASE,
)
_ANCHOR_RE = re.compile(r"<a\s+href=\"([^\"]+)\"[^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_JAR_IN_PARENS_RE = re.compile(r"\(([^()]+\.jar(?:\.disabled)?)\)\s*$", re.IGNORECASE)


@dataclass
class LocalMetadata:
    """本机上能找到的整合包信息（可能来自多个文件）。"""

    source: str = ""
    path: Path | None = None
    pack_name: str = ""
    pack_version: str = ""
    mc_version: str = ""
    loader: str = ""
    loader_version: str = ""
    project_files: dict[int, int] = field(default_factory=dict)  # projectID -> fileID
    filenames: dict[str, str] = field(default_factory=dict)      # 文件名 -> 显示名
    warnings: list[str] = field(default_factory=list)

    def merge(self, other: "LocalMetadata") -> None:
        for attr in ("source", "pack_name", "pack_version", "mc_version", "loader",
                     "loader_version"):
            if not getattr(self, attr) and getattr(other, attr):
                setattr(self, attr, getattr(other, attr))
        if self.path is None and other.path is not None:
            self.path = other.path
        self.project_files.update(other.project_files)
        self.filenames.update(other.filenames)
        self.warnings.extend(w for w in other.warnings if w not in self.warnings)

    @property
    def has_info(self) -> bool:
        return bool(self.pack_version or self.project_files or self.filenames)


def split_loader(loader_id: str) -> tuple[str, str]:
    """``neoforge-21.1.259`` -> ``("neoforge", "21.1.259")``。"""
    text = (loader_id or "").strip()
    if not text:
        return "", ""
    match = re.match(r"^([a-zA-Z]+)[-_](.+)$", text)
    if match:
        return match.group(1).lower(), match.group(2)
    return text.lower(), ""


def guess_pack_version(*texts: str) -> str:
    """从目录名 / 文件名里猜整合包版本，例如 ``ServerFiles-8.0`` -> ``8.0``。"""
    for text in texts:
        if not text:
            continue
        match = _PACK_VERSION_RE.search(text)
        if match:
            return match.group(1)
    return ""


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    except (OSError, ValueError):
        return None


def parse_curse_manifest(path: Path) -> LocalMetadata:
    data = _read_json(path)
    meta = LocalMetadata(source="manifest.json", path=path)
    if not isinstance(data, dict):
        meta.warnings.append(f"无法解析 {path}")
        return meta
    meta.pack_name = str(data.get("name") or "")
    meta.pack_version = str(data.get("version") or "")
    minecraft = data.get("minecraft") if isinstance(data.get("minecraft"), dict) else {}
    meta.mc_version = str(minecraft.get("version") or "")
    loaders = minecraft.get("modLoaders") or []
    if isinstance(loaders, list) and loaders:
        first = loaders[0] if isinstance(loaders[0], dict) else {}
        meta.loader, meta.loader_version = split_loader(str(first.get("id") or ""))
    for entry in data.get("files") or []:
        if not isinstance(entry, dict):
            continue
        try:
            meta.project_files[int(entry["projectID"])] = int(entry["fileID"])
        except (KeyError, TypeError, ValueError):
            continue
    return meta


def parse_minecraftinstance(path: Path) -> LocalMetadata:
    data = _read_json(path)
    meta = LocalMetadata(source="minecraftinstance.json", path=path)
    if not isinstance(data, dict):
        meta.warnings.append(f"无法解析 {path}")
        return meta
    pack = data.get("installedModpack") if isinstance(data.get("installedModpack"), dict) else {}
    meta.pack_name = str(pack.get("name") or "")
    meta.pack_version = str(pack.get("version") or "")
    meta.mc_version = str(data.get("gameVersion") or "")
    meta.loader, meta.loader_version = split_loader(str(data.get("baseModLoader", {}).get("name")
                                                       if isinstance(data.get("baseModLoader"), dict)
                                                       else ""))
    for entry in data.get("installedMods") or []:
        if not isinstance(entry, dict):
            continue
        filename = str(entry.get("fileName") or "")
        if not filename:
            continue
        try:
            meta.project_files[int(entry["projectID"])] = int(entry["fileID"])
        except (KeyError, TypeError, ValueError):
            pass
        meta.filenames[filename] = str(entry.get("name") or "")
    return meta


def parse_modlist_html(path: Path) -> LocalMetadata:
    meta = LocalMetadata(source="modlist.html", path=path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return meta
    for href, body in _ANCHOR_RE.findall(text):
        label = html.unescape(re.sub(r"<[^>]+>", "", body)).strip()
        match = _JAR_IN_PARENS_RE.search(label)
        if not match:
            continue
        filename = match.group(1).strip()
        name = label[: match.start()].strip()
        meta.filenames[filename] = name
        project = re.search(r"/projects/(\d+)", href)
        file_id = re.search(r"/files/(\d+)", href)
        if project and file_id:
            meta.project_files[int(project.group(1))] = int(file_id.group(1))
    return meta


def _scan_dirs(roots: list[Path]) -> list[Path]:
    """在给定目录及其父目录里查找元数据文件。"""
    seen: list[Path] = []
    for root in roots:
        for candidate in (root, root.parent):
            if candidate and candidate not in seen and candidate.is_dir():
                seen.append(candidate)
    return seen


def find_local_metadata(*roots: Path) -> LocalMetadata:
    """按优先级合并本机可用的整合包元数据。"""
    meta = LocalMetadata()
    found: list[LocalMetadata] = []
    for directory in _scan_dirs([r for r in roots if r]):
        for name in _METADATA_FILES:
            path = directory / name
            if not path.is_file():
                continue
            # 目录里的 manifest.json 才当作整合包清单，避免误读模组自带的 json
            if name == "manifest.json":
                candidate = parse_curse_manifest(path)
                if not candidate.project_files and not candidate.pack_version:
                    continue
            elif name == "minecraftinstance.json":
                candidate = parse_minecraftinstance(path)
                if not candidate.project_files and not candidate.pack_version:
                    continue
            elif name == "modlist.html":
                candidate = parse_modlist_html(path)
                if not candidate.filenames:
                    continue
            else:
                continue
            found.append(candidate)
    for candidate in found:
        meta.merge(candidate)
    return meta


def read_manifest_from_zip(path: Path) -> dict | None:
    """从本地整合包 zip 里读取 manifest.json（无需解压）。"""
    import zipfile

    try:
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if name.lower() in ("manifest.json",) or name.lower().endswith("/manifest.json"):
                    return json.loads(zf.read(name).decode("utf-8-sig", errors="replace"))
    except (OSError, ValueError, zipfile.BadZipFile):
        return None
    return None


def find_pack_zip(*roots: Path) -> Path | None:
    """在安装目录及其父目录里找用户下载的整合包 zip（可选，能省去远程读取）。"""
    patterns = ("*All*the*Mods*10*.zip", "*ATM10*.zip", "*ServerFiles*.zip")
    for root in _scan_dirs([r for r in roots if r]):
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for pattern in patterns:
            for path in entries:
                if path.is_file() and path.match(pattern):
                    return path
    return None
