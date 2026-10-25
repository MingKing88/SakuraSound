"""VolRider 网页版后端：把音频核心暴露成 HTTP 接口，前端是纯静态页面。

运行（Windows）：
    python web\\server.py
然后浏览器打开 http://127.0.0.1:8000

接口：
    GET  /api/state    -> 会话、总音量、设备、均衡状态、事件
    POST /api/command  -> {"type": "session_volume"|"master_volume"|"default_device"
                          |"target"|"enabled"|"auto_app"|"autostart", ...}

mock 模式（无 Windows 音频环境时演示用）：
    python web\\server.py --mock
会模拟 3 个应用的响度起伏，前端可以完整预览；此模式不碰真实音频。
"""

import argparse
import json
import os
import queue
import random
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

WEB_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(WEB_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

POLL_S = 0.1


class AudioEngine(threading.Thread):
    """音频轮询线程：真实模式复用 volrider_core，mock 模式模拟数据。

    真实模式与桌面版 qt_app.py 的引擎同构：所有 pycaw 调用
    只发生在本线程，避免 COM 跨线程问题。
    """

    def __init__(self, mock=False):
        super().__init__(daemon=True)
        self.mock = mock
        self.cmd_queue = queue.Queue()
        self.lock = threading.Lock()
        self.state = {
            "sessions": [],
            "master": 1.0,
            "reference": 0.7,
            "devices": [],
            "default_device": None,
            "selftest_result": None,
            "events": [],
            "error": None,
            "autostart": False,
            "enabled": True,
            "target": 0.7,
            "phase": "idle",
            "mode": "mock" if mock else "real",
        }
        self.stop_flag = False
        self.core = None
        self.rider = None
        # 会话按会话键索引（实例标识优先，退回进程名#PID），显示名只用于界面；
        # 键解析见 _resolve_session（新命令带 key，老命令只有名字时按名字找第一个）。
        self._sessions_by_key = {}
        self._last_master_seen = None
        self._last_master_cmd = (None, 0.0)
        self._last_master_event = 0.0
        # 真实音频初始化失败时置起（绝不静默切到演示模式，见 run）：
        self.init_failed = False
        self.init_done = False
        self.init_error = None
        # 粘性错误（如开机自启动设置失败）：每轮成功 tick 后仍保留，不被清掉。
        self._sticky_error = None
        # 自检结果序号（每做一次自检加一，界面靠它和时间戳认出新结果）。
        self._selftest_seq = 0
        # ---- mock 状态 ----
        self._mock_apps = [
            {"name": "Chrome", "key": "mock:Chrome", "volume": 0.8, "peak": 0.5, "auto": True},
            {"name": "网易云音乐", "key": "mock:网易云音乐", "volume": 0.6, "peak": 0.3, "auto": True},
            {"name": "游戏", "key": "mock:游戏", "volume": 0.9, "peak": 0.7, "auto": True},
        ]
        self._mock_smooth = {}
        self._mock_devices = [
            {"id": "mock-speaker", "name": "扬声器 (Mock)"},
            {"id": "mock-headset", "name": "耳机 (Mock)"},
        ]
        self._mock_default = "mock-speaker"

    # ---------------------------------------------------------------- 真实模式

    def _real_init(self):
        import volrider_core as core

        self.core = core
        # 先验音频库：缺依赖时这里就报出真正原因，由 run() 如实上报，
        # 而不是初始化成功、界面却空空如也。
        core.require_audio()
        self.rider = core.Rider(target=0.7)
        try:
            with self.lock:
                self.state["autostart"] = core.is_autostart_enabled()
        except Exception:
            pass

    def _resolve_session(self, cmd):
        """按命令里的 key 找会话；老命令只有名字时，按名字找第一个。

        返回 (key, 会话快照) 或 (None, None)。
        """
        key = cmd.get("key")
        if key is not None:
            info = self._sessions_by_key.get(key)
            if info is not None:
                return key, info
        name = cmd.get("name")
        if name is not None:
            for k, info in self._sessions_by_key.items():
                if info.name == name:
                    return k, info
        return None, None

    def _real_commands(self):
        core = self.core
        while True:
            try:
                cmd = self.cmd_queue.get_nowait()
            except queue.Empty:
                return
            kind = cmd.get("type")
            try:
                if kind == "session_volume":
                    key, info = self._resolve_session(cmd)
                    if info is not None:
                        core.set_session_volume(info.session, float(cmd.get("value", 0)))
                        self.rider.user_set_volume(key, float(cmd.get("value", 0)))
                elif kind == "master_volume":
                    core.set_master_volume(float(cmd.get("value", 0)))
                    self._last_master_cmd = (float(cmd.get("value", 0)), time.time())
                elif kind == "default_device":
                    ok, roles = core.set_default_device_detailed(cmd.get("device_id", ""))
                    if ok:
                        msg = "已切换输出设备：%s" % cmd.get("device_name", "")
                        if not roles.get(0):
                            msg += "（控制台角色未生效）"
                        self.rider.emit(msg)
                    else:
                        self.rider.emit("切换失败：Windows 未公开接口在你的系统上不可用，"
                                        "请在系统声音设置里手动切换")
                elif kind == "selftest_device":
                    # 输出设备自检：结果进 state，界面弹框显示（不打命令行日志）。
                    try:
                        result = core.selftest_default_device()
                    except Exception as e:
                        result = {"device_id": None, "hresult_multimedia": None,
                                  "hresult_console": None, "verified_default_id": None,
                                  "ok": False,
                                  "error": "%s: %s" % (type(e).__name__, e)}
                    self._selftest_seq += 1
                    result = dict(result)
                    result["seq"] = self._selftest_seq
                    result["ts"] = time.time()
                    with self.lock:
                        self.state["selftest_result"] = result
                    self.rider.emit("输出设备自检完成")
                elif kind == "target":
                    # target 命令钳制到 0.1–1.0（滑杆本身只给 0.5–0.9，接口层再守一道）。
                    # 改目标不是等 20 分钟：立刻请求一次同步，否则改了看起来没用。
                    self.rider.target = max(0.1, min(1.0, float(cmd.get("value", 0.7))))
                    self.rider.request_sync()
                elif kind == "enabled":
                    # 拨开自动均衡开关：进入同步相位（立刻同步一次，随后 5 秒一次、
                    # 满 3 分钟后固定）；关掉则立刻停掉相位，不再同步。
                    self.rider.enabled = bool(cmd.get("value", True))
                    if self.rider.enabled:
                        self.rider.start_phase()
                    else:
                        self.rider.stop_phase()
                elif kind == "reference":
                    # 基准应用：key 为空 = 回到自动；key 按会话键匹配，界面恢复时按名也可
                    self.rider.set_reference(cmd.get("key") or None,
                                             cmd.get("name") or None)
                elif kind == "auto_app":
                    key, info = self._resolve_session(cmd)
                    if info is not None:
                        self.rider.set_auto(key, bool(cmd.get("value", True)),
                                            display=info.name)
                elif kind == "autostart":
                    try:
                        core.set_autostart(bool(cmd.get("value", False)))
                    except Exception as e:
                        # 开机自启动失败不能静默吞掉：记成粘性错误，状态栏会一直显示，
                        # 直到下一次设置成功（成功时清掉）。
                        err = "开机自启动设置失败：%s" % e
                        with self.lock:
                            self._sticky_error = err
                            self.state["error"] = err
                    else:
                        with self.lock:
                            self._sticky_error = None
                            self.state["autostart"] = bool(cmd.get("value", False))
            except Exception:
                pass

    def _real_tick(self, tick):
        core = self.core
        try:
            sessions = core.list_sessions()
            master, _mute = core.get_master_volume()
        except Exception as e:
            # 以前这里是静默 return，界面永远停在“正在读取”，查不出原因。
            # 现在把错误写进状态（前端显示）并打印到黑窗口，失败原因一目了然。
            err = "%s: %s" % (type(e).__name__, e)
            with self.lock:
                self.state["error"] = err
            print("音频读取失败：%s" % err, flush=True)
            return
        with self.lock:
            # 成功读到音频后，错误栏恢复成粘性错误（平时是 None，即不显示）。
            self.state["error"] = self._sticky_error
        self._sessions_by_key = {s.key: s for s in sessions}
        self.rider.tick(sessions)
        events = list(self.rider.events)
        # 相位状态供界面显示：同步中剩几秒固定 / 已固定 / 已关 / 待触发。
        _now = time.time()
        if not self.rider.enabled:
            _phase = "off"
        elif _now < self.rider._phase_until:
            _phase = "syncing:%d" % max(0, int(self.rider._phase_until - _now + 0.999))
        elif self.rider._phase_until != 0.0:
            _phase = "fixed"
        else:
            _phase = "idle"
        if self._last_master_seen is not None and abs(master - self._last_master_seen) > 0.01:
            cmd_val, cmd_time = self._last_master_cmd
            own = cmd_val is not None and abs(master - cmd_val) < 0.01 and time.time() - cmd_time < 1.0
            if not own and time.time() - self._last_master_event > 1.0:
                events.append("检测到系统总音量变化：%d%%" % round(master * 100))
                self._last_master_event = time.time()
        self._last_master_seen = master
        if tick % 5 == 1:
            try:
                devices = core.list_devices()
                default_id = core.get_default_device_id()
            except Exception:
                devices, default_id = [], None
            with self.lock:
                if devices:
                    self.state["devices"] = devices
                if default_id:
                    self.state["default_device"] = default_id
        with self.lock:
            self.state["sessions"] = [
                {"name": s.name, "key": s.key, "volume": s.volume, "peak": s.peak,
                 # 条形图显示有效峰值（原声峰值×音量），即耳朵听到的相对大小；
                 # 原声峰值本身不随音量变，拿它当条子会误导“音量变了条子不动”。
                 "smooth": self.rider._effective.get(s.key, s.peak * s.volume),
                 "auto": self.rider.auto_apps.get(s.key, True)}
                for s in sessions
            ]
            self.state["master"] = master
            self.state["reference"] = self.rider.reference
            self.state["enabled"] = self.rider.enabled
            self.state["target"] = self.rider.target
            self.state["phase"] = _phase
            self.state["reference_key"] = self.rider.reference_key
            self.state["reference_name"] = self.rider.reference_name
            if events:
                self.state["events"] = events[-3:]

    # ---------------------------------------------------------------- mock 模式

    def _mock_commands(self):
        while True:
            try:
                cmd = self.cmd_queue.get_nowait()
            except queue.Empty:
                return
            kind = cmd.get("type")

            def _find_mock(cmd):
                key = cmd.get("key")
                if key is not None:
                    for app in self._mock_apps:
                        if app["key"] == key:
                            return app
                name = cmd.get("name")
                for app in self._mock_apps:
                    if app["name"] == name:
                        return app
                return None

            if kind == "session_volume":
                app = _find_mock(cmd)
                if app is not None:
                    app["volume"] = float(cmd.get("value", 0))
            elif kind == "master_volume":
                with self.lock:
                    self.state["master"] = float(cmd.get("value", 0))
            elif kind == "default_device":
                self._mock_default = cmd.get("device_id", self._mock_default)
                with self.lock:
                    self.state["events"] = ["已切换输出设备：%s" % cmd.get("device_name", "")]
            elif kind == "selftest_device":
                # 演示模式不执行真实切换，只返回说明，让弹框链路能走通。
                self._selftest_seq += 1
                with self.lock:
                    self.state["selftest_result"] = {
                        "mock": True,
                        "seq": self._selftest_seq,
                        "ts": time.time(),
                        "device_id": self._mock_default,
                        "hresult_multimedia": None,
                        "hresult_console": None,
                        "verified_default_id": self._mock_default,
                        "ok": None,
                        "error": None,
                    }
                    self.state["events"] = ["输出设备自检完成（演示模式）"]
            elif kind == "target":
                # target 命令钳制到 0.1–1.0（与真实模式一致）。
                with self.lock:
                    self.state["target"] = max(0.1, min(1.0, float(cmd.get("value", 0.7))))
            elif kind == "enabled":
                with self.lock:
                    self.state["enabled"] = bool(cmd.get("value", True))
            elif kind == "auto_app":
                app = _find_mock(cmd)
                if app is not None:
                    app["auto"] = bool(cmd.get("value", True))
            elif kind == "autostart":
                with self.lock:
                    self.state["autostart"] = bool(cmd.get("value", False))

    def _mock_tick(self):
        target = self.state["target"]
        enabled = self.state["enabled"]
        sounding = []
        for app in self._mock_apps:
            # 响度随机游走，模拟真实播放的起伏
            app["peak"] = min(1.0, max(0.0, app["peak"] + random.uniform(-0.08, 0.08)))
            prev = self._mock_smooth.get(app["key"], app["peak"])
            self._mock_smooth[app["key"]] = max(app["peak"], prev * 0.85)
            if app["peak"] >= 0.02:
                sounding.append(app)
        ref = target
        if sounding:
            ref = min(max(self._mock_smooth[a["key"]] for a in sounding), target)
        if enabled:
            for app in sounding:
                if not app["auto"]:
                    continue
                smooth = self._mock_smooth[app["key"]]
                if smooth > ref * 1.15:
                    app["volume"] = max(0.05, app["volume"] * (ref / smooth) ** 0.5)
                elif smooth < ref * 0.6 and app["volume"] < 1.0:
                    app["volume"] = min(1.0, app["volume"] * 1.05)
        with self.lock:
            self.state["sessions"] = [
                {"name": a["name"], "key": a["key"], "volume": a["volume"], "peak": a["peak"],
                 "smooth": self._mock_smooth.get(a["key"], a["peak"]), "auto": a["auto"]}
                for a in self._mock_apps
            ]
            self.state["reference"] = ref
            self.state["phase"] = "off" if not enabled else "idle"
            self.state["devices"] = self._mock_devices
            self.state["default_device"] = self._mock_default

    # ---------------------------------------------------------------- 主循环

    def run(self):
        if not self.mock:
            try:
                import comtypes

                comtypes.CoInitialize()
            except Exception:
                pass
            try:
                self._real_init()
                self.init_done = True
            except Exception as e:
                # 真实音频初始化失败：如实记下来，不静默切到演示模式。
                # 演示模式只在 --mock 显式开启时才进；桌面版会弹框明说原因，
                # 网页版 main() 会直接报错退出。
                self.init_failed = True
                self.init_error = "%s: %s" % (type(e).__name__, e)
                with self.lock:
                    self.state["error"] = self.init_error
                    self.state["mode"] = "failed"
                print("真实音频初始化失败：%s" % self.init_error, flush=True)
        tick = 0
        try:
            while not self.stop_flag:
                tick += 1
                if self.mock:
                    self._mock_commands()
                    self._mock_tick()
                elif self.init_failed:
                    # 初始化失败后不再轮询，等主线程处理（弹框或退出）。
                    time.sleep(POLL_S)
                else:
                    self._real_commands()
                    self._real_tick(tick)
                time.sleep(POLL_S)
        finally:
            if not self.mock:
                try:
                    import comtypes

                    comtypes.CoUninitialize()
                except Exception:
                    pass


def make_handler(engine):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=WEB_DIR, **kwargs)

        def log_message(self, *args):
            pass

        def _send_json(self, obj):
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/api/state":
                with engine.lock:
                    self._send_json(dict(engine.state))
            else:
                super().do_GET()

        def do_POST(self):
            if self.path == "/api/command":
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length > 0 else b"{}"
                try:
                    cmd = json.loads(raw.decode("utf-8"))
                except Exception:
                    cmd = {}
                engine.cmd_queue.put(cmd)
                self._send_json({"ok": True})
            else:
                self.send_response(404)
                self.end_headers()

    return Handler


def main():
    parser = argparse.ArgumentParser(description="VolRider 网页版后端")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--mock", action="store_true", help="模拟音频数据（演示/非 Windows 环境）")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    args = parser.parse_args()

    engine = AudioEngine(mock=args.mock)
    engine.start()
    if not args.mock:
        # 等真实初始化出结果（失败时不进演示，直接报错退出）。
        for _ in range(20):
            if engine.init_failed or engine.init_done:
                break
            time.sleep(0.1)
        if engine.init_failed:
            print("真实音频初始化失败：%s" % engine.init_error, flush=True)
            print("自查：确认在 Windows 10/11 上运行、音频服务正常、文件解压完整；"
                  "演示请加 --mock。", flush=True)
            engine.stop_flag = True
            return 1
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(engine))
    url = "http://127.0.0.1:%d" % args.port
    print("VolRider v8.1（Qt 桌面版 · 新界面）", flush=True)
    print("VolRider 前端已启动：%s  （按 Ctrl+C 退出）" % url, flush=True)
    print("模式：%s" % ("mock 演示" if engine.mock else "真实音频"), flush=True)
    # 懒人关键一步：服务器已经开始监听，直接帮用户打开浏览器，
    # 不用他再手动敲地址。打不开也不崩溃，只打印地址让他手动开。
    if not args.no_browser:
        try:
            import webbrowser

            if not webbrowser.open(url):
                print("浏览器没有自动打开，请手动访问：%s" % url)
        except Exception:
            print("浏览器没有自动打开，请手动访问：%s" % url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        engine.stop_flag = True
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
