"""检测流程编排：扫描 -> 识别 -> 查新 -> 归类。

所有网络访问都在这里串起来，UI 只关心回调与最终报告。
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    pack_source: Path | None = None   # 用户指定的整合包 zip / 解压目录（可选）


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
    cf_project_id: str = ""
    cf_mod: dict | None = None
    cf_file: dict | None = None
    mr_version: dict | None = None


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


def _source_overlaps_instance(source: Path | None, install: InstallInfo) -> bool:
    """判断“整合包原包”是否就是实例自身（那样会把手动添加的模组也算成自带）。"""
    if source is None:
        return False
    try:
        source_path = source.resolve()
        mods_dir = install.mods_dir.resolve()
        game_dir = install.game_dir.resolve()
    except OSError:
        return False
    if source_path in (mods_dir, game_dir, game_dir / "manifest.json"):
        return True
    return mods_dir.is_relative_to(source_path)


class Checker:
    def __init__(self, options: CheckOptions, log: LogCb | None = None,
                 progress: ProgressCb | None = None, stage: StageCb | None = None,
                 cancel: threading.Event | None = None,
                 on_result: Callable[[ModResult], None] | None = None) -> None:
        self.options = options
        self.log = log or (lambda _msg: None)
        self.cancel = cancel or threading.Event()
        self.progress = _Progress(progress, stage, self.cancel)
        self.on_result = on_result   # 每查完一个模组就回调，界面可以边查边显示
        # 限速依据（2026-10 查阅）：Modrinth 官方文档明确 300 请求/分钟/IP，
        # 这里取 4 次/秒（240/分钟）留出余量；CurseForge 未公开额度但会返回 429，
        # 取 6 次/秒，并在查新阶段分批停顿。下载走单独的低速客户端。
        self.http = HttpClient(rate_per_sec=6.0, cancel_event=self.cancel)
        self.http_modrinth = HttpClient(rate_per_sec=4.0, cancel_event=self.cancel)
        self.cache = CacheStore(cache_dir())
        self.modrinth = ModrinthProvider(self.http_modrinth, self.cache, self.log)
        self.curseforge = CurseForgeProvider(self.http, self.cache,
                                            api_key=options.cf_api_key, log=self.log)
        self.atm = Atm10Provider(self.http, self.curseforge, self.cache, self.log)
        self._failed_shas: dict[str, str] = {}   # sha1 -> 识别阶段的失败原因

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
            ("构建官方模组清单", 24),
            ("查询最新版本", 32),
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

        # ---------------- 整包 & 官方清单
        # 放在查新之前：这样流式显示出来的每一行都带着“自带 / 手动”归属。
        self.progress.enter(2)
        report = Report(install=install)
        report.pack = self._pack_status(install)
        index: OfficialIndex | None = None
        if options.verify_official:
            index, warnings = self._official_index(install)
            report.index = index
            report.warnings.extend(warnings)

        # ---------------- 查新（每查完一个就回调，界面边查边显示）
        self.progress.enter(3)
        results = self._query_results(jars, identities, index, game_version, loader)
        report.mods = results
        report.query_errors = sum(1 for r in results if r.state is UpdateState.ERROR)

        # ---------------- 归类
        self.progress.enter(4)
        self._complete_origin_ids(results, identities, index, game_version, loader)
        for result in results:
            self._classify(result, index, identities)

        if (options.pack_source is None and report.index and report.index.pack_version
                and install.pack_version
                and versioning.compare(report.index.pack_version, install.pack_version) != 0):
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
                    self._failed_shas[jar.sha1] = str(error)
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
                    cf_project_id=str(mod.get("id") or ""),
                    cf_mod=mod,
                    cf_file=file,
                )
        if errors:
            self.log(f"CurseForge 查询失败 {errors} 个（已跳过）")
        self.log(f"CurseForge 识别成功 {sum(1 for i in identities.values() if i.source is Source.CURSEFORGE)} 个")

    # ------------------------------------------------------------------ 最新版本
    def _query_results(self, jars: list[JarEntry], identities: dict[str, _Identity],
                       index: OfficialIndex | None, game_version: str,
                       loader: str) -> list[ModResult]:
        """逐条查询并回调，界面因此可以在检测过程中不断追加行。"""
        results: list[ModResult] = []

        def publish(result: ModResult) -> None:
            self._classify(result, index, identities)
            results.append(result)
            if self.on_result is not None:
                self.on_result(result)

        pending_modrinth: list[JarEntry] = []
        pending_cf: dict[str, list[JarEntry]] = {}
        for jar in jars:
            identity = identities.get(jar.sha1) if jar.sha1 else None
            if identity is None or identity.source is Source.NONE:
                # 未识别：没有可查的数据源，立即出结果
                publish(self._build_result(jar, None, {}, {}, game_version, loader))
            elif identity.source is Source.MODRINTH:
                pending_modrinth.append(jar)
            else:
                pending_cf.setdefault(identity.project_id, []).append(jar)

        if pending_modrinth:
            latest_map, ignored = self._modrinth_latest(pending_modrinth, game_version, loader)
            for jar in pending_modrinth:
                publish(self._build_result(
                    jar, identities[jar.sha1], latest_map, {}, game_version, loader,
                    blocked_prerelease=jar.sha1 in ignored))

        if pending_cf:
            self._curseforge_latest(pending_cf, identities, game_version, loader, publish)
        return results

    @staticmethod
    def _classify(result: ModResult, index: OfficialIndex | None,
                  identities: dict[str, _Identity]) -> None:
        identity = identities.get(result.jar.sha1) if result.jar.sha1 else None
        cf_id = identity.cf_project_id if identity else ""
        origin, detail = classify(result.jar, index, cf_id)
        result.origin = origin
        result.origin_detail = detail
        if not detail:
            result.origin_detail = "未能获取官方清单" if index is None else "无法判断"

    @staticmethod
    def _prerelease_channel(jar: JarEntry) -> bool:
        """本地 jar 是否走 beta/alpha 通道（文件名或 jar 内版本号带预发布标记）。"""
        return versioning.is_prerelease(jar.filename, jar.jar_version)

    @staticmethod
    def _version_is_prerelease(version: dict) -> bool:
        kind = str(version.get("version_type") or "").lower()
        if kind:
            return kind != "release"
        return versioning.is_prerelease(str(version.get("version_number") or ""))

    def _stable_modrinth_version(self, version: dict, game_version: str,
                                 loader: str) -> dict | None:
        """最新版本是 beta/alpha 时，回退到该项目的最近正式版。"""
        project_id = str(version.get("project_id") or "")
        if not project_id:
            return None
        for item in self.modrinth.project_versions(project_id, game_version, loader):
            if not self._version_is_prerelease(item):
                return item
        return None

    def _modrinth_latest(self, jars: list[JarEntry], game_version: str,
                         loader: str) -> tuple[dict[str, dict], set[str]]:
        """返回 (sha1 -> 最新正式版, 因为只有 beta/alpha 而被忽略的 sha1)。"""
        if not self.options.use_modrinth:
            return {}, set()
        hashes = [jar.sha1 for jar in jars if jar.sha1]
        if not hashes:
            return {}, set()
        latest_map = self.modrinth.latest(
            hashes, game_version, loader,
            progress=lambda done, total: self.progress.emit(done, total))
        filtered: dict[str, dict] = {}
        ignored: set[str] = set()
        for jar in jars:
            version = latest_map.get(jar.sha1)
            if not version:
                continue
            if not self._version_is_prerelease(version) or self._prerelease_channel(jar):
                filtered[jar.sha1] = version
                continue
            stable = self._stable_modrinth_version(version, game_version, loader)
            if stable is not None:
                filtered[jar.sha1] = stable
            else:
                ignored.add(jar.sha1)
        return filtered, ignored

    def _curseforge_latest(self, groups: dict[str, list[JarEntry]],
                           identities: dict[str, _Identity], game_version: str,
                           loader: str,
                           publish: Callable[[ModResult], None]) -> None:
        """逐项目查询最新文件，完成一个就发布一个，不再等全部结束。"""
        if not self.options.use_curseforge:
            for group in groups.values():
                for jar in group:
                    publish(self._build_result(jar, identities[jar.sha1], {}, {},
                                               game_version, loader))
            return
        total = len(groups)
        done = 0

        def work(item: tuple[str, list[JarEntry]]):
            project_id, group = item
            allow = any(self._prerelease_channel(jar) for jar in group)
            try:
                latest = self.curseforge.latest_file(project_id, game_version, loader,
                                                     allow_prerelease=allow)
                blocked = False
                if latest is None and not allow:
                    # 再确认一次是否“只剩下 beta/alpha”，以便给出更准确的说明
                    blocked = self.curseforge.latest_file(
                        project_id, game_version, loader, allow_prerelease=True) is not None
                return project_id, group, latest, blocked, None
            except Cancelled:
                raise
            except Exception as exc:
                return project_id, group, None, False, exc

        with ThreadPoolExecutor(max_workers=max(1, self.options.concurrency)) as pool:
            futures = [pool.submit(work, item) for item in groups.items()]
            for future in as_completed(futures):
                self.progress.check_cancel()
                project_id, group, latest, blocked, error = future.result()
                done += 1
                self.progress.emit(done, total)
                if done % 60 == 0 and done < total:
                    # 分批停顿：CurseForge 未公开额度，连续请求更容易撞 429
                    self._pause(0.8)
                if error is not None:
                    self.log(f"CurseForge 最新版本查询失败（{project_id}）：{error}")
                    for jar in group:
                        failed = self._build_result(jar, identities[jar.sha1], {}, {},
                                                    game_version, loader)
                        failed.state = UpdateState.ERROR
                        failed.note = f"查询失败：{error}"
                        publish(failed)
                    continue
                latest_map = {project_id: latest} if latest else {}
                for jar in group:
                    publish(self._build_result(jar, identities[jar.sha1], {}, latest_map,
                                               game_version, loader,
                                               blocked_prerelease=blocked))

    def _pause(self, seconds: float) -> None:
        """分批之间的短暂停顿，降低触发 429 的概率（可随时取消）。"""
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            self.progress.check_cancel()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.1, remaining))

    # ------------------------------------------------------------------ 结果装配
    def _build_result(self, jar: JarEntry, identity: _Identity | None,
                      modrinth_latest: dict[str, dict], cf_latest: dict[str, dict],
                      game_version: str, loader: str,
                      *, blocked_prerelease: bool = False) -> ModResult:
        result = ModResult(jar=jar)
        if identity is None or identity.source is Source.NONE:
            reason = self._failed_shas.get(jar.sha1 or "")
            if reason:
                result.state = UpdateState.ERROR
                result.note = f"查询失败：{reason}"
            else:
                result.state = UpdateState.UNKNOWN
                result.note = "Modrinth / CurseForge 均未找到匹配的项目"
            result.installed_version = jar.jar_version
            return result

        result.source = identity.source
        result.project_id = identity.project_id
        result.project_title = identity.project_title
        result.project_url = identity.project_url
        result.installed_version = identity.installed_version or jar.jar_version
        result.installed_date = identity.installed_date
        result.installed_url = self._version_url(identity, identity.mr_version if
                                                 identity.source is Source.MODRINTH
                                                 else identity.cf_file)
        prerelease = self._prerelease_channel(jar)

        if identity.source is Source.MODRINTH:
            latest = modrinth_latest.get(jar.sha1, {})
            if latest:
                result.latest_version = str(latest.get("version_number") or "")
                result.latest_date = versioning.parse_iso(latest.get("date_published"))
                result.latest_url = self._version_url(identity, latest)
                self._set_mr_download(result, latest)
                newer = versioning.decide(result.installed_version, result.latest_version,
                                          result.installed_date, result.latest_date,
                                          game_version, loader)
                result.state = UpdateState.OUTDATED if newer else UpdateState.CURRENT
                if newer:
                    result.change_level = versioning.change_level(
                        result.installed_version, result.latest_version,
                        game_version, loader, prerelease=prerelease)
                    if prerelease:
                        result.note = "本地为预发布版本，按 beta/alpha 通道比较"
            elif blocked_prerelease:
                result.state = UpdateState.CURRENT
                result.note = "最新版本是 beta/alpha，已按稳定通道忽略"
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
            result.latest_url = self._version_url(identity, latest)
            self._set_cf_download(result, latest)
            same_file = (result.latest_filename.lower() == jar.filename.lower())
            newer = None if same_file else versioning.decide(
                result.installed_version, result.latest_version,
                result.installed_date, result.latest_date, game_version, loader)
            if newer is None:
                # 已装的正是最新文件 / 无法比较时，不报“可更新”
                result.state = UpdateState.CURRENT if same_file else UpdateState.UNKNOWN
            else:
                result.state = UpdateState.OUTDATED if newer else UpdateState.CURRENT
            if result.state is UpdateState.OUTDATED:
                result.change_level = versioning.change_level(
                    result.installed_version, result.latest_version,
                    game_version, loader, prerelease=prerelease)
                notes = []
                if prerelease:
                    notes.append("本地为预发布版本，按 beta/alpha 通道比较")
                if identity.confidence == "项目名匹配":
                    notes.append("按项目名关联，建议人工确认")
                result.note = "；".join(notes)
        elif blocked_prerelease:
            result.state = UpdateState.CURRENT
            result.note = "最新版本是 beta/alpha，已按稳定通道忽略"
        else:
            result.state = UpdateState.UNKNOWN
            result.note = f"没有适用于 {game_version} / {loader} 的 CurseForge 文件"
        return result

    @staticmethod
    def _version_url(identity: _Identity, item: dict | None) -> str:
        """版本 / 文件的发布页面：优先 Modrinth，其次 CurseForge。

        用户需要点进去读发版说明，判断大版本更新是否存在破坏性变更。
        """
        if not item:
            return ""
        if identity.source is Source.MODRINTH:
            version_id = str(item.get("id") or "")
            if not version_id:
                return ""
            slug = identity.project_url.rsplit("/", 1)[-1] if identity.project_url else ""
            return f"https://modrinth.com/mod/{slug or identity.project_id}/version/{version_id}"
        if identity.source is Source.CURSEFORGE:
            slug = str((identity.cf_mod or {}).get("slug") or "")
            file_id = item.get("id")
            if slug:
                if file_id:
                    return (f"https://www.curseforge.com/minecraft/mc-mods/{slug}"
                            f"/files/{file_id}")
                return f"https://www.curseforge.com/minecraft/mc-mods/{slug}/files"
        return ""

    @staticmethod
    def _set_cf_download(result: ModResult, latest: dict) -> None:
        """记录 CurseForge 最新文件的下载信息（供“更新”使用）。"""
        result.download_url = str(latest.get("downloadUrl") or "")
        result.download_filename = str(latest.get("fileName") or "")
        result.download_size = int(latest.get("fileLength") or 0)
        for item in latest.get("hashes") or []:
            if item.get("algo") == 1:          # 1 = sha1
                result.download_sha1 = str(item.get("value") or "").lower()
                break

    @staticmethod
    def _set_mr_download(result: ModResult, latest: dict) -> None:
        """记录 Modrinth 版本里主文件的下载信息。"""
        files = latest.get("files") or []
        chosen = next((item for item in files if item.get("primary")), None)
        if chosen is None:
            chosen = next((item for item in files
                           if str(item.get("filename") or "").lower().endswith(".jar")), None)
        if chosen is None and files:
            chosen = files[0]
        if not chosen:
            return
        result.download_url = str(chosen.get("url") or "")
        result.download_filename = str(chosen.get("filename") or "")
        result.download_size = int(chosen.get("size") or 0)
        hashes = chosen.get("hashes") or {}
        if isinstance(hashes, dict):
            result.download_sha1 = str(hashes.get("sha1") or "").lower()

    # ------------------------------------------------------------------ 整包 & 清单
    def _complete_origin_ids(self, results: list[ModResult], identities: dict[str, _Identity],
                             index: OfficialIndex | None, game_version: str,
                             loader: str) -> None:
        """给“文件名与哈希都不在清单里”的 jar 补查 CurseForge 项目 ID。

        自行升级过的整合包模组文件名会变，但项目 ID 不变；只有拿到它才能把这类
        模组仍判为“整合包自带”，而不是误报成“手动添加”。
        """
        if index is None or not index.usable or not index.project_files:
            return
        if not self.options.use_curseforge:
            return
        pending: list[JarEntry] = []
        for result in results:
            jar = result.jar
            if not jar.sha1:        # 身份以 sha1 为键，没有哈希就无处回填
                continue
            if jar.filename.lower() in index.filenames:
                continue
            if jar.sha1 in index.sha1s:
                continue
            identity = identities.get(jar.sha1)
            if identity is not None and identity.cf_project_id:
                continue
            pending.append(jar)
        if not pending:
            return

        self.log(f"归属核验：{len(pending)} 个模组不在清单文件名中，改用 CurseForge 项目 ID 判定")
        total = len(pending)
        done = 0

        def work(jar: JarEntry):
            try:
                return jar, self.curseforge.resolve_jar(jar, game_version, loader)
            except Cancelled:
                raise
            except Exception:  # 单个模组失败不影响归属判断
                return jar, ({}, None, "")

        with ThreadPoolExecutor(max_workers=max(1, self.options.concurrency)) as pool:
            for jar, (mod, _file, _confidence) in pool.map(work, pending):
                done += 1
                self.progress.emit(done, total, "归属核验")
                mod_id = str((mod or {}).get("id") or "")
                if not mod_id or not jar.sha1:
                    continue
                identity = identities.get(jar.sha1)
                if identity is None:
                    identity = _Identity()
                    identities[jar.sha1] = identity
                identity.cf_project_id = mod_id

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
        local_meta = packmeta.find_local_metadata(install.game_dir, install.root,
                                                  install.game_dir.parent)
        version_hint = install.pack_version

        # 0) 用户指定的整合包原包（zip 或解压目录）优先，避免误用同名的其它归档
        if self.options.pack_source is not None:
            user_meta = packmeta.load_pack_reference(self.options.pack_source)
            if user_meta.has_info:
                warnings.extend(user_meta.warnings)
                if (install.pack_version and user_meta.pack_version
                        and versioning.compare(user_meta.pack_version, install.pack_version) != 0):
                    warnings.append(
                        f"指定清单的版本（{user_meta.pack_version}）与实例版本"
                        f"（{install.pack_version}）不一致，归属判断可能有偏差。")
                    # 版本不同时按清单自身版本缓存，避免污染实例版本的缓存
                    version_hint = user_meta.pack_version
                self.log(f"使用指定的整合包清单：{user_meta.source}，"
                         f"{len(user_meta.filenames)} 个文件 / {len(user_meta.project_files)} 个项目")
                merged = packmeta.LocalMetadata()
                merged.merge(local_meta)      # 本地：补版本 / 加载器等信息
                merged.merge(user_meta)       # 用户清单：覆盖文件名与项目 ID
                merged.source = user_meta.source or merged.source
                merged.path = user_meta.path or merged.path
                local_meta = merged
                if _source_overlaps_instance(user_meta.path, install):
                    warnings.append(
                        "指定的原包就是当前实例本身（或实例内的目录），其中已经包含手动添加的模组，"
                        "无法区分归属；建议改选整合包原始 zip 或其解压目录。")
            else:
                warnings.extend(user_meta.warnings or [
                    f"无法从指定路径读取整合包清单：{self.options.pack_source}"])
                warnings.append("已退回实例自带的清单或远程官方清单。")
        else:
            candidate = packmeta.find_pack_zip(install.game_dir, install.root)
            if candidate is not None:
                self.log(f"发现疑似整合包归档：{candidate.name}（未自动采用，"
                         f"如需精确判断请在界面上指定整合包原包）")

        if not self.options.use_curseforge:
            # 没有 CurseForge 时只能依赖本地清单（文件名 / 哈希 / 项目 ID）
            if not (local_meta.filenames or local_meta.sha1s or local_meta.project_files):
                warnings.append("未启用 CurseForge，且本机没有可用的整合包清单，无法判断模组归属。")
                return None, warnings
            return build_official_index(
                local_meta=local_meta, atm=self.atm, cf=self.curseforge, cache=self.cache,
                pack_version_hint=version_hint, local_zip=None,
                use_curseforge=False, concurrency=self.options.concurrency,
                cancel=self.cancel, log=self.log,
                progress=lambda done, total: self.progress.emit(done, total),
            ).index, warnings

        outcome = build_official_index(
            local_meta=local_meta, atm=self.atm, cf=self.curseforge, cache=self.cache,
            pack_version_hint=version_hint, local_zip=self._local_zip(),
            use_curseforge=True, concurrency=self.options.concurrency,
            cancel=self.cancel, log=self.log,
            progress=lambda done, total: self.progress.emit(done, total),
        )
        warnings.extend(outcome.warnings)
        if outcome.index is None:
            warnings.append("无法建立官方模组清单，所有模组归属显示为“未知”。")
        return outcome.index, warnings

    def _local_zip(self) -> Path | None:
        """用户指定的是 zip 时，可作为 manifest 的备用来源。"""
        source = self.options.pack_source
        return source if source is not None and source.is_file() else None


_STATE_ORDER = {UpdateState.ERROR: 0, UpdateState.OUTDATED: 1, UpdateState.UNKNOWN: 2,
                UpdateState.CURRENT: 3}
_ORIGIN_ORDER = {Origin.MANUAL: 0, Origin.UNKNOWN: 1, Origin.PACK: 2}
