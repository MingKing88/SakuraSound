; 樱响 SakuraSound 安装包（NSIS 脚本，在 Linux 上用 makensis 编译即可产出 Windows 安装程序）
; 安装到当前用户目录，无需管理员权限；带开始菜单与桌面快捷方式、卸载程序。
; 安装时默认写开机自启动（HKCU Run 键，值名 SakuraSound，指向安装目录的启动器），
; 应用里开机自启动开关首次打开即显示开，关掉开关即删掉该 Run 值；卸载时也删掉它。
; 本版不带均衡器、不带音频驱动插件；以前单独装过的音频驱动是你自己的软件，卸载时不动它。
; 卸载注意：
;   - 卸载程序正在运行删不掉自己：原进程把自己复制到 $TEMP（改名区分），
;     启动副本后退出；副本按注册表里的真安装目录卸载，最后留一个一次性
;     批处理等副本退出后删掉副本自己再自删——当场清干净，不用重启。
!include "MUI2.nsh"

Name "樱响"
OutFile "SakuraSound-Setup-v1.0.1.exe"
InstallDir "$LOCALAPPDATA\SakuraSound"
RequestExecutionLevel user
SetCompressor /SOLID lzma
Icon "staging/SakuraSound/icon.ico"

!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"

Section "樱响" SecMain
  SectionIn RO
  SetOutPath "$INSTDIR"
  File /r "staging/SakuraSound/*"
  CreateDirectory "$SMPROGRAMS\SakuraSound"
  CreateShortCut "$SMPROGRAMS\SakuraSound\SakuraSound.lnk" "$INSTDIR\SakuraSound.exe" "" "$INSTDIR\icon.ico"
  CreateShortCut "$DESKTOP\SakuraSound.lnk" "$INSTDIR\SakuraSound.exe" "" "$INSTDIR\icon.ico"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SakuraSound" "DisplayName" "樱响"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SakuraSound" "UninstallString" "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SakuraSound" "DisplayVersion" "1.0.1"
  ; 安装即开机自启动：HKCU Run 键，值名与应用内一致（SakuraSound），卸载段已会删掉它
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "SakuraSound" '"$INSTDIR\SakuraSound.exe"'
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecMain} "樱响桌面程序（必需）。"
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Section "Uninstall"
  ; ---- 卸载程序自身残留（选了 (b)：复制到 $TEMP 再启动副本，当场清干净） ----
  ; 正在运行的 exe 删不掉自己。原进程把自己复制到 $TEMP（改名区分，
  ; 靠文件名认出谁是副本，不靠路径比较——路径大小写抖动不会导致死循环），
  ; 启动副本后原进程退出；副本按注册表里的真安装目录卸载（副本自己的
  ; $INSTDIR 会是 $TEMP，不能直接用），最后留一个一次性批处理等副本
  ; 退出后删掉副本自己再自删。读不到真安装目录就安全中止，什么都不删。
  StrCmp $EXEFILE "SakuraSound-Uninstall-Copy.exe" uninstall_real
  WriteRegStr HKCU "Software\SakuraSound" "UninstallDir" "$INSTDIR"
  ClearErrors
  CopyFiles "$EXEDIR\Uninstall.exe" "$TEMP\SakuraSound-Uninstall-Copy.exe"
  IfErrors uninstall_copy_failed
  Exec '"$TEMP\SakuraSound-Uninstall-Copy.exe"'
  Quit
  uninstall_copy_failed:
  MessageBox MB_OK|MB_ICONSTOP "卸载程序复制失败，卸载已中止，什么都没删。请重试，或手动删除安装目录。"
  Quit
  uninstall_real:
  ReadRegStr $INSTDIR HKCU "Software\SakuraSound" "UninstallDir"
  StrCmp $INSTDIR "" uninstall_abort
  Goto uninstall_go
  uninstall_abort:
  MessageBox MB_OK|MB_ICONSTOP "无法确认 樱响的安装目录，已中止卸载，什么都没删。请从开始菜单重新运行卸载程序。"
  Quit
  uninstall_go:
  RMDir /r "$INSTDIR"
  Delete "$SMPROGRAMS\SakuraSound\SakuraSound.lnk"
  RMDir "$SMPROGRAMS\SakuraSound"
  Delete "$DESKTOP\SakuraSound.lnk"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\SakuraSound"
  ; 开机自启动值（应用里写 Run 键、值名 SakuraSound）
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "SakuraSound"
  ; 清掉应用镜像的注册表键（含 UninstallDir）
  DeleteRegKey HKCU "Software\SakuraSound"
  ; 副本自己正在运行，删不掉自己：留一个一次性批处理，等副本退出后
  ; 删掉副本 exe 再自删（ping 只是等一秒，避免空转占 CPU）。
  FileOpen $1 "$TEMP\SakuraSound-Uninstall-Cleanup.bat" w
  FileWrite $1 "@echo off$\r$\n"
  FileWrite $1 ":wait$\r$\n"
  FileWrite $1 "ping -n 2 127.0.0.1 >nul$\r$\n"
  FileWrite $1 "del /f /q $\"$TEMP\SakuraSound-Uninstall-Copy.exe$\"$\r$\n"
  FileWrite $1 "if exist $\"$TEMP\SakuraSound-Uninstall-Copy.exe$\" goto wait$\r$\n"
  FileWrite $1 "del /f /q $\"%~f0$\"$\r$\n"
  FileClose $1
  Exec '"$SYSDIR\cmd.exe" /c "$TEMP\SakuraSound-Uninstall-Cleanup.bat"'
SectionEnd
