"""检测流程编排：扫描 -> 识别 -> 查新 -> 归类。

所有网络访问都在这里串起来，UI 只关心回调与最终报告。
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from modchecker import packmeta, scanner, versioning
from modchecker.appconfig import DEFAULT_GAME_VERSION, DEFAULT_LOADER, cache_dir
from modchecker.cache import CacheStore
from modchecker.models import (InstallInfo, JarEntry, ModResult, OfficialIndex, Origin,
                               PackStatus, Report, Source, UpdateState)
from modchecker.net import Cancelled, HttpClient
from modchecker.official import build_official_index, classify
from modchecker.providers.atm10 import Atm10Provider
from modchecker.providers.curseforge import CurseForgeProvider
from modchecker.providers.modrinth import ModrinthProvider

ProgressCb = Callable[[str, int], None]          # (阶段描述, 百分比)
StageCb = Callable[[str, int, int], None]        # (阶段描述, 已完成, 总数)
LogCb = Callable[[str], None]


@dataclass
class CheckOptions:
    game_version: str = ""
    loader: str = ""
    include_disabled: bool = False
    use_modrinth: bool = True
    use_curseforge: bool = True
    cf_api_key: str = ""
    concurrency: int = 6
    verify_official: bool = True
    pack_zip: Path | None = None


@dataclass
class _Identity:
    """一个 jar 的识别结果。"""

    source: Source = Source.NONE
    project_id: str = ""
    project_title: str = ""
    project_url: str = ""
    installed_version: str = ""
    installed_date: datetime | None = None
    confidence: str = ""
    cf_mod: dict | None = None
    mr_version: dict | None = None


def _empty_identity() -> _Identity:
    return _Identity()


class _Progress:
    """把多阶段进度折算成整体百分比。"""

    def __init__(self, callback: ProgressCb | None, stage_callback: StageCb | None,
                 cancel: threading.Event) -> None:
        self._cb = callback
        self._stage_cb = stage_callback
        self.cancel = cancel
        self._plan: list[tuple[str, float]] = []
        self._index = 0
        self._offset = 0.0
        self._weight = 100.0

    def plan(self, stages: list[tuple[str, float]]) -> None:
        self._plan = stages
        total = sum(w for _, w in self._plan) or 1.0
        self._plan = [(name, w / total * 100.0) for name, w in self._plan]

    def enter(self, index: int) -> None:
        if not self._plan:
            return
        self._index = min(index, len(self._plan) - 1)
        self._offset = sum(w for _, w in self._plan[: self._index])
        self._weight = self._plan[self._index][1]
        self.emit(0, 0)

    @property
    def label(self) -> str:
        return self._plan[self._index][0] if self._plan else ""

    def emit(self, done: int, total: int, label: str = "") -> None:
        fraction = (done / total) if total else 1.0
        percent = int(max(0.0, min(99.0, self._offset + self._weight * fraction)))
        text = label or self.label
        if self._cb:
            self._cb(text, percent)
        if self._stage_cb:
            self._stage_cb(text, done, total)

    def check_cancel(self) -> None:
        if self.cancel.is_set():
            raise Cancelled()


class Checker:
    def __init__(self, options: CheckOptions, log: LogCb | None = None,
                 progress: ProgressCb | None = None, stage: StageCb | None = None,
                 cancel: threading.Event | None = None) -> None:
        self.options = options
        self.log = log or (lambda _msg: None)
        self.cancel = cancel or threading.Event()
        self.progress = _Progress(progress, stage, self.cancel)
        self.http = HttpClient(rate_per_sec=8.0, cancel_event=self.cancel)
        self.cache = CacheStore(cache_dir())
        self.modrinth = ModrinthProvider(self.http, self.cache, self.log)
        self.curseforge = CurseForgeProvider(self.http, self.cache,
                                            api_key=options.cf_api_key, log=self.log)
        self.atm = Atm10Provider(self.http, self.curseforge, self.cache, self.log)

    # ------------------------------------------------------------------ 入口
    def run(self, directory: Path) -> Report:
        started = time.time()
        try:
            report = self._run(directory)
        finally:
            self.cache.flush()
        report.elapsed = time.time() - started
        return report

    # ------------------------------------------------------------------ 主流程
    def _run(self, directory: Path) -> Report:
        options = self.options
        self.progress.plan([
            ("扫描 mods 目录", 12),
            ("识别模组来源", 26),
            ("查询最新版本", 24),
            ("构建官方模组清单", 26),
            ("整理检测结果", 6),
        ])
        self.progress.enter(0)
        install = scanner.detect_install(directory)
        game_version = options.game_version or install.mc_version or DEFAULT_GAME_VERSION
        loader = (options.loader or install.loader or DEFAULT_LOADER).lower()
        self.log(f"安装目录：{install.mods_dir}")
        self.log(f"版本基准：Minecraft {game_version} / {loader}")

        sha1_cache = self._sha1_cache()
        jars = scanner.scan_jars(
            install.mods_dir,
            include_disabled=options.include_disabled,
            workers=max(4, options.concurrency + 2),
            sha1_cache=sha1_cache,
            progress=lambda done, total: self.progress.emit(done, total),
            cancel=self.cancel,
        )
        self.cache.sha1_index.set("paths", sha1_cache)
        if not jars:
            raise RuntimeError(f"mods 目录中没有找到 jar 文件：{install.mods_dir}")
        install.jar_total = len(jars)
        self.log(f"共发现 {len(jars)} 个 jar")

        # ---------------- 识别
        self.progress.enter(1)
        identities: dict[str, _Identity] = {}
        self._identify_modrinth(jars, game_version, loader, identities)
        self._identify_curseforge(jars, game_version, loader, identities)

        # ---------------- 查新
        self.progress.enter(2)
        modrinth_latest = self._modrinth_latest(jars, identities, game_version, loader)
        latest_by_identity = self._curseforge_latest(identities, game_version, loader)

        results: list[ModResult] = []
        for jar in jars:
            identity = identities.get(jar.sha1) if jar.sha1 else None
            result = self._build_result(jar, identity, modrinth_latest, latest_by_identity,
                                        game_version, loader)
            results.append(result)
        report = Report(install=install, mods=results)
        report.query_errors = sum(1 for r in results if r.state is UpdateState.ERROR)

        # ---------------- 整合包自身与官方清单
        self.progress.enter(3)
        report.pack = self._pack_status(install)
        index: OfficialIndex | None = None
        if options.verify_official:
            index, warnings = self._official_index(install)
            report.index = index
            report.warnings.extend(warnings)

        # ---------------- 归类
        self.progress.enter(4)
        for result in results:
            identity = identities.get(result.jar.sha1) if result.jar.sha1 else None
            cf_id = str((identity.cf_mod or {}).get("id") or "") if identity else ""
            origin, detail = classify(result.jar, index, cf_id)
            result.origin = origin
            result.origin_detail = detail
            if not detail:
                result.origin_detail = "未能获取官方清单" if index is None else "无法判断"

        if report.index and report.index.pack_version and install.pack_version:
            if report.index.pack_version != install.pack_version:
                report.warnings.append(
                    f"官方清单版本（{report.index.pack_version}）与本地整合包版本"
                    f"（{install.pack_version}）不一致，分类结果可能有偏差。")
        if any(m.jar.disabled for m in results):
            self.log("注意：包含被禁用的 jar（.jar.disabled）")

        results.sort(key=lambda r: (_STATE_ORDER.get(r.state, 9),
                                    _ORIGIN_ORDER.get(r.origin, 9),
                                    r.title.lower()))
        self.progress.emit(1, 1, "检测完成")
        return report

    # ------------------------------------------------------------------ 识别细节
    def _sha1_cache(self) -> dict[str, str]:
        raw = self.cache.sha1_index.get("paths") or {}
        return dict(raw) if isinstance(raw, dict) else {}

    def _identify_modrinth(self, jars: list[JarEntry], game_version: str, loader: str,
                           identities: dict[str, _Identity]) -> None:
        if not self.options.use_modrinth:
            return
        hashes = [jar.sha1 for jar in jars if jar.sha1]
        if not hashes:
            return
        versions = self.modrinth.identify(
            hashes, progress=lambda done, total: self.progress.emit(done, total))
        projects = self.modrinth.projects(
            list({v.get("project_id", "") for v in versions.values() if v.get("project_id")}))
        for sha1, version in versions.items():
            project = projects.get(version.get("project_id", ""), {})
            identities[sha1] = _Identity(
                source=Source.MODRINTH,
                project_id=str(version.get("project_id") or ""),
                project_title=str(project.get("title") or ""),
                project_url=f"https://modrinth.com/mod/{project.get('slug')}" if project.get("slug") else "",
                installed_version=str(version.get("version_number") or ""),
                installed_date=versioning.parse_iso(version.get("date_published")),
                confidence="文件哈希匹配",
                mr_version=version,
            )
        self.log(f"Modrinth 识别成功 {len(versions)}/{len(hashes)} 个")

    def _identify_curseforge(self, jars: list[JarEntry], game_version: str, loader: str,
                             identities: dict[str, _Identity]) -> None:
        if not self.options.use_curseforge:
            return
        pending = [jar for jar in jars if jar.sha1 and jar.sha1 not in identities]
        if not pending:
            return
        self.log(f"CurseForge 补全识别：{len(pending)} 个")
        total = len(pending)
        done = 0
        errors = 0

        def work(jar: JarEntry):
            try:
                mod, file, confidence = self.curseforge.resolve_jar(jar, game_version, loader)
                return jar, mod, file, confidence, None
            except Cancelled:
                raise
            except Exception as exc:  # 单个模组失败不影响整体
                return jar, {}, None, "", exc

        with ThreadPoolExecutor(max_workers=max(1, self.options.concurrency)) as pool:
            for jar, mod, file, confidence, error in pool.map(work, pending):
                done += 1
                self.progress.emit(done, total)
                if error is not None:
                    errors += 1
                    continue
                if not mod:
                    continue
                installed_version = ""
                installed_date = None
                if file:
                    installed_version = str(file.get("displayName") or file.get("fileName") or "")
                    installed_date = versioning.parse_iso(file.get("fileDate"))
                if not installed_version:
                    installed_version = jar.jar_version
                identities[jar.sha1] = _Identity(
                    source=Source.CURSEFORGE,
                    project_id=str(mod.get("id") or ""),
                    project_title=str(mod.get("name") or ""),
                    project_url=str(mod.get("links", {}).get("websiteUrl") or
                                     f"https://www.curseforge.com/minecraft/mc-mods/{mod.get('slug')}"),
                    installed_version=installed_version,
                    installed_date=installed_date,
                    confidence=confidence,
                    cf_mod=mod,
                )
        if errors:
            self.log(f"CurseForge 查询失败 {errors} 个（已跳过）")
        self.log(f"CurseForge 识别成功 {sum(1 for i in identities.values() if i.source is Source.CURSEFORGE)} 个")

    # ------------------------------------------------------------------ 最新版本
    def _modrinth_latest(self, jars: list[JarEntry], identities: dict[str, _Identity],
                         game_version: str, loader: str) -> dict[str, dict]:
        if not self.options.use_modrinth:
            return {}
        hashes = [jar.sha1 for jar in jars
                  if jar.sha1 and identities.get(jar.sha1, _empty_identity()).source is Source.MODRINTH]
        if not hashes:
            return {}
        return self.modrinth.latest(
            hashes, game_version, loader,
            progress=lambda done, total: self.progress.emit(done, total))

    def _curseforge_latest(self, identities: dict[str, _Identity], game_version: str,
                           loader: str) -> dict[str, dict]:
        """project_id -> 最新 CF 文件。"""
        if not self.options.use_curseforge:
            return {}
        targets = {ident.project_id: ident for ident in identities.values()
                   if ident.source is Source.CURSEFORGE and ident.project_id}
        if not targets:
            return {}
        result: dict[str, dict] = {}
        total = len(targets)
        done = 0

        def work(item: tuple[str, _Identity]):
            project_id = item[0]
            try:
                return project_id, self.curseforge.latest_file(project_id, game_version, loader)
            except Cancelled:
                raise
            except Exception:
                return project_id, None

        with ThreadPoolExecutor(max_workers=max(1, self.options.concurrency)) as pool:
            for project_id, file in pool.map(work, list(targets.items())):
                done += 1
                self.progress.emit(done, total)
                if file:
                    result[project_id] = file
        return result

    # ------------------------------------------------------------------ 结果装配
    def _build_result(self, jar: JarEntry, identity: _Identity | None,
                      modrinth_latest: dict[str, dict], cf_latest: dict[str, dict],
                      game_version: str, loader: str) -> ModResult:
        result = ModResult(jar=jar)
        if identity is None or identity.source is Source.NONE:
            result.state = UpdateState.UNKNOWN
            result.installed_version = jar.jar_version
            result.note = "Modrinth / CurseForge 均未找到匹配的项目"
            return result

        result.source = identity.source
        result.project_id = identity.project_id
        result.project_title = identity.project_title
        result.project_url = identity.project_url
        result.installed_version = identity.installed_version or jar.jar_version
        result.installed_date = identity.installed_date

        if identity.source is Source.MODRINTH:
            latest = modrinth_latest.get(jar.sha1, {})
            if latest:
                result.latest_version = str(latest.get("version_number") or "")
                result.latest_date = versioning.parse_iso(latest.get("date_published"))
                newer = versioning.decide(result.installed_version, result.latest_version,
                                          result.installed_date, result.latest_date,
                                          game_version, loader)
                result.state = UpdateState.OUTDATED if newer else UpdateState.CURRENT
            else:
                result.state = UpdateState.UNKNOWN
                result.note = f"没有适用于 {game_version} / {loader} 的 Modrinth 版本"
            return result

        # CurseForge
        latest = cf_latest.get(identity.project_id or "", {})
        if latest:
            result.latest_version = str(latest.get("displayName") or latest.get("fileName") or "")
            result.latest_date = versioning.parse_iso(latest.get("fileDate"))
            result.latest_filename = str(latest.get("fileName") or "")
            same_file = (result.latest_filename.lower() == jar.filename.lower())
            newer = None if same_file else versioning.decide(
                result.installed_version, result.latest_version,
                result.installed_date, result.latest_date, game_version, loader)
            if newer is None:
                # 已装的正是最新文件 / 无法比较时，不报“可更新”
                result.state = UpdateState.CURRENT if same_file else UpdateState.UNKNOWN
            else:
                result.state = UpdateState.OUTDATED if newer else UpdateState.CURRENT
            if identity.confidence == "项目名匹配" and result.state is UpdateState.OUTDATED:
                result.note = "按项目名关联，建议人工确认"
        else:
            result.state = UpdateState.UNKNOWN
            result.note = f"没有适用于 {game_version} / {loader} 的 CurseForge 文件"
        return result

    # ------------------------------------------------------------------ 整包 & 清单
    def _pack_status(self, install: InstallInfo) -> PackStatus:
        status = PackStatus(installed_version=install.pack_version)
        releases = self.atm.releases()
        status.release_count = len(releases)
        if not releases:
            status.message = "无法获取 ATM10 发行版列表"
            return status
        status.latest = releases[0]
        if install.pack_version:
            status.update_available = versioning.compare(
                status.latest.version, install.pack_version) > 0
            if status.update_available:
                status.message = (f"整合包有更新：{install.pack_version} → "
                                  f"{status.latest.version}（{status.latest.uploaded_at[:10]}）")
            elif versioning.compare(status.latest.version, install.pack_version) == 0:
                status.message = f"整合包已是最新版本 {status.latest.version}"
            else:
                status.message = (f"本地版本 {install.pack_version} 高于线上最新 "
                                  f"{status.latest.version}（可能是测试版）")
        else:
            status.message = f"未能识别整合包版本，线上最新为 {status.latest.version}"
        return status

    def _official_index(self, install: InstallInfo) -> tuple[OfficialIndex | None, list[str]]:
        warnings: list[str] = []
        pack_zip = self.options.pack_zip or packmeta.find_pack_zip(
            install.game_dir, install.root)
        if pack_zip:
            self.log(f"发现本地整合包归档：{pack_zip.name}（将直接读取其中的 manifest.json）")
        if not self.options.use_curseforge:
            # 没有 CurseForge 时只能依赖本地 modlist.html 之类的文件
            local_meta = packmeta.find_local_metadata(install.game_dir, install.root,
                                                      install.game_dir.parent)
            if not local_meta.filenames:
                warnings.append("未启用 CurseForge，且本机没有 modlist.html，无法判断模组归属。")
                return None, warnings
            return build_official_index(
                local_meta=local_meta, atm=self.atm, cf=self.curseforge, cache=self.cache,
                pack_version_hint=install.pack_version, local_zip=pack_zip,
                use_curseforge=False, concurrency=self.options.concurrency,
                cancel=self.cancel, log=self.log,
                progress=lambda done, total: self.progress.emit(done, total),
            ).index, warnings

        local_meta = packmeta.find_local_metadata(install.game_dir, install.root,
                                                  install.game_dir.parent)
        outcome = build_official_index(
            local_meta=local_meta, atm=self.atm, cf=self.curseforge, cache=self.cache,
            pack_version_hint=install.pack_version, local_zip=pack_zip,
            use_curseforge=True, concurrency=self.options.concurrency,
            cancel=self.cancel, log=self.log,
            progress=lambda done, total: self.progress.emit(done, total),
        )
        warnings.extend(outcome.warnings)
        if outcome.index is None:
            warnings.append("无法建立官方模组清单，所有模组归属显示为“未知”。")
        return outcome.index, warnings


_STATE_ORDER = {UpdateState.OUTDATED: 0, UpdateState.ERROR: 1, UpdateState.UNKNOWN: 2,
                UpdateState.CURRENT: 3}
_ORIGIN_ORDER = {Origin.MANUAL: 0, Origin.UNKNOWN: 1, Origin.PACK: 2}
