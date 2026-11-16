"""读取手机执行端使用的股票计划。"""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    # 鉴权请求只发给配置的服务地址。
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_plans(code=None):
    url = "https://192.255.236.236:8000/api/stocks"
    if code is not None:
        if not re.fullmatch(r"[0-9]{6}", code):
            raise ValueError("股票代码应为六位数字")
        url += "/" + code

    token = (Path.home() / ".config/redis-racknerd/stock-api.token").read_text().strip()
    if not token:
        raise ValueError("股票接口令牌文件为空")
    request = Request(url, headers={"Authorization": "Bearer " + token})
    with build_opener(NoRedirect()).open(request, timeout=15) as response:
        data = json.load(response)
    if not isinstance(data, dict):
        raise ValueError("股票接口返回格式异常")
    if code is None and not isinstance(data.get("stocks"), list):
        raise ValueError("列表响应缺少 stocks 数组")
    if code is not None and data.get("code") != code:
        raise ValueError("详情响应与请求的股票代码不符")
    return data


def quote_symbol(code):
    if not re.fullmatch(r"[0-9]{6}", code):
        raise ValueError("行情代码应为六位数字")
    if code.startswith(("6",)):
        return "sh" + code
    if code.startswith(("0", "3")):
        return "sz" + code
    if code.startswith(("4", "8", "92")):
        return "bj" + code
    raise ValueError("不支持的行情代码：" + code)


def parse_quotes(text, codes, now):
    from datetime import datetime
    from decimal import Decimal
    from zoneinfo import ZoneInfo
    expected = {quote_symbol(code): code for code in codes}
    quotes = {}
    for symbol, payload in re.findall(r'v_([a-z]{2}[0-9]{6})="([^"]*)"', text):
        if symbol not in expected:
            continue
        fields = payload.split("~")
        try:
            code = expected[symbol]
            if fields[2] != code:
                continue
            price = Decimal(fields[3])
            stamp = datetime.strptime(fields[30], "%Y%m%d%H%M%S").replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            age = (now - stamp).total_seconds()
            if not price.is_finite() or price <= 0 or not -5 <= age <= 90:
                continue
            quotes[code] = dict(last=str(price), at=stamp.isoformat())
        except (IndexError, ValueError, ArithmeticError):
            continue
    return quotes


def fetch_quotes(codes, now=None):
    """Batch Tencent quotes; never forward plan API credentials to this host."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    codes = sorted(set(codes))
    result = {}
    for start in range(0, len(codes), 50):
        batch = codes[start:start + 50]
        url = "https://qt.gtimg.cn/q=" + ",".join(quote_symbol(c) for c in batch)
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with build_opener(NoRedirect()).open(request, timeout=5) as response:
            text = response.read(1024 * 1024).decode("gbk")
        result.update(parse_quotes(text, batch, now or datetime.now(ZoneInfo("Asia/Shanghai"))))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("code", nargs="?", help="六位股票代码，省略时读取列表")
    try:
        print(json.dumps(fetch_plans(parser.parse_args().code), ensure_ascii=False, indent=2))
    except (URLError, OSError, ValueError) as error:
        sys.exit(f"读取股票计划失败：{error}")
