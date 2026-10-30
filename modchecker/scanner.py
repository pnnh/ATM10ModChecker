"""安装目录探测与 mods 扫描。"""

from __future__ import annotations

import hashlib
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from modchecker import packmeta
from modchecker.i18n import t
from modchecker.jarinfo import read_jar_metadata
from modchecker.models import InstallInfo, InstallKind, JarEntry

ProgressFn = Callable[[int, int], None]

_LIB_NEOFORGE_RE = re.compile(r"^neoforge-(\d+\.\d+\.\d+)", re.IGNORECASE)
_INSTALLER_RE = re.compile(r"^neoforge-(\d+\.\d+\.\d+)-installer\.jar$", re.IGNORECASE)


class ScanError(Exception):
    """无法确定安装目录结构。"""


def _jar_files(directory: Path, include_disabled: bool, recursive: bool = False) -> list[Path]:
    if not directory.is_dir():
        return []
    items: Iterable[Path]
    if recursive:
        items = directory.rglob("*.jar")
    else:
        items = directory.glob("*.jar")
    result = [p for p in items if p.is_file()]
    if include_disabled:
        pattern = "*.jar.disabled"
        extra = directory.rglob(pattern) if recursive else directory.glob(pattern)
        result.extend(p for p in extra if p.is_file())
    return result


def _mods_candidates(root: Path) -> list[Path]:
    """常见启动器布局：ServerFiles、.minecraft、Prism/minecraft、直接选中 mods 目录。"""
    candidates: list[Path] = []
    if root.name.lower() == "mods" and root.is_dir():
        candidates.append(root)
    for relative in ("mods", ".minecraft/mods", "minecraft/mods", ".minecraft"):
        path = root / relative
        if path.is_dir():
            candidates.append(path if path.name.lower() == "mods" else path / "mods")
    # 兜底：向下找一层包含 jar 的 mods 目录
    if not any(p.is_dir() for p in candidates):
        for child in root.iterdir() if root.is_dir() else []:
            if child.is_dir():
                nested = child / "mods"
                if nested.is_dir():
                    candidates.append(nested)
                nested_mc = child / ".minecraft" / "mods"
                if nested_mc.is_dir():
                    candidates.append(nested_mc)
    unique: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved.is_dir() and resolved not in unique:
            unique.append(resolved)
    return unique


def _detect_kind(game_dir: Path, root: Path) -> InstallKind:
    server_markers = ("server.properties", "eula.txt", "bukkit.yml", "run.sh", "startserver.bat")
    client_markers = ("options.txt", "saves", "screenshots", "resourcepacks", "shaderpacks")
    if any((game_dir / m).exists() for m in server_markers):
        return InstallKind.SERVER
    if any((game_dir / m).exists() for m in client_markers):
        return InstallKind.CLIENT
    lowered = f"{game_dir.name} {root.name}".lower()
    if "server" in lowered:
        return InstallKind.SERVER
    if ".minecraft" in str(game_dir).lower() or "client" in lowered:
        return InstallKind.CLIENT
    return InstallKind.UNKNOWN


def neoforge_to_mc(loader_version: str) -> str:
    """``21.1.247`` -> ``1.21.1``；``21.0.16`` -> ``1.21``。"""
    match = re.match(r"^(\d+)\.(\d+)", loader_version or "")
    if not match:
        return ""
    major, minor = int(match.group(1)), int(match.group(2))
    return f"1.{major}.{minor}" if minor else f"1.{major}"


def _detect_loader_version(game_dir: Path, root: Path) -> str:
    libs = game_dir / "libraries" / "net" / "neoforged" / "neoforge"
    if libs.is_dir():
        versions = sorted((p.name for p in libs.iterdir() if p.is_dir()), reverse=True)
        for name in versions:
            if re.match(r"^\d+\.\d+\.\d+", name):
                return name
    for directory in (game_dir, root):
        if not directory.is_dir():
            continue
        for item in directory.glob("neoforge-*-installer.jar"):
            match = _INSTALLER_RE.match(item.name)
            if match:
                return match.group(1)
    return ""


def _detect_mc_version(game_dir: Path, loader_version: str) -> str:
    versions_dir = game_dir / "versions"
    if versions_dir.is_dir():
        names = [p.name for p in versions_dir.iterdir() if p.is_dir()]
        named = [n for n in names if re.match(r"^1\.\d+(\.\d+)?$", n)]
        if named:
            return sorted(named, key=lambda s: [int(x) for x in s.split(".")], reverse=True)[0]
    return neoforge_to_mc(loader_version)


def detect_install(selected: Path) -> InstallInfo:
    """根据用户选择的目录推断游戏根目录、mods 目录与版本信息。"""
    root = selected.expanduser().resolve()
    if not root.is_dir():
        raise ScanError(t("scan.dir_missing", path=root))

    candidates = _mods_candidates(root)
    if not candidates:
        raise ScanError(t("scan.mods_missing"))

    # 选择 jar 最多的候选目录
    mods_dir = max(candidates, key=lambda p: len(_jar_files(p, include_disabled=True)))
    game_dir = mods_dir.parent

    local = packmeta.find_local_metadata(game_dir, root, game_dir.parent)
    loader_version = local.loader_version or _detect_loader_version(game_dir, root)
    mc_version = local.mc_version or _detect_mc_version(game_dir, loader_version)
    loader = local.loader or ("neoforge" if loader_version else "")
    pack_version = local.pack_version or packmeta.guess_pack_version(
        game_dir.name, game_dir.parent.name, root.name)

    info = InstallInfo(
        root=root,
        game_dir=game_dir,
        mods_dir=mods_dir,
        kind=_detect_kind(game_dir, root),
        mc_version=mc_version,
        loader=loader,
        loader_version=loader_version,
        pack_name=local.pack_name,
        pack_version=pack_version,
        metadata_path=str(local.path) if local.path else "",
        jar_total=len(_jar_files(mods_dir, include_disabled=True)),
    )
    return info


# --------------------------------------------------------------------------- 扫描 jar


def hash_file(path: Path) -> str:
    digest = hashlib.sha1()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def scan_jars(
    mods_dir: Path,
    include_disabled: bool = False,
    workers: int = 8,
    sha1_cache: dict[str, str] | None = None,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> list[JarEntry]:
    """枚举并（按需）指纹化 mods 目录下的 jar。sha1 结果按 路径+mtime+size 缓存。"""
    paths = sorted(_jar_files(mods_dir, include_disabled), key=lambda p: p.name.lower())
    total = len(paths)
    cache = sha1_cache if sha1_cache is not None else {}
    entries: list[JarEntry] = []
    done = 0
    lock = threading.Lock()

    def work(path: Path) -> JarEntry:
        stat = path.stat()
        disabled = path.name.lower().endswith(".disabled")
        key = f"{path}|{int(stat.st_mtime)}|{stat.st_size}"
        sha1 = cache.get(key, "")
        if not sha1:
            sha1 = hash_file(path)
        meta = read_jar_metadata(path)
        return JarEntry(
            path=path,
            filename=path.name,
            disabled=disabled,
            size=stat.st_size,
            mtime=stat.st_mtime,
            sha1=sha1,
            mod_id=meta["mod_id"],
            display_name=meta["name"],
            jar_version=meta["version"],
        )

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for entry in pool.map(work, paths):
            if cancel is not None and cancel.is_set():
                break
            entries.append(entry)
            with lock:
                done += 1
                current = done
            if progress is not None:
                progress(current, total)
            cache[f"{entry.path}|{int(entry.mtime)}|{entry.size}"] = entry.sha1
    return entries
