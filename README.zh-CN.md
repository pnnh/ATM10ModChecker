# ATM10 模组更新检测器

[English](README.md) | **简体中文**

[![Release](https://img.shields.io/github/v/release/pnnh/mcmodchecker)](https://github.com/pnnh/mcmodchecker/releases)
[![Release workflow](https://github.com/pnnh/mcmodchecker/actions/workflows/release.yml/badge.svg)](https://github.com/pnnh/mcmodchecker/actions/workflows/release.yml)
[![License: AGPL v3+](https://img.shields.io/badge/license-AGPL--3.0--or--later-blue)](LICENSE)

一个桌面工具：把 **All the Mods 10（ATM10）** 整合包实例里的每一个模组与公开模组仓库比对，
告诉你哪些模组可以更新，并区分哪些是整合包自带的、哪些是你自己手动添加的。

程序以**自包含单文件可执行程序**发布 —— Python 与 Qt 运行时全部打包在内，无需安装任何依赖。

> ### 请先读这里
>
> 这是一个**个人兴趣项目**，绝大部分代码是与 AI 协作完成的，**没有经过严谨测试**，
> 最初只是因为我自己和几个朋友用得上才做出来。请你在了解风险的前提下使用。
>
> - **务必先备份实例** —— 至少把 `mods` 目录复制一份 —— 再让程序去替换文件。
>   更新逻辑是按“可回滚”设计的，但请不要仅凭这句话就放心。
> - **适用范围**：目前只针对 **All the Mods 10** 整合包（NeoForge 1.21.1）做过验证。
>   其它整合包、其它 Minecraft 版本、以及原版 / Fabric / Forge 实例**都没有测试过**，
>   版本识别、归属判定和更新建议在这些环境下可能是错的，也可能完全不可用。
> - 不提供任何形式的担保。具体条款见 [`LICENSE`](LICENSE)（AGPL-3.0-or-later）。
> - **只收 Issue**：没有支持承诺，也不接受外部贡献，详见 [反馈与贡献](#反馈与贡献)。

## 界面截图

| English | 简体中文 |
| --- | --- |
| <img src="screenshots/ScreenShot.png" alt="English UI" width="620"> | <img src="screenshots/ScreenShot.zh-CN.png" alt="简体中文界面" width="620"> |

---

## 功能特性

| | |
| --- | --- |
| **一键体检** | 选中整合包实例目录（或 `mods` 目录），一次性扫描其中所有 `*.jar`。 |
| **按哈希识别** | 通过 SHA-1 在 Modrinth 与 CurseForge 上匹配模组，改过名的 jar 也能正确识别。 |
| **更新检测** | 与“支持当前 MC 版本 / 加载器的最新版本”比对，并给出跨度等级（大版本 / 次版本 / 补丁 / 构建）。 |
| **归属判定** | 读取 ATM10 官方 `manifest.json`，把每个模组标记为**整合包自带**或**手动添加**，一眼看出“多装了什么”。 |
| **安全的批量更新** | 勾选任意数量模组批量下载替换，全程校验并在失败时回滚。 |
| **排序、筛选、搜索** | 按状态 / 归属筛选，按名称搜索，任意列排序，点击版本号直达更新日志页面。 |
| **导出 CSV** | 把整份报告（状态、版本、日期、来源、链接、备注）导出为表格。 |
| **中英双语界面** | 英文 / 简体中文，默认跟随系统语言，运行中可随时切换。 |
| **日志切片** | 诊断信息写入可执行文件旁的 `.ATM10ModChecker/logs/latest.log`，按天归档；从终端启动时同步输出到控制台。 |

---

## 下载与运行

前往 [Releases](https://github.com/pnnh/mcmodchecker/releases) 页面下载最新构建。

程序是**便携**的：设置、缓存与日志都放在可执行文件旁边自动创建的 `.ATM10ModChecker` 目录里，
放到哪里都能用，删掉也不留痕迹 —— 详见 [文件位置与卸载](#文件位置与卸载)。

### Windows（x64）

1. 下载 `ATM10ModChecker-windows-x64.exe`（也可以下载 `.zip` 压缩包）。
2. 双击运行。无需安装、无需 Python、无需管理员权限。

### Linux（x64）

1. 下载 `ATM10ModChecker-linux-x64.zip` 并解压。
2. 运行：

   ```bash
   chmod +x ATM10ModChecker
   ./ATM10ModChecker
   ```

   > 也可以直接下载 `ATM10ModChecker-linux-x64` 单文件，但 Release 下载会丢失可执行位，
   > 记得先 `chmod +x`。

### 校验构建溯源

所有附件都由 GitHub Actions 构建，并附带
[Artifact Attestation](https://docs.github.com/actions/using-artifact-attestations)
（SLSA 构建溯源），可以证明该二进制确实由本仓库构建得出：

```bash
gh attestation verify ATM10ModChecker-windows-x64.exe --repo pnnh/mcmodchecker
gh attestation verify ATM10ModChecker-linux-x64.zip  --repo pnnh/mcmodchecker
```

### 从源码运行

```bash
git clone https://github.com/pnnh/mcmodchecker.git
cd mcmodchecker
python -m venv .venv && source .venv/bin/activate    # Windows：.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

需要 Python 3.10+（推荐 3.12），唯一的依赖是 `PySide6-Essentials`。

---

## 使用说明

1. 点击 **浏览…** 选择整合包实例目录。程序会自动探测 `mods/`、`manifest.json`、
   `minecraftinstance.json`、`modlist.html` 以及 NeoForge 的 `libraries/` 结构，
   选中实例根目录即可；如果启动时带了路径参数，会自动填入。
2. *（可选）* **选择整合包原包** —— 原始 ATM10 `.zip` 或解压后的纯净目录。
   这是判断“哪些模组属于整合包”最可靠的方式；不指定时会先看本地元数据，
   再退而远程读取官方 zip 内的 `manifest.json`（HTTP 范围请求，仅几百 KB）。
3. 点击 **开始检测**，结果会边查边显示。
4. 查看表格后，勾选若干行点 **更新所选**，或直接点击单个模组的状态单元格只更新它。
5. **导出 CSV** 保存报告。

### 各列含义

| 列 | 含义 |
| --- | --- |
| ☑ | 行选择；表头复选框可全选所有“可更新”的模组。 |
| 状态 | 已最新 / 大版本更新 / 次版本更新 / 补丁更新 / 构建更新 / 未知 / 查询失败。 |
| 模组 | 项目名称，取不到时退回模组 ID 或文件名。 |
| 归属 | *整合包自带* 或 *手动添加*。 |
| 当前版本 / 最新版本 | 版本号及对应发布时间，点击可打开更新日志。 |
| 来源 | Modrinth、CurseForge 或未识别。 |
| 文件名 | 磁盘上的 jar 文件名。 |

把鼠标停在某一行上会显示完整信息（项目、ID、日期，以及查询失败的具体原因）。

### 更新做了些什么

对每个被选中的模组，程序会：

1. 从官方 CDN 下载文件（限速、可取消）；
2. 校验 SHA-1 与预期文件大小；
3. 先写成 `mods/` 下的临时 `.part` 文件；
4. 把旧 jar 改名为 `*.bak`，再原子替换为新文件；
5. 任何一步失败都会把 `.bak` 改回去，绝不会留下半个损坏的模组。

确认对话框会列出所有将被替换的模组，并强制你勾选确认那些**跨大版本**的更新。
旧 jar 会以 `.bak` 保留在磁盘上，确认没问题后可以自行删除。

---

## 设置

从工具栏打开 **设置**：

| 设置项 | 说明 |
| --- | --- |
| 界面语言 | *跟随系统*（默认）、English、简体中文。立即生效，无需重启。 |
| Minecraft / 加载器 | 留空自动探测（兜底为 1.21.1 / NeoForge）。 |
| Modrinth / CurseForge | 分别启用或停用某个来源。 |
| CurseForge API Key | 可选。不填则使用公共只读代理（`api.curse.tools`）。 |
| 扫描已禁用模组 | 同时扫描 `*.jar.disabled`。 |
| 并发数 | 并行请求数量（默认 6），遇到限流可以调小。 |
| 整合包原包 | 用于归属判定的原始整合包 zip / 解压目录。 |

设置文件保存在**可执行文件旁边**的 `.ATM10ModChecker` 目录里：

- Windows：`ATM10ModChecker.exe` 同级的 `.ATM10ModChecker\settings.json`
- Linux / macOS：可执行文件同级的 `.ATM10ModChecker/settings.json`

只要程序目录可写，就不会往 `%APPDATA%`、用户主目录或注册表里写任何东西，所以删掉这一个
目录就彻底干净了，详见 [文件位置与卸载](#文件位置与卸载)。

### 关于语言

首次启动会按操作系统语言选择：系统语言为中文时使用简体中文，否则使用英文。
之后可以在设置对话框顶部的语言下拉框中随时切换，整个界面会立即重新翻译。

---

## 日志

所有诊断信息写入可执行文件旁的 `.ATM10ModChecker/logs` 目录：

```
ATM10ModChecker.exe
.ATM10ModChecker/
  settings.json                    # 你的设置
  cache/                           # 接口响应缓存
  logs/
    latest.log                     # 当前会话，始终保持最新
    ATM10ModChecker-2026-10-29.log # 历史日志，保留最近 30 天
```

- `latest.log` **永远**是最新的日志；跨天后旧内容会被改名为
  `ATM10ModChecker-YYYY-MM-DD.log`，并重新创建 `latest.log`。
- 只记录 `INFO` 及以上级别（Info / Warning / Error / Critical），包括 Qt 自身的告警、
  主线程与工作线程里所有未捕获的异常。
- 程序目录不可写（只读目录、沙箱环境）时，设置、缓存与日志会一起退回到用户目录：
  Windows 用 `%APPDATA%\ATM10ModChecker`，Linux 用 `~/.local/state/ATM10ModChecker`，
  macOS 用 `~/Library/Application Support/ATM10ModChecker`。
- 从终端启动时同样的内容会同步输出到标准输出 —— Windows 上也不例外，
  窗口程序会自动附着到父进程的控制台。

反馈问题时请附上 `.ATM10ModChecker/logs/latest.log`。

---

## 文件位置与卸载

程序产生的全部数据都放在**可执行文件旁边**的一个目录里：

```
ATM10ModChecker.exe                # Linux / macOS 下是可执行文件本体
.ATM10ModChecker/
  settings.json                    # 语言、API Key、上次目录、整合包原包……
  cache/                           # 接口响应缓存，随时可以删
  logs/                            # latest.log + 最近 30 天的归档
```

所以卸载只需要几秒钟：

1. 关闭程序；
2. 删除可执行文件；
3. 删除同一目录下的 `.ATM10ModChecker` 目录。

没有安装程序、没有注册表项、没有服务、没有开机自启，`%APPDATA%` 和主目录里也不会留下
任何东西 —— 前提是程序所在目录本身可写。

几点说明：

- **程序不会自己去改你的游戏实例。** 只有你按下更新按钮时它才会写 `mods/` 目录，
  留下的痕迹就是被替换 jar 旁边的 `*.bak` 文件；想彻底干净就把它一并删掉。
- **可执行文件在哪个目录，数据就在哪个目录。** 放在下载目录里的旧副本有自己的一套设置；
  如果你把 exe 挪到别处，记得把 `.ATM10ModChecker` 一起搬过去，否则程序会当作首次运行。
- **只读位置。** 如果程序目录不可写（例如装在 `C:\Program Files`，或直接从挂载的磁盘镜像
  里运行），数据会退回到 [日志](#日志) 一节列出的用户目录。这种情况下那个目录也要一并删除；
  想要“便携”效果就把可执行文件放到可写的位置。
- **从旧版本升级**：旧版本把设置放在用户目录，首次启动时会把旧 `settings.json` 复制一份
  到新位置，旧目录原样保留，不需要的话自行删除。
- 卸载不会回滚你已经更新过的模组，也不会改动整合包本身。

---

## 数据与隐私

程序只会访问以下主机，且仅用于识别模组和获取整合包清单：

- `api.modrinth.com` —— 哈希查询与版本元数据；
- `api.curseforge.com` / `api.curse.tools` —— CurseForge 查询（未填 API Key 时走公共代理）；
- `api.cfwidget.com` 与 ATM10 的 CDN 主机 —— 整合包版本列表与 `manifest.json`。

没有遥测、不需要账号、不上传任何数据。响应会缓存在可执行文件旁的 `.ATM10ModChecker/cache`，
再次检测时更快，也不会频繁冲击 API。

> 限流：Modrinth 限制每 IP 每分钟 300 次请求；程序对 Modrinth 最多 4 次/秒、
> CurseForge 最多 6 次/秒，并在遇到 HTTP 429 时按 `Retry-After` 退避重试。

---

## 构建与发布

仓库自带 [release 工作流](.github/workflows/release.yml)，推送符合语义化版本的 tag
（`v1.1.0`、`v1.2.0-rc1` 等）即自动触发，流程为：

1. 校验 tag 与 `modchecker/__init__.py` 中的 `__version__` 是否一致；
2. 在 Windows 与 Ubuntu 22.04 上用 PyInstaller 构建 `--onefile` 单文件程序；
3. 用 `--version` 冒烟测试打包后的可执行文件；
4. 为可执行文件与压缩包生成 Artifact Attestation；
5. 发布 GitHub Release，附带 `ATM10ModChecker-windows-x64.exe`、
   `ATM10ModChecker-linux-x64.zip` 等附件。

发布步骤：

```bash
# 先修改 modchecker/__init__.py 里的版本号
git tag v1.1.0
git push origin v1.1.0
```

本地手动打包：

```bash
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean --onefile --name ATM10ModChecker main.py
# Windows 上再加 --windowed，避免弹出控制台窗口
```

### 命令行

```bash
ATM10ModChecker             # 打开图形界面
ATM10ModChecker /path/mods  # 打开界面并预选目录
ATM10ModChecker --version   # 输出版本号后退出
```

---

## 目录结构

```
main.py                    # 入口：日志、致命错误兜底、启动 Qt
modchecker/
  logging_setup.py         # latest.log + 按天切片 + 控制台同步
  i18n.py                  # 中英文文案表
  appconfig.py             # 设置与缓存路径
  scanner.py               # 实例探测、jar 扫描、SHA-1 计算
  checker.py               # 主流程：识别 → 清单 → 查新 → 归类
  official.py              # 官方清单索引与归属判定
  packmeta.py              # manifest / modlist / minecraftinstance 解析
  updater.py               # 带校验与回滚的模组替换
  versioning.py            # 版本比较与跨度等级
  remotezip.py、net.py、cache.py、jarinfo.py
  providers/               # Modrinth、CurseForge、ATM10 客户端
  ui/                      # PySide6 主窗口、表格模型、工作线程、设置对话框
```

---

## 已知限制

- **只支持 ATM10。** 识别逻辑、官方清单处理和归属判定都是围绕 NeoForge 1.21.1 上的 ATM10
  整合包写的。其它整合包、其它 Minecraft 版本、以及原版 / Fabric / Forge 实例都没有测试过，
  版本识别与归属判定很可能不准，或者直接显示为“未知”。
- **个人项目，测试有限。** 仓库没有自动化测试，CI 里也只有冒烟测试。对于冷门模组、
  非常规目录结构、以及限流情况下的行为，都没有做过穷尽验证，也没有走过任何检查清单。
  请把每次更新都当成一次实验：先备份，谨慎使用。
- **仅 CurseForge 分发的模组**：部分文件不提供公开下载地址，这类模组会被标记为可更新，
  但没有直链，程序会改为跳转到文件页面。
- **Modrinth / CurseForge 之外的模组**（私有、自编译、已弃坑的 jar）无法识别，
  会显示为“未识别”，程序绝不会改动它们。
- **离线**只能看到已缓存的内容 —— 识别与查新都需要网络。

---

## 反馈与贡献

这是个人项目，**不接受外部贡献，请不要提交 Pull Request**。评审和维护别人写的补丁要花
的时间远超我在这类兴趣工具上愿意投入的精力，PR 会被直接关闭、不做评审。

- **欢迎提 Issue**：可以反馈可复现的问题，也可以提建议 —— 但请理解，建议可能永远不会实现。
- 反馈崩溃时请附上 `.ATM10ModChecker/logs/latest.log`，并说明 `ATM10ModChecker --version`
  的输出。
- 代码采用 AGPL-3.0-or-later：如果你需要改动，完全可以直接 fork 一份自己维护。

---

## 开源协议

Copyright (C) 2026 pnnh。

本项目是自由软件，采用
**[GNU Affero 通用公共许可证第 3 版或更新版本](LICENSE)**（`AGPL-3.0-or-later`）。简而言之：

| | |
| --- | --- |
| 你可以 | 运行、学习、修改并再分发，也包括商业用途。 |
| 你必须 | 继续以 AGPL 授权，分发修改版时公开源代码；并且由于 AGPL 第 13 条，如果你的修改版通过网络向他人提供服务，需要向这些用户提供源码。 |
| 本项目 | **不提供任何担保**，也不对实例损坏、模组丢失等后果承担责任。 |

之所以选 AGPL 而不是 MIT / Apache，是因为这类工具很容易被人改造后包装成服务；AGPL 能保证
被改造的版本同样保持开源。Qt 采用 LGPL-3.0，与 AGPL-3.0 兼容，可以组合进同一个作品中。

打包进发布程序的三方组件 —— PySide6 / Qt（LGPL-3.0）、CPython（PSF-2.0）、
PyInstaller 引导程序（GPL-2.0 及引导程序例外条款）—— 均已在
[`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md) 与 [`licenses/`](licenses/) 中
连同完整协议原文一并说明。
