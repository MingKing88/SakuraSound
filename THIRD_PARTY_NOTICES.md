# 第三方声明

樱响自身代码采用 MIT 许可证（见 LICENSE，Copyright © 2026 YearnRiver）。

## 开源依赖（仅列实际用到的）

- pycaw（MIT，Copyright 2016 AndreMiras）—— Windows Core Audio 会话接口。
- PySide6 / Shiboken6 / Qt（LGPL-3.0-only 或 GPL-2.0-only 或 GPL-3.0-only，The Qt Company）—— 桌面界面框架。
- comtypes（MIT 风格许可，Copyright Thomas Heller 及 Comtypes Developers）—— pycaw 的 COM 底层。
- psutil（BSD-3-Clause）—— 进程信息辅助。

以上第三方代码仍归各自作者、遵循各自许可证，本项目的 MIT 只覆盖樱响自身代码，不把第三方说成自己的，也不改写第三方的许可。发行包里各依赖的许可证文本已随包附带；源码仓库本身不分发这些依赖（用户 `pip install -r requirements.txt` 自行安装）。

## 字体与素材

- 站酷快乐体（ZCOOL KuaiLe）—— OFL 开源字体，内置于发行包，用于界面圆体显示。
- 樱花树背景图与樱花图标为本项目原创生成素材，随本项目 MIT 许可分发。

## 已移除的第三方

2026-10-25 起，本程序不再附带任何第三方音频软件：均衡器与音频驱动联动已整块删掉，发行包里没有驱动安装包，也不会读写驱动的配置文件。以前单独装过的驱动是你自己的软件，与樱响相互独立，卸载樱响时不动它。
