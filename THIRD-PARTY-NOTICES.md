# Third-party notices

ATM10 Mod Checker itself is licensed under the **GNU Affero General Public License,
version 3 or (at your option) any later version** — see [`LICENSE`](LICENSE).

```
Copyright (C) 2026 pnnh

This program is free software: you can redistribute it and/or modify it under the terms of
the GNU Affero General Public License as published by the Free Software Foundation, either
version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU Affero General Public License for more details.
```

The release builds bundle a few third-party components. Their licenses are reproduced below
so that every download is self-contained with respect to attribution requirements.

---

## Components bundled in the released executables

| Component | Version | License | Role |
| --- | --- | --- | --- |
| PySide6-Essentials (Qt for Python) | ≥ 6.6 | **LGPL-3.0** (or GPL-3.0 / commercial) | GUI toolkit |
| Qt 6 (QtCore, QtGui, QtWidgets and their dependencies) | 6.x | **LGPL-3.0** | Shipped as shared libraries inside the bundle |
| shiboken6 | 6.x | **LGPL-3.0** | Python/C++ binding layer of PySide6 |
| CPython | 3.12 | **PSF-2.0** | Python interpreter |
| PyInstaller bootloader | 6.x | **GPL-2.0-or-later with the PyInstaller bootloader exception** | Self-extracting launcher |

Full license texts:

- [`licenses/LGPL-3.0.txt`](licenses/LGPL-3.0.txt) — GNU Lesser General Public License v3
- [`licenses/GPL-3.0.txt`](licenses/GPL-3.0.txt) — GNU General Public License v3 (the base of LGPLv3)
- [`LICENSE`](LICENSE) — GNU Affero General Public License v3

### Qt / PySide6 (LGPL-3.0)

Qt and PySide6 are **not** covered by this project's AGPL license. They are used unmodified,
dynamically linked, and can be replaced:

- The complete source of this application is available in this repository, and the exact
  commands used to produce the release build are documented in
  [`.github/workflows/release.yml`](.github/workflows/release.yml). You may rebuild the
  application against any compatible Qt build you prefer.
- If you need a bundle whose Qt libraries can be swapped out file by file, rebuild with
  `pyinstaller --onedir` instead of `--onefile`; the resulting directory exposes the Qt
  libraries as ordinary shared objects.
- The Qt source code is available at <https://download.qt.io/official_releases/qt/>.

Neither this project nor its author is affiliated with The Qt Company, Mojang Studios,
CurseForge, Modrinth, or the All the Mods team.

---

## Build-time tools (not redistributed inside the executable as a separable component)

| Tool | License |
| --- | --- |
| PyInstaller | GPL-2.0-or-later with the bootloader exception (only the bootloader ends up in the binary) |
| pip / setuptools | MIT |
| GitHub Actions runner software | see each action's own repository |

The PyInstaller bootloader exception explicitly permits bundling applications under
licenses of the author's choosing, so shipping an AGPL-licensed application this way is
allowed.

---

## Data, trademarks and services

- **Minecraft** is a trademark of Mojang Studios / Microsoft. **All the Mods 10** is a modpack
  by the ATM team. This project is an unofficial, unaffiliated third-party tool.
- The app queries the public **Modrinth**, **CurseForge** and **CFWidget** APIs. It only reads
  metadata and download URLs; it does **not** redistribute mod jars, modpack archives,
  textures, or any other game content. Downloading a mod file is a direct transfer between
  your machine and the platform's own CDN, subject to that platform's terms of service.
- No API keys, credentials, or user data are shipped or collected by this project.

---

## No warranty

These components are provided "as is", without warranty of any kind, to the extent permitted
by applicable law. See the individual license texts above for the exact wording.
