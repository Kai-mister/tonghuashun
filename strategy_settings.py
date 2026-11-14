"""Validated, shared strategy settings."""
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

DEFAULTS = dict(target_amount="10000", min_amount="5000", max_amount="20000",
                buy_time="09:20", strategy="aggressive")


def validate(data):
    if not isinstance(data, dict):
        raise ValueError("设置必须是对象")
    result = dict(DEFAULTS, **data)
    for key in ("target_amount", "min_amount", "max_amount"):
        try:
            value = Decimal(str(result[key]))
        except InvalidOperation as error:
            raise ValueError("请输入有效金额") from error
        if not value.is_finite() or value <= 0:
            raise ValueError("金额必须为正数")
        result[key] = str(value)
    if not Decimal(result["min_amount"]) <= Decimal(result["target_amount"]) <= Decimal(result["max_amount"]):
        raise ValueError("金额须满足 最低 ≤ 建议 ≤ 最高")
    if not isinstance(result["buy_time"], str) or not re.fullmatch(r"(09|10|11|13|14):[0-5][0-9]", result["buy_time"]):
        raise ValueError("请输入 HH:MM 格式的交易时间")
    clock = result["buy_time"]
    if not ("09:15" <= clock <= "11:29" or "13:00" <= clock <= "14:59"):
        raise ValueError("挂单时间须在 09:15–11:29 或 13:00–14:59")
    if result["strategy"] not in ("aggressive", "conservative"):
        raise ValueError("策略选项无效")
    return {key: result[key] for key in DEFAULTS}


def load(path):
    path = Path(path)
    return validate(json.loads(path.read_text()) if path.exists() else {})


def save(path, data):
    path = Path(path)
    result = validate(data)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(result))
    temporary.replace(path)
    return result
