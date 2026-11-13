"""Adapter for the Android simulated account's order form and daily reports."""
import re
import time
import xml.etree.ElementTree as ET
from decimal import Decimal


class Simulator:
    pkg = "com.hexin.plat.android"

    def __init__(self, trader):
        self.trader = trader
        self.d = trader.d
        self.account = None

    def field(self, key, **kwargs):
        return self.d(resourceId=f"{self.pkg}:id/{key}", **kwargs)

    def text(self, value):
        return self.d(packageName=self.pkg, text=value)

    def title(self, value):
        return self.field("page_title_view", text=value).exists

    def check_account(self):
        current = self.field("account_info_view").get_text(timeout=2)
        if not current or (self.account and current != self.account):
            raise RuntimeError("模拟账号已变化")
        self.account = current

    def tab(self, name):
        if self.d.app_current().get("package") != self.pkg:
            self.d.app_start(self.pkg)
        if self.title("当日委托") or self.title("当日成交"):
            self.d.press("back")
        if not (self.title("模拟炒股") and self.field("btn", text=name).exists):
            if not self.trader.go_to_trade():
                raise RuntimeError("无法确认模拟练习区")
            self.text(name).click(timeout=3)
        else:
            self.check_account()
            self.field("btn", text=name).click(timeout=3)
        if not self.field("page_title_view", text="模拟炒股").wait(4):
            raise RuntimeError("页面缺少模拟炒股标题")
        self.check_account()

    def form(self, side, code):
        if side not in ("买入", "卖出") or not re.fullmatch(r"[0-9]{6}", code):
            raise ValueError("证券代码或方向无效")
        self.tab(side)
        stock = self.field("auto_stockcode")
        stock.set_text(code)
        button = side[0] + " " + side[1] + "(模拟炒股)"
        for _ in range(15):
            if (stock.get_text() == code and self.text(button).exists
                    and self.field("stockname").exists and self.field("txt_zuixin").exists):
                # Wait for the name, available shares and quote to update together.
                time.sleep(.4)
                break
            time.sleep(.2)
        name = self.field("stockname").get_text(timeout=2)
        if not self.title("模拟炒股") or not name or stock.get_text() != code:
            raise RuntimeError("股票或模拟仓未确认")
        return name, button

    def position(self, code):
        return self.quote(code)

    def quote(self, code):
        name, _ = self.form("卖出", code)
        self.field("chicang", text="持仓").click(timeout=2)
        time.sleep(.3)
        nodes = self.nodes()
        def field_text(key):
            return next(n.get("text", "") for n in nodes
                        if n.get("resource-id") == self.pkg + ":id/" + key)
        if field_text("auto_stockcode") != code or field_text("stockname") != name:
            raise RuntimeError("行情与持仓查询的证券不符")
        available = re.fullmatch(r"可卖([\d,]+)股", field_text("couldbuy"))
        if available is None:
            raise RuntimeError("无法读取可卖数量")
        shares = int(available[1].replace(",", ""))
        total = self.holding_total(nodes, name, shares)
        if shares > total:
            raise RuntimeError("可卖数量超过总持仓")
        return dict(name=name, last=field_text("txt_zuixin"), limit=field_text("dietingprice"),
                    total=total, available=shares)

    def holding_total(self, nodes, name, available):
        if any(n.get("text")=="没有持仓数据" for n in nodes) and available == 0:
            return 0
        if not any(n.get("text")=="持仓/可用" for n in nodes):
            raise RuntimeError("持仓表头未加载")
        for table in nodes:
            if table.get("resource-id") != self.pkg + ":id/recyclerview_id":
                continue
            complete = bool(len(table)) and table.get("scrollable") == "false"
            for row in table:
                cells = [n.get("text") for n in row.iter("node") if n.get("text")]
                if len(cells) != 8:
                    complete = False
                    continue
                if cells[0] == name:
                    total, free = (v.replace(",", "") for v in cells[4:6])
                    if total.isdigit() and free.isdigit() and int(free) == available:
                        return int(total)
                    raise RuntimeError("持仓行与卖出页数量不一致")
            if complete and not available:
                return 0
        raise RuntimeError(f"无法从持仓列表核对 {name} 的持仓/可用数量")

    def submit(self, side, code, quantity, price, before_confirm=None):
        name, button = self.form(side, code)
        edits = self.d(packageName=self.pkg, className="android.widget.EditText")
        if edits.count != 3 or int(quantity) <= 0:
            raise ValueError("数量或交易表单无效")
        if price is None:
            price = edits[1].get_text()
        price = Decimal(str(price))
        if not price.is_finite() or price <= 0:
            raise ValueError("委托价格无效")
        edits[1].set_text(format(price, "f"))
        edits[2].set_text(str(quantity))
        self.check_account()
        if not self.title("模拟炒股") or self.field("auto_stockcode").get_text() != code:
            raise RuntimeError("委托模拟仓或代码未确认")
        self.text(button).click(timeout=3)
        labels = [n.get("text", "").strip() for n in self.nodes() if n.get("text")]
        def value(key):
            return labels[labels.index(key) + 1]
        try:
            valid = ("委托" + side + "确认" in labels and value("代码") == code
                     and value("名称") == name and int(value("数量")) == int(quantity)
                     and Decimal(value("价格")) == price)
            if not valid:
                raise ValueError("确认页与委托参数不符")
            if before_confirm:
                before_confirm(name)
        except Exception:
            self.text("取消").click_exists(timeout=1)
            raise
        self.text("确认" + side).click(timeout=3)
        receipt = self.d(packageName=self.pkg, textMatches=r".*合同号.*\d+.*").get_text(timeout=6)
        contract = re.search(r"合同号\D*(\d+)", receipt)
        if not contract:
            raise RuntimeError("委托回执待核对")
        self.text("确定").click(timeout=2)
        return dict(success=True, mode="simulate", contract=contract[1], name=name,
                    code=code, side=side, quantity=int(quantity), price=str(price))

    def nodes(self):
        return [n for n in ET.fromstring(self.d.dump_hierarchy()).iter("node")
                if n.get("package") == self.pkg]

    def report(self, fills=False, cancel_page=False):
        self.tab("撤单" if cancel_page else "查询")
        title = "当日成交" if fills else "当日委托"
        if not cancel_page:
            self.text(title).click(timeout=3)
            if not self.field("page_title_view", text=title).wait(4):
                raise RuntimeError("查询页面未加载")
            if fills:
                self.field("tab_name", text="当日成交").click(timeout=2)
        self.check_account()
        time.sleep(.4)
        nodes = self.nodes()
        # The smallest common ancestor of the named columns is one record.
        rows = []
        parents = {child: node for node in nodes for child in node}
        for node in nodes:
            if node.get("resource-id") != self.pkg + ":id/result0":
                continue
            row = node
            while row in parents:
                row = parents[row]
                columns = {n.get("resource-id", "").split("/")[-1]: n.get("text")
                           for n in row.iter("node") if n.get("text")}
                if "result7" in columns:
                    break
            item = dict(name=columns["result0"], time=columns["result1"],
                        side=columns["result6"], price=columns["result2"],
                        quantity=int(columns["first_tv"]))
            if fills:
                item["amount"] = columns["result7"]
            else:
                item.update(filled=int(columns["second_tv"]), status=columns["result7"])
            rows.append(item)
        return rows

    def cancel(self, expected, code=None):
        rows = self.report(cancel_page=True)
        keys = ("name", "time", "side", "price", "quantity")
        matches = [row for row in rows if all(row[k] == expected[k] for k in keys)]
        if len(matches) != 1 or matches[0]["status"] not in ("未成交", "部分成交", "已报"):
            raise RuntimeError("没有唯一可撤委托")
        selector = self.field("result1", text=expected["time"])
        if selector.count != 1 or not self.title("模拟炒股"):
            raise RuntimeError("撤单行不唯一或模拟仓未确认")
        selector.click()
        def detail(field):
            return self.field(field).get_text(timeout=2).split()[-1]
        if not (self.text("委托撤单确认").exists and detail("stockname_textview")==expected["name"]
                and detail("option_textview")=="撤"+expected["side"]+"单"
                and (code is None or detail("stockcode_textview")==code)
                and Decimal(detail("orderprice_textview"))==Decimal(expected["price"])
                and int(detail("ordernumber_textview"))==expected["quantity"]):
            self.text("取消").click_exists(timeout=1)
            raise RuntimeError("撤单确认参数不符")
        self.field("option_chedan").click()
        return dict(success=True, mode="simulate", order=expected)
