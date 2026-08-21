# dailyGetPrice

## 学习网站
https://www.shinnytech.com/

国内期货与股票的日线数据获取及量化策略分析工具集。

## 项目结构

```
dailyGetPrice/
├── strategy_stocks/
│   └── get_beyond_daily20.py           # 股票突破20日新高筛选
└── strategy_futures/
    ├── get_price_futures.py            # 期货日线数据获取 + 主力合约识别
    ├── pattern_fullscan_futures.py     # K线形态扫描
    └── daily_20_latest_open_futures.py # 海龟策略最新开仓信号
```

## 各模块说明

### `strategy_futures/get_price_futures.py` — 期货日线数据获取

通过 akshare 从新浪财经获取国内主要活跃期货品种主力合约的历史日线数据。

- 覆盖 55 个品种（黑色系、化工、有色金属、农产品）
- 自动识别主力合约（按持仓量选择），换月时自动切换并合并旧历史
- 增量追加模式：日常运行仅追加新日期数据，换月/首次才全量抓取
- 当日收盘后即可获取当天数据
- 输出：单品种 CSV、汇总 CSV、汇总 Excel（可选）、主力合约列表 CSV

```bash
python -m strategy_futures.get_price_futures            # 全部品种
python -m strategy_futures.get_price_futures RB0 I0     # 指定品种
python -m strategy_futures.get_price_futures --excel    # 额外生成Excel
python -m strategy_futures.get_price_futures --force    # 强制全量刷新
```

### `strategy_stocks/get_beyond_daily20.py` — 股票突破20日新高筛选

扫描沪深主板股票，筛选当天收盘价突破前20日最高价的标的。

- 默认从中证2000成分股中筛选
- 筛选条件：收盘价 > 20日最高价，且当日涨幅 ≥ 2%，收盘价 ≤ 30元
- 20线程并发获取数据
- 输出：`strategy_stocks_output/beyond_daily20.md`（突破股票列表）

```bash
python -m strategy_stocks.get_beyond_daily20
python -m strategy_stocks.get_beyond_daily20 000852   # 指定指数代码
```

### `strategy_futures/daily_20_latest_open_futures.py` — 最新开仓信号汇总

基于海龟策略，汇总所有品种的最新持仓状态和开仓信号。

- 对每个品种运行回测，判断最新一笔交易是否仍持仓
- 区分盈利持仓、亏损持仓、已平仓、无交易
- 计算当前浮盈/浮亏及10日出场通道
- 汇总最近5个交易日的新开仓品种
- 输出：`strategy_futures_output/latest_open.md`

```bash
python daily_20_latest_open_futures.py output_futures/futures_main_daily_20260730.csv
```

### `strategy_futures/pattern_fullscan_futures.py` — K线形态扫描

对全部期货品种扫描最新一根K线完成的经典形态。

- 识别 23 种经典K线形态：锤子线、流星线、十字星、吞没、孕线、早晨/黄昏之星、红三兵、三乌鸦、跳空缺口、岛形反转等
- 每种形态标注方向（多/空/中性）
- 输出：汇总表 + 命中品种详情及K线图表

```bash
python pattern_fullscan_futures.py output_futures/futures_main_daily_20260708.csv
```

## 依赖

```bash
pip install akshare pandas openpyxl mplfinance matplotlib
```