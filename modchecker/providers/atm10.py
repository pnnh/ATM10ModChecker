"""ATM10 整合包自身：发行版列表、官方 manifest 抓取。"""

from __future__ import annotations

import re
import urllib.parse
from pathlib import Path
from typing import Callable

from modchecker import packmeta
from modchecker.appconfig import ATM10_CF_ID, ATM10_SLUG
from modchecker.cache import CacheStore
from modchecker.i18n import t
from modchecker.models import PackRelease
from modchecker.net import HttpClient
from modchecker.providers.curseforge import CurseForgeProvider
from modchecker.remotezip import RemoteZip, RemoteZipError

CFWIDGET_URL = f"https://api.cfwidget.com/minecraft/modpacks/{ATM10_SLUG}"
_CDN_HOSTS = ("edge.forgecdn.net", "mediafilez.forgecdn.net")
_VERSION_RE = re.compile(r"(\d+(?:\.\d+){1,2})\s*$")

Logger = Callable[[str], None]


def parse_release_version(display: str, filename: str = "") -> str:
    for text in (display, filename):
        match = _VERSION_RE.search(text or "")
        if match:
            return match.group(1)
    return ""


def _cdn_urls(file_id: int, filename: str) -> list[str]:
    """按 CurseForge CDN 的文件路径规则拼接直链（两个域名等价，互为备选）。"""
    bucket, suffix = divmod(int(file_id), 1000)
    quoted = urllib.parse.quote(filename)
    return [f"https://{host}/files/{bucket}/{suffix}/{quoted}" for host in _CDN_HOSTS]


class Atm10Provider:
    def __init__(self, http: HttpClient, cf: CurseForgeProvider, cache: CacheStore,
                 log: Logger | None = None) -> None:
        self.http = http
        self.cf = cf
        self.cache = cache
        self.log = log or (lambda _msg: None)

    # ------------------------------------------------------------------ 发行版
    def releases(self) -> list[PackRelease]:
        cached = self.cache.pack_releases.get("atm10")
        if cached:
            return [PackRelease(**item) for item in cached]
        try:
            data = self.http.get_json(CFWIDGET_URL)
        except Exception as exc:
            self.log(t("provider.atm10.release_failed", error=exc))
            return []
        items: list[PackRelease] = []
        for entry in (data or {}).get("files") or []:
            if not isinstance(entry, dict):
                continue
            display = str(entry.get("display") or "")
            filename = str(entry.get("name") or "")
            items.append(PackRelease(
                file_id=int(entry.get("id") or 0),
                display=display,
                filename=filename,
                version=parse_release_version(display, filename),
                release_type=str(entry.get("type") or ""),
                uploaded_at=str(entry.get("uploaded_at") or ""),
                filesize=int(entry.get("filesize") or 0),
                game_versions=[str(v) for v in entry.get("versions") or []],
            ))
        items.sort(key=lambda r: r.file_id, reverse=True)
        if items:
            self.cache.pack_releases.set("atm10", [r.__dict__ for r in items])
        return items

    def latest_release(self) -> PackRelease | None:
        releases = self.releases()
        return releases[0] if releases else None

    def release_for_version(self, version: str) -> PackRelease | None:
        if not version:
            return None
        for release in self.releases():
            if release.version == version:
                return release
        return None

    # ------------------------------------------------------------------ 官方清单
    def download_urls(self, release: PackRelease) -> list[str]:
        """该发行版可能的下载直链（API 直链 + 按规则拼出的 CDN 链接）。"""
        urls: list[str] = []
        if release.download_url:
            urls.append(release.download_url)
        detail = self.cf.file(ATM10_CF_ID, release.file_id) if release.file_id else None
        api_url = str((detail or {}).get("downloadUrl") or "")
        if api_url:
            urls.append(api_url)
        if release.filename and release.file_id:
            urls.extend(_cdn_urls(release.file_id, release.filename))
        ordered: list[str] = []
        for url in urls:
            if url and url not in ordered:
                ordered.append(url)
        return ordered

    def _nearest_release(self, target: PackRelease | None) -> PackRelease | None:
        """版本号最接近的另一个发行版（旧版归档失效时用作代替）。"""
        if target is None:
            return None
        best: PackRelease | None = None
        best_distance = 0.0
        for release in self.releases():
            if release.file_id == target.file_id or not release.version:
                continue
            distance = abs(_version_float(release.version) - _version_float(target.version))
            if best is None or distance < best_distance:
                best, best_distance = release, distance
        return best

    def _manifest_targets(self, release: PackRelease | None) -> list[tuple[PackRelease, bool]]:
        """按优先级给出候选发行版，第二项标记它是否不是本地对应版本。"""
        targets: list[tuple[PackRelease, bool]] = []
        if release is not None:
            targets.append((release, False))
        seen = {r.file_id for r, _ in targets}
        for candidate in (self._nearest_release(release), self.latest_release()):
            if candidate is not None and candidate.file_id not in seen:
                seen.add(candidate.file_id)
                targets.append((candidate, True))
        return targets

    def fetch_manifest(self, release: PackRelease | None, local_zip: Path | None
                       ) -> tuple[dict | None, str]:
        """返回 ``(manifest, 来源说明)``。

        CurseForge 会归档旧版本的整合包 zip（例如 ATM10 8.0 已 404），
        所以按“本地 zip -> 对应版本 -> 版本号最接近 -> 最新版”的顺序尝试。
        """
        if local_zip and local_zip.is_file():
            manifest = packmeta.read_manifest_from_zip(local_zip)
            if manifest:
                return manifest, f"本地整合包 zip（{local_zip.name}）"
            self.log(t("provider.atm10.no_local_manifest", path=local_zip))

        targets = self._manifest_targets(release)
        if not targets:
            return None, ""

        for target, substitute in targets:
            for url in self.download_urls(target):
                try:
                    manifest = RemoteZip(self.http, url).read_json(("manifest.json",))
                except (RemoteZipError, OSError, ValueError) as exc:
                    self.log(t("provider.atm10.remote_manifest_failed", version=target.version, error=exc))
                    continue
                except Exception as exc:  # 网络/解析异常都换下一个候选
                    self.log(t("provider.atm10.remote_manifest_failed", version=target.version, error=exc))
                    continue
                if not manifest:
                    continue
                if substitute:
                    return manifest, t("provider.atm10.substitute_manifest",
                                       actual=target.version,
                                       wanted=release.version if release else '?')
                return manifest, f"ATM10 {release.version if release else target.version} 官方包（远程读取）"
        return None, ""


def _version_float(version: str) -> float:
    """把 ``8.3`` -> ``8.3``，便于计算版本距离。"""
    parts = [p for p in re.split(r"\D+", version or "") if p]
    if not parts:
        return 0.0
    value = 0.0
    for index, part in enumerate(parts[:2]):
        value += int(part) / (100 ** index)
    return value
