"""樱响（SakuraSound）发行包构建脚本（Linux 上跑，产出 Windows 可用的包）。

产出：
  SakuraSound-Portable-v1.0.0.zip —— 便携包：内嵌 Python + 预装依赖，解压双击即用
  SakuraSound-Setup-v1.0.0.exe    —— 安装包（需 makensis）：装到用户目录，带快捷方式与卸载
                              （本版不带均衡器、不带音频驱动插件，只做响度均衡）

Qt 桌面版：双击 SakuraSound.exe 打开原生程序窗口（不再是网页），
启动器与 Qt 程序都无黑窗口，关闭窗口后缩到托盘。

内嵌 Python 说明：python.org 的 embeddable 包（3.12.10）+ 纯 Python 轮子
（pycaw、comtypes）+ psutil 的 Windows 预编译轮子 + ctypes 版 winreg 替代
+ PySide6-Essentials / shiboken6 的 Windows 预编译轮子（Qt 界面）。
"""

import glob
import math
import os
import shutil
import struct
import subprocess
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
STAGING = os.path.join(HERE, "staging", "SakuraSound")
EMBED_ZIP = os.path.join(HERE, "python-3.12.10-embed-amd64.zip")


# ---------------------------------------------------------------- 图标
# 正式图标：项目根目录 sakura.ico（由定稿 webp 多尺寸生成，16/32/48/256），
# 不再用旧深色喇叭图标生成逻辑；QSS 用的小樱花 sakura_icon.png 是另一张
# 小图（下拉箭头/滑杆手柄），绝不能用它覆盖正式图标。

# ---------------------------------------------------------------- 组装

def clean_staging():
    staging_root = os.path.join(HERE, "staging")
    if os.path.isdir(staging_root):
        shutil.rmtree(staging_root)
    os.makedirs(STAGING)


def build_staging():
    clean_staging()
    # 1. 内嵌 Python
    with zipfile.ZipFile(EMBED_ZIP) as z:
        z.extractall(os.path.join(STAGING, "python"))
    py_dir = os.path.join(STAGING, "python")
    # 2. 预装依赖轮子（pycaw / comtypes / psutil）+ Qt 轮子（PySide6 / shiboken6）
    for whl in sorted(glob.glob(os.path.join(HERE, "wheels", "*.whl"))):
        with zipfile.ZipFile(whl) as z:
            z.extractall(py_dir)
    for whl in sorted(glob.glob(os.path.join(HERE, "wheels-qt", "*.whl"))):
        with zipfile.ZipFile(whl) as z:
            z.extractall(py_dir)
    # 3. ctypes 版 winreg（内嵌包没有 winreg.pyd）
    shutil.copy(os.path.join(HERE, "winreg.py"), os.path.join(py_dir, "winreg.py"))
    # 4. 程序文件（Qt 桌面版 + 核心 + 引擎模块），跳过 __pycache__。
    # 注意：均衡器已删，不再拷 peq.py，也不再附带音频驱动安装包（代码见 archive/，以后版本可再接回来）。
    # 注意：只拷 web/server.py，不拷 web 的三个静态文件（index.html/app.js/style.css）——
    # Qt 包里引擎是直接 import 的，网页前端用不上，打进去只是白占体积。
    shutil.copy(os.path.join(PROJECT, "volrider_core.py"), os.path.join(STAGING, "volrider_core.py"))
    shutil.copy(os.path.join(PROJECT, "qt_app.py"), os.path.join(STAGING, "qt_app.py"))
    # 樱花图标：QSS 里下拉箭头、滑杆手柄用 image: url(sakura_icon.png) 引用，
    # 按钮图标也用它，必须跟 qt_app.py 同目录，否则真机上图标会丢。
    shutil.copy(os.path.join(PROJECT, "sakura_icon.png"), os.path.join(STAGING, "sakura_icon.png"))
    # 正式应用图标 + 樱花树预设图：跟 qt_app.py 同目录，make_icon() 与树预设靠它们找文件。
    shutil.copy(os.path.join(PROJECT, "sakura.ico"), os.path.join(STAGING, "sakura.ico"))
    shutil.copy(os.path.join(PROJECT, "sakura-tree-cool.png"), os.path.join(STAGING, "sakura-tree-cool.png"))
    # 圆体字体：跟 qt_app.py 同目录，程序启动时用 QFontDatabase 加载，否则真机上没圆体。
    shutil.copy(os.path.join(PROJECT, "ZCOOLKuaiLe-Regular.ttf"), os.path.join(STAGING, "ZCOOLKuaiLe-Regular.ttf"))
    os.makedirs(os.path.join(STAGING, "web"), exist_ok=True)
    shutil.copy(os.path.join(PROJECT, "web", "server.py"), os.path.join(STAGING, "web", "server.py"))
    for name in ("VERSION.txt", "LICENSE", "ThirdPartyLicenses.txt"):
        shutil.copy(os.path.join(PROJECT, name), os.path.join(STAGING, name))
    with open(os.path.join(STAGING, "README.txt"), "w", encoding="utf-8") as f:
        f.write(
            "樱响 SakuraSound v1.0.0 使用说明\n"
            "双击 SakuraSound.exe 即可打开桌面程序窗口（不需要浏览器、不需要装 Python）。\n"
            "本版只做系统响度均衡，不带均衡器，也不需要安装任何音频驱动插件。\n"
        "界面为浅色玻璃＋樱花风，字体为内置站酷快乐体圆体。\n"
            "想调音色请用各播放器自带的音效。\n"
            "关闭窗口后程序缩到右下角托盘：右键托盘图标 → 退出，才是真正退出。\n"
            "开机自启动在程序里勾选。卸载（安装版）：控制面板 → 程序 → 樱响 → 卸载。\n"
        )
    # 5. 图标：正式 sakura.ico 复制为安装器/启动器用的 icon.ico（不重新生成旧图标）。
    shutil.copy(os.path.join(PROJECT, "sakura.ico"), os.path.join(STAGING, "icon.ico"))
    # 6. 备用启动 bat（没有 exe 时也能双击用；start 让 cmd 窗口立即消失）
    with open(os.path.join(STAGING, "SakuraSound.bat"), "w", encoding="utf-8") as f:
        f.write("@echo off\r\ncd /d %~dp0\r\nstart \"\" python\\pythonw.exe qt_app.py\r\n")
    return py_dir


def build_launcher():
    gcc = shutil.which("x86_64-w64-mingw32-gcc")
    windres = shutil.which("x86_64-w64-mingw32-windres")
    if not gcc:
        print("未找到 mingw，跳过 SakuraSound.exe 编译（可用 SakuraSound.bat 启动）")
        return False
    work = os.path.join(HERE, "launcher_build")
    os.makedirs(work, exist_ok=True)
    shutil.copy(os.path.join(STAGING, "icon.ico"), os.path.join(work, "icon.ico"))
    shutil.copy(os.path.join(HERE, "launcher.rc"), os.path.join(work, "launcher.rc"))
    objs = []
    if windres:
        # windres 输出 .o（COFF 对象）才能被 ld 链接；.res 格式链接器不认。
        # 在 work 目录里跑，让它找到同目录的 icon.ico。
        subprocess.run([windres, "launcher.rc", "-o", "launcher.o"], cwd=work, check=True)
        objs.append(os.path.join(work, "launcher.o"))
    cmd = [gcc, "-mwindows", "-municode", os.path.join(HERE, "launcher.c")] + objs + ["-lshell32", "-o", os.path.join(STAGING, "SakuraSound.exe")]
    subprocess.run(cmd, check=True)
    print("SakuraSound.exe 已编译")
    return True


def build_portable_zip():
    out = os.path.join(PROJECT, "SakuraSound-Portable-v1.0.0.zip")
    if os.path.exists(out):
        os.remove(out)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for root, _dirs, files in os.walk(STAGING):
            for name in files:
                full = os.path.join(root, name)
                arc = os.path.join("SakuraSound", os.path.relpath(full, STAGING))
                z.write(full, arc)
    return out


def build_installer():
    makensis = shutil.which("makensis")
    if not makensis:
        print("未找到 makensis，跳过安装包（可用便携包）")
        return None
    out = os.path.join(PROJECT, "SakuraSound-Setup-v1.0.0.exe")
    if os.path.exists(out):
        os.remove(out)
    subprocess.run([makensis, os.path.join(HERE, "installer.nsi")], cwd=HERE, check=True)
    # makensis 的 OutFile 是相对路径，落在 HERE
    built = os.path.join(HERE, "SakuraSound-Setup-v1.0.0.exe")
    if os.path.exists(built):
        shutil.move(built, out)
    return out


def main():
    build_staging()
    print("staging 已组装：", STAGING)
    build_launcher()
    portable = build_portable_zip()
    print("便携包：%s（%.1f MB）" % (portable, os.path.getsize(portable) / 1048576))
    installer = build_installer()
    if installer and os.path.exists(installer):
        print("安装包：%s（%.1f MB）" % (installer, os.path.getsize(installer) / 1048576))
    print("完成。staging 树：")
    for root, dirs, files in os.walk(STAGING):
        level = root.replace(STAGING, "").count(os.sep)
        if level > 2:
            dirs[:] = []
            continue
        print("  " + os.path.relpath(root, STAGING) + "/  " + ", ".join(sorted(files)[:12]))


if __name__ == "__main__":
    main()
