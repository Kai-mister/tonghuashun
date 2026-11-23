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
    native = os.environ.get('THS_NATIVE') == '1'
    headers = {"Content-Type":"application/json"}
    if native:
        from pathlib import Path
        headers['Authorization'] = 'Bearer ' + Path('state/manager.key').read_text().strip()
    request = Request("http://127.0.0.1:19008/jsonrpc/0" if native else "http://[::1]:9008/jsonrpc/0", body, headers)
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
        for attempt in range(3):
            try:
                if not self.wait(timeout):
                    raise RuntimeError(f"未找到控件 {self.attrs}")
                return rpc("getText", self.selector)
            except RuntimeError as error:
                if "StaleObjectException" not in str(error) or attempt == 2:
                    raise
                time.sleep(.2)


    def set_text(self, value):
        if not rpc("setText",self.selector,value):
            raise RuntimeError("控件输入失败")

    def click(self, timeout=3):
        if not self.wait(timeout):
            raise RuntimeError(f"无法点击 {self.attrs}")
        if os.environ.get('THS_NATIVE') == '1':
            # Some THS labels acknowledge ACTION_CLICK without invoking their parent.
            # Use one physical gesture on the freshly observed target, never both.
            import re
            import xml.etree.ElementTree as ET
            names = dict(resourceId='resource-id', packageName='package', className='class',
                         text='text', description='content-desc')
            nodes = []
            for n in ET.fromstring(rpc('dumpWindowHierarchy', False, 60)).iter('node'):
                if all(k == 'instance' or (re.fullmatch(v, n.get('text', '')) if k == 'textMatches'
                       else n.get(names[k], '') == v) for k,v in self.attrs.items()):
                    nodes.append(n)
            index = self.attrs.get('instance', 0)
            if index >= len(nodes):
                raise RuntimeError(f"点击前控件已变化 {self.attrs}")
            bounds = list(map(int, re.findall(r'-?\d+', nodes[index].get('bounds', ''))))
            if len(bounds) != 4 or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
                raise RuntimeError('点击目标边界无效')
            x,y = (bounds[0]+bounds[2])//2, (bounds[1]+bounds[3])//2
            clicked = rpc('swipe', x,y,x,y,0)
        else:
            clicked = rpc('click', self.selector)
        if not clicked:
            raise RuntimeError(f"无法点击 {self.attrs}")

    def click_exists(self, timeout=1):
        if self.wait(timeout):
            self.click()


class Device:
    def __call__(self, **kwargs):
        return Element(**kwargs)

    def dump_hierarchy(self):
        return rpc("dumpWindowHierarchy", False, 60)

    def swipe(self, x1, y1, x2, y2):
        rpc("swipe", x1, y1, x2, y2, 30)

    def press(self, key):
        rpc("pressKey", key)

    @property
    def info(self):
        return rpc("deviceInfo")

    def screen_on(self):
        rpc("wakeUp")
        if os.environ.get('THS_NATIVE') == '1':
            return
        env = dict(os.environ)
        env.pop("LD_LIBRARY_PATH", None)
        subprocess.run(["/system/bin/cmd", "window", "dismiss-keyguard"],
                       env=env, timeout=4, check=False, stdout=subprocess.DEVNULL)
        time.sleep(.4)

    def app_current(self):
        return {"package":rpc("deviceInfo")["currentPackageName"]}

    def app_start(self, pkg):
        if os.environ.get('THS_NATIVE') == '1':
            rpc('appStart', pkg)
            time.sleep(1)
            return
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
        simulated = self.d(resourceId=pkg+":id/page_title_view", text="模拟炒股")
        if simulated.exists:
            return True
        marker = self.d(text="模拟练习区",packageName=pkg)
        # A cold start may restore a stack of stock detail screens.
        for _ in range(8):
            if marker.exists or self.d(text="交易",packageName=pkg).exists:
                break
            back = self.d(resourceId=pkg+":id/backButton")
            if back.exists:
                back.click()
            else:
                self.d.press('back')
            time.sleep(.4)
            if self.d.app_current().get('package') != pkg:
                return False
        if not marker.exists:
            self.d(text="交易",packageName=pkg).click()
            if simulated.wait(1) or marker.wait(1):
                return True
            self.d(text="模拟",packageName=pkg).click()
        return simulated.wait(1) or marker.wait(4)


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
