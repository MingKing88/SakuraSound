"""VolRider 核心：Windows 音频会话、响度均衡、设备切换、开机自启动。

设计要点（对应用户要的四点）：
1. 各音源响度可视化：用 IAudioMeterInformation 读每个会话的实时峰值。
2. 开机自启动：写 HKCU Run 键，不需要管理员权限。
3. 检测系统本身对音量的调整：每 100ms 轮询一次总音量和各会话音量；
   凡是不是均衡器自己改的变动，一律视为用户手动调整。
4. 显示并切换音源输出：枚举渲染端点，用 IPolicyConfig.SetDefaultEndpoint
   切换默认设备（Windows 没有公开 API，这是开源工具通用的未公开接口，
   失败时返回 False，由界面提示手动去系统声音设置里切换）。

注意：所有 pycaw 调用都必须集中在同一个线程（轮询线程）里做，
因为 COM 要求每个线程单独 CoInitialize；界面线程只通过命令队列发指令。
"""

import ctypes
import os
import sys
import time
from ctypes import HRESULT, POINTER, cast

try:
    # 内嵌 Python 发行包里没有 winreg.pyd：开机自启动功能降级处理，
    # 核心音频功能不受影响（发行包里会附带一个 ctypes 版 winreg 替代）。
    import winreg
except ImportError:
    winreg = None

try:
    from comtypes import CLSCTX_ALL, CoCreateInstance, GUID, IUnknown
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    try:
        from pycaw.pycaw import IAudioMeterInformation
    except Exception:
        IAudioMeterInformation = None
    _AUDIO_OK = True
    _AUDIO_ERROR = None
except Exception as e:
    AudioUtilities = None
    IAudioEndpointVolume = None
    IAudioMeterInformation = None
    _AUDIO_OK = False
    # 记下真正的失败原因，别让后面的代码报一张冠李戴的错
    _AUDIO_ERROR = "%s: %s" % (type(e).__name__, e)


def require_audio():
    if not _AUDIO_OK:
        raise RuntimeError(
            "音频库未就绪（%s），请先在解压目录执行 pip install -r requirements.txt"
            % (_AUDIO_ERROR or "未知原因")
        )


# ---------------------------------------------------------------- 会话快照

class SessionInfo:
    """一次轮询里某个应用的音频会话状态。session 保留原始对象以便改音量。

    key 是会话键（见 list_sessions）：同一进程开多个会话时也不串台；
    name 只是显示名（进程名），两个同名会话在界面上长一个样，
    但命令按 key 走，各自独立。
    """

    def __init__(self, name, volume, peak, session, key=None):
        self.name = name
        self.volume = volume
        self.peak = peak
        self.session = session
        self.key = key if key is not None else name


def list_sessions():
    """返回当前所有正在发声（或曾经发声）的应用会话。"""
    require_audio()
    out = []
    for s in AudioUtilities.GetAllSessions():
        try:
            proc = s.Process
            name = proc.name() if proc is not None else "系统声音"
        except Exception:
            name = "未知应用"
        try:
            volume = s.SimpleAudioVolume.GetMasterVolume()
        except Exception:
            continue  # 读不到音量的会话（已过期）直接跳过
        peak = 0.0
        if IAudioMeterInformation is not None:
            try:
                meter = s._ctl.QueryInterface(IAudioMeterInformation)
                peak = float(meter.GetPeakValue())
            except Exception:
                peak = 0.0
        # 会话键优先用系统分配的实例标识（同一进程多个会话也互不干扰）；
        # 取不到时退回“进程名#PID”，显示名始终是进程名。
        try:
            key = s.InstanceIdentifier
        except Exception:
            key = None
        if not key:
            try:
                pid = s.ProcessId
            except Exception:
                pid = None
            key = "%s#%s" % (name, pid)
        out.append(SessionInfo(name, volume, peak, s, key))
    return out


def set_session_volume(session, value):
    value = max(0.0, min(1.0, float(value)))
    session.SimpleAudioVolume.SetMasterVolume(value, None)
    return value


# ---------------------------------------------------------------- 总音量

def _endpoint_volume():
    """取默认播放设备的音量接口。

    新版 pycaw 的 GetSpeakers() 返回 AudioDevice 包装器（自带 EndpointVolume
    属性），旧版返回原始 IMMDevice（需 Activate）。两种写法都兼容，
    避免新版上每轮 tick 都在这里抛 AttributeError 导致界面全空。
    """
    speakers = AudioUtilities.GetSpeakers()
    if hasattr(speakers, "EndpointVolume"):
        return speakers.EndpointVolume
    interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def get_master_volume():
    """返回 (总音量 0~1, 是否静音)。"""
    require_audio()
    vol = _endpoint_volume()
    return vol.GetMasterVolumeLevelScalar(), bool(vol.GetMute())


def set_master_volume(value):
    require_audio()
    vol = _endpoint_volume()
    vol.SetMasterVolumeLevelScalar(max(0.0, min(1.0, float(value))), None)


# ---------------------------------------------------------------- 输出设备

def list_devices():
    """返回 [{'id': 设备 ID, 'name': 友好名}]，只保留渲染（播放）设备。"""
    require_audio()
    out = []
    for d in AudioUtilities.GetAllDevices():
        try:
            name = d.FriendlyName
            dev_id = d.id
        except Exception:
            continue
        try:
            # eRender=0，eCapture=1；录音设备不进播放下拉，查不到方向时宁可保留
            if AudioUtilities.GetEndpointDataFlow(dev_id, 1) == 1:
                continue
        except Exception:
            pass
        out.append({"id": dev_id, "name": name})
    return out


def get_default_device_id():
    require_audio()
    return AudioUtilities.GetSpeakers().id


# IPolicyConfig 的 CLSID（Windows 未公开接口，开源项目通用做法）
# 注意：音频库缺失时 GUID 根本没引入成功，这里必须先判断，
# 否则 import 本身就会报一张冠李戴的 NameError，掩盖真正的缺依赖问题。
if _AUDIO_OK:
    _CLSID_POLICY_CONFIG_CLIENT = GUID("{870AF99C-171D-4F9E-AF0D-E63DF40C2BC9}")
else:
    _CLSID_POLICY_CONFIG_CLIENT = None


def _policy_config_class():
    """取 IPolicyConfig 的 comtypes 接口类。

    首选 pycaw 自带的定义（虚表顺序经 pycaw 源码核实：8 个 Unused 占位后
    是 Get/SetPropertyValue，再是 SetDefaultEndpoint）。
    老版 pycaw 没有该模块时，按同一虚表顺序内联定义一份。
    """
    try:
        from pycaw.api.policyconfig import IPolicyConfig

        return IPolicyConfig
    except Exception:
        pass
    try:
        from comtypes import COMMETHOD
        from ctypes.wintypes import BOOL, DWORD, LPCWSTR

        try:
            from pycaw.api.mmdeviceapi import PROPERTYKEY
            from pycaw.api.mmdeviceapi.depend import PROPVARIANT
        except Exception:
            from pycaw.pycaw import PROPERTYKEY, PROPVARIANT

        class _IPolicyConfig(IUnknown):
            _case_insensitive_ = True
            _iid_ = GUID("{f8679f50-850a-41cf-9c72-430f290290c8}")
            _methods_ = (
                COMMETHOD([], HRESULT, "Unused1"),
                COMMETHOD([], HRESULT, "Unused2"),
                COMMETHOD([], HRESULT, "Unused3"),
                COMMETHOD([], HRESULT, "Unused4"),
                COMMETHOD([], HRESULT, "Unused5"),
                COMMETHOD([], HRESULT, "Unused6"),
                COMMETHOD([], HRESULT, "Unused7"),
                COMMETHOD([], HRESULT, "Unused8"),
                COMMETHOD(
                    [], HRESULT, "GetPropertyValue",
                    (["in"], LPCWSTR, "pwstrDeviceId"),
                    (["in"], POINTER(PROPERTYKEY), "pKey"),
                    (["out"], POINTER(PROPVARIANT), "pValue"),
                ),
                COMMETHOD(
                    [], HRESULT, "SetPropertyValue",
                    (["in"], LPCWSTR, "pwstrDeviceId"),
                    (["in"], POINTER(PROPERTYKEY), "pKey"),
                    (["in"], POINTER(PROPVARIANT), "pValue"),
                ),
                COMMETHOD(
                    [], HRESULT, "SetDefaultEndpoint",
                    (["in"], LPCWSTR, "pwstrDeviceId"),
                    (["in"], DWORD, "role"),
                ),
                COMMETHOD(
                    [], HRESULT, "SetEndpointVisibility",
                    (["in"], LPCWSTR, "pwstrDeviceId"),
                    (["in"], BOOL, "bVisible"),
                ),
            )

        return _IPolicyConfig
    except Exception:
        return None


def _default_is(device_id):
    """校验多媒体默认设备是否真的变成了 device_id（只信实测，不信返回值）。

    GetSpeakers() 取的是渲染＋多媒体角色的默认设备，所以这里校验的
    就是多媒体角色——切换成败以多媒体角色为准。
    """
    try:
        return AudioUtilities.GetSpeakers().id == device_id
    except Exception:
        return False


def set_default_device_detailed(device_id):
    """把 device_id 设为默认播放设备，返回 (ok, roles)。

    roles 按角色分别报告两个 SetDefaultEndpoint 调用的成败：
    {1: 多媒体角色, 0: 控制台角色}。ok 以多媒体角色为准：
    多媒体调用成功、且实测多媒体默认设备真的变了，才算成功。
    """
    require_audio()
    cls = _policy_config_class()
    if cls is None:
        return False, {1: False, 0: False}
    try:
        pc = CoCreateInstance(_CLSID_POLICY_CONFIG_CLIENT, interface=cls, clsctx=CLSCTX_ALL)
        roles = {}
        for role in (1, 0):  # 1 = 多媒体，0 = 控制台
            roles[role] = (pc.SetDefaultEndpoint(device_id, role) == 0)
        ok = bool(roles.get(1)) and _default_is(device_id)
        return ok, roles
    except Exception:
        return False, {1: False, 0: False}


def set_default_device(device_id):
    """把 device_id 设为默认播放设备（多媒体 + 控制台两个角色）。

    用正规 COM 接口调用，不再手算虚表槽位；调用成功后还要实测默认设备
    真的变了才算成功，否则返回 False（界面会提示手动去系统声音设置里切）。
    成败以多媒体角色为准，逐角色的明细见 set_default_device_detailed。
    """
    ok, _roles = set_default_device_detailed(device_id)
    return ok


def selftest_default_device():
    """自检：把当前默认设备原地再设一次（设为自己本身，不改动实际默认）。

    只用于诊断切换接口本身是否可用：多媒体角色 1、控制台角色 0 各调一次
    SetDefaultEndpoint，捕获每个角色的原始 HRESULT（comtypes 在失败时抛
    COMError，原始码在异常的 hresult 上；直接返回时就是该整数），再用
    _default_is 实测默认设备是否仍是该 id。返回 dict：

        {device_id, hresult_multimedia, hresult_console,
         verified_default_id, ok, error}

    hresult 为原始整数（成功为 0；拿不到时为 None，此时看 error）。
    ok = 多媒体角色成功且实测默认设备仍是该 id。
    本函数只新增，不改动 set_default_device_detailed 的签名与行为。
    """
    result = {
        "device_id": None,
        "hresult_multimedia": None,
        "hresult_console": None,
        "verified_default_id": None,
        "ok": False,
        "error": None,
    }
    try:
        require_audio()
    except Exception as e:
        result["error"] = "%s: %s" % (type(e).__name__, e)
        return result
    try:
        device_id = get_default_device_id()
    except Exception as e:
        result["error"] = "读取当前默认设备失败：%s: %s" % (type(e).__name__, e)
        return result
    result["device_id"] = device_id
    cls = _policy_config_class()
    if cls is None:
        result["error"] = "IPolicyConfig 接口未取得（接口未注册或音频库定义缺失）"
        return result
    try:
        pc = CoCreateInstance(_CLSID_POLICY_CONFIG_CLIENT, interface=cls, clsctx=CLSCTX_ALL)
    except Exception as e:
        result["error"] = "创建 IPolicyConfig 失败：%s: %s" % (type(e).__name__, e)
        return result
    for role, key in ((1, "hresult_multimedia"), (0, "hresult_console")):
        try:
            hr = pc.SetDefaultEndpoint(device_id, role)
        except Exception as e:
            hr = getattr(e, "hresult", None)
        result[key] = hr
    try:
        result["verified_default_id"] = get_default_device_id()
    except Exception:
        result["verified_default_id"] = None
    result["ok"] = (result["hresult_multimedia"] == 0
                    and result["verified_default_id"] == device_id)
    return result


# ---------------------------------------------------------------- 开机自启动

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APP_NAME = "SakuraSound"


def _autostart_command():
    exe = sys.executable.replace("python.exe", "pythonw.exe")
    root = os.path.dirname(os.path.abspath(__file__))
    # 发行包优先用启动器 exe；源码版用桌面程序 qt_app.py；网页版 server.py 只作退路。
    launcher = os.path.join(root, "SakuraSound.exe")
    if os.path.exists(launcher):
        return '"%s"' % launcher
    qt_py = os.path.join(root, "qt_app.py")
    if os.path.exists(qt_py):
        return '"%s" "%s"' % (exe, qt_py)
    server_py = os.path.join(root, "web", "server.py")
    if os.path.exists(server_py):
        return '"%s" "%s"' % (exe, server_py)
    return '"%s" "%s"' % (exe, qt_py)


def is_autostart_enabled():
    if winreg is None:
        return False
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_QUERY_VALUE)
        try:
            winreg.QueryValueEx(key, _APP_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False


def set_autostart(enable):
    if winreg is None:
        raise RuntimeError("开机自启动需要 winreg 支持，当前 Python 环境缺少该模块")
    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE
    )
    try:
        if enable:
            winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, _autostart_command())
        else:
            try:
                winreg.DeleteValue(key, _APP_NAME)
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)


# ---------------------------------------------------------------- 自动均衡（A 路线：音量骑手）

# 自动基准分层（v8.15，按程序名算，不是窗口标题、不是内容类型）：
#   层 0 = 浏览器，层 1 = 其他，层 2 = 流媒体。
# 指定基准应用仍走原有逻辑、不进分层；自动模式下高层只要有出声的
# 未手动调过应用就赢，不管低层多响；同一层里最响的赢。
_BROWSER_NAMES = {
    "chrome", "msedge", "edge", "firefox", "opera", "brave", "arc",
    "vivaldi", "chromium", "thorium", "sogou_explorer", "360se",
}
_STREAMING_KEYWORDS = (
    "spotify", "cloudmusic", "netease", "qqmusic", "kugou", "kuwo",
    "bilibili", "iqiyi", "youku", "qqlive", "tencentvideo", "netflix",
    "tidal", "deezer", "ytmusic", "youtube_music", "musicbee",
)


def _reference_tier(name):
    """返回自动基准的层号：0 浏览器，1 其他，2 流媒体。

    name 是 SessionInfo.name（进程名，如 chrome.exe）。先判浏览器
    （整名匹配），再判流媒体（关键字包含匹配），其余为其他层，
    所以 chrome 等浏览器不会被流媒体关键字误判。
    """
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1].strip().lower()
    if base.endswith(".exe"):
        base = base[:-4]
    if base in _BROWSER_NAMES:
        return 0
    for kw in _STREAMING_KEYWORDS:
        if kw in base:
            return 2
    return 1


class Rider:
    """按峰值自动推拉各应用音量，让不同音源听起来一样响。

    均衡目标是相对的，不是绝对的：基准取“正在出声的应用里最响的
    那个有效峰值”，但不超过目标滑杆值。各应用向基准看齐，只管应用之间
    的相对平衡；绝对响度永远由系统总音量说了算——总音量一调，
    均衡后的整体响度就跟着动，均衡器绝不会反向补偿总音量的变化。

    关键修正（2026-10-25 真机截图实证）：Windows 会话峰值表读的是
    改音量之前的原声峰值——音量 5% 时峰值还能显示 28%/56%，所以它
    根本不随会话音量变。以前直接拿它当反馈，音量一拉峰值不动，
    均衡器就一轮接一轮拉到 5% 地板，两个应用都贴地板、响度还是差一倍。
    现在控制量改成有效峰值 = 原声平滑峰值 × 当前会话音量（这才是耳朵
    实际听到的相对大小），拉音量会让有效峰值跟着动，回路才能收敛。
    另加顶格锚定：有出声应用音量已到 100% 还推不上去时，基准不能高于
    它的有效峰值，否则响的应用永远拉不下来、安静的那个永远追不上。
    但锚定有下限（目标的 60%）：极小声的源不能把所有应用一起拖到
    听不见——骑手只能拉低、不能放大，极小声的源只能接受它仍偏小。

    触发式同步（2026-10-25 用户明确要求，不再实时同步）：
    轮询仍是每 100ms（条形图、峰值显示照常实时），但音量只在
    “相位”里动，相位外一动不动——
    ——拨开“自动均衡”开关：立刻同步一次，随后每 5 秒同步一次，
      满 3 分钟后固定（再也不动，直到下一次触发）；关掉开关则立刻停；
    ——新程序首声：出声满 2 秒后进入同样的相位（立刻同步一次，
      随后每 5 秒一次、满 3 分钟后固定）；相位进行中新程序加入，
      3 分钟窗口从最新一次触发重算；
    ——用户主动改目标、重开某应用的自动时：立刻单次同步一次
      （不进相位，否则改个目标也要等 3 分钟才生效，看起来像改了没用）。
    这样做的直接好处：浏览器视频中间一小段没声音时，其他应用的音量
    不会被实时追着拉没——两次同步之间音量根本不动，无声段拖不动别人；
    同步那一刻出声的应用才参与基准计算，静音应用不参与、不被调、
    也不拖基准。同步用慢速峰值（峰值保持、慢衰减，约 20 秒窗口）算
    目标音量 = 基准 / 慢速原声峰值，一次到位，而不是每轮挪 5%。

    v8.12 三处借鉴（GitHub 同类项目 Wale / Volume Leveler）：
    ——分块平均：长时平均不再用 EMA 0.999（旧歌响度拖很久），改成
      Wale 式分块平均：出声样本每 10 个合成 1 块（约 1 秒出声时间），
      取最近 100 块的块均值（约 100 秒出声时间），满 100 块后旧块滑出，
      换歌后旧歌的影响最多残留一个窗口，不再无限拖尾；
    ——基准应用：默认仍是“所有未手动调过的出声应用里最响的”，但用户
      可在界面指定一个应用当基准（例如“以网易云为准”），其他应用都
      向它看齐；指定应用不出声时自动退回默认算法；
    ——漂移重校：相位固定后不再是“固定到死”——若某应用的长期响度
      相对固定那一刻偏离超过约 ±3dB（比值 <0.70 或 >1.43）且持续
      约 3 秒，自动重进相位再同步一次（Volume Leveler 的漂移重校思路），
      同一应用换了个特别响/特别轻的视频也不用手动拨开关。

    关键规则：用户手动改的音量，均衡器必须让路，但不再等于关自动。
    以前的做法是“一有外部改动就关自动”，这在实际使用里是误判：
    很多播放器（网易云等）的内置滑杆本身就是直接改 Windows 会话音量，
    而切歌/换源时播放器还会把会话音量弹回它自己滑杆的位置——这两种
    变动都不是用户在系统音量合成器里“要关自动”，却都被当成了手动关自动。
    新规则：外部改动只记为该应用的偏好（trim），自动继续开着：
    ——回到它上次的用户音量（典型就是切歌回弹）：不改偏好、不发提示，
      下次同步时按原偏好算；
    ——调到了一个新音量：把这次变动记成新的相对偏好（新音量/均衡器
      上次设的值），下次同步按“基准 × 偏好”算，不会硬拉回改动之前；
    ——真正想关自动，只用界面上的“自动”开关，那才是开关。
    """

    def __init__(self, target=0.7):
        self.target = target          # 目标滑杆值：基准的上限（0.5~0.9 之间调）
        self.reference = target       # 本轮实际基准（供界面显示）
        self.enabled = True           # 总开关
        # 下列三个字典一律按会话键 key 索引（实例标识优先，退回进程名#PID），
        # 不按显示名：同名会话各算各的，互不串台。显示时才用进程名。
        self.auto_apps = {}           # 会话键 -> 是否自动均衡（默认 True）
        self._last_set = {}           # 会话键 -> (均衡器最后一次设的值, 时间)
        self._smooth = {}             # 会话键 -> 平滑后的峰值
        self._trim = {}               # 会话键 -> 用户相对偏好（默认 1.0）
        self._user_vol = {}           # 会话键 -> 该应用自己的滑杆音量（首次见到的、
                                      # 或用户上次手动调到的音量；切歌回弹就回到这个值）
        self._reset_smooth = set()    # 界面滑杆刚调过的会话：下一轮平滑峰值直接取实测值
        self._effective = {}          # 会话键 -> 有效峰值（原声平滑峰值 × 会话音量，界面条形图用它）
        self._slow_smooth = {}        # 会话键 -> 慢速原声峰值（峰值保持、0.99/轮慢衰减，备用）
        self._avg_peak = {}           # 会话键 -> 长时平均原声峰值（分块平均，见 _chunk_avg；对外仍保留这个字典名，值是块均值）
        self._chunk_buf = {}          # 会话键 -> 当前块内未满 10 个的出声样本
        self._chunks = {}             # 会话键 -> 最近 100 块的块均值（每块 10 个出声样本，约 1 秒出声时间）
        self.reference_key = None     # 指定基准应用的会话键（None = 自动：分层，指定 > 浏览器 > 其他 > 流媒体，同一层里最响的赢）
        self.reference_name = None    # 指定基准应用的显示名（供界面恢复/显示用，键失效时按名匹配）
        self._avg_at_fix = {}         # 会话键 -> 相位固定那一刻的长时平均（漂移重校的比较基线）
        self._drift_ticks = {}        # 会话键 -> 连续偏离固定基线的 tick 数（约 3 秒才触发重校）
        self._seen = set()            # 已见过的会话键
        self._first_sound_time = {}   # 会话键 -> 首次持续出声的开始时间（满 2 秒才同步）
        self._first_sound_done = set()  # 已完成首声同步的会话键
        self._last_sync = {}          # 会话键 -> 上次同步时间（同步过的才记，满 3 分钟再同步）
        self._sync_requested = False  # 用户改目标/重开自动时置起，下次有出声应用时同步一次
        self._phase_until = 0.0       # 相位结束时间（0 = 不在相位里）
        self._last_phase_sync = 0.0   # 相位里上次同步时间（0 = 相位刚开始，下轮立刻同步）
        self._phase_interval = 5.0    # 相位里同步间隔（秒）
        self._phase_duration = 180.0  # 相位总长（秒）：3 分钟后固定
        self._phase_end_emitted = True  # 相位结束提示是否已发（初始 True，避免开机就发）
        self._first_sound_delay = 2.0  # 首声同步等待（秒）
        self.events = []              # 本轮产生的状态消息（给界面状态栏）
        self._pending_events = []     # 跨 tick 攒下的消息（切换设备、恢复自动等）

    def start_phase(self, now=None):
        """进入同步相位：立刻同步一次，随后每 5 秒一次、满 3 分钟后固定。
        调用方是拨开自动均衡开关、或新程序首声；相位进行中再次调用
        会把 3 分钟窗口从这次触发重算。"""
        import time as _time
        now = _time.time() if now is None else now
        self._phase_until = now + self._phase_duration
        self._last_phase_sync = 0.0
        self._phase_end_emitted = False
        self._sync_requested = True

    def stop_phase(self):
        """关掉自动均衡时停掉相位，不再同步。"""
        self._phase_until = 0.0
        self._sync_requested = False

    # ---- 分块平均（Wale 式）与基准应用、漂移重校 ----
    def _chunk_avg(self, key):
        """返回该应用的长时平均：最近 100 块的块均值，未满的当前块也算一块。"""
        chunks = list(self._chunks.get(key, []))
        buf = self._chunk_buf.get(key, [])
        if buf:
            chunks.append(sum(buf) / len(buf))
        if not chunks:
            return 0.0
        return sum(chunks) / len(chunks)

    def _push_chunk_sample(self, key, peak):
        """出声样本进当前块；满 10 个合成一块，超 100 块时最旧块滑出。"""
        buf = self._chunk_buf.setdefault(key, [])
        buf.append(peak)
        if len(buf) >= 10:
            self._chunks.setdefault(key, []).append(sum(buf) / len(buf))
            # deque 式滑出：不用 collections 也可以，列表切一片即可（最多 100 项，便宜）
            self._chunks[key] = self._chunks[key][-100:]
            self._chunk_buf[key] = []
        self._avg_peak[key] = self._chunk_avg(key)

    def _reset_chunk_avg(self, key, peak):
        """换歌回弹：旧歌的平均清零，新歌从这一个样本开始算。"""
        self._chunks[key] = []
        self._chunk_buf[key] = [peak]
        self._avg_peak[key] = peak

    def set_reference(self, key, name=None):
        """指定基准应用（key 为空 = 回到自动）；指定应用不出声时 tick 里自动退回默认算法。"""
        self.reference_key = key if key else None
        self.reference_name = name if key else None
        if self.reference_key:
            self.emit("基准应用已设为「%s」：其他应用都向它看齐" % (name or key))
        else:
            self.emit("基准应用已回到自动（分层：浏览器 > 其他 > 流媒体，同一层里最响的）")

    def request_sync(self):
        """用户主动改目标/重开自动时请求一次同步（不立即调音量，下一轮
        有出声应用时由 tick 统一做同步，避免在命令处理里直接动音频）。"""
        self._sync_requested = True

    def emit(self, message):
        """在 tick 之外产生的消息：先攒着，下一轮 tick 开始时并入本轮事件，
        避免被 tick 开头的 events 清空吃掉（之前切换设备的成败提示就是这么丢的）。"""
        self._pending_events.append(message)

    def set_auto(self, key, enabled, display=None):
        """界面勾选/取消某会话的“自动”。重开时必须重置基线和偏好：
        否则下一轮还会拿“手动改之前均衡器设的值”跟当前音量比，
        立刻又判定为手动改动——这就是之前“勾上自动又自己弹掉”的原因。
        现在手动改动本身不再关自动，所以这里只负责真正的开关。"""
        self.auto_apps[key] = bool(enabled)
        if enabled:
            self._last_set.pop(key, None)
            self._trim.pop(key, None)
            self._user_vol.pop(key, None)
            self._effective.pop(key, None)
            self._avg_peak.pop(key, None)
            self._chunk_buf.pop(key, None)
            self._chunks.pop(key, None)
            self._avg_at_fix.pop(key, None)
            self._drift_ticks.pop(key, None)
            self._reset_smooth.discard(key)
            # 重开自动不是等 3 分钟：立刻请求一次同步（有出声应用时做）。
            self._sync_requested = True
            self.emit("已恢复「%s」的自动均衡" % (display if display is not None else key))

    def tick(self, sessions):
        now = time.time()
        # 本轮事件 = 跨 tick 攒下的消息 + 本轮新产生的
        self.events = self._pending_events
        self._pending_events = []
        # ---------- 第一段：只检测、不调音量（每 100ms 跑，音量不动） ----------
        trigger = False
        for s in sessions:
            name = s.name
            key = s.key
            self._seen.add(key)
            # 快慢两条峰值：快的是界面条形图（上升立刻跟、下降 0.85 衰减）；
            # 慢的是同步计算（峰值保持、0.99 慢衰减，约 20 秒窗口），
            # 同步那一刻的估计才不会被一帧安静前奏 / 一小段无声带偏。
            if key in self._reset_smooth:
                self._reset_smooth.discard(key)
                self._smooth[key] = s.peak
            else:
                prev = self._smooth.get(key, 0.0)
                self._smooth[key] = max(s.peak, prev * 0.85)
            smooth = self._smooth[key]
            prev_slow = self._slow_smooth.get(key, 0.0)
            self._slow_smooth[key] = max(s.peak, prev_slow * 0.99)
            # 长时平均：只在出声时更新，静音不进平均；分块平均（10 个出声样本
            # 一块、最近 100 块），1 秒爆炸只占一块的十分之一，带不偏它，
            # 且旧块满 100 后滑出，换歌后旧歌不会无限残留。
            if s.peak >= 0.02:
                self._push_chunk_sample(key, s.peak)
            # 首次见到该会话：先记下它自己的音量，当作滑杆基线
            if key not in self._user_vol:
                self._user_vol[key] = s.volume
                self._trim.setdefault(key, 1.0)
            # 检测外部音量变动：只记偏好、不调音量、不关自动
            last = self._last_set.get(key)
            if (
                last is not None
                and abs(s.volume - last[0]) > 0.02
                and now - last[1] > 0.3  # 0.3 秒内的变动视为均衡器自己的回写
            ):
                user_vol = self._user_vol.get(key, s.volume)
                self._smooth[key] = s.peak
                smooth = s.peak
                if abs(s.volume - user_vol) <= 0.02:
                    # 切歌/换源回弹：不改偏好、不发提示；慢速估计也要跟新歌走，
                    # 否则旧歌的响度会在慢速估计里残留约 20 秒。
                    self._slow_smooth[key] = s.peak
                    self._reset_chunk_avg(key, s.peak)  # 换歌回弹：新歌的平均从头算，旧歌不残留
                    self._last_set[key] = (s.volume, now)
                else:
                    if last[0] >= 0.05:
                        trim = self._trim.get(key, 1.0) * (s.volume / last[0])
                        self._trim[key] = max(0.2, min(2.0, trim))
                    else:
                        self._trim[key] = 1.0
                    self._user_vol[key] = s.volume
                    self._last_set[key] = (s.volume, now)
                    self.events.append(
                        "「%s」音量已按你手动调的新位置继续自动均衡，自动没有断开"
                        % name
                    )
            # 界面条形图用快有效峰值（实时显示，音量不动时条子照常动）
            self._effective[key] = smooth * s.volume
            # 触发检测：只看自动开着的应用；静音应用不参与、不触发、
            # 不拖基准——视频一小段没声音时，其他应用的音量就不会被拖动。
            if not self.enabled or not self.auto_apps.get(key, True):
                continue
            if s.peak >= 0.02:
                if key not in self._first_sound_time:
                    self._first_sound_time[key] = now
                if (key not in self._first_sound_done
                        and now - self._first_sound_time[key] >= self._first_sound_delay):
                    # 新程序首声：进入相位（立刻同步一次，随后 5 秒一次、3 分钟后固定）
                    self._first_sound_done.add(key)
                    self._phase_until = now + self._phase_duration
                    self._last_phase_sync = 0.0
                    self._phase_end_emitted = False
                    trigger = True
            else:
                # 出声中断：首声计时清零（短促爆音不算首声），已完成首声的不清，
                # 它之后靠 3 分钟周期触发，而不是一恢复出声就立刻再同步。
                self._first_sound_time.pop(key, None)
        # 消失的会话清掉触发类状态，避免长期运行里字典无限长大；
        # 偏好类状态（trim/user_vol）也一起清，重现时按新会话算。
        current_keys = {s.key for s in sessions}
        for store in (self._seen, self._first_sound_done):
            for k in list(store):
                if k not in current_keys:
                    store.discard(k)
        for d in (self._first_sound_time, self._last_sync, self._slow_smooth, self._avg_peak,
                  self._chunk_buf, self._chunks, self._avg_at_fix, self._drift_ticks,
                  self._smooth, self._effective, self._trim, self._user_vol,
                  self._last_set):
            for k in list(d):
                if k not in current_keys:
                    d.pop(k, None)
        self._reset_smooth = {k for k in self._reset_smooth if k in current_keys}
        # ---------- 基准（每轮都算，供界面标记线用；不调音量时也显示） ----------
        sounding = [s for s in sessions if s.peak >= 0.02]
        untrimmed = [s for s in sounding if self._trim.get(s.key, 1.0) == 1.0]
        def _eff_sync(s):
            raw = self._avg_peak.get(s.key, self._slow_smooth.get(s.key, self._smooth.get(s.key, s.peak)))
            return raw * s.volume
        seed = None
        if self.reference_key is not None:
            for s in sounding:
                if s.key == self.reference_key:
                    seed = s
                    break
        if seed is not None:
            # 指定基准：就是它自己（哪怕它被手动调过、音量已顶格），只受目标上限约束，
            # 不套“目标 60% 下限”——用户明说以它为准，低于下限也按它算。
            self.reference = min(_eff_sync(seed), self.target)
        elif untrimmed:
            # v8.15 分层：先取层号最小且非空的那一层，只在该层内跑
            # 原有最响/顶格锚点/目标上限/目标 60% 下限逻辑；高层只要有
            # 出声的未手动调过应用就赢，不管低层多响（例如浏览器小游戏
            # 当基准，音乐流媒体被拉下来拉平，游戏不再被音乐带高）。
            # 同步后真正拉平：层内基准就是该层最响的有效峰值，同步段
            # 会把该层内外的自动应用都向它看齐，不保留音乐略响的差距。
            best_tier = min(_reference_tier(s.name) for s in untrimmed)
            tier_apps = [s for s in untrimmed if _reference_tier(s.name) == best_tier]
            loudest = max(_eff_sync(s) for s in tier_apps)
            self.reference = min(loudest, self.target)
            ceiling = [_eff_sync(s) for s in tier_apps if s.volume >= 0.99]
            if ceiling:
                self.reference = min(self.reference, min(ceiling))
            self.reference = max(self.reference, self.target * 0.6)
        else:
            self.reference = self.target
        ref = self.reference
        # ---------- 漂移重校：相位已固定后，某应用长期响度偏离固定基线 ----------
        if (self.enabled and self._phase_until != 0.0 and now >= self._phase_until
                and self._phase_end_emitted):
            drifted = None
            for s in sounding:
                if not self.auto_apps.get(s.key, True):
                    continue
                base = self._avg_at_fix.get(s.key)
                cur = self._avg_peak.get(s.key, 0.0)
                if not base or base < 0.02 or cur < 0.02:
                    self._drift_ticks.pop(s.key, None)
                    continue
                ratio = cur / base
                if ratio < 0.70 or ratio > 1.43:
                    self._drift_ticks[s.key] = self._drift_ticks.get(s.key, 0) + 1
                    if self._drift_ticks[s.key] >= 30:  # 100ms tick × 30 ≈ 3 秒持续偏离
                        drifted = s
                        break
                else:
                    self._drift_ticks.pop(s.key, None)
            if drifted is not None:
                self._drift_ticks.clear()
                self._avg_at_fix.clear()
                self.start_phase(now)
                self.events.append("检测到「%s」响度漂移（换了更响/更轻的内容），已重新同步" % drifted.name)
        # 相位里：每 5 秒同步一次（_last_phase_sync==0 表示相位刚开始，立刻同步）
        # 必须有出声的自动应用才触发，否则没应用出声时每 5 秒空同步一次、
        # 状态栏会被“无需调整”刷屏。
        if self.enabled and now < self._phase_until:
            if self._last_phase_sync == 0.0 or now - self._last_phase_sync >= self._phase_interval:
                if any(s.peak >= 0.02 and self.auto_apps.get(s.key, True)
                       for s in sessions):
                    trigger = True
        # 相位刚结束：发一次“已固定”提示，之后不再发
        if (not self._phase_end_emitted and self._phase_until != 0.0
                and now >= self._phase_until):
            # 固定那一刻记下各出声应用的长时平均，作为漂移重校的基线
            for s in sounding:
                if self._avg_peak.get(s.key, 0.0) >= 0.02:
                    self._avg_at_fix[s.key] = self._avg_peak[s.key]
            self.events.append("响度已固定（下次拨开关、新程序出声或响度漂移时再同步）")
            self._phase_end_emitted = True
        # ---------- 第二段：触发时才同步一次，直接算到目标音量 ----------
        if self._sync_requested:
            # 用户主动请求：有出声的自动应用才做，否则留着等出声时做
            # （首声逻辑本身也会同步，所以留着也不会丢）。
            if any(s.peak >= 0.02 and self.auto_apps.get(s.key, True)
                   for s in sessions if self.enabled):
                trigger = True
        if not trigger or not self.enabled:
            if not trigger:
                self._sync_requested = False if not any(
                    s.peak >= 0.02 for s in sessions) else self._sync_requested
            return
        was_requested = self._sync_requested
        self._sync_requested = False
        if now < self._phase_until:
            self._last_phase_sync = now
        changed = []
        for s in sounding:
            key = s.key
            if not self.auto_apps.get(key, True):
                continue
            raw = self._avg_peak.get(key, self._slow_smooth.get(key, self._smooth.get(key, s.peak)))
            if raw < 0.02:
                continue
            ref_app = min(ref * self._trim.get(key, 1.0), 1.0)
            desired = max(0.05, min(1.0, ref_app / raw))
            self._last_sync[key] = now
            if abs(desired - s.volume) > 0.01:
                try:
                    set_session_volume(s.session, desired)
                    self._last_set[key] = (desired, now)
                    self._effective[key] = self._smooth.get(key, s.peak) * desired
                    changed.append(s.name)
                except Exception:
                    pass
        if changed:
            self.events.append("已同步响度：%s（相位内 5 秒后再同步，3 分钟后固定）" % "、".join(changed))
        elif was_requested:
            # 只有用户主动请求/相位开始那次才发“无需调整”确认；
            # 相位里每 5 秒的例行同步没变化时静默，否则状态栏每 5 秒刷一次。
            self.events.append("响度已同步（无需调整，相位内 5 秒后再同步，3 分钟后固定）")

    def user_set_volume(self, key, value):
        """界面滑杆是用户本人在调：同样记成偏好，不让下一轮均衡把它拉回去。
        偏好按“新音量 / 均衡器上次设的值”累乘；从 0 附近恢复时偏好归 1。"""
        last = self._last_set.get(key)
        if last is not None and last[0] >= 0.05 and abs(value - last[0]) > 0.02:
            trim = self._trim.get(key, 1.0) * (value / last[0])
            self._trim[key] = max(0.2, min(2.0, trim))
        elif last is not None and last[0] < 0.05:
            self._trim[key] = 1.0
        self._user_vol[key] = value
        self._reset_smooth.add(key)
        self._last_set[key] = (value, time.time())
