"""启动同花顺 USB / 云手机自动化服务。"""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


def adb(*args):
    result = subprocess.run(
        ["adb", *args], capture_output=True, text=True, timeout=30
    )
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return result.stdout.strip()


def select_device(args):
    if args.cloud:
        # 云平台有时提供本地隧道地址，必须使用供应商分配的完整端口。
        host, separator, port = args.cloud.rpartition(":")
        if not host or not separator or not port.isascii() or not port.isdigit() or not 1 <= int(port) <= 65535:
            raise ValueError("--cloud 需要 HOST:PORT")
        message = adb("connect", args.cloud)
        serial = args.cloud
    elif args.serial:
        serial = args.serial
        message = ""
    else:
        serial = adb("-d", "get-serialno")
        message = ""

    try:
        state = adb("-s", serial, "get-state")
        if state != "device":
            raise RuntimeError(state)
    except RuntimeError as error:
        raise RuntimeError(f"设备 {serial} 未就绪。{message} {error}") from error
    return serial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["devices", "check", "serve", "worker"])
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--serial", help="adb devices 中已连接的设备序列号")
    target.add_argument("--cloud", help="云手机 ADB 接入地址 HOST:PORT")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--state", default="~/.local/state/ths-sim/strategy.sqlite3")
    args = parser.parse_args()
    if not shutil.which("adb"):
        sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
        sdk = Path(sdk) if sdk else Path.home() / "Library/Android/sdk"
        os.environ["PATH"] = str(sdk / "platform-tools") + os.pathsep + os.environ.get("PATH", "")
    if args.command == "devices":
        print(adb("devices", "-l"))
        return
    serial = select_device(args)
    os.environ["ANDROID_SERIAL"] = serial
    from ths.config import config

    package = adb("-s", serial, "shell", "pm", "path", config.THS_PACKAGE)
    if not any(line.startswith("package:") for line in package.splitlines()):
        raise RuntimeError(f"{serial} 未检测到同花顺 {config.THS_PACKAGE}")
    if args.command == "check":
        from ths.trader import ThsTrader

        trader = ThsTrader()
        print(f"{serial} 已连接，已安装同花顺，当前前台应用：{trader.d.app_current().get('package')}")
        return
    if args.command == "worker":
        from ths.trader import ThsTrader
        from strategy_worker import run
        run(ThsTrader(), args.state)
        return
    import uvicorn
    from ths import app

    if app.trader is None:
        raise RuntimeError("uiautomator2 初始化失败，详见上方日志")
    uvicorn.run(app.app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.TimeoutExpired, ValueError) as error:
        sys.exit(f"启动失败：{error}")
