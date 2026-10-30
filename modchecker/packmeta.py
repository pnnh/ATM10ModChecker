"""解析本地整合包元数据（CurseForge manifest / 启动器实例文件 / modlist.html）。

三种文件的可用信息不同：
* ``manifest.json``（CurseForge 整合包）——至少含 projectID + fileID；
  少数第三方分发版本还会附上 ``fileName`` 与 ``hashes``，可直接离线比对；
* ``minecraftinstance.json``（CurseForge 客户端）——有安装时使用的 fileName；
* ``modlist.html``（部分整合包随包分发）——正文形如 ``名称 (文件名.jar)``，最理想。

用户指定的整合包原包（zip / 解压目录）统一由 :func:`load_pack_reference` 读取。
"""

from __future__ import annotations

import html
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from modchecker.i18n import t

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
    project_names: dict[int, str] = field(default_factory=dict)  # projectID -> 文件名
    filenames: dict[str, str] = field(default_factory=dict)      # 文件名 -> 显示名
    sha1s: set[str] = field(default_factory=set)                 # 清单内文件的 sha1
    warnings: list[str] = field(default_factory=list)

    def merge(self, other: "LocalMetadata") -> None:
        for attr in ("source", "pack_name", "pack_version", "mc_version", "loader",
                     "loader_version"):
            if not getattr(self, attr) and getattr(other, attr):
                setattr(self, attr, getattr(other, attr))
        if self.path is None and other.path is not None:
            self.path = other.path
        self.project_files.update(other.project_files)
        self.project_names.update(other.project_names)
        for name, label in other.filenames.items():
            if label or name not in self.filenames:
                self.filenames[name] = label
        self.sha1s.update(other.sha1s)
        self.warnings.extend(w for w in other.warnings if w not in self.warnings)

    @property
    def has_info(self) -> bool:
        return bool(self.pack_version or self.project_files or self.filenames or self.sha1s)


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


def manifest_metadata(data, source: str, path: Path | None = None) -> LocalMetadata:
    """把 CurseForge ``manifest.json`` 的内容转成 :class:`LocalMetadata`。

    部分整合包（例如经第三方启动器分发的 ATM10）会在 ``files`` 里额外带上
    ``fileName`` 与 ``hashes``，这时不需要任何网络请求就能得到完整清单；
    只有 ``projectID/fileID`` 时才需要再走 CurseForge 解析文件名。
    """
    meta = LocalMetadata(source=source, path=path)
    if not isinstance(data, dict):
        meta.warnings.append(t("packmeta.unparsable", path=path or source))
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
            project_id = int(entry["projectID"])
            file_id = int(entry["fileID"])
        except (KeyError, TypeError, ValueError):
            continue
        meta.project_files[project_id] = file_id
        filename = str(entry.get("fileName") or "").strip()
        if not filename:
            continue
        meta.project_names[project_id] = filename
        meta.filenames[filename] = ""
        hashes = entry.get("hashes")
        if isinstance(hashes, dict):
            sha1 = str(hashes.get("sha1") or "").strip().lower()
            if sha1:
                meta.sha1s.add(sha1)
    return meta


def parse_curse_manifest(path: Path) -> LocalMetadata:
    return manifest_metadata(_read_json(path), "manifest.json", path)


def parse_minecraftinstance(path: Path) -> LocalMetadata:
    data = _read_json(path)
    meta = LocalMetadata(source="minecraftinstance.json", path=path)
    if not isinstance(data, dict):
        meta.warnings.append(t("packmeta.unparsable", path=path))
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
    try:
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if name.lower() in ("manifest.json",) or name.lower().endswith("/manifest.json"):
                    return json.loads(zf.read(name).decode("utf-8-sig", errors="replace"))
    except (OSError, ValueError, zipfile.BadZipFile):
        return None
    return None


def parse_manifest_from_zip(path: Path) -> LocalMetadata:
    source = t("packmeta.zip_source", name=path.name)
    data = read_manifest_from_zip(path)
    if data is None:
        return LocalMetadata(source=source, path=path,
                             warnings=[t("packmeta.zip_no_manifest", path=path)])
    return manifest_metadata(data, source, path)


def _manifest_candidates(directory: Path) -> list[Path]:
    """目录本身或下一层子目录里的 manifest.json（解压时常会多套一层文件夹）。"""
    candidates = [directory / "manifest.json"]
    try:
        children = [child for child in directory.iterdir() if child.is_dir()]
    except OSError:
        children = []
    candidates.extend(child / "manifest.json" for child in children)
    return [path for path in candidates if path.is_file()]


def load_pack_reference(selected: Path | str) -> LocalMetadata:
    """读取用户指定的整合包原包：zip 文件、解压目录，或单独的 manifest.json。

    用户显式指定比自动探测更可靠：父目录里的同名 zip 未必就是当前实例的来源。
    """
    path = Path(selected).expanduser()
    if path.is_file():
        if path.name.lower() == "manifest.json":
            return parse_curse_manifest(path)
        if zipfile.is_zipfile(path):
            return parse_manifest_from_zip(path)
        return LocalMetadata(path=path,
                             warnings=[t("packmeta.not_zip_or_manifest", path=path)])
    if not path.is_dir():
        return LocalMetadata(path=path, warnings=[t("packmeta.path_missing", path=path)])

    for manifest in _manifest_candidates(path):
        meta = parse_curse_manifest(manifest)
        if meta.project_files or meta.filenames:
            meta.source = t("packmeta.extracted_dir", name=path.name)
            return meta

    # 没有 manifest.json 时，解压目录里的 mods/*.jar 本身就是最精确的官方文件列表
    mods_dirs = [path] if path.name.lower() == "mods" else []
    mods_dirs.extend([path / "mods", path / "overrides" / "mods"])
    jars: list[str] = []
    for mods_dir in mods_dirs:
        if mods_dir.is_dir():
            jars.extend(item.name for item in sorted(mods_dir.glob("*.jar")) if item.is_file())
    if jars:
        source = (t("packmeta.mods_dir", name=path.name) if path.name.lower() == "mods"
                  else t("packmeta.extracted_mods", name=path.name))
        return LocalMetadata(
            source=source, path=path,
            filenames={name: "" for name in jars},
            pack_version=guess_pack_version(path.name, path.parent.name),
        )

    modlist = path / "modlist.html"
    if modlist.is_file():
        meta = parse_modlist_html(modlist)
        if meta.filenames:
            meta.source = t("packmeta.extracted_mods", name=f"{path.name}/modlist.html")
            return meta

    return LocalMetadata(path=path, warnings=[t("packmeta.no_manifest", path=path)])


def find_pack_zip(*roots: Path) -> Path | None:
    """在安装目录及其父目录里找疑似整合包 zip。

    只按文件名猜测，可能命中同名但版本不同的归档，因此仅用于给用户提示，
    不应作为归属判断的依据（以用户显式指定的原包为准）。
    """
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
