# trader.py
import uiautomator2 as u2
import time
import logging
import re
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable, Literal
from functools import wraps
from ths.config import config


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 耗时测量装饰器
def timer(func: Callable) -> Callable:
    """
    装饰器，用于测量方法执行的耗时（秒级，有小数点）
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            return result
        finally:
            end_time = time.time()
            elapsed = end_time - start_time
            logger.info(f"⌛ 方法 {func.__name__} 执行耗时: {elapsed:.3f} 秒")
    return wrapper

TradeMode = Literal["simulate"]

class ThsTrader:
    def __init__(self):
        self.device_serial = config.DEVICE_SERIAL
        self.d = None
        self.package = config.THS_PACKAGE
        self.trade_mode: TradeMode = "simulate"
        self.save_screenshot: bool = False
        self.connect()

    @timer
    def connect(self):
        """连接设备"""
        try:
            logger.info(f"正在连接设备: {self.device_serial}")
            self.d = u2.connect(self.device_serial)

            # 测试连接
            info = self.d.info
            logger.info(f"✅ 连接成功: {info.get('productName')}")
            logger.info(f"Android版本: {info.get('version')}")
            logger.info(f"屏幕尺寸: {info.get('displayWidth')}x{info.get('displayHeight')}")

            return True
        except Exception as e:
            logger.error(f"❌ 连接失败: {e}")
            raise

    @timer
    def wait(self, seconds: float = None):
        """等待"""
        time.sleep(seconds or config.PAGE_LOAD_TIMEOUT)

    @timer
    def screenshot(self, name: str = None) -> str:
        """截图"""
        if not self.save_screenshot:
            return ""

        if name is None:
            name = f"ths_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"

        path = config.SCREENSHOT_DIR / name
        self.d.screenshot(str(path))
        logger.info(f"📸 截图已保存: {path}")
        return str(path)

    # ==================== 基本操作 ====================
    @timer
    def click_button_by_text(self, text: str, timeout: int = None, instance: int = 0) -> bool:
        """通过文字点击按钮"""
        timeout = timeout or config.DEFAULT_TIMEOUT
        logger.info(f"点击按钮: {text}")

        # 自动匹配所有按钮 + 文字
        elem = self.d(className="android.widget.Button", text=text, instance=instance)
        if elem.wait(timeout=timeout):
            elem.click()
            return True

        # 如果Button没找到，自动重试TextView（兼容弹窗）
        elem = self.d(className="android.widget.TextView", text=text, instance=instance)
        if elem.wait(timeout=timeout):
            elem.click()
            return True

        logger.warning(f"未找到按钮: {text}")
        return False
    @timer
    def click_by_text(self, text: str, timeout: int = None, instance: int = 0) -> bool:
        """通过文字点击"""
        timeout = timeout or config.DEFAULT_TIMEOUT
        logger.info(f"点击: {text}")

        elem = self.d(text=text, instance=instance)
        if elem.wait(timeout=timeout):
            elem.click()
            return True

        logger.warning(f"未找到: {text}")
        return False

    @timer
    def click_by_desc(self, desc: str, timeout: int = None) -> bool:
        """通过描述点击"""
        timeout = timeout or config.DEFAULT_TIMEOUT
        elem = self.d(description=desc)
        if elem.wait(timeout=timeout):
            elem.click()
            return True
        return False

    @timer
    def click_by_xpath(self, xpath: str) -> bool:
        """通过XPath点击"""
        try:
            self.d.xpath(xpath).click()
            return True
        except:
            return False

    @timer
    def input_text(self, text: str, instance: int = 0) -> bool:
        """输入文本"""
        edit = self.d(className="android.widget.EditText", instance=instance)
        if edit.exists:
            edit.clear_text()
            edit.set_text(text)
            logger.info(f"输入: {text}")
            return True
        return False

    @timer
    def get_text(self, instance: int = 0, className: str = "android.widget.TextView") -> str:
        """获取文本"""
        elem = self.d(className=className, instance=instance)
        if elem.exists:
            return elem.get_text()
        return ""

    # ==================== 后退导航功能 ====================

    @timer
    def back(self, times: int = 1) -> bool:
        """
        后退操作
        times: 后退次数
        """
        for i in range(times):
            logger.info(f"后退操作 ({i + 1}/{times})")
            self.d.press("back")
            self.wait(0.5)  # 每次后退后等待页面加载

        return True

    @timer
    def back_to_home(self, max_back: int = 10) -> bool:
        """
        一直后退直到回到首页
        max_back: 最大后退次数，防止死循环
        """
        logger.info("尝试返回首页")

        for i in range(max_back):
            # 检查是否已经在首页
            if self._is_home_page():
                logger.info(f"已到达首页，后退了{i}次")
                return True

            # 执行后退
            self.d.press("back")
            self.wait(0.5)

        logger.warning(f"后退{max_back}次后仍未到达首页")
        return False

    @timer
    def _is_home_page(self) -> bool:
        """判断是否在同花顺首页"""
        # 检查首页特有的元素（底部导航栏）
        home_indicators = ["自选", "行情", "资讯", "交易", "我的"]

        for indicator in home_indicators:
            if self.d(text=indicator).exists:
                return True

        return False

    @timer
    def back_to_trade_main(self) -> bool:
        """
        返回到交易主页面（买入/卖出/持仓/撤单等选项页）
        """
        logger.info("返回交易主页面")

        max_back = 5
        for i in range(max_back):
            if self._is_trade_main_page():
                logger.info(f"已到达交易主页面，后退了{i}次")
                return True

            self.d.press("back")
            self.wait(0.5)

        logger.warning("未能返回交易主页面")
        return False

    @timer
    def _is_trade_main_page(self) -> bool:
        """判断是否在交易主页面"""
        return self.d.app_current().get("package") == self.package and all(
            self.d(text=text, packageName=self.package).exists
            for text in ("模拟练习区", "买入", "卖出", "持仓", "撤单", "查询")
        )

    @timer
    def back_from_buy(self) -> bool:
        """从买入页面返回交易主页面"""
        logger.info("从买入页面返回")

        # 尝试点击返回按钮

        # 尝试点击返回按钮
        if self.click_by_text("返回", timeout=2):
            self.wait(1)
            return True

        # 尝试点击取消
        if self.click_by_text("取消", timeout=2):
            self.wait(1)
            return True
        self.wait(1)
        # 最后使用系统返回
        return self.back()

    @timer
    def back_from_sell(self) -> bool:
        """从卖出页面返回交易主页面"""
        return self.back_from_buy()  # 逻辑相同

    @timer
    def back_from_position_detail(self) -> bool:
        """从持仓详情页返回持仓列表"""
        logger.info("从持仓详情页返回")
        return self.back()

    @timer
    def back_to_trade_from_positions(self) -> bool:
        """从持仓列表返回交易主页面"""
        logger.info("从持仓列表返回交易主页面")
        return self.back()

    # ==================== 应用控制 ====================

    @timer
    def open_app(self) -> Dict[str, Any]:
        """打开同花顺"""
        logger.info("打开同花顺")
        self.d.app_start(self.package)
        self.wait(3)
        return {"success": True, "message": "应用已启动"}

    @timer
    def close_app(self) -> Dict[str, Any]:
        """关闭同花顺"""
        logger.info("关闭同花顺")
        self.d.app_stop(self.package)
        return {"success": True, "message": "应用已关闭"}

    @timer
    def restart_app(self) -> Dict[str, Any]:
        """重启同花顺"""
        logger.info("重启同花顺")
        self.close_app()
        self.wait(1)
        return self.open_app()

    # ==================== 交易导航 ====================

    @timer
    def go_to_trade(self) -> bool:
        """进入交易页面"""
        if self._is_trade_main_page():
            return True
        if self.d.app_current().get("package") != self.package:
            return False
        if self.click_by_text("交易", timeout=3) or self.click_by_desc("交易", timeout=3):
            self.wait(1)
        if not self._is_trade_main_page():
            if not self.click_by_text("模拟", timeout=3):
                return False
            self.wait(2)
        return self._is_trade_main_page()

    def go_to_trade_main(self) -> bool:
        return self.go_to_trade()

    @timer
    def set_trade_mode(self, mode: str = "simulate") -> bool:
        return mode == "simulate" and self.go_to_trade()

    # ==================== 账户信息 ====================

    @timer
    def get_account_summary(self) -> Dict[str, Any]:
        """
        获取账户概览信息
        返回: 总资产、浮动盈亏、总市值、当日参考盈亏
        """
        result = {
            "success": False,
            "mode": self.trade_mode,
            "total_asset": None,
            "float_profit": None,
            "total_market_value": None,
            "daily_profit": None,
            "screenshot": None,
            "raw_data": {}
        }

        try:
            logger.info(f"当前交易模式: {self.trade_mode}")

            # 确保在交易页面
            if not self.go_to_trade():
                raise Exception("无法进入交易页面")


            # 截图保存现场
            result["screenshot"] = self.screenshot("account_summary.png")

            # 等待本地网络加载
            self.wait(2)

            # 获取所有文本
            result = self.get_account_summary_result()
            if "total_asset" not in result.keys():
                self.wait(2)
                result = self.get_account_summary_result()

        except Exception as e:
            logger.error(f"获取账户概览失败: {e}")
            result["error"] = str(e)
            result["screenshot"] = self.screenshot("account_error.png")

        return result

    def get_account_summary_result(self) -> Dict[str, Any]:
        # 获取所有文本
        result = {
            "success": False,
            "mode": self.trade_mode,
            "raw_data": {}
        }
        all_texts = []
        # 先拿到数量，再精准遍历，不浪费时间
        # 先拿到控件总数（关键！不卡、不等）
        count = self.d(className="android.widget.TextView").count

        # 根据数量精准遍历，0 等待
        for i in range(count):
            try:
                tv = self.d(className="android.widget.TextView", instance=i)
                if tv.exists:  # 瞬间判断，不等待20秒
                    t = tv.get_text()
                    if t and t.strip():
                        all_texts.append(t.strip())
            except Exception as e:
                logger.error(f"获取文本失败: {e}")
        logger.warning(f"所有元素文本: {all_texts}")
        if len(all_texts) <= 30:
            logger.warning("可能是网络问题未找到任何文本信息，等待2秒后重试")
            return result

        result["raw_data"]["all_texts"] = all_texts[:30]

        # 解析各类资产信息
        for i, text in enumerate(all_texts):
            # 总资产
            if "总资产" in text and i + 1 < len(all_texts):
                result["total_asset"] = all_texts[i + 1]

            # 浮动盈亏
            if "浮动盈亏" in text and i + 1 < len(all_texts):
                result["float_profit"] = all_texts[i + 1]

            # 总市值
            if "总市值" in text and i + 2 < len(all_texts):
                result["total_market_value"] = all_texts[i + 2]

            # 当日盈亏
            if "当日参考盈亏" in text and i + 1 < len(all_texts):
                result["daily_profit"] = all_texts[i + 1]

        result["success"] = True
        logger.info(f"账户概览获取成功")
        return result

    # ==================== 持仓管理 ====================

    @timer
    def go_to_positions(self) -> bool:
        """进入持仓页面"""
        if not self.go_to_trade():
            return False

        if self.click_by_text("持仓", timeout=5):
            self.wait(2)
            return True

        if self.click_by_text("持仓查询", timeout=3):
            self.wait(2)
            return True

        return False

    @timer
    def get_positions(self) -> Dict[str, Any]:
        """
        获取持仓信息
        返回: 持仓列表
        """
        result = {
            "success": False,
            "mode": self.trade_mode,
            "positions": [],
            "summary": {},
            "screenshot": None
        }

        try:
            if not self.go_to_positions():
                raise Exception("无法进入持仓页面")

            # 截图
            result["screenshot"] = self.screenshot("positions.png")

            # 获取所有文本
            all_texts = []
            for tv in self.d(className="android.widget.TextView"):
                if tv.exists:
                    text = tv.get_text()
                    if text and len(text) < 30:  # 过滤长文本
                        all_texts.append(text)

            # 解析持仓
            positions = []
            current_pos = {}

            for i, text in enumerate(all_texts):
                # 识别股票代码（6位数字）
                if re.match(r'^\d{6}$', text):
                    if current_pos:
                        positions.append(current_pos)
                    current_pos = {"code": text}

                # 股票名称（2-4个汉字）
                elif re.match(r'^[\u4e00-\u9fa5]{2,4}$', text) and current_pos:
                    current_pos["name"] = text

                # 数量（纯数字）
                elif re.match(r'^\d+$', text) and current_pos and "quantity" not in current_pos:
                    current_pos["quantity"] = text

                # 价格（带小数点的数字）
                elif re.match(r'^[\d,]+\.\d{2}$', text) and current_pos:
                    if "price" not in current_pos:
                        current_pos["price"] = text.replace(',', '')
                    elif "cost" not in current_pos:
                        current_pos["cost"] = text.replace(',', '')

                # 盈亏（带负号的数字）
                elif re.match(r'^-?[\d,]+\.\d{2}$', text) and current_pos:
                    current_pos["profit"] = text.replace(',', '')

            # 添加最后一个
            if current_pos:
                positions.append(current_pos)

            result["positions"] = positions
            result["success"] = True
            logger.info(f"获取到 {len(positions)} 条持仓记录")

            # 从持仓页面返回交易主页面
            self.back_to_trade_from_positions()

        except Exception as e:
            logger.error(f"获取持仓失败: {e}")
            result["error"] = str(e)
            result["screenshot"] = self.screenshot("positions_error.png")

        return result

    @timer
    def get_position_detail(self, index: int = 0) -> Dict[str, Any]:
        """
        获取单个持仓的详细信息
        index: 持仓列表中的索引
        """
        result = {
            "success": False,
            "mode": self.trade_mode,
            "position": {},
            "screenshot": None
        }

        try:
            if not self.go_to_positions():
                raise Exception("无法进入持仓页面")

            # 点击指定持仓
            list_view = self.d(className="android.widget.ListView")
            if list_view.exists:
                items = list_view.child()
                if len(items) > index:
                    items[index].click()
                    self.wait(2)

                    # 截图
                    result["screenshot"] = self.screenshot("position_detail.png")

                    # 获取详情页信息
                    detail_info = self._parse_position_detail()
                    result["position"] = detail_info
                    result["success"] = True

                    # 返回持仓列表
                    self.back_from_position_detail()
                else:
                    raise Exception(f"没有第{index + 1}个持仓")
            else:
                raise Exception("没有持仓数据")

        except Exception as e:
            logger.error(f"获取持仓详情失败: {e}")
            result["error"] = str(e)

        return result

    @timer
    def _parse_position_detail(self) -> Dict[str, Any]:
        """解析持仓详情页信息"""
        info = {}

        texts = []
        for tv in self.d(className="android.widget.TextView"):
            if tv.exists:
                text = tv.get_text()
                if text:
                    texts.append(text)

        for i, text in enumerate(texts):
            if "股票名称" in text and i + 1 < len(texts):
                info["name"] = texts[i + 1]
            elif "股票代码" in text and i + 1 < len(texts):
                info["code"] = texts[i + 1]
            elif "持仓数量" in text and i + 1 < len(texts):
                info["quantity"] = texts[i + 1]
            elif "可用数量" in text and i + 1 < len(texts):
                info["available"] = texts[i + 1]
            elif "成本价" in text and i + 1 < len(texts):
                info["cost_price"] = texts[i + 1]
            elif "现价" in text and i + 1 < len(texts):
                info["current_price"] = texts[i + 1]
            elif "盈亏" in text and i + 1 < len(texts):
                info["profit"] = texts[i + 1]
            elif "盈亏比例" in text and i + 1 < len(texts):
                info["profit_ratio"] = texts[i + 1]

        return info
    @timer
    def get_all_texts(self):
        all_texts = []
        # 先拿到数量，再精准遍历，不浪费时间
        # 先拿到控件总数（关键！不卡、不等）
        count = self.d(className="android.widget.TextView").count

        # 根据数量精准遍历，0 等待
        for i in range(count):
            try:
                tv = self.d(className="android.widget.TextView", instance=i)
                if tv.exists:  # 瞬间判断，不等待20秒
                    t = tv.get_text()
                    if t and t.strip():
                        all_texts.append(t.strip())
            except Exception as e:
                logger.error(f"获取文本失败: {e}")
        logger.warning(f"所有元素文本: {all_texts}")
        return all_texts

    def click_search_stock(self, num):
        self.wait(2)
        logger.info(f"点击搜索结果中的第{num}个股票")

        all_texts = []
        # 先拿到数量，再精准遍历，不浪费时间
        # 先拿到控件总数（关键！不卡、不等）
        count = self.d(className="android.widget.TextView").count

        # 根据数量精准遍历，0 等待
        for i in range(count):
            try:
                tv = self.d(className="android.widget.TextView", instance=i)
                if tv.exists:  # 瞬间判断，不等待20秒
                    t = tv.get_text()
                    if t and t.strip():
                        all_texts.append(t.strip())
            except Exception as e:
                logger.error(f"获取文本失败: {e}")
        logger.warning(f"所有元素文本: {all_texts}")

        for i, text in enumerate(all_texts):
            # 搜索结果
            if "搜索结果" in text and i + num - 1 + 1 < len(all_texts):
                self.click_by_text(all_texts[i + 1])

        # list_view = self.d(className="android.widget.ListView")
        # if list_view.exists:
        #     items = list_view.child()
        #     if len(items) > num:
        #         items[num].click()
        #         self.wait(1)
        #     else:
        #         raise Exception(f"没有第{num + 1}个股票")
        # else:
        #     raise Exception("没有搜索结果")

    # ==================== 交易操作 ====================

    def _sim_call(self, method, *args):
        from ths.simulator import Simulator
        try:
            return method(Simulator(self), *args)
        except Exception as error:
            return {"success": False, "mode": "simulate", "error": str(error)}

    def buy(self, code, price, quantity, mode=None):
        if mode not in (None, "simulate"):
            return {"success": False, "error": "仅支持模拟交易"}
        return self._sim_call(lambda sim: sim.submit("买入", code, quantity, price))

    def sell(self, code, price, quantity, mode=None):
        if mode not in (None, "simulate"):
            return {"success": False, "error": "仅支持模拟交易"}
        return self._sim_call(lambda sim: sim.submit("卖出", code, quantity, price))

    def get_orders(self, order_type="today"):
        if order_type != "today":
            return {"success": False, "error": "模拟账户不支持历史委托查询"}
        return self._sim_call(lambda sim: {"success": True, "mode": "simulate", "orders": sim.report()})

    def get_fills(self):
        return self._sim_call(lambda sim: {"success": True, "mode": "simulate", "fills": sim.report(True)})

    def cancel_order(self, order_index=0):
        def cancel(sim):
            rows = [r for r in sim.report(cancel_page=True) if r["status"] in ("未成交", "部分成交", "已报")]
            return sim.cancel(rows[order_index])
        return self._sim_call(cancel)

    @timer
    def find_buttons(self) -> List[Dict[str, Any]]:
        """查找所有可点击按钮"""
        buttons = []

        # 查找所有可点击的TextView
        for elem in self.d(className="android.widget.TextView", clickable=True):
            if elem.exists and elem.info.get('text'):
                buttons.append({
                    "text": elem.info['text'],
                    "bounds": elem.info.get('bounds', {}),
                    "resource_id": elem.info.get('resourceName', '')
                })

        # 查找Button
        for elem in self.d(className="android.widget.Button"):
            if elem.exists and elem.info.get('text'):
                buttons.append({
                    "text": elem.info['text'],
                    "bounds": elem.info.get('bounds', {}),
                    "resource_id": elem.info.get('resourceName', '')
                })

        return buttons

    @timer
    def dump_ui(self) -> str:
        """导出UI结构"""
        xml = self.d.dump_hierarchy()
        path = config.SCREENSHOT_DIR / f"ui_dump_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xml"
        with open(path, "w", encoding="utf-8") as f:
            f.write(xml)
        return str(path)

    @timer
    def get_current_activity(self) -> str:
        """获取当前Activity"""
        try:
            current = self.d.app_current()
            return current.get('activity', 'unknown')
        except:
            return "unknown"