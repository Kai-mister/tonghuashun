"""Local Android shell client for the device's uiautomator2 JSON-RPC service."""
import json
import os
import subprocess
import time
from urllib.request import Request, urlopen

from strategy_worker import run
from ths.simulator import Simulator

MASK = dict(text=1,textMatches=4,className=16,packageName=0x80000,
            resourceId=0x200000,instance=0x1000000,description=64)


def rpc(method, *args):
    body = json.dumps(dict(jsonrpc="2.0", id=1, method=method, params=args)).encode()
    request = Request("http://[::1]:9008/jsonrpc/0", body, {"Content-Type":"application/json"})
    with urlopen(request, timeout=12) as response:
        result = json.load(response)
    if result.get("error"):
        raise RuntimeError(str(result["error"]))
    return result["result"]


class Element:
    def __init__(self, **attrs):
        self.attrs = attrs
        self.selector = dict(attrs, mask=sum(MASK[k] for k in attrs),
                             childOrSibling=[], childOrSiblingSelector=[])

    def __getitem__(self, index):
        return Element(**self.attrs, instance=index)

    @property
    def count(self):
        return rpc("count", self.selector)

    @property
    def exists(self):
        return rpc("exist", self.selector)

    def wait(self, timeout=3):
        return rpc("waitForExists", self.selector, int(timeout*1000))

    def get_text(self, timeout=2):
        if not self.wait(timeout):
            raise RuntimeError(f"未找到控件 {self.attrs}")
        return rpc("getText",self.selector)

    def set_text(self, value):
        if not rpc("setText",self.selector,value):
            raise RuntimeError("控件输入失败")

    def click(self, timeout=3):
        if not self.wait(timeout) or not rpc("click",self.selector):
            raise RuntimeError(f"无法点击 {self.attrs}")

    def click_exists(self, timeout=1):
        if self.wait(timeout):
            self.click()


class Device:
    def __call__(self, **kwargs):
        return Element(**kwargs)

    def dump_hierarchy(self):
        return rpc("dumpWindowHierarchy", False, 60)

    def press(self, key):
        rpc("pressKey", key)

    @property
    def info(self):
        return rpc("deviceInfo")

    def screen_on(self):
        rpc("wakeUp")
        env = dict(os.environ)
        env.pop("LD_LIBRARY_PATH", None)
        subprocess.run(["/system/bin/cmd", "window", "dismiss-keyguard"],
                       env=env, timeout=4, check=False, stdout=subprocess.DEVNULL)
        time.sleep(.4)

    def app_current(self):
        return {"package":rpc("deviceInfo")["currentPackageName"]}

    def app_start(self, pkg):
        env = dict(os.environ)
        env.pop("LD_LIBRARY_PATH", None)
        subprocess.run(["/system/bin/cmd", "activity", "start-activity", "-n",
                        pkg + "/.LogoEmptyActivity"], check=True, env=env, stdout=subprocess.DEVNULL)
        time.sleep(1)


class LocalTrader:
    def __init__(self):
        self.d = Device()

    def go_to_trade(self):
        pkg = Simulator.pkg
        if self.d.app_current()["package"] != pkg:
            return False
        marker = self.d(text="模拟练习区",packageName=pkg)
        if not marker.exists:
            self.d(text="交易",packageName=pkg).click()
            if marker.wait(1):
                return True
            self.d(text="模拟",packageName=pkg).click()
        return marker.wait(4)


if __name__ == "__main__":
    import logging
    import sys
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(message)s")
    trader = LocalTrader()
    if sys.argv[1:] == ["check"]:
        from stock_api import fetch_plans
        sim = Simulator(trader)
        print("plans", fetch_plans()["count"], "fills", sim.report(True), flush=True)
    else:
        run(trader,"state/strategy.sqlite3")
