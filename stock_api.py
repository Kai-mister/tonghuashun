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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("code", nargs="?", help="六位股票代码，省略时读取列表")
    try:
        print(json.dumps(fetch_plans(parser.parse_args().code), ensure_ascii=False, indent=2))
    except (URLError, OSError, ValueError) as error:
        sys.exit(f"读取股票计划失败：{error}")
