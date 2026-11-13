# 同花顺 Android 模拟仓自动化

电脑上运行 Python 服务，通过 ADB 操作指定 Android 设备上的同花顺。USB 真机和云手机使用同一套 REST 接口。服务和交易实现均随仓库提供。

## 本机 USB 调试

安装 Python 3.12 和 Android SDK Platform Tools，将 adb 加入 PATH。在仓库根目录创建虚拟环境并安装依赖。手机开启 USB 调试，连接数据线并允许该电脑调试。

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run.py devices
.venv/bin/python run.py check
.venv/bin/python run.py serve
```

默认选择唯一的 USB 设备。多台设备时可指定 `--serial 序列号`。检查命令验证设备状态、同花顺安装情况和 UI 自动化连接。

## 迁移到云手机

将仓库复制到能访问云手机 ADB 地址的控制机。安装 Python 3.12 和 Android SDK Platform Tools，让 adb 位于 PATH 中。按云厂商说明启用 ADB 调试、授权控制机，并建立所需的网络隧道。云手机内安装同花顺并登录所需账户。

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
# 将下列地址换成云平台提供的地址或隧道本地端口
.venv/bin/python run.py check --cloud 127.0.0.1:15555
.venv/bin/python run.py serve --cloud 127.0.0.1:15555
```

已通过厂商工具连接且出现在 adb devices 列表中的设备，也可直接使用 `--serial`。云平台需要支持 ADB 和 uiautomator2。服务监听控制机的 127.0.0.1:8000，端口可用 `--port` 修改。

## 调用

```sh
curl -fsS http://127.0.0.1:8000/
curl -fsS -X POST http://127.0.0.1:8000/ths/open
curl -fsS -X POST 'http://127.0.0.1:8000/ths/set_mode?mode=simulate'
curl -fsS http://127.0.0.1:8000/ths/positions
```

在 /docs 查看完整参数。账户、持仓、委托分别使用 GET /ths/account、/ths/positions、/ths/orders。买入、卖出和撤单分别使用 POST /ths/buy、/ths/sell、/ths/cancel。检查响应中的 success 和 error。交易接口的 success 表示界面操作结果，委托和成交情况以交易账户的记录为准。

交易页面定位沿用 Watery Traders（ths_adb_trader，MIT License）。云端与真机使用相同的同花顺版本有助于复用控件定位。

## 手机主动读取股票计划

在运行 Python 的设备上，将 Bearer 令牌保存到当前用户的私有文件
`~/.config/redis-racknerd/stock-api.token`。使用标准库客户端读取列表或单股详情：

```sh
python stock_api.py
python stock_api.py 002222
```

程序也可导入 `stock_api.fetch_plans()` 或 `stock_api.fetch_plans("002222")`。
返回值保留接口提供的两档价格和计划日期。读取计划不会触发交易。

## 生成当日策略计划

运行 `python premarket.py` 读取当日计划。浅回调优先，使用所选档位的 buy_high 作为限价。09:20 的单票计划按委托金额（不含费用）最接近 10,000 元计算，限制在 5,000 至 20,000 元之间。两个数量同样接近时取较小值，无可申报数量时标记跳过。planned_sell_date 的 14:50 是到期退出触发时刻，所有时间使用北京时间。此命令输出计划。实际模拟下单、委托和成交查询由下述执行进程处理。

## 真机模拟仓执行

PJX110 已安装独立 Android arm64 Python 运行时，目录为 `/data/local/tmp/ths-sim`。执行程序直接调用手机本地的 UI 服务，监听地址为 IPv6 回环地址。执行期间保持手机联网、解锁、同花顺可前台操作，避免与人工操作或另一个控制进程争用 UI。锁屏或系统休眠会影响准点执行。

- 程序在北京时间 09:19 预取计划，09:20 这一分钟确认当日买单。错过窗口不会在盘中补买。
- 提交确认前写入 SQLite 意图，回执记录合同号。模拟当日委托列表不显示合同号，按模拟账号、名称、方向、价格、数量和时间唯一匹配。无法唯一确定的委托保持待核对，跨日未核实的委托需要人工核对。模拟仓不支持历史委托查询。
- 已成交的策略买单从下一交易日监控，读取卖出页最新价和可卖数量。止盈、止损或到期日 14:50 触发后，使用模拟客户端卖出页显示的有效报价下限提交限价单。按累计成交更新策略余额，对未成交且报价已落后于新的下限的委托尝试撤改。下限委托是允许的最低卖价，实际成交取决于盘口。
- 当日成交明细接口为 `GET /ths/fills`。测试及人工持仓不会自动加入策略账本。
- 手机重启会结束执行进程，重新解锁后从设备 shell 运行 `sh /data/local/tmp/ths-sim/phone/background.sh`。日志、进程号和 SQLite 账本位于该目录的 `state/`。不要删除账本。
- USB 或云手机外部控制方式可通过 `run.py worker` 启动。每个模拟账户只使用一个执行进程及对应账本。

## Android 管理 App

在 PJX110 桌面打开「模拟仓管家」查看策略进程状态、盘前持仓核对和最近策略委托。暂停在当前一轮结束后生效，已有模拟委托继续有效；恢复沿用同一账本。管理 App 读取手机本机回环服务，不需要电脑或无线调试。重启手机后按上文重新启动 background.sh，同时恢复本机管理服务。

APK 位于 android/dist/sim-manager.apk。每台设备单独配对：在部署目录 state/manager.key 写入随机 32 字节的十六进制串，限制为 shell 用户可读，通过 ADB shell 向 cn.local.simmanager/.Pair 发送名为 key 的字符串。接收器仅接受具备系统 DUMP 权限的调用方。重装并清除数据后需要重新配对。
