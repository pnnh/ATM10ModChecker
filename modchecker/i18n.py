"""界面文案的国际化（英文 / 简体中文）。

默认英文；启动时若设置为 ``auto``，则按操作系统语言选择，识别不到就用英文。
用法：``from modchecker.i18n import t``，然后 ``t("button.start")``。
"""

from __future__ import annotations

import locale
import os
from typing import Any

# 可选的语言（auto = 跟随系统）
LANGUAGES: tuple[str, ...] = ("auto", "en", "zh")
LANGUAGE_NATIVE_NAMES = {"auto": "", "en": "English", "zh": "简体中文"}

_current = "en"


# ---------------------------------------------------------------------- 语言探测
def detect_system_language() -> str:
    """判断操作系统语言，中文返回 ``zh``，其余一律 ``en``。"""
    # 1) Qt 能拿到系统区域设置时最准确（Windows / macOS 的界面语言）
    try:
        from PySide6.QtCore import QLocale  # 延迟导入：非 GUI 场景下也能用本模块

        name = QLocale.system().name().lower()
        # "C" / "POSIX" 表示没有配置区域，继续看环境变量
        if name and name not in ("c", "posix"):
            return "zh" if name.startswith("zh") else "en"
    except Exception:  # pragma: no cover - 没有 Qt 时退回环境变量
        pass
    # 2) POSIX 环境变量
    for env in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        value = (os.environ.get(env) or "").strip().lower()
        if value:
            return "zh" if value.startswith("zh") else "en"
    # 3) Python 的区域设置（Windows 上形如 "Chinese (Simplified)_China"）
    try:
        name = (locale.getlocale()[0] or "").lower()
    except Exception:
        name = ""
    return "zh" if name.startswith(("zh", "chinese")) else "en"


def resolve(preference: str) -> str:
    """把用户设置（auto / en / zh）解析成实际使用的语言。"""
    value = (preference or "auto").strip().lower()
    if value in ("en", "zh"):
        return value
    return detect_system_language()


def set_language(language: str) -> None:
    global _current
    _current = language if language in ("en", "zh") else "en"


def get_language() -> str:
    return _current


def configure(preference: str) -> str:
    """按用户设置初始化语言，返回最终使用的语言代码。"""
    set_language(resolve(preference))
    return _current


def t(key: str, **kwargs: Any) -> str:
    """取当前语言的文案；缺失的 key 回退英文，再回退 key 本身。

    注意：空字符串是合法文案（例如复选框列的表头本来就不显示文字），
    所以这里必须用 ``is None`` 判断缺失，不能用真值判断。
    """
    text = _CATALOG.get(_current, {}).get(key)
    if text is None:
        text = _CATALOG["en"].get(key)
    if text is None:
        text = key
    if not kwargs:
        return text
    try:
        return text.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return text


# ---------------------------------------------------------------------- 文案表
_EN: dict[str, str] = {
    "app.title": "ATM10 Mod Checker",
    "app.subtitle": "Compares the jars in your mods folder with the latest versions on "
                    "Modrinth / CurseForge, tells pack-bundled mods apart from manually "
                    "added ones, and can update the selected mods to their latest versions.",

    # 按钮 / 输入框
    "button.browse": "Browse…",
    "button.start": "Start check",
    "button.cancel": "Cancel",
    "button.settings": "Settings",
    "button.pick_zip": "Select zip…",
    "button.pick_dir": "Select folder…",
    "button.clear": "Clear",
    "button.batch_update": "Batch update",
    "button.batch_update_n": "Batch update ({n})",
    "button.export": "Export CSV",
    "button.log": "Log",
    "placeholder.path": "Select the ATM10 directory (the client .minecraft folder or the "
                        "server ServerFiles folder)",
    "placeholder.pack": "Optional: the original modpack zip, or the clean folder extracted "
                        "from it (leave empty to use the instance manifest)",
    "placeholder.search": "Search mod name / file name / modId",

    # 顶部信息
    "label.pack": "Pack source: ",
    "chip.kind": "Type: -",
    "chip.mc": "Minecraft: -",
    "chip.loader": "Loader: -",
    "chip.pack": "Pack version: -",
    "chip.index": "Official manifest: -",
    "chip.kind_value": "Type: {value}",
    "chip.mc_value": "Minecraft: {value}",
    "chip.loader_value": "Loader: {value}",
    "chip.pack_value": "Pack version: {value}",
    "chip.index_value": "Official manifest: {version} / {items} items",
    "chip.index_missing": "Official manifest: not found",
    "chip.index_unusable": "Official manifest: not fetched",
    "chip.index_bad_path": "Official manifest: invalid path",
    "chip.index_source_specified": "Specified source: {source}",
    "chip.index_source_instance": "Instance folder: {source}",
    "chip.index_items_tip": "{source}\n{projects} projects, {names} file names, "
                            "{hashes} hashes",
    "banner.idle": "Not checked yet",
    "banner.pack_update": "⚠ {message}  Latest release on {date}, {count} releases",
    "banner.pack_current": "✓ {message}",
    "banner.pack_unknown": "Cannot fetch pack version information",
    "banner.pack_unknown_generic": "Unable to fetch pack version information",

    # 过滤栏
    "filter.state.all": "All states",
    "filter.state.outdated": "Updatable",
    "filter.state.current": "Up to date",
    "filter.state.unknown": "Unknown",
    "filter.state.error": "Check failed",
    "filter.origin.all": "All origins",
    "filter.origin.manual": "Manually added",
    "filter.origin.pack": "From pack",
    "filter.origin.unknown": "Unknown origin",
    "filter.only_updates": "Only updatable",

    # 表头
    "column.select": "",
    "column.state": "Status",
    "column.title": "Mod",
    "column.origin": "Origin",
    "column.installed": "Installed",
    "column.installed_date": "Installed on",
    "column.latest": "Latest",
    "column.latest_date": "Latest on",
    "column.source": "Source",
    "column.filename": "File name",

    # 状态 / 变更级别 / 归属 / 数据源
    "state.outdated": "Updatable",
    "state.current": "Up to date",
    "state.unknown": "Unknown",
    "state.error": "Check failed",
    "change.major": "Major update",
    "change.minor": "Minor update",
    "change.patch": "Bug-fix update",
    "change.build": "Build update",
    "change.prerelease": "Beta/alpha update",
    "change.unknown": "Updatable",
    "origin.pack": "From pack",
    "origin.manual": "Manually added",
    "origin.unknown": "Unknown",
    "source.modrinth": "Modrinth",
    "source.curseforge": "CurseForge",
    "source.none": "Unrecognized",
    "kind.client": "Client",
    "kind.server": "Server",
    "kind.unknown": "Unknown",
    "kind.value": "Type: {value}",

    # 状态栏
    "status.ready": "Ready",
    "status.identified": "mods folder: {path} ({count} jars)",
    "status.read_failed": "Failed to read the folder: {error}",
    "status.checking": "Checking… {count} mods shown",
    "status.checking_initial": "Checking…",
    "status.done": "Check finished in {seconds:.1f}s",
    "status.cancelled": "Cancelled",
    "status.cancelled_partial": "Cancelled, {count} mods shown (incomplete)",
    "status.failed": "Check failed",
    "status.failed_partial": "Check failed, {count} mods shown (incomplete)",
    "status.cancelling": "Cancelling…",
    "status.stopping_update": "Stopping the update…",
    "status.pack_loading": "Fetching pack version information…",
    "status.exported": "Exported: {path}",
    "status.no_direct_link": "{title}: this file has no direct download link, please "
                             "download it manually from the project page",
    "status.updating": "Updating {done}/{total}…",
    "status.updating_progress": "Updating {done}/{total} (succeeded {ok})",
    "status.progress": "{label}… {percent}%",
    "status.stage": "{label}… {done}/{total}",
    "status.stage_plain": "{label}…",

    # 统计
    "stats.total": "Total {n} mods",
    "stats.outdated": "Updatable {n}",
    "stats.current": "Up to date {n}",
    "stats.unknown": "Unknown {n}",
    "stats.failed": "Check failed {n}",
    "stats.manual": "Manually added {n}",
    "stats.pack": "From pack {n}",
    "stats.origin_unknown": "Origin unknown {n}",
    "stats.empty": "—",

    # 提示气泡
    "tip.state_click": "Click to update this mod to the latest version (confirmed in a "
                       "dialog, cannot be undone)",
    "tip.version_link": "Click to open the release page in your browser and read the "
                        "changelog",
    "tip.version_fallback": "Click to open the project page / site search in your browser",
    "tip.failure": "Failure reason: {reason}",
    "tip.file": "File: {name}",
    "tip.project": "Project: {title}",
    "tip.installed": "Installed: {version}",
    "tip.installed_date": "Installed on: {date}",
    "tip.latest": "Latest: {version}",
    "tip.latest_date": "Latest on: {date}",
    "tip.mod_id": "modId: {mod_id}",
    "tip.origin": "Origin basis: {detail}",
    "tip.note": "Note: {note}",
    "tip.link": "Link: {url}",

    # 对话框
    "dialog.need_dir.title": "Directory required",
    "dialog.need_dir.text": "Please select the ATM10 installation directory first.",
    "dialog.no_source.title": "No data source",
    "dialog.no_source.text": "Enable at least one data source (Modrinth or CurseForge).",
    "dialog.check_failed.title": "Check failed",
    "dialog.export_failed.title": "Export failed",
    "dialog.update.title": "Confirm mod update",
    "dialog.update.text": "The following mods will be updated to their latest versions:\n{names}",
    "dialog.update.more": "{names} and {count} more mods",
    "dialog.update.irreversible": "This action cannot be undone! Back up the whole game "
                                  "instance (at least the mods folder) before continuing.",
    "dialog.update.backup": "Official files replace the old jars; the old files are kept "
                            "as .bak backups.",
    "dialog.update.breaking": "{names} are major/minor updates and may contain breaking "
                              "changes (config files, registry IDs, data formats, APIs). "
                              "Open the “Latest” column to read the release notes first.",
    "dialog.update.unclear": "{count} mod(s) cannot be classified by version number; "
                             "reading their release notes is recommended.",
    "dialog.update.aware": "I have read the release notes and understand the consequences.",
    "dialog.update.accept": "I have a backup, start updating",
    "dialog.update.cancel": "Cancel",
    "dialog.update_failed.title": "Some mods failed to update",
    "dialog.file.choose_dir": "Select the ATM10 installation directory",
    "dialog.file.choose_pack_zip": "Select the modpack zip",
    "dialog.file.zip_filter": "Zip files (*.zip)",
    "dialog.file.choose_pack_dir": "Select the extracted modpack folder",
    "dialog.file.export": "Export check results",
    "dialog.file.csv_filter": "CSV files (*.csv)",
    "dialog.error.title": "Unexpected error",

    # 日志面板
    "log.update_start": "[Update] Updating {count} mod(s)",
    "log.update_ok": "[Update] {title}: {message}",
    "log.update_failed": "[Update failed] {title}: {message}",
    "log.warning": "[Warning] {text}",
    "log.query_failed_hint": "[Hint] {count} mod(s) failed to be checked, try again later.",
    "log.notice": "[Notice] {text}",
    "log.startup": "[Startup] {text}",

    "csv.status": "Status",
    "csv.mod": "Mod",
    "csv.origin": "Origin",
    "csv.installed": "Installed",
    "csv.installed_date": "Installed on",
    "csv.latest": "Latest",
    "csv.latest_date": "Latest on",
    "csv.source": "Source",
    "csv.filename": "File name",
    "csv.mod_id": "modId",
    "csv.link": "Link",
    "csv.note": "Note",

    # 设置对话框
    "settings.title": "Advanced settings",
    "settings.language_box": "Language",
    "settings.language_label": "Interface language:",
    "settings.language_auto": "Follow system",
    "settings.version_box": "Version baseline (leave empty to detect automatically)",
    "settings.mc_placeholder": "e.g. 1.21.1",
    "settings.mc_label": "Minecraft version:",
    "settings.loader_label": "Mod loader:",
    "settings.version_hint": "“Latest” is only searched among builds matching this "
                             "Minecraft version and loader, to avoid incompatible updates.",
    "settings.source_box": "Data sources",
    "settings.modrinth": "Enable Modrinth (no API key, covers about 60%)",
    "settings.curseforge": "Enable CurseForge (fills in identification and latest "
                           "versions, coverage close to 100%)",
    "settings.key_label": "CurseForge API key:",
    "settings.key_placeholder": "Leave empty to use the public read-only proxy api.curse.tools",
    "settings.verify": "Build the official mod manifest while checking (separates "
                       "pack-bundled and manually added mods)",
    "settings.scan_box": "Scanning",
    "settings.disabled": "Also check disabled mods (*.jar.disabled)",
    "settings.concurrency": "Network concurrency:",
    "settings.pack_box": "Pack source (optional, improves origin detection)",
    "settings.pack_placeholder": "The original modpack zip, or the clean folder extracted "
                                 "from it",
    "settings.hint": "Tip: the official manifest is cached, so a given pack version is "
                     "parsed only once; clear the cache folder to force a refresh.",
    "settings.pick_zip": "Select modpack zip",
    "settings.pick_dir": "Select extracted modpack folder",

    # 检查器阶段 / 日志 / 说明
    "stage.scan": "Scanning mods folder",
    "stage.identify": "Identifying mod sources",
    "stage.manifest": "Building official manifest",
    "stage.versions": "Querying latest versions",
    "stage.wrapup": "Wrapping up",
    "stage.done": "Check finished",
    "log.install_dir": "Install directory: {path}",
    "log.version_base": "Version baseline: Minecraft {mc} / {loader}",
    "log.jar_count": "{count} jars found",
    "log.disabled_jars": "Note: disabled jars (*.jar.disabled) are included",
    "log.modrinth_identified": "Modrinth identified {hit}/{total} jars",
    "log.cf_resolve": "CurseForge lookups: {count} jars",
    "log.cf_failures": "{count} CurseForge lookups failed (skipped)",
    "log.cf_identified": "CurseForge identified {count} jars",
    "log.cf_latest_failed": "CurseForge latest version lookup failed ({project}): {error}",
    "log.origin_lookup": "{count} mods are not listed by file name; checking CurseForge "
                         "project IDs",
    "log.pack_source_used": "Using the specified pack manifest: {source}, {count} items",
    "log.pack_candidate": "Possible modpack archive found: {name} (not used automatically; "
                          "set it as the pack source to be sure)",
    "warn.pack_version_mismatch": "Official manifest version ({manifest}) differs from the "
                                  "local pack version ({local}); classification may be "
                                  "inaccurate.",
    "note.no_project": "No matching project found on Modrinth / CurseForge",
    "note.no_mr_version": "No Modrinth version available for {mc} / {loader}",
    "note.no_cf_version": "No CurseForge file available for {mc} / {loader}",
    "note.prerelease_blocked": "The latest version is beta/alpha and was skipped (stable "
                               "channel)",
    "note.prerelease_channel": "Installed build is a prerelease; comparing within the "
                               "beta/alpha channel",
    "note.name_match": "Matched by project name, please verify manually",
    "note.query_failed": "Lookup failed: {error}",
    "note.updated": "{message}",

    # 官方清单
    "official.local_source": "local metadata",
    "official.local_manifest": "Using the local pack manifest: {files} file names / "
                               "{hashes} hashes ({source}), no network needed",
    "official.cached_manifest": "Reusing the cached official manifest: ATM10 {version} "
                                "({count} mods)",
    "official.no_release": "No official release found for ATM10 {version}; falling back to "
                           "the manifest of the latest release {latest}.",
    "official.archive_fallback": "The official archive for ATM10 {version} is unavailable; "
                                 "using the manifest of {actual}. Some mods may be "
                                 "misclassified as manually added.",
    "official.manifest_source": "Official manifest source: {source}, {count} mods "
                                "({names} file names)",
    "official.no_manifest": "Could not fetch the official manifest.json; mod origin cannot "
                            "be determined.",
    "official.partial": "Only {resolved}/{declared} file names were resolved; "
                        "classification may be incomplete.",
    "official.origin_filename": "File name is in the official manifest",
    "official.origin_hash": "File hash is in the official manifest",
    "official.origin_project": "Project ID is in the official manifest",
    "official.origin_missing": "Not present in the official manifest",
    "official.origin_unknown_no_index": "No official manifest available",
    "official.origin_unknown_generic": "Undetermined",

    # 数据源日志
    "provider.atm10.release_failed": "Failed to fetch the ATM10 release list: {error}",
    "provider.atm10.no_local_manifest": "No manifest.json inside the local zip: {path}",
    "provider.atm10.remote_manifest_failed": "Failed to read the remote pack manifest "
                                             "(ATM10 {version}): {error}",
    "provider.cf.project_failed": "CurseForge project lookup failed ({id}): {error}",
    "provider.cf.file_failed": "CurseForge file lookup failed ({id}/{file}): {error}",
    "provider.cf.files_failed": "CurseForge file list lookup failed ({id}): {error}",
    "provider.cf.search_failed": "CurseForge search failed ({term}): {error}",
    "provider.mr.identify_failed": "Modrinth batch identification failed: {error}",
    "provider.mr.projects_failed": "Failed to fetch Modrinth project info: {error}",
    "provider.mr.latest_failed": "Modrinth latest version lookup failed, falling back to "
                                 "per-project queries: {error}",
    "provider.mr.versions_failed": "Failed to fetch the Modrinth version list ({id}): {error}",

    # 扫描 / 整合包元数据
    "scan.dir_missing": "Directory does not exist: {path}",
    "scan.mods_missing": "No mods folder was found in the selected directory (tried mods, "
                         ".minecraft/mods, minecraft/mods).",
    "packmeta.unparsable": "Cannot parse {path}",
    "packmeta.not_zip_or_manifest": "Neither a zip nor a manifest.json: {path}",
    "packmeta.path_missing": "The specified pack path does not exist: {path}",
    "packmeta.zip_source": "modpack zip ({name})",

    # 更新器
    "update.not_outdated": "The mod is not in the “updatable” state",
    "update.no_direct_url": "This file has no direct download link, please download it "
                            "manually from the project page",
    "update.bad_filename": "The download is not a jar file: {name}",
    "update.target_exists": "Target file already exists, not overwritten: {name}",
    "update.already_downloaded": "Target file already exists with a matching checksum",
    "update.downloading": "Downloading {title} → {name}",
    "update.size_mismatch": "Size mismatch (received {got} bytes, expected {expected})",
    "update.sha1_mismatch": "SHA-1 verification failed ({sha1}…)",
    "update.write_failed": "Failed to write the temporary file: {error}",
    "update.replace_failed": "Failed to replace the file: {error}",
    "update.done_with_backup": "Updated; the old file is backed up as {name}",
    "update.done": "Updated",
    "update.failed_prefix": "Update failed: {message}",
    "update.unexpected": "Unexpected error: {error}",

    # ------------------------------------------------------------------ 补充（1.1）
    "column.filename_disabled": " (disabled)",
    "tip.batch_update": "Enabled after ticking the boxes on the left: update the selected mods "
                        "to their latest versions",
    "chip.index_source_tip": "Source: {source}",
    "chip.index_source_missing": "no usable manifest found",
    "chip.index_no_classify": "Cannot tell pack-bundled mods from manually added ones",
    "chip.version_unknown": "unknown version",
    "chip.value_unknown": "not detected",
    "status.open_url_failed": "Could not open the browser: {url}",
    "status.update_done": "Update finished: {ok} succeeded",
    "status.update_cancelled_suffix": ", cancelled ({total} in total)",
    "status.update_failed_suffix": ", {failed} failed (see the log)",

    "pack.no_releases": "Could not fetch the ATM10 release list",
    "pack.update_available": "Pack update available: {installed} → {latest} ({date})",
    "pack.up_to_date": "The pack is already on the latest version {version}",
    "pack.local_newer": "The local version {installed} is newer than the latest release "
                        "{latest} (maybe a test build)",
    "pack.version_unknown": "Could not detect the pack version; the latest release is {latest}",

    "warn.specified_version_diff": "The specified manifest version ({manifest}) differs from "
                                   "the instance version ({installed}); origin detection may "
                                   "be off.",
    "warn.specified_overlap": "The specified pack is the instance itself (or a folder inside "
                              "it), which already contains manually added mods, so origins "
                              "cannot be told apart; choose the original pack zip or its "
                              "extracted folder instead.",
    "warn.specified_unreadable": "Could not read the pack manifest from {path}.",
    "warn.fallback_local": "Fell back to the instance manifest or the remote official manifest.",
    "warn.no_cf_manifest": "CurseForge is disabled and there is no usable pack manifest on "
                           "this computer, so mod origins cannot be determined.",
    "warn.no_index": "Could not build the official mod manifest, so every mod shows "
                     "“Unknown” as its origin.",
    "scan.no_jars": "No jar files were found in the mods folder: {path}",

    "packmeta.zip_no_manifest": "No usable manifest.json inside the zip: {path}",
    "packmeta.extracted_dir": "extracted folder ({name})",
    "packmeta.mods_dir": "mods folder ({name})",
    "packmeta.extracted_mods": "extracted folder ({name}/mods)",
    "packmeta.no_manifest": "Neither manifest.json nor mods/*.jar inside the folder: {path}",
    "provider.atm10.substitute_manifest": "ATM10 {actual} official pack (standing in for the "
                                          "unavailable {wanted})",

    "log.use_pack_source": "Using the specified pack manifest: {source}, {files} files / "
                           "{projects} projects",
    "log.startup": "[Startup] {text}",
    "status.no_check_yet": "Not checked yet",

    "common.list_separator": ", ",
    "stage.origin": "Verifying mod origins",
    "provider.cf.official_api": "CurseForge official API",
    "provider.cf.proxy": "CurseForge public proxy",
    "dialog.error.text": "Something went wrong:\n{error}\n\nThe full traceback is in .ATM10ModChecker/logs/latest.log.",
    "dialog.error_text_crash": "The main window could not be created. "
                               "See .ATM10ModChecker/logs/latest.log for details.",

    # 网络 / 远程 zip 的底层错误
    "net.timeout": "Request timed out",
    "remotezip.size_unknown": "Could not determine the modpack archive size",
    "remotezip.no_central_directory": "No zip central directory found (not a standard zip?)",
    "remotezip.broken": "Malformed zip structure",
    "remotezip.zip64": "ZIP64 modpack archives are not supported",
    "remotezip.central_directory_failed": "Failed to parse the zip central directory",
    "remotezip.unsupported_method": "Unsupported compression method {method}",
}

_ZH: dict[str, str] = {
    "app.title": "ATM10 模组更新检测器",
    "app.subtitle": "比对 mods 目录中的 jar 与 Modrinth / CurseForge 上的最新版本，"
                    "区分整合包自带与手动添加的模组，并可按需把选定模组更新到最新版本。",

    "button.browse": "浏览…",
    "button.start": "开始检测",
    "button.cancel": "取消",
    "button.settings": "设置",
    "button.pick_zip": "选择 zip…",
    "button.pick_dir": "选择目录…",
    "button.clear": "清除",
    "button.batch_update": "批量更新",
    "button.batch_update_n": "批量更新（{n}）",
    "button.export": "导出 CSV",
    "button.log": "日志",
    "placeholder.path": "选择 ATM10 安装目录（客户端 .minecraft 目录或服务端 ServerFiles 目录）",
    "placeholder.pack": "可选：整合包原始 zip，或原始 zip 解压后的纯净目录（留空则用实例自带的清单）",
    "placeholder.search": "搜索模组名 / 文件名 / modId",

    "label.pack": "整合包原包：",
    "chip.kind": "类型：-",
    "chip.mc": "Minecraft：-",
    "chip.loader": "加载器：-",
    "chip.pack": "整合包版本：-",
    "chip.index": "官方清单：-",
    "chip.kind_value": "类型：{value}",
    "chip.mc_value": "Minecraft：{value}",
    "chip.loader_value": "加载器：{value}",
    "chip.pack_value": "整合包版本：{value}",
    "chip.index_value": "官方清单：{version} / {items} 项",
    "chip.index_missing": "官方清单：未找到",
    "chip.index_unusable": "官方清单：未获取",
    "chip.index_bad_path": "官方清单：路径无效",
    "chip.index_source_specified": "指定来源：{source}",
    "chip.index_source_instance": "实例目录：{source}",
    "chip.index_items_tip": "{source}\n项目 {projects} 个，文件名 {names} 个，哈希 {hashes} 个",
    "banner.idle": "尚未检测",
    "banner.pack_update": "⚠ {message}　最新版发布于 {date}，共 {count} 个发行版",
    "banner.pack_current": "✓ {message}",
    "banner.pack_unknown": "无法获取整合包版本信息",
    "banner.pack_unknown_generic": "无法获取整合包版本信息",

    "filter.state.all": "全部状态",
    "filter.state.outdated": "可更新",
    "filter.state.current": "已最新",
    "filter.state.unknown": "未知",
    "filter.state.error": "查询失败",
    "filter.origin.all": "全部归属",
    "filter.origin.manual": "手动添加",
    "filter.origin.pack": "整合包自带",
    "filter.origin.unknown": "未知归属",
    "filter.only_updates": "只看可更新",

    "column.select": "",
    "column.state": "状态",
    "column.title": "模组",
    "column.origin": "归属",
    "column.installed": "当前版本",
    "column.installed_date": "当前发布时间",
    "column.latest": "最新版本",
    "column.latest_date": "最新发布时间",
    "column.source": "来源",
    "column.filename": "文件名",

    "state.outdated": "可更新",
    "state.current": "已最新",
    "state.unknown": "未知",
    "state.error": "查询失败",
    "change.major": "主版本更新",
    "change.minor": "次版本更新",
    "change.patch": "bug 修复更新",
    "change.build": "构建更新",
    "change.prerelease": "beta/alpha 更新",
    "change.unknown": "可更新",
    "origin.pack": "整合包自带",
    "origin.manual": "手动添加",
    "origin.unknown": "未知",
    "source.modrinth": "Modrinth",
    "source.curseforge": "CurseForge",
    "source.none": "未识别",
    "kind.client": "客户端",
    "kind.server": "服务器端",
    "kind.unknown": "未知",
    "kind.value": "类型：{value}",

    "status.ready": "就绪",
    "status.identified": "已识别 mods 目录：{path}（{count} 个 jar）",
    "status.read_failed": "读取目录失败：{error}",
    "status.checking": "检测中… 已显示 {count} 个模组",
    "status.checking_initial": "检测中…",
    "status.done": "检测完成，用时 {seconds:.1f} 秒",
    "status.cancelled": "已取消",
    "status.cancelled_partial": "已取消，已显示 {count} 个模组（未完成）",
    "status.failed": "检测失败",
    "status.failed_partial": "检测失败，已显示 {count} 个模组（未完成）",
    "status.cancelling": "正在取消…",
    "status.stopping_update": "正在停止更新…",
    "status.pack_loading": "正在获取整合包版本信息…",
    "status.exported": "已导出：{path}",
    "status.no_direct_link": "{title}：该文件没有可用的下载直链，请到项目页手动下载",
    "status.updating": "正在更新 {done}/{total}…",
    "status.updating_progress": "正在更新 {done}/{total}（成功 {ok}）",
    "status.progress": "{label}… {percent}%",
    "status.stage": "{label}… {done}/{total}",
    "status.stage_plain": "{label}…",

    "stats.total": "共 {n} 个模组",
    "stats.outdated": "可更新 {n}",
    "stats.current": "已最新 {n}",
    "stats.unknown": "未知 {n}",
    "stats.failed": "查询失败 {n}",
    "stats.manual": "手动添加 {n}",
    "stats.pack": "整合包自带 {n}",
    "stats.origin_unknown": "归属未知 {n}",
    "stats.empty": "—",

    "tip.state_click": "点击可更新到最新版本（会先弹窗确认，操作不可撤销）",
    "tip.version_link": "点击在浏览器打开版本发布页，查看发版说明",
    "tip.version_fallback": "点击在浏览器打开项目页面 / 站内搜索",
    "tip.failure": "失败原因：{reason}",
    "tip.file": "文件：{name}",
    "tip.project": "项目：{title}",
    "tip.installed": "当前版本：{version}",
    "tip.installed_date": "当前发布时间：{date}",
    "tip.latest": "最新版本：{version}",
    "tip.latest_date": "最新发布时间：{date}",
    "tip.mod_id": "modId：{mod_id}",
    "tip.origin": "归属依据：{detail}",
    "tip.note": "说明：{note}",
    "tip.link": "链接：{url}",

    "dialog.need_dir.title": "需要安装目录",
    "dialog.need_dir.text": "请先选择 ATM10 的安装目录。",
    "dialog.no_source.title": "没有可用的数据源",
    "dialog.no_source.text": "请至少启用一个数据源（Modrinth 或 CurseForge）。",
    "dialog.check_failed.title": "检测失败",
    "dialog.export_failed.title": "导出失败",
    "dialog.update.title": "确认更新模组",
    "dialog.update.text": "将把以下模组更新到最新版本：\n{names}",
    "dialog.update.more": "{names} 等 {count} 个模组",
    "dialog.update.irreversible": "此操作不可撤销！请务必先手动备份整个游戏实例"
                                  "（至少备份 mods 目录）。",
    "dialog.update.backup": "程序会用官方文件替换旧 jar，旧文件保留为 .bak 备份。",
    "dialog.update.breaking": "{names} 属于主版本 / 次版本更新，可能包含破坏性变更"
                              "（配置文件、注册表 ID、数据格式、API 等）。"
                              "建议先点击“最新版本”打开版本发布页阅读发版说明。",
    "dialog.update.unclear": "另有 {count} 个模组无法按版本号判断更新幅度，同样建议先查看发版说明。",
    "dialog.update.aware": "我已阅读相关发版说明，知晓更新可能带来的后果",
    "dialog.update.accept": "我已备份，开始更新",
    "dialog.update.cancel": "取消",
    "dialog.update_failed.title": "部分模组更新失败",
    "dialog.file.choose_dir": "选择 ATM10 安装目录",
    "dialog.file.choose_pack_zip": "选择整合包原始 zip",
    "dialog.file.zip_filter": "Zip 文件 (*.zip)",
    "dialog.file.choose_pack_dir": "选择整合包解压后的目录",
    "dialog.file.export": "导出检测结果",
    "dialog.file.csv_filter": "CSV 文件 (*.csv)",
    "dialog.error.title": "意外错误",

    "log.update_start": "[更新] 开始更新 {count} 个模组",
    "log.update_ok": "[更新] {title}：{message}",
    "log.update_failed": "[更新失败] {title}：{message}",
    "log.warning": "[警告] {text}",
    "log.query_failed_hint": "[提示] {count} 个模组查询失败，可稍后重试。",
    "log.notice": "[提示] {text}",
    "log.startup": "[启动] {text}",

    "csv.status": "状态",
    "csv.mod": "模组",
    "csv.origin": "归属",
    "csv.installed": "当前版本",
    "csv.installed_date": "当前发布时间",
    "csv.latest": "最新版本",
    "csv.latest_date": "最新发布时间",
    "csv.source": "来源",
    "csv.filename": "文件名",
    "csv.mod_id": "modId",
    "csv.link": "链接",
    "csv.note": "备注",

    "settings.title": "高级设置",
    "settings.language_box": "语言 / Language",
    "settings.language_label": "界面语言：",
    "settings.language_auto": "跟随系统",
    "settings.version_box": "版本基准（留空则自动识别）",
    "settings.mc_placeholder": "例如 1.21.1",
    "settings.mc_label": "Minecraft 版本：",
    "settings.loader_label": "模组加载器：",
    "settings.version_hint": "“最新版本”只在匹配的 MC 版本 + 加载器下查找，避免误报不兼容的更新。",
    "settings.source_box": "数据源",
    "settings.modrinth": "启用 Modrinth（无需 API Key，覆盖约 60%）",
    "settings.curseforge": "启用 CurseForge（补全识别与最新版本，覆盖率接近 100%）",
    "settings.key_label": "CurseForge API Key：",
    "settings.key_placeholder": "留空则使用公共只读代理 api.curse.tools",
    "settings.verify": "检测时构建官方模组清单（用于区分整合包自带 / 手动添加）",
    "settings.scan_box": "扫描",
    "settings.disabled": "同时检测被禁用的模组（*.jar.disabled）",
    "settings.concurrency": "网络并发数：",
    "settings.pack_box": "整合包原包（可选，用于精确判断自带 / 手动）",
    "settings.pack_placeholder": "整合包原始 zip，或原始 zip 解压后的纯净目录",
    "settings.hint": "提示：官方清单也会缓存，同一整合包版本只需解析一次；"
                     "清空缓存目录可强制刷新。",
    "settings.pick_zip": "选择整合包 zip",
    "settings.pick_dir": "选择整合包解压后的目录",

    "stage.scan": "扫描 mods 目录",
    "stage.identify": "识别模组来源",
    "stage.manifest": "构建官方模组清单",
    "stage.versions": "查询最新版本",
    "stage.wrapup": "整理检测结果",
    "stage.done": "检测完成",
    "log.install_dir": "安装目录：{path}",
    "log.version_base": "版本基准：Minecraft {mc} / {loader}",
    "log.jar_count": "共发现 {count} 个 jar",
    "log.disabled_jars": "注意：包含被禁用的 jar（.jar.disabled）",
    "log.modrinth_identified": "Modrinth 识别成功 {hit}/{total} 个",
    "log.cf_resolve": "CurseForge 补全识别：{count} 个",
    "log.cf_failures": "CurseForge 查询失败 {count} 个（已跳过）",
    "log.cf_identified": "CurseForge 识别成功 {count} 个",
    "log.cf_latest_failed": "CurseForge 最新版本查询失败（{project}）：{error}",
    "log.origin_lookup": "归属核验：{count} 个模组不在清单文件名中，改用 CurseForge 项目 ID 判定",
    "log.pack_source_used": "使用指定的整合包清单：{source}，共 {count} 项",
    "log.pack_candidate": "发现疑似整合包归档：{name}（未自动采用，建议手动指定为整合包原包）",
    "warn.pack_version_mismatch": "官方清单版本（{manifest}）与本地整合包版本（{local}）不一致，"
                                  "分类结果可能有偏差。",
    "note.no_project": "Modrinth / CurseForge 均未找到匹配的项目",
    "note.no_mr_version": "没有适用于 {mc} / {loader} 的 Modrinth 版本",
    "note.no_cf_version": "没有适用于 {mc} / {loader} 的 CurseForge 文件",
    "note.prerelease_blocked": "最新版本是 beta/alpha，已按稳定通道忽略",
    "note.prerelease_channel": "本地为预发布版本，按 beta/alpha 通道比较",
    "note.name_match": "按项目名关联，建议人工确认",
    "note.query_failed": "查询失败：{error}",
    "note.updated": "{message}",

    "official.local_source": "本地元数据",
    "official.local_manifest": "使用本地整合包清单：{files} 个文件 / {hashes} 个哈希"
                               "（{source}），无需联网解析",
    "official.cached_manifest": "复用已缓存的官方清单：ATM10 {version}（{count} 个模组）",
    "official.no_release": "没有找到 ATM10 {version} 的官方发行版，改用最新版 {latest} 的清单。",
    "official.archive_fallback": "ATM10 {version} 的官方归档不可用，已改用 {actual} 的清单，"
                                 "个别模组可能被误判为“手动添加”。",
    "official.manifest_source": "官方清单来源：{source}，共 {count} 个模组（自带文件名 {names} 个）",
    "official.no_manifest": "无法获取官方 manifest.json，无法判断模组归属。",
    "official.partial": "官方清单只解析出 {resolved}/{declared} 个文件名，分类结果可能不完整。",
    "official.origin_filename": "文件名在官方清单中",
    "official.origin_hash": "文件哈希在官方清单中",
    "official.origin_project": "项目 ID 在官方清单中",
    "official.origin_missing": "官方清单中不存在",
    "official.origin_unknown_no_index": "未能获取官方清单",
    "official.origin_unknown_generic": "无法判断",

    "provider.atm10.release_failed": "获取 ATM10 发行版列表失败：{error}",
    "provider.atm10.no_local_manifest": "本地 zip 中没有找到 manifest.json：{path}",
    "provider.atm10.remote_manifest_failed": "读取远端整合包清单失败（ATM10 {version}）：{error}",
    "provider.cf.project_failed": "CurseForge 项目查询失败（{id}）：{error}",
    "provider.cf.file_failed": "CurseForge 文件查询失败（{id}/{file}）：{error}",
    "provider.cf.files_failed": "CurseForge 文件列表查询失败（{id}）：{error}",
    "provider.cf.search_failed": "CurseForge 搜索失败（{term}）：{error}",
    "provider.mr.identify_failed": "Modrinth 批量识别失败：{error}",
    "provider.mr.projects_failed": "Modrinth 项目信息获取失败：{error}",
    "provider.mr.latest_failed": "Modrinth 最新版本查询失败，改用逐项目查询：{error}",
    "provider.mr.versions_failed": "Modrinth 版本列表获取失败（{id}）：{error}",

    "scan.dir_missing": "目录不存在：{path}",
    "scan.mods_missing": "在所选目录中没有找到 mods 文件夹（已尝试 mods、.minecraft/mods、"
                         "minecraft/mods）。",
    "packmeta.unparsable": "无法解析 {path}",
    "packmeta.not_zip_or_manifest": "既不是 zip 也不是 manifest.json：{path}",
    "packmeta.path_missing": "指定的整合包路径不存在：{path}",
    "packmeta.zip_source": "整合包 zip（{name}）",

    "update.not_outdated": "当前不是“可更新”状态",
    "update.no_direct_url": "该文件没有提供直接下载链接，请到项目页手动下载",
    "update.bad_filename": "下载文件名不是 jar：{name}",
    "update.target_exists": "目标文件已存在，未覆盖：{name}",
    "update.already_downloaded": "目标文件已存在且校验一致",
    "update.downloading": "下载 {title} → {name}",
    "update.size_mismatch": "文件大小不符（收到 {got} 字节，预期 {expected}）",
    "update.sha1_mismatch": "SHA-1 校验失败（{sha1}…）",
    "update.write_failed": "写入临时文件失败：{error}",
    "update.replace_failed": "替换文件失败：{error}",
    "update.done_with_backup": "已更新；旧文件备份为 {name}",
    "update.done": "已更新",
    "update.failed_prefix": "更新失败：{message}",
    "update.unexpected": "意外错误：{error}",

    # ------------------------------------------------------------------ 补充（1.1）
    "column.filename_disabled": "（已禁用）",
    "tip.batch_update": "勾选左侧复选框后可用：把所选模组更新到最新版本",
    "chip.index_source_tip": "来源：{source}",
    "chip.index_source_missing": "未找到可用清单",
    "chip.index_no_classify": "无法区分整合包自带与手动添加的模组",
    "chip.version_unknown": "未知版本",
    "chip.value_unknown": "未识别",
    "status.open_url_failed": "无法打开浏览器：{url}",
    "status.update_done": "更新完成：成功 {ok} 个",
    "status.update_cancelled_suffix": "，已取消（总计 {total} 个）",
    "status.update_failed_suffix": "，失败 {failed} 个（详见日志）",

    "pack.no_releases": "无法获取 ATM10 发行版列表",
    "pack.update_available": "整合包有更新：{installed} → {latest}（{date}）",
    "pack.up_to_date": "整合包已是最新版本 {version}",
    "pack.local_newer": "本地版本 {installed} 高于线上最新 {latest}（可能是测试版）",
    "pack.version_unknown": "未能识别整合包版本，线上最新为 {latest}",

    "warn.specified_version_diff": "指定清单的版本（{manifest}）与实例版本（{installed}）不一致，"
                                   "归属判断可能有偏差。",
    "warn.specified_overlap": "指定的原包就是当前实例本身（或实例内的目录），其中已经包含"
                              "手动添加的模组，无法区分归属；建议改选整合包原始 zip 或其解压目录。",
    "warn.specified_unreadable": "无法从指定路径读取整合包清单：{path}。",
    "warn.fallback_local": "已退回实例自带的清单或远程官方清单。",
    "warn.no_cf_manifest": "未启用 CurseForge，且本机没有可用的整合包清单，无法判断模组归属。",
    "warn.no_index": "无法建立官方模组清单，所有模组归属显示为“未知”。",
    "scan.no_jars": "mods 目录中没有找到 jar 文件：{path}",

    "packmeta.zip_no_manifest": "zip 中没有找到可用的 manifest.json：{path}",
    "packmeta.extracted_dir": "解压目录（{name}）",
    "packmeta.mods_dir": "mods 目录（{name}）",
    "packmeta.extracted_mods": "解压目录（{name}/mods）",
    "packmeta.no_manifest": "目录中没有找到 manifest.json 或 mods/*.jar：{path}",
    "provider.atm10.substitute_manifest": "ATM10 {actual} 官方包（代替无可用归档的 {wanted}）",

    "log.use_pack_source": "使用指定的整合包清单：{source}，{files} 个文件 / {projects} 个项目",
    "log.startup": "[启动] {text}",
    "status.no_check_yet": "尚未检测",

    "common.list_separator": "、",
    "stage.origin": "归属核验",
    "provider.cf.official_api": "CurseForge 官方 API",
    "provider.cf.proxy": "CurseForge 公共代理",
    "dialog.error.text": "操作失败：\n{error}\n\n完整堆栈见 .ATM10ModChecker/logs/latest.log。",
    "dialog.error_text_crash": "无法创建主窗口，详情见 .ATM10ModChecker/logs/latest.log。",

    # 网络 / 远程 zip 的底层错误
    "net.timeout": "请求超时",
    "remotezip.size_unknown": "无法获取整合包体积",
    "remotezip.no_central_directory": "未找到 zip 中央目录（可能不是标准 zip）",
    "remotezip.broken": "zip 结构异常",
    "remotezip.zip64": "不支持 ZIP64 整合包",
    "remotezip.central_directory_failed": "中央目录解析失败",
    "remotezip.unsupported_method": "不支持的压缩方式 {method}",
}

_CATALOG: dict[str, dict[str, str]] = {"en": _EN, "zh": _ZH}
