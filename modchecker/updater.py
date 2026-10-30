"""把“可更新”的模组下载到本地 mods 目录并替换旧 jar。

替换顺序是安全的：旧 jar 先改名为 ``.bak`` → 新文件以 ``.part`` 落盘并校验
→ 原子替换到目标名；任何一步失败都会把 ``.bak`` 改回去，不会留下半个模组。
旧文件默认保留为 ``.bak``，作为用户手动备份之外的第二层保险。
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from modchecker.i18n import t
from modchecker.models import ChangeLevel, ModResult, UpdateState
from modchecker.net import HttpClient

Logger = Callable[[str], None]


@dataclass
class UpdateOutcome:
    """单个模组的更新结果。只在主线程通过 :func:`apply_outcome` 落到结果对象上。"""

    result: ModResult
    ok: bool
    message: str = ""
    new_path: Path | None = None
    new_filename: str = ""
    disabled: bool = False


def _sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _file_sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ModUpdater:
    """逐个下载并替换模组；非线程池，调用方负责放到后台线程。"""

    def __init__(self, http: HttpClient, log: Logger | None = None) -> None:
        self.http = http
        self.log = log or (lambda _msg: None)

    def update(self, result: ModResult) -> UpdateOutcome:
        if not result.has_update:
            return UpdateOutcome(result, False, t("update.not_outdated"))
        if not result.download_url:
            return UpdateOutcome(result, False, t("update.no_direct_url"))
        name = Path(result.download_filename or "").name
        if not name.lower().endswith(".jar"):
            return UpdateOutcome(result, False, t("update.bad_filename", name=name or "-"))

        old_path = result.jar.path
        target = old_path.with_name(name)
        if result.jar.disabled:
            target = target.with_name(target.name + ".disabled")

        if target.exists() and target.resolve() != old_path.resolve():
            if result.download_sha1 and _file_sha1(target) == result.download_sha1:
                return UpdateOutcome(result, True, t("update.already_downloaded"),
                                     new_path=target, new_filename=target.name,
                                     disabled=target.name.endswith(".disabled"))
            return UpdateOutcome(result, False, t("update.target_exists", name=target.name))

        self.log(t("update.downloading", title=result.title, name=target.name))
        data = self.http.request("GET", result.download_url, headers={"Accept": "*/*"})
        if result.download_size and len(data) != result.download_size:
            return UpdateOutcome(result, False,
                                 t("update.size_mismatch", got=len(data),
                                   expected=result.download_size))
        actual = _sha1_bytes(data)
        if result.download_sha1 and actual != result.download_sha1:
            return UpdateOutcome(result, False, t("update.sha1_mismatch", sha1=actual[:12]))

        tmp = target.with_name(f".{target.name}.part")
        try:
            tmp.write_bytes(data)
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            return UpdateOutcome(result, False, t("update.write_failed", error=exc))

        backup: Path | None = None
        try:
            if old_path.exists():
                backup = old_path.with_name(old_path.name + ".bak")
                if backup.exists():
                    backup = old_path.with_name(f"{old_path.name}.{int(time.time())}.bak")
                old_path.rename(backup)
            os.replace(tmp, target)
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            if backup is not None and backup.exists() and not old_path.exists():
                try:
                    backup.rename(old_path)
                except OSError:
                    pass
            return UpdateOutcome(result, False, t("update.replace_failed", error=exc))

        message = (t("update.done_with_backup", name=backup.name) if backup
                   else t("update.done"))
        return UpdateOutcome(result, True, message, new_path=target,
                             new_filename=target.name,
                             disabled=target.name.endswith(".disabled"))


def apply_outcome(result: ModResult, outcome: UpdateOutcome) -> None:
    """把更新结果写回结果对象（必须在主线程调用，避免与表格读取竞争）。"""
    if not outcome.ok:
        result.note = t("update.failed_prefix", message=outcome.message)
        return
    if outcome.new_path is not None:
        result.jar.path = outcome.new_path
        result.jar.filename = outcome.new_filename
        result.jar.disabled = outcome.disabled
        result.jar.sha1 = result.download_sha1
        result.jar.jar_version = ""
        try:
            stat = outcome.new_path.stat()
            result.jar.size = stat.st_size
            result.jar.mtime = stat.st_mtime
        except OSError:
            pass
    result.installed_version = result.latest_version
    result.installed_date = result.latest_date
    result.installed_url = result.latest_url
    result.state = UpdateState.CURRENT
    result.change_level = ChangeLevel.NONE
    result.note = outcome.message
