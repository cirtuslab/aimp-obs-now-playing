#!/usr/bin/env python3
"""AIMP Now Playing -> OBS.

Run with a GUI:
    python main.py

Run headless (server + export files only):
    python main.py --headless
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from pathlib import Path

from aimp_obs import __version__
from aimp_obs.aimp_api import AimpClient, AlbumArtReceiver, CMD_UNREGISTER_NOTIFY
from aimp_obs.cover import CoverStore
from aimp_obs.paths import app_root
from aimp_obs.server import OverlayServer
from aimp_obs.settings import SettingsStore
from aimp_obs.state import StateHub


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AIMP Now Playing -> OBS")
    p.add_argument("--host", default="127.0.0.1", help="HTTP 服务监听地址 (默认 127.0.0.1)")
    p.add_argument("--port", type=int, default=None, help="HTTP 服务端口 (默认读取已保存设置)")
    p.add_argument("--export", default=None, help="导出 nowplaying.json / cover.png 等文件的目录")
    p.add_argument("--refresh", type=int, default=None, help="状态刷新间隔毫秒 (默认读取已保存设置)")
    p.add_argument("--headless", action="store_true", help="不显示 GUI，仅运行服务与导出")
    p.add_argument("--version", action="version", version=f"AIMP Now Playing → OBS {__version__}")
    return p.parse_args(argv)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    args = parse_args(argv)
    base = app_root()
    settings = SettingsStore()
    port = args.port if args.port is not None else settings.port
    refresh_ms = args.refresh if args.refresh is not None else settings.refresh_ms
    if args.export:
        export_dir = Path(args.export)
    elif settings.export_dir:
        export_dir = Path(settings.export_dir)
    else:
        export_dir = base / "export"

    client = AimpClient()
    receiver = AlbumArtReceiver()
    try:
        receiver.start()
    except Exception as exc:
        print(f"警告: 无法创建封面接收窗口: {exc}", file=sys.stderr)

    if client.connected and receiver.hwnd:
        try:
            client.register_notify(receiver.hwnd)
        except Exception:
            pass

    cover_store = CoverStore()
    state_hub = StateHub(client, receiver, cover_store, export_dir=export_dir)
    server = OverlayServer(state_hub, cover_store, host=args.host, port=port, config=settings.overlay)
    server_started = server.start()
    if server_started:
        print(f"OBS 浏览器源地址: {server.url}")
    else:
        print("警告: HTTP 服务启动失败", file=sys.stderr)
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(
            "警告: 服务监听在非回环地址，局域网内其他设备可以访问 /api/config 修改样式。",
            file=sys.stderr,
        )

    stop_event = threading.Event()
    poll_thread = threading.Thread(
        target=_poll_loop, args=(state_hub, refresh_ms, stop_event), daemon=True,
        name="StatePoller",
    )
    poll_thread.start()

    if args.headless:
        print("无 GUI 模式运行中 (Ctrl+C 退出)…")
        try:
            signal.signal(signal.SIGINT, lambda *_: stop_event.set())
            while not stop_event.wait(1):
                pass
        except KeyboardInterrupt:
            pass
    else:
        try:
            from aimp_obs.gui import App
            app = App(client, receiver, state_hub, cover_store, server, export_dir, refresh_ms, settings)
            app.mainloop()
        except Exception as exc:
            print(f"GUI 启动失败: {exc}", file=sys.stderr)
            print("正在以无 GUI 模式运行…", file=sys.stderr)
            try:
                signal.signal(signal.SIGINT, lambda *_: stop_event.set())
                while not stop_event.wait(1):
                    pass
            except KeyboardInterrupt:
                pass

    stop_event.set()
    if client.connected and receiver.hwnd:
        try:
            client.unregister_notify(receiver.hwnd)
        except Exception:
            pass
    server.stop()
    receiver.stop()
    return 0


def _poll_loop(state_hub, refresh_ms: int, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            state_hub.refresh()
        except Exception:
            pass
        stop_event.wait(max(100, refresh_ms) / 1000)


if __name__ == "__main__":
    sys.exit(main())
