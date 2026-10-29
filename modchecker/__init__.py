"""ATM10 模组更新检测器。

只做检测：比对本地 mods 目录中的 .jar 与公开模组源（Modrinth / CurseForge）的
最新可用版本，并区分哪些模组来自整合包、哪些是手动添加的。
"""

from __future__ import annotations

__version__ = "1.0.0"
APP_NAME = "ATM10 模组更新检测器"
APP_ID = "ATM10ModChecker"
