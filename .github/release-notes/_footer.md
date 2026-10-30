## 下载 / Download

| Platform | File | How to run |
| -------- | ---- | ---------- |
| Windows x64 | `ATM10ModChecker-windows-x64.exe` | 双击运行 / double-click |
| Windows x64 | `ATM10ModChecker-windows-x64.zip` | 解压后双击 `ATM10ModChecker.exe` |
| Linux x64 | `ATM10ModChecker-linux-x64.zip` | 解压后 `./ATM10ModChecker` |
| Linux x64 | `ATM10ModChecker-linux-x64` | `chmod +x` 后运行 / `chmod +x`, then run it |

程序已自带 Python 与 Qt 运行库，无需安装任何依赖（自包含单文件）。
The executable bundles Python and Qt, so no extra dependencies are needed.

设置、缓存与日志都写在程序旁边的 `.ATM10ModChecker` 目录里，删掉它即完成卸载。
Settings, cache and logs live in `.ATM10ModChecker` next to the executable; deleting it uninstalls
the app.

> **Personal hobby project / 个人兴趣项目**：mostly built together with AI assistants,
> not rigorously tested, and only validated against the All the Mods 10 pack.
> 请先备份实例再使用；其它整合包与原版实例未经验证。
> Licensed under AGPL-3.0-or-later — full text in the `LICENSE` file inside each archive.

## 构建溯源 / Build provenance

所有附件都附带 GitHub Artifact Attestation（SLSA build provenance）。
Every asset ships with a GitHub Artifact Attestation, verifiable with the GitHub CLI:

```bash
gh attestation verify ATM10ModChecker-windows-x64.exe --repo {{repository}}
gh attestation verify ATM10ModChecker-linux-x64.zip --repo {{repository}}
```
