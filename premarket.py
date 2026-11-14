"""按上海日期筛选当日买入计划，保留选中档位的风控价格。"""

import argparse
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_DOWN
import json
from zoneinfo import ZoneInfo

from stock_api import fetch_plans
from strategy_settings import validate


SHANGHAI = ZoneInfo("Asia/Shanghai")


def order_quantity(code, price, settings=None):
    settings = validate(settings or {})
    if code.startswith(("688", "689")):
        minimum, step, maximum = 200, 1, 100000
    elif code.startswith(("92", "43", "83", "87", "88")):
        minimum, step, maximum = 100, 1, 1000000
    elif code.startswith(("000", "001", "002", "003", "300", "301", "600", "601", "603", "605")):
        minimum, step, maximum = 100, 100, 1000000
    else:
        raise ValueError(f"无法确定 {code} 的申报单位")
    unit_cost = price * step
    low = max(minimum // step, int((Decimal(settings["min_amount"]) / unit_cost).to_integral_value(rounding=ROUND_CEILING)))
    high = min(maximum // step, int((Decimal(settings["max_amount"]) / unit_cost).to_integral_value(rounding=ROUND_FLOOR)))
    if low > high:
        return 0
    nearest = int((Decimal(settings["target_amount"]) / unit_cost).to_integral_value(rounding=ROUND_HALF_DOWN))
    return step * min(high, max(low, nearest))


def select_plans(stocks, buy_date, settings=None):
    settings = validate(settings or {})
    plans = []
    for stock in stocks:
        if stock["planned_buy_date"] != buy_date.isoformat():
            continue
        tier = "shallow" if settings["strategy"] == "aggressive" and stock.get("shallow") else "deep"
        levels = stock.get(tier)
        if not isinstance(levels, dict):
            raise ValueError(f"{stock['code']} 缺少 {tier} 价格")
        try:
            prices = {key: Decimal(str(levels[key])) for key in
                      ("buy_low", "buy_high", "stop_loss", "take_profit")}
            if not all(value.is_finite() for value in prices.values()):
                raise ValueError("价格必须为有限数值")
            if not 0 < prices["stop_loss"] < prices["buy_low"] <= prices["buy_high"] < prices["take_profit"]:
                raise ValueError("回调区间与止盈止损点不一致")
        except (KeyError, InvalidOperation, ValueError) as error:
            raise ValueError(f"{stock['code']} 的 {tier} 价格无效：{error}") from error
        limit = prices["buy_high"]
        quantity = order_quantity(stock["code"], limit, settings)
        sell_date = date.fromisoformat(stock["planned_sell_date"])
        plans.append({
            "buy_at": datetime.combine(buy_date, time.fromisoformat(settings["buy_time"]), SHANGHAI).isoformat(),
            "liquidate_at": datetime.combine(sell_date, time(14, 50), SHANGHAI).isoformat(),
            "limit_price": str(limit), "quantity": quantity,
            "order_value": str(quantity * limit),
            "skip_reason": None if quantity else "没有符合金额范围的可申报数量",
            "code": stock["code"], "planned_buy_date": stock["planned_buy_date"],
            "planned_sell_date": stock["planned_sell_date"], "tier": tier,
            **{key: str(value) for key, value in prices.items()},
        })
    return plans


def exit_progress(*, bought_filled, sold_filled, sell_open, available):
    """各数量来自已核对的成交和委托；available 是扣除冻结后的可卖余额。"""
    counts = (bought_filled, sold_filled, sell_open, available)
    if any(type(value) is not int or value < 0 for value in counts):
        raise ValueError("持仓和委托数量必须为非负整数")
    remaining = bought_filled - sold_filled
    if remaining < sell_open:
        raise ValueError("卖出成交和在途委托超过策略买入成交")
    return {
        "remaining": remaining,
        "open_quantity": sell_open,
        "can_submit": min(remaining - sell_open, available),
        "closed": bought_filled > 0 and remaining == 0,
    }


def exit_reason(plan, *, last_price, now, sellable_remaining, deadline=None):
    """输入已核对的策略持仓可卖余量和含时区的截止时刻。"""
    if deadline is None:
        deadline = datetime.fromisoformat(plan["liquidate_at"])
    if now.utcoffset() is None or deadline.utcoffset() is None:
        raise ValueError("监控时间和截止时间必须带时区")
    if sellable_remaining <= 0:
        return None
    if now >= deadline:
        return "deadline"
    if last_price is None:
        return None
    price = Decimal(str(last_price))
    if not price.is_finite() or price <= 0:
        raise ValueError("行情价格无效")
    if price <= Decimal(plan["stop_loss"]):
        return "stop_loss"
    if price >= Decimal(plan["take_profit"]):
        return "take_profit"
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, default=datetime.now(ZoneInfo("Asia/Shanghai")).date())
    args = parser.parse_args()
    print(json.dumps(select_plans(fetch_plans()["stocks"], args.date), indent=2, ensure_ascii=False))
