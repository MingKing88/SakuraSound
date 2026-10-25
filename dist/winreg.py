"""winreg 的 ctypes 替代实现（仅随内嵌 Python 发行包附带）。

内嵌 Python 没有 winreg.pyd；本模块用 advapi32.dll 的 Win32 API
实现 winreg 的常用子集：OpenKey / CloseKey / QueryValueEx /
SetValueEx / DeleteValue / CreateKey / EnumValue / EnumKey。
在完整 Python 里永远不会用到它（真正的 winreg.pyd 优先，
且本文件只放进发行包的 python/ 目录，不进源码包）。
注意：本文件只在 Windows 上能导入（ctypes.windll 仅 Windows 有）。
"""

import ctypes
from ctypes import POINTER, c_ulong, c_void_p, c_wchar_p

_advapi32 = ctypes.windll.advapi32

HKEY_CLASSES_ROOT = 0x80000000
HKEY_CURRENT_USER = 0x80000001
HKEY_LOCAL_MACHINE = 0x80000002
HKEY_USERS = 0x80000003
KEY_QUERY_VALUE = 0x0001
KEY_SET_VALUE = 0x0002
KEY_CREATE_SUB_KEY = 0x0004
KEY_ENUMERATE_SUB_KEYS = 0x0008
KEY_READ = 0x20019
KEY_WRITE = 0x20006
KEY_ALL_ACCESS = 0xF003F
REG_NONE = 0
REG_SZ = 1
REG_EXPAND_SZ = 2
REG_BINARY = 3
REG_DWORD = 4
REG_MULTI_SZ = 7
REG_QWORD = 11

ERROR_SUCCESS = 0
ERROR_FILE_NOT_FOUND = 2
ERROR_MORE_DATA = 234
ERROR_NO_MORE_ITEMS = 259

_advapi32.RegOpenKeyExW.argtypes = [c_void_p, c_wchar_p, c_ulong, c_ulong, POINTER(c_void_p)]
_advapi32.RegOpenKeyExW.restype = c_ulong
_advapi32.RegCloseKey.argtypes = [c_void_p]
_advapi32.RegCloseKey.restype = c_ulong
_advapi32.RegQueryValueExW.argtypes = [c_void_p, c_wchar_p, c_void_p, POINTER(c_ulong), c_void_p, POINTER(c_ulong)]
_advapi32.RegQueryValueExW.restype = c_ulong
_advapi32.RegSetValueExW.argtypes = [c_void_p, c_wchar_p, c_ulong, c_ulong, c_void_p, c_ulong]
_advapi32.RegSetValueExW.restype = c_ulong
_advapi32.RegDeleteValueW.argtypes = [c_void_p, c_wchar_p]
_advapi32.RegDeleteValueW.restype = c_ulong
_advapi32.RegCreateKeyExW.argtypes = [c_void_p, c_wchar_p, c_ulong, c_wchar_p, c_ulong, c_ulong, c_void_p, POINTER(c_void_p), c_void_p]
_advapi32.RegCreateKeyExW.restype = c_ulong
_advapi32.RegEnumValueW.argtypes = [c_void_p, c_ulong, c_wchar_p, POINTER(c_ulong), c_void_p, POINTER(c_ulong), c_void_p, POINTER(c_ulong)]
_advapi32.RegEnumValueW.restype = c_ulong
_advapi32.RegEnumKeyExW.argtypes = [c_void_p, c_ulong, c_wchar_p, POINTER(c_ulong), c_void_p, c_wchar_p, c_void_p, c_void_p]
_advapi32.RegEnumKeyExW.restype = c_ulong


class _Key:
    """winreg 句柄的轻量包装，支持 CloseKey 与 with 语句。"""

    def __init__(self, hkey):
        self._hkey = hkey

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        CloseKey(self)
        return False

    def Detach(self):
        h, self._hkey = self._hkey, 0
        return h


def _check(status):
    if status == ERROR_FILE_NOT_FOUND:
        raise FileNotFoundError("注册表项或值不存在")
    if status == ERROR_NO_MORE_ITEMS:
        raise OSError("没有更多项")
    if status != ERROR_SUCCESS:
        raise OSError("注册表操作失败，错误码 %d" % status)


def _handle(key):
    return key._hkey if isinstance(key, _Key) else key


def OpenKey(key, sub_key, reserved=0, access=KEY_READ):
    hkey = c_void_p()
    status = _advapi32.RegOpenKeyExW(_handle(key), sub_key, 0, access, ctypes.byref(hkey))
    _check(status)
    return _Key(hkey.value)


def CloseKey(key):
    h = _handle(key)
    if h:
        _advapi32.RegCloseKey(h)
        if isinstance(key, _Key):
            key._hkey = 0


def QueryValueEx(key, value_name):
    h = _handle(key)
    vtype = c_ulong(0)
    size = c_ulong(0)
    status = _advapi32.RegQueryValueExW(h, value_name, None, ctypes.byref(vtype), None, ctypes.byref(size))
    _check(status)
    buf = ctypes.create_string_buffer(size.value)
    status = _advapi32.RegQueryValueExW(h, value_name, None, ctypes.byref(vtype), buf, ctypes.byref(size))
    _check(status)
    t = vtype.value
    if t in (REG_SZ, REG_EXPAND_SZ):
        text = buf.raw[:size.value].decode("utf-16-le", "ignore")
        return text.rstrip("\x00"), t
    if t == REG_DWORD:
        return int.from_bytes(buf.raw[:4], "little"), t
    if t == REG_QWORD:
        return int.from_bytes(buf.raw[:8], "little"), t
    return buf.raw[:size.value], t


def SetValueEx(key, value_name, reserved, value_type, value):
    h = _handle(key)
    if value_type in (REG_SZ, REG_EXPAND_SZ):
        data = (str(value) + "\x00").encode("utf-16-le")
    elif value_type == REG_DWORD:
        data = int(value).to_bytes(4, "little")
    elif value_type == REG_QWORD:
        data = int(value).to_bytes(8, "little")
    elif isinstance(value, (bytes, bytearray)):
        data = bytes(value)
    else:
        data = str(value).encode("utf-16-le")
    status = _advapi32.RegSetValueExW(h, value_name, 0, value_type, data, len(data))
    _check(status)


def DeleteValue(key, value_name):
    status = _advapi32.RegDeleteValueW(_handle(key), value_name)
    _check(status)


def CreateKey(key, sub_key):
    hkey = c_void_p()
    status = _advapi32.RegCreateKeyExW(_handle(key), sub_key, 0, None, 0, KEY_ALL_ACCESS, None, ctypes.byref(hkey), None)
    _check(status)
    return _Key(hkey.value)


def EnumValue(key, index):
    """枚举第 index 个值，返回 (name, data, type)。

    data 按类型解码（与 QueryValueEx 同一套规则，外加 REG_MULTI_SZ 解成
    str 列表；其它类型返回原始 bytes）。数据放不下时（ERROR_MORE_DATA）
    把缓冲区放大重读，最多重试 8 次。
    comtypes 的类型库生成器就靠这个读值（它会对 REG_SZ 的结果调 .split），
    所以 data 绝不能恒为 None。
    """
    h = _handle(key)
    name_buf = ctypes.create_unicode_buffer(256)
    name_len = c_ulong(256)
    vtype = c_ulong(0)
    data_buf = ctypes.create_string_buffer(1024)
    data_len = c_ulong(1024)
    for _attempt in range(8):
        status = _advapi32.RegEnumValueW(h, index, name_buf, ctypes.byref(name_len), None,
                                         ctypes.byref(vtype), data_buf, ctypes.byref(data_len))
        if status == ERROR_SUCCESS:
            break
        if status == ERROR_MORE_DATA:
            need = data_len.value if data_len.value > 0 else 1024
            data_buf = ctypes.create_string_buffer(need)
            data_len = c_ulong(need)
            if name_len.value > 256:
                name_buf = ctypes.create_unicode_buffer(name_len.value)
            name_len = c_ulong(name_len.value if name_len.value > 0 else 256)
            continue
        if status == ERROR_NO_MORE_ITEMS:
            raise OSError("没有更多值")
        _check(status)
    else:
        raise OSError("RegEnumValueW: 缓冲区始终不够")
    raw = data_buf.raw[:data_len.value]
    t = vtype.value
    if t in (REG_SZ, REG_EXPAND_SZ):
        data = raw.decode("utf-16-le", "ignore").rstrip("\x00")
    elif t == REG_DWORD:
        data = int.from_bytes(raw[:4], "little")
    elif t == REG_QWORD:
        data = int.from_bytes(raw[:8], "little")
    elif t == REG_MULTI_SZ:
        data = [s for s in raw.decode("utf-16-le", "ignore").split("\x00") if s]
    else:
        data = raw
    return name_buf.value, data, t


def EnumKey(key, index):
    h = _handle(key)
    name_buf = ctypes.create_unicode_buffer(256)
    name_len = c_ulong(256)
    status = _advapi32.RegEnumKeyExW(h, index, name_buf, ctypes.byref(name_len), None, None, None, None)
    if status == ERROR_NO_MORE_ITEMS:
        raise OSError("没有更多子项")
    _check(status)
    return name_buf.value
