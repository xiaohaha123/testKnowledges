# 期货海龟策略(短期20日)设计文档

## 1. 策略定义

| 项目 | 说明 |
|---|---|
| 名称 | TurtleDaily20 |
| 品种 | 国内期货主力合约(螺纹钢、铁矿石等) |
| 频率 | 日线 |
| 方向 | 双向(多+空) |
| 类型 | 趋势跟踪, 中长线持仓 |
| 核心逻辑 | 突破20日最高价做多, 跌破20日最低价做空; 跌破10日最低价平多, 突破10日最高价平空 |

### 1.1 系统概览

```
海龟交易法则(简化版)核心组件:

  1) 入场: 当日盘中突破20日最高价+1tick做多, 跌破20日最低价-1tick做空
  2) 出场: 10日反向突破(系统出场)
  不加仓, 不止损, 每次固定1手
```

### 1.2 入场规则

```
做多入场: 当日 high > max(high[-20:-1])
  → 突破价 = 20日最高价 + 1tick
  → 建立1手多头, 入场价 = 突破价

做空入场: 当日 low < min(low[-20:-1])
  → 突破价 = 20日最低价 - 1tick
  → 建立1手空头, 入场价 = 突破价

例: 前20日最高价=2123, 品种tick=1
  → 当日最高价触及2124 → 入场做多@2124

> "前20日" = 当前K线之前的20根日线, 不含当日
> 用当日high/low判断是否突破(盘中可能触及), 用突破价+1tick作为入场价
> 日线回测中无法知道盘中精确路径, 假设: 若high>突破位则成交
```

### 1.3 出场规则(系统出场)

```
多头出场: 当日 low < min(low[-10:-1])
  → 出场价 = 10日最低价 - 1tick
  → 全部平掉多头持仓

空头出场: 当日 high > max(high[-10:-1])
  → 出场价 = 10日最高价 + 1tick
  → 全部平掉空头持仓

> 出场用10日反向突破, 无止损, 纯系统出场
> 入场用high/low判断突破, 出场也用high/low判断
> 出场价 = 突破位±1tick, 而非收盘价
```

---

## 2. 数据需求

| 字段 | 类型 | 说明 |
|---|---|---|
| date | str | 日期 YYYY-MM-DD |
| open | float | 开盘价 |
| high | float | 最高价 |
| low | float | 最低价 |
| close | float | 收盘价 |
| volume | int | 成交量 |

数据源: 可直接复用 `get_price.py` 输出的 8列 MetaStock CSV

---

## 3. 代码架构

```
dailyGetPrice/
├── strategy/
│   ├── __init__.py
│   ├── config.py              # 参数配置
│   ├── bar.py                 # K线数据结构
│   ├── signal.py              # 20日/10日突破信号
│   ├── engine.py              # 回测引擎
│   ├── analyzer.py            # 绩效分析
│   └── data_loader.py         # 数据加载(复用get_price)
└── books/量化交易/量化策略/daily_20.md   # 本文档
```

### 3.1 config.py

```python
class Config:
    # 策略参数
    entry_breakout = 20        # 入场突破天数
    exit_breakout = 10         # 出场突破天数
    tick_size = 1              # 最小变动价位(按品种设置)

    # 回测参数
    initial_capital = 1000000  # 初始资金
    commission_pct = 0.0001    # 手续费率
    contract_multiplier = 10   # 合约乘数
    lots = 1                   # 固定1手

    # 数据
    data_file = "RB2609.csv"
```

### 3.2 bar.py

```python
class Bar:
    __slots__ = ["date", "open", "high", "low", "close", "volume"]

    def __init__(self, date: str, o, h, l, c, v):
        self.date = date
        self.open = float(o)
        self.high = float(h)
        self.low = float(l)
        self.close = float(c)
        self.volume = int(v)
```

### 3.3 signal.py — 突破信号

```python
class BreakoutSignal:
    """海龟突破信号: 20日入场 + 10日出场"""

    def __init__(self, entry_period: int = 20, exit_period: int = 10):
        self.entry_period = entry_period
        self.exit_period = exit_period

    def entry_signal(self, bars: list[Bar], idx: int) -> str:
        """
        入场信号: 当日high突破20日最高价做多, 当日low跌破20日最低价做空
        返回: "long" / "short" / "none"
        """
        if idx < self.entry_period:
            return "none"
        recent = bars[idx - self.entry_period : idx]
        upper = max(b.high for b in recent)
        lower = min(b.low for b in recent)
        cur = bars[idx]
        if cur.high > upper:
            return "long"
        if cur.low < lower:
            return "short"
        return "none"

    def exit_signal(self, bars: list[Bar], idx: int, direction: str) -> bool:
        """
        出场信号: 当日low跌破10日最低价平多, 当日high突破10日最高价平空
        返回: True=应平仓
        """
        if idx < self.exit_period:
            return False
        recent = bars[idx - self.exit_period : idx]
        cur = bars[idx]
        if direction == "long" and cur.low < min(b.low for b in recent):
            return True
        if direction == "short" and cur.high > max(b.high for b in recent):
            return True
        return False
```

### 3.4 engine.py — 回测引擎

```python
class Position:
    """持仓: 固定1手, 无止损"""

    def __init__(self, direction: str, entry_price: float, entry_date: str):
        self.direction = direction
        self.entry_price = entry_price
        self.entry_date = entry_date

    def pnl(self, exit_price: float, mul: int) -> float:
        if self.direction == "long":
            return (exit_price - self.entry_price) * mul
        return (self.entry_price - exit_price) * mul


class Trade:
    __slots__ = ["direction", "entry_price", "exit_price", "pnl",
                 "reason", "entry_date", "exit_date"]

    def __init__(self, direction, entry_price, exit_price, pnl,
                 reason, entry_date, exit_date):
        self.direction = direction
        self.entry_price = entry_price
        self.exit_price = exit_price
        self.pnl = pnl
        self.reason = reason
        self.entry_date = entry_date
        self.exit_date = exit_date


class BacktestEngine:
    """海龟回测引擎(1手, 不加仓, 无止损)"""

    def __init__(self, config: Config):
        self.cfg = config
        self.signal = BreakoutSignal(config.entry_breakout, config.exit_breakout)
        self.position = None
        self.equity = config.initial_capital
        self.trades = []

    def run(self, bars: list[Bar]) -> list[Trade]:
        for i in range(len(bars)):
            if i < self.cfg.entry_breakout:
                continue

            # 1) 有持仓 → 检查系统出场(10日反向突破)
            if self.position and self.signal.exit_signal(bars, i, self.position.direction):
                self._close(bars, i, "exit_signal")
                continue

            # 2) 无持仓 → 检查入场信号(20日突破)
            if not self.position:
                sig = self.signal.entry_signal(bars, i)
                if sig in ("long", "short"):
                    self._open(sig, bars, i)

        if self.position:
            self._close(bars, len(bars) - 1, "end_of_data")

        return self.trades

    def _open(self, direction, bars, idx):
        tick = self.cfg.tick_size
        recent = bars[idx - self.cfg.entry_breakout : idx]
        if direction == "long":
            price = max(b.high for b in recent) + tick
        else:
            price = min(b.low for b in recent) - tick
        self.position = Position(direction, price, bars[idx].date)
        self._deduct_commission(price)

    def _close(self, bars, idx, reason):
        tick = self.cfg.tick_size
        bar = bars[idx]
        if reason == "exit_signal":
            recent = bars[idx - self.cfg.exit_breakout : idx]
            if self.position.direction == "long":
                price = min(b.low for b in recent) - tick
            else:
                price = max(b.high for b in recent) + tick
        else:
            price = bar.close

        raw_pnl = self.position.pnl(price, self.cfg.contract_multiplier)
        comm = price * self.cfg.contract_multiplier * self.cfg.commission_pct
        net_pnl = raw_pnl - comm
        self.equity += net_pnl

        self.trades.append(Trade(
            direction=self.position.direction,
            entry_price=self.position.entry_price,
            exit_price=price,
            pnl=net_pnl,
            reason=reason,
            entry_date=self.position.entry_date,
            exit_date=bar.date))
        self.position = None

    def _deduct_commission(self, price):
        comm = price * self.cfg.contract_multiplier * self.cfg.commission_pct
        self.equity -= comm
```

### 3.5 analyzer.py

```python
class Analyzer:
    def __init__(self, trades: list[Trade], initial_capital: float):
        self.trades = trades
        self.initial = initial_capital

    def summary(self) -> dict:
        total = len(self.trades)
        if total == 0:
            return {"总交易次数": 0}

        wins = [t for t in self.trades if t.pnl > 0]
        losses = [t for t in self.trades if t.pnl <= 0]
        total_pnl = sum(t.pnl for t in self.trades)

        cum = [0]
        for t in self.trades:
            cum.append(cum[-1] + t.pnl)
        peak = 0
        max_dd = 0
        for v in cum:
            peak = max(peak, v)
            max_dd = max(max_dd, peak - v)

        reasons = {}
        for t in self.trades:
            reasons[t.reason] = reasons.get(t.reason, 0) + 1

        win_pnl = sum(t.pnl for t in wins)
        loss_pnl = abs(sum(t.pnl for t in losses))

        return {
            "总交易次数": total,
            "盈利次数": len(wins),
            "亏损次数": len(losses),
            "胜率": f"{len(wins)/total*100:.1f}%",
            "总盈亏": f"{total_pnl:.2f}",
            "盈利总额": f"{win_pnl:.2f}",
            "亏损总额": f"{loss_pnl:.2f}",
            "盈亏比": f"{win_pnl/loss_pnl:.2f}" if loss_pnl else "N/A",
            "单笔最大盈利": f"{max(t.pnl for t in self.trades):.2f}",
            "单笔最大亏损": f"{min(t.pnl for t in self.trades):.2f}",
            "最大回撤": f"{max_dd:.2f}",
            "收益率": f"{total_pnl/self.initial*100:.1f}%",
            "出场原因分布": reasons,
        }

    def equity_curve(self) -> list[tuple]:
        curve = []
        eq = self.initial
        for t in self.trades:
            eq += t.pnl
            curve.append((t.exit_date, eq))
        return curve
```

### 3.6 data_loader.py — 复用get_price

```python
from strategy.bar import Bar

def load_from_metastock_csv(path: str) -> list[Bar]:
    """直接读取 get_price.py 输出的8列MetaStock CSV"""
    bars = []
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            parts = line.strip().split(",")
            if len(parts) < 8:
                continue
            d, o, h, l, c, v = parts[2], parts[3], parts[4], parts[5], parts[6], parts[7]
            if len(d) == 8:
                d = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            if not o:
                continue
            bars.append(Bar(date=d, o=o, h=h, l=l, c=c, v=v))
    return bars
```

---

## 4. 调用流程

```python
from strategy.config import Config
from strategy.data_loader import load_from_metastock_csv
from strategy.engine import BacktestEngine
from strategy.analyzer import Analyzer

cfg = Config()
bars = load_from_metastock_csv(cfg.data_file)
engine = BacktestEngine(cfg)
trades = engine.run(bars)
result = Analyzer(trades, cfg.initial_capital).summary()

for k, v in result.items():
    print(f"{k}: {v}")
```

---

## 5. 逐根推进示例

```
假设: 合约乘数10, tick=1, 固定1手

Day 1-20:   无信号
Day 21:     前20日最高价=2123, 当日high=2125 > 2123 → 突破
            入场做多@2124 (= 2123+1tick)
            持仓: 1手多头

Day 22-35:  无出场信号, 持仓不动

Day 36:     前10日最低价=2090, 当日low=2088 < 2090 → 系统出场
            出场@2089 (= 2090-1tick)
            亏损 = (2089 - 2124) × 10 × 1 = -350

另一场景:
Day 21:     做多入场@2124
Day 22-50:  趋势上行, 持仓不动
Day 51:     前10日最低价=2350, 当日low=2348 < 2350 → 系统出场
            出场@2349 (= 2350-1tick)
            盈利 = (2349 - 2124) × 10 × 1 = +2250
```

---

## 6. 关键特征

### 6.1 为什么胜率低但能赚钱

```
海龟策略典型特征:
  胜率: 30-40% (大部分突破是假突破, 小亏)
  盈亏比: 3:1 以上 (少数大趋势赚大钱, 覆盖多次小亏)
  核心逻辑: "截断亏损, 让利润奔跑"
  → 20日突破捕捉趋势起点
  → 10日出场给趋势足够空间
  → 无止损, 纯靠系统出场(信任趋势跟踪逻辑)
```

### 6.2 参数敏感性

| 参数 | 默认值 | 敏感度 | 说明 |
|---|---|---|---|
| 入场突破 | 20日 | 高 | 短→信号多假突破; 长→信号少但可靠 |
| 出场突破 | 10日 | 高 | 短→出场快截断利润; 长→回吐多 |
| tick_size | 1 | 低 | 影响入场/出场价偏移, 不影响信号 |

### 6.3 回测陷阱

| 陷阱 | 说明 | 本策略如何处理 |
|---|---|---|
| 未来函数 | 用了未产生数据 | lookback = bars[i-20:i], 不含当前bar |
| 入场价≠收盘价 | 用突破价+1tick入场, 非收盘价 | 当日high>突破位即成交, 入场价=突破位+1tick |
| 出场价≠收盘价 | 用突破价±1tick出场, 非收盘价 | 当日low/high触发, 出场价=突破位±1tick |
| 同日出场 | 同日触发入场和出场 | 有持仓时不开仓, 先检查出场 |
| 盘中路径未知 | 日线无法知道盘中精确路径 | 假设: 若high>突破位则成交(乐观假设) |
