/* VolRider 启动器 v8.1 诊断版：双击后用内嵌 Python（无窗口模式）启动 Qt 桌面程序。
   本身用 -mwindows 编译成 GUI 子系统，不产生任何黑窗口；
   子进程 pythonw.exe 同样无窗口。启动 2 秒内子进程就退出则弹框报错，
   否则启动器直接退出，Qt 程序独立运行（关闭窗口后缩到托盘）。
   全程用 W 版 API（wchar_t）：非 ASCII 路径（比如用户名是中文）也不会
   在 ANSI 代码页里被转丢；目录取到后若拼出的路径会超 MAX_PATH，
   命令行与工作目录改走 \\?\ 前缀（CreateProcessW 支持该形式）。
   诊断版与 v8.1 正式版的区别（仅此两处）：
   （1）命令行改 wcscpy/wcscat 显式拼接，不用 swprintf；
   （2）CreateProcessW 失败时先用 ShellExecuteW 再试一次，若也失败，
       弹框同时显示两次的错误码＋系统错误文本，不再只显示一句通用话。 */
#include <windows.h>
#include <shellapi.h>
#include <stdio.h>
#include <stdlib.h>

/* 把无符号长整型以十进制追加到 dst 末尾（不依赖 swprintf）。 */
static void append_ulong(wchar_t *dst, unsigned long v) {
    wchar_t tmp[24];
    int i = 0;
    if (v == 0) {
        wcscat(dst, L"0");
        return;
    }
    while (v > 0) {
        tmp[i++] = (wchar_t)(L'0' + (v % 10));
        v /= 10;
    }
    while (i > 0) {
        wchar_t ch[2];
        ch[0] = tmp[--i];
        ch[1] = L'\0';
        wcscat(dst, ch);
    }
}

/* 取系统错误文本写进 buf（去尾换行）；取不到则写一句占位。 */
static void format_error(DWORD err, wchar_t *buf, size_t cap) {
    wchar_t *msg = NULL;
    DWORD n = FormatMessageW(FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM |
                             FORMAT_MESSAGE_IGNORE_INSERTS,
                             NULL, err, 0, (LPWSTR)&msg, 0, NULL);
    if (n > 0 && msg) {
        while (n > 0 && (msg[n - 1] == L'\r' || msg[n - 1] == L'\n'))
            msg[--n] = L'\0';
        wcsncpy(buf, msg, cap - 1);
        buf[cap - 1] = L'\0';
        LocalFree(msg);
    } else {
        wcscpy(buf, L"（无系统错误文本）");
    }
}

int WINAPI wWinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, LPWSTR lpCmdLine, int nCmdShow) {
    /* 1. 取 exe 所在目录：缓冲区从 1024 起翻倍，直到装下（上限 32767）。
       GetModuleFileNameW 装不下时返回 cap（不含结尾 0 也会被截断），
       所以 n >= cap 就说明要换更大的缓冲区，不能将就着用。 */
    DWORD cap = 1024;
    wchar_t *dir = NULL;
    for (;;) {
        dir = (wchar_t *)malloc(cap * sizeof(wchar_t));
        if (!dir) return 1;
        DWORD n = GetModuleFileNameW(NULL, dir, cap);
        if (n == 0) {
            free(dir);
            MessageBoxW(NULL, L"找不到程序所在目录。", L"VolRider", MB_OK | MB_ICONERROR);
            return 1;
        }
        if (n < cap) break;
        free(dir);
        cap *= 2;
        if (cap > 32767) {
            MessageBoxW(NULL, L"程序所在路径太长，启动器装不下。请把它解压到更浅的目录再试。",
                        L"VolRider", MB_OK | MB_ICONERROR);
            return 1;
        }
    }
    wchar_t *slash = wcsrchr(dir, L'\\');
    if (!slash) {
        free(dir);
        MessageBoxW(NULL, L"找不到程序所在目录。", L"VolRider", MB_OK | MB_ICONERROR);
        return 1;
    }
    *slash = L'\0';

    /* 2. 超长路径：命令行与工作目录改走 \\?\ 前缀（只影响超长情形，正常路径原样）。
       ShellExecuteW 不吃 \\?\ 前缀，所以兜底重试一律用不带前缀的普通路径。 */
    wchar_t *use_dir = dir;
    wchar_t *dir_long = NULL;
    if (wcslen(dir) + 32 > 260) {
        dir_long = (wchar_t *)malloc((4 + wcslen(dir) + 1) * sizeof(wchar_t));
        if (dir_long) {
            wcscpy(dir_long, L"\\\\?\\");
            wcscat(dir_long, dir);
            use_dir = dir_long;
        }
    }

    /* 3. 显式拼接命令行："<dir>\python\pythonw.exe" "<dir>\qt_app.py"。
       长度 = 两倍目录长 + 两段后缀 + 引号空格 + 结尾 0，+64 足够。 */
    size_t cmd_cap = wcslen(use_dir) * 2 + 64;
    wchar_t *cmd = (wchar_t *)malloc(cmd_cap * sizeof(wchar_t));
    if (!cmd) return 1;
    cmd[0] = L'\0';
    wcscat(cmd, L"\"");
    wcscat(cmd, use_dir);
    wcscat(cmd, L"\\python\\pythonw.exe\" \"");
    wcscat(cmd, use_dir);
    wcscat(cmd, L"\\qt_app.py\"");

    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));
    if (!CreateProcessW(NULL, cmd, NULL, NULL, FALSE, 0, NULL, use_dir, &si, &pi)) {
        /* 先记下 CreateProcess 的错误码，再做任何其他调用。 */
        DWORD err1 = GetLastError();
        wchar_t text1[512];
        format_error(err1, text1, 512);

        /* 兜底重试：ShellExecuteW 直接打开 pythonw.exe，参数为带引号的脚本路径。
           ShellExecute 返回值 > 32 为成功，<= 32 本身就是错误码。 */
        size_t pyw_cap = wcslen(dir) + 32;
        wchar_t *pyw = (wchar_t *)malloc(pyw_cap * sizeof(wchar_t));
        wchar_t *arg = (wchar_t *)malloc(pyw_cap * sizeof(wchar_t));
        if (pyw && arg) {
            pyw[0] = L'\0';
            wcscat(pyw, dir);
            wcscat(pyw, L"\\python\\pythonw.exe");
            arg[0] = L'\0';
            wcscat(arg, L"\"");
            wcscat(arg, dir);
            wcscat(arg, L"\\qt_app.py\"");
            HINSTANCE ret = ShellExecuteW(NULL, L"open", pyw, arg, dir, SW_SHOWNORMAL);
            if ((INT_PTR)ret > 32) {
                /* 兜底成功：程序已拉起，启动器直接退出（与正常路径一致）。 */
                return 0;
            }
            {
                DWORD err2 = (DWORD)(INT_PTR)ret;
                wchar_t text2[512];
                wchar_t dlg[4096];
                format_error(err2, text2, 512);
                dlg[0] = L'\0';
                wcscat(dlg, L"启动失败（诊断版）。\n\nCreateProcess 失败，错误码 ");
                append_ulong(dlg, err1);
                wcscat(dlg, L"：");
                wcscat(dlg, text1);
                wcscat(dlg, L"\nShellExecute 失败，错误码 ");
                append_ulong(dlg, err2);
                wcscat(dlg, L"：");
                wcscat(dlg, text2);
                wcscat(dlg, L"\n\n请把这两个错误码发回，便于定位原因"
                            L"（错误 5 拒绝访问通常是杀毒软件拦截）。");
                MessageBoxW(NULL, dlg, L"VolRider", MB_OK | MB_ICONERROR);
            }
        } else {
            /* 兜底连拼路径的内存都没拿到：只报第一次的错误码。 */
            wchar_t dlg[2048];
            dlg[0] = L'\0';
            wcscat(dlg, L"启动失败（诊断版）。\n\nCreateProcess 失败，错误码 ");
            append_ulong(dlg, err1);
            wcscat(dlg, L"：");
            wcscat(dlg, text1);
            wcscat(dlg, L"\nShellExecute 未能重试（内存不足）。");
            MessageBoxW(NULL, dlg, L"VolRider", MB_OK | MB_ICONERROR);
        }
        return 1;
    }
    /* Qt 程序启动需要一点时间；只等 2 秒：子进程还活着就是启动成功，
       启动器退出（不常驻）；2 秒内就退出说明起不来，弹框提示看报错的方法。 */
    DWORD waited = WaitForSingleObject(pi.hProcess, 2000);
    if (waited == WAIT_OBJECT_0) {
        MessageBoxW(NULL, L"VolRider 没能启动起来（程序很快就退出了）。\n\n"
                          L"可能原因：文件没解压完整，或系统缺少运行库。\n"
                          L"想看具体报错：打开命令提示符，进到这个文件夹，\n"
                          L"运行 python\\python.exe qt_app.py，把报错截图发来。",
                    L"VolRider", MB_OK | MB_ICONERROR);
    }
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);
    return 0;
}
