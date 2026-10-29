"""官方模组清单：判断某个 jar 是“整合包自带”还是“手动添加”。

清单来源（按优先级）：
1. 本机的 ``modlist.html`` / ``minecraftinstance.json``（直接含文件名，零额外请求）；
2. 本机的 ``manifest.json`` 或用户指定的整合包 zip；
3. 远程读取官方整合包 zip 里的 ``manifest.json``（HTTP Range，几百 KB）。

``manifest.json`` 只有 projectID/fileID，需要再通过 CurseForge 解析出文件名，
这一步有缓存，同一个整合包版本只需做一次。
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from modchecker.cache import CacheStore
from modchecker.models import JarEntry, OfficialIndex, Origin
from modchecker.packmeta import LocalMetadata
from modchecker.providers.atm10 import Atm10Provider
from modchecker.providers.curseforge import CurseForgeProvider

Logger = Callable[[str], None]
ProgressFn = Callable[[int, int], None]


@dataclass
class IndexOutcome:
    index: OfficialIndex | None = None
    warnings: list[str] = field(default_factory=list)


def _cache_key(version: str) -> str:
    return f"atm10|{version}"


def _load_cached(cache: CacheStore, version: str) -> OfficialIndex | None:
    raw = cache.official_index.get(_cache_key(version))
    if not isinstance(raw, dict):
        return None
    index = OfficialIndex(
        pack_version=raw.get("pack_version", ""),
        mc_version=raw.get("mc_version", ""),
        loader=raw.get("loader", ""),
        source=raw.get("source", ""),
        filenames=set(raw.get("filenames") or []),
        sha1s=set(raw.get("sha1s") or []),
        project_files=dict(raw.get("project_files") or {}),
        declared=int(raw.get("declared") or 0),
        resolved=int(raw.get("resolved") or 0),
        complete=bool(raw.get("complete", True)),
    )
    return index if index.usable else None


def _store(cache: CacheStore, index: OfficialIndex, *extra_versions: str) -> None:
    payload = {
        "pack_version": index.pack_version,
        "mc_version": index.mc_version,
        "loader": index.loader,
        "source": index.source,
        "filenames": sorted(index.filenames),
        "sha1s": sorted(index.sha1s),
        "project_files": index.project_files,
        "declared": index.declared,
        "resolved": index.resolved,
        "complete": index.complete,
    }
    keys = {_cache_key(index.pack_version)}
    keys.update(_cache_key(v) for v in extra_versions if v)
    for key in keys:
        cache.official_index.set(key, payload)


def build_official_index(
    *,
    local_meta: LocalMetadata,
    atm: Atm10Provider,
    cf: CurseForgeProvider,
    cache: CacheStore,
    pack_version_hint: str = "",
    local_zip: Path | None = None,
    use_curseforge: bool = True,
    concurrency: int = 6,
    cancel: threading.Event | None = None,
    log: Logger | None = None,
    progress: ProgressFn | None = None,
) -> IndexOutcome:
    log = log or (lambda _msg: None)
    outcome = IndexOutcome()

    project_files: dict[int, int] = dict(local_meta.project_files)
    filenames: set[str] = {name.lower() for name in local_meta.filenames}
    display_names: dict[int, str] = {}
    source_parts: list[str] = []
    declared = len(project_files)
    pack_version = pack_version_hint or local_meta.pack_version
    mc_version = local_meta.mc_version
    loader = local_meta.loader

    # 1) 已有完整清单（含文件名）时无需联网
    if filenames and not project_files:
        index = OfficialIndex(
            pack_version=pack_version, mc_version=mc_version, loader=loader,
            source=local_meta.source or "本地元数据", filenames=filenames,
            declared=len(filenames), resolved=len(filenames),
        )
        log(f"使用本地整合包清单：{len(filenames)} 个模组（{local_meta.source}）")
        return IndexOutcome(index=index)

    if pack_version:
        cached = _load_cached(cache, pack_version)
        if cached is not None:
            log(f"复用已缓存的官方清单：ATM10 {cached.pack_version}（{len(cached.filenames)} 个模组）")
            return IndexOutcome(index=cached)

    # 2) 需要 manifest 才能补齐 projectID/fileID
    if not project_files and use_curseforge:
        release = atm.release_for_version(pack_version) if pack_version else None
        if release is None:
            release = atm.latest_release()
            if release and pack_version:
                outcome.warnings.append(
                    f"没有找到 ATM10 {pack_version} 的官方发行版，改用最新版 {release.version} 的清单。")
        manifest, manifest_source = atm.fetch_manifest(release, local_zip)
        if manifest:
            source_parts.append(manifest_source)
            mc_version = mc_version or str((manifest.get("minecraft") or {}).get("version") or "")
            manifest_version = str(manifest.get("version") or "")
            if manifest_version:
                # 归档失效时会退而使用其他版本，这里以“实际读到的清单版本”为准
                if pack_version and manifest_version != pack_version:
                    outcome.warnings.append(
                        f"ATM10 {pack_version} 的官方归档不可用，已改用 {manifest_version} 的清单，"
                        f"个别模组可能被误判为“手动添加”。")
                pack_version = manifest_version
            for entry in manifest.get("files") or []:
                if not isinstance(entry, dict):
                    continue
                try:
                    project_files[int(entry["projectID"])] = int(entry["fileID"])
                except (KeyError, TypeError, ValueError):
                    continue
            declared = max(declared, len(project_files))
            log(f"官方清单来源：{manifest_source}，共 {len(project_files)} 个模组")
        else:
            outcome.warnings.append("无法获取官方 manifest.json，无法判断模组归属。")

    # 3) 通过 CurseForge 把 projectID/fileID 解析成文件名
    if project_files and use_curseforge:
        total = len(project_files)
        done = 0

        def resolve(item: tuple[int, int]) -> tuple[int, dict | None]:
            pid, fid = item
            if cancel is not None and cancel.is_set():
                return pid, None
            return pid, cf.file(pid, fid)

        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            for pid, file in pool.map(resolve, list(project_files.items())):
                done += 1
                if file:
                    name = str(file.get("fileName") or "")
                    if name:
                        filenames.add(name.lower())
                        display_names[pid] = name
                if progress is not None:
                    progress(done, total)
                if cancel is not None and cancel.is_set():
                    break
        if progress is not None:
            progress(total, total)

    if not filenames and not project_files:
        return outcome

    index = OfficialIndex(
        pack_version=pack_version,
        mc_version=mc_version,
        loader=loader,
        source=" + ".join(p for p in source_parts if p) or local_meta.source or "本地元数据",
        filenames=filenames,
        sha1s=set(),
        project_files={str(pid): display_names.get(pid, "") for pid in project_files},
        declared=declared,
        resolved=len(filenames),
        complete=declared == 0 or len(filenames) >= declared * 0.95,
    )
    if not index.complete:
        outcome.warnings.append(
            f"官方清单只解析出 {len(filenames)}/{declared} 个文件名，分类结果可能不完整。")
    if pack_version:
        _store(cache, index, pack_version_hint)
    outcome.index = index
    return outcome


def classify(jar: JarEntry, index: OfficialIndex | None, cf_project_id: str = ""
             ) -> tuple[Origin, str]:
    """返回 ``(归属, 依据说明)``。"""
    if index is None or not index.usable:
        return Origin.UNKNOWN, ""
    name = jar.filename.lower()
    if name in index.filenames:
        return Origin.PACK, "文件名在官方清单中"
    if jar.sha1 and jar.sha1 in index.sha1s:
        return Origin.PACK, "文件哈希在官方清单中"
    if cf_project_id and str(cf_project_id) in index.project_files:
        return Origin.PACK, "项目 ID 在官方清单中"
    if index.filenames:
        return Origin.MANUAL, "官方清单中不存在"
    return Origin.UNKNOWN, ""
