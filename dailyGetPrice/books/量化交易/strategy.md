# 1分钟突破反转策略设计文档

## 1. 策略定义

| 项目 | 说明 |
|---|---|
| 名称 | MinuteBreakoutReversal |
| 品种 | 国内期货主力合约 |
| 频率 | 1分钟K线 |
| 方向 | 双向(多+空)，多空互为反手 |
| 类型 | 日内策略，不留隔夜仓 |
| 核心逻辑 | 突破前10根最高价→做多/反手多；跌破前10根最低价→做空/反手空 |

### 1.1 信号规则(入场+出场统一)

```
信号 = 同一套逻辑, 入场和反手共用:

做多信号: close > max(high[-10:-1])
  → 无持仓时: 开多
  → 持空头时: 平空 + 开多(反手)

做空信号: close < min(low[-10:-1])
  → 无持仓时: 开空
  → 持多头时: 平多 + 开空(反手)

无信号: close 在 [min(low[-10:-1]), max(high[-10:-1])] 区间内
  → 保持当前持仓不变
```

> "前10根" = 当前K线之前的10根, 不含当前K线, 即 lookback = bars[i-10:i]

**关键设计**: 多空互为反手条件，同一信号既触发出场又触发新入场，无需独立止损止盈。

### 1.2 日内时间约束

```
交易日时间轴(以日盘9:00-15:00为例, 夜盘同理):

  9:00 ────── 9:10 │ 9:11 ──────────── 14:30 │ 14:31 ── 14:55 │ 14:55  15:00
  ╰── 开盘缓冲 ─╯   ╰── 正常交易时段 ──╯   ╰── 收盘缓冲 ─╯  ╰强平╯

时段A: 开盘缓冲(前10min)
  9:00-9:10 → 不开仓，不平仓，不产生信号

时段B: 正常交易
  9:11-14:30 → 可开仓、可平仓、可反手，信号正常执行

时段C: 收盘缓冲(最后30min)
  14:31-14:55 → 只平仓，不反手，不开新仓
  即: 有持仓时，若触发反向信号则仅平仓(不反手开新仓)；无持仓时不允许开仓

时段D: 强制平仓
  14:55 → 无条件平掉所有持仓，当天结束
```

夜盘时间约束(有夜盘品种):

```
  21:00-21:10 → 不开仓(开盘缓冲10min)
  21:11-22:30 → 正常交易
  22:31-22:55 → 只平仓(收盘缓冲30min, 不反手不开新仓)
  22:55       → 强平
  (部分品种23:00收盘, 部分01:00/02:30收盘, 时间轴相应调整)
```

---

## 2. 数据需求

| 字段 | 类型 | 说明 |
|---|---|---|
| datetime | str | YYYY-MM-DD HH:MM |
| open | float | 开盘价 |
| high | float | 最高价 |
| low | float | 最低价 |
| close | float | 收盘价 |
| volume | int | 成交量 |

### 数据文件格式

```csv
datetime,open,high,low,close,volume
2026-07-27 09:01,3070,3075,3068,3073,1234
2026-07-27 09:02,3073,3078,3072,3076,987
...
```

### 数据源

```
1. TqSdk天勤(推荐, 免费1min期货数据)
2. vnpy数据服务
3. 自建爬虫(交易所/新浪)
```

---

## 3. 代码架构

```
dailyGetPrice/
├── strategy/
│   ├── __init__.py
│   ├── config.py              # 参数配置
│   ├── bar.py                 # K线数据结构
│   ├── signal.py              # 信号生成
│   ├── session.py             # 日内时段判断
│   ├── engine.py              # 回测引擎
│   ├── analyzer.py            # 绩效分析
│   └── data_loader.py         # 数据加载
└── strategy.md                # 本文档
```

### 3.1 config.py

```python
class Config:
    lookback = 10              # 回望K线数
    open_buffer_min = 10       # 开盘不开仓缓冲(min)
    close_buffer_min = 30      # 收盘只平仓缓冲(min)
    force_close_min = 5        # 强平距收盘倒数(min)

    initial_capital = 100000
    commission_pct = 0.0001    # 手续费率
    slippage_ticks = 1         # 滑点(tick数)
    contract_multiplier = 10   # 合约乘数
    margin_ratio = 0.10        # 保证金比例

    # 日盘时间
    day_open = (9, 0)          # 日盘开盘
    day_close = (15, 0)        # 日盘收盘
    # 夜盘时间(有夜盘品种才启用)
    night_open = (21, 0)
    night_close = (23, 0)      # 23:00收盘品种; 01:00品种改为(1,0)

    data_file = "RB2609_1min.csv"
```

### 3.2 bar.py

```python
from datetime import datetime

class Bar:
    __slots__ = ["datetime", "open", "high", "low", "close", "volume"]

    def __init__(self, dt: str, o, h, l, c, v):
        self.datetime = datetime.strptime(dt, "%Y-%m-%d %H:%M")
        self.open = float(o)
        self.high = float(h)
        self.low = float(l)
        self.close = float(c)
        self.volume = int(v)

    @property
    def date(self):
        return self.datetime.date()

    @property
    def time(self):
        return self.datetime.time()

    @property
    def hour_min(self) -> tuple[int, int]:
        return (self.datetime.hour, self.datetime.minute)
```

### 3.3 session.py — 日内时段判断

```python
class TradingSession:
    """判断当前K线处于哪个交易时段"""

    def __init__(self, config: Config):
        self.open_buf = config.open_buffer_min
        self.close_buf = config.close_buffer_min
        self.force_close = config.force_close_min
        self.day_open = config.day_open
        self.day_close = config.day_close
        self.night_open = config.night_open
        self.night_close = config.night_close

    def _minutes_from_open(self, bar: Bar) -> int | None:
        """当前K线距开盘多少分钟, None表示不在交易时段"""
        hm = bar.hour_min
        # 日盘
        if self.day_open <= hm < self.day_close:
            return (hm[0] - self.day_open[0]) * 60 + (hm[1] - self.day_open[1])
        # 夜盘
        if self.night_open <= hm or hm < self.night_close:
            if hm >= self.night_open:
                return (hm[0] - self.night_open[0]) * 60 + (hm[1] - self.night_open[1])
            else:  # 跨日(01:00收盘等)
                return (hm[0] + 24 - self.night_open[0]) * 60 + (hm[1] - self.night_open[1])
        return None

    def _minutes_to_close(self, bar: Bar) -> int | None:
        """当前K线距收盘多少分钟"""
        hm = bar.hour_min
        if self.day_open <= hm < self.day_close:
            return (self.day_close[0] - hm[0]) * 60 + (self.day_close[1] - hm[1])
        if hm >= self.night_open or hm < self.night_close:
            close_h = self.night_close[0]
            if close_h <= 3:  # 跨日收盘(01:00/02:30)
                if hm >= self.night_open:
                    return (close_h + 24 - hm[0]) * 60 + (hm[1] - close_h)  # 简化
                else:
                    return (close_h - hm[0]) * 60 + (0 - hm[1])
            return (close_h - hm[0]) * 60 + (0 - hm[1])
        return None

    def can_open(self, bar: Bar) -> bool:
        """是否允许开新仓"""
        m_open = self._minutes_from_open(bar)
        m_close = self._minutes_to_close(bar)
        if m_open is None or m_close is None:
            return False
        if m_open < self.open_buf:
            return False
        if m_close <= self.close_buf:
            return False
        return True

    def can_close_only(self, bar: Bar) -> bool:
        """是否处于收盘缓冲期(只平仓, 不反手不开新仓)"""
        m_open = self._minutes_from_open(bar)
        m_close = self._minutes_to_close(bar)
        if m_open is None or m_close is None:
            return False
        if m_open < self.open_buf:
            return False
        if m_close <= self.close_buf and m_close > self.force_close:
            return True
        return False

    def should_force_close(self, bar: Bar) -> bool:
        """是否应该强制平仓"""
        m_close = self._minutes_to_close(bar)
        if m_close is None:
            return False
        return m_close <= self.force_close

    def is_trading_time(self, bar: Bar) -> bool:
        """是否在交易时段内(含开盘缓冲)"""
        return self._minutes_from_open(bar) is not None
```

### 3.4 signal.py — 信号生成

```python
class BreakoutSignal:
    """信号生成: 入场与反手共用同一逻辑"""

    def __init__(self, lookback: int = 10):
        self.lookback = lookback

    def next_signal(self, bars: list[Bar], idx: int) -> str:
        """
        返回: "long" / "short" / "none"
        "long": close > 前10根最高价 → 做多或反手多
        "short": close < 前10根最低价 → 做空或反手空
        "none": 在区间内, 不触发任何操作
        """
        if idx < self.lookback:
            return "none"

        recent = bars[idx - self.lookback : idx]
        upper = max(b.high for b in recent)
        lower = min(b.low for b in recent)
        cur = bars[idx]

        if cur.close > upper:
            return "long"
        elif cur.close < lower:
            return "short"
        return "none"
```

### 3.5 engine.py — 回测引擎

```python
class Position:
    __slots__ = ["direction", "entry_price", "entry_idx", "entry_bar"]

    def __init__(self, direction, price, idx, bar):
        self.direction = direction   # "long" or "short"
        self.entry_price = price
        self.entry_idx = idx
        self.entry_bar = bar         # 记录入场K线(用于区分交易日)

    def pnl(self, exit_price, mul):
        if self.direction == "long":
            return (exit_price - self.entry_price) * mul
        return (self.entry_price - exit_price) * mul


class Trade:
    __slots__ = ["direction", "entry_price", "exit_price", "entry_idx",
                 "exit_idx", "pnl", "reason", "entry_dt", "exit_dt"]

    def __init__(self, direction, entry_price, exit_price, entry_idx,
                 exit_idx, pnl, reason, entry_dt, exit_dt):
        self.direction = direction
        self.entry_price = entry_price
        self.exit_price = exit_price
        self.entry_idx = entry_idx
        self.exit_idx = exit_idx
        self.pnl = pnl               # 含手续费和滑点
        self.reason = reason          # "reverse"/"force_close"/"end_of_data"
        self.entry_dt = entry_dt
        self.exit_dt = exit_dt


class BacktestEngine:
    """回测引擎: 逐根推进, 日内约束, 反手逻辑"""

    def __init__(self, config: Config):
        self.cfg = config
        self.signal = BreakoutSignal(config.lookback)
        self.session = TradingSession(config)
        self.position = None
        self.cash = config.initial_capital
        self.trades = []

    def run(self, bars: list[Bar]) -> list[Trade]:
        for i in range(len(bars)):
            bar = bars[i]

            # 跳过非交易时段
            if not self.session.is_trading_time(bar):
                continue

            # 强制平仓(距收盘≤5min)
            if self.position and self.session.should_force_close(bar):
                self._close(bar, i, "force_close")
                continue

            # 生成信号
            sig = self.signal.next_signal(bars, i)

            # 有持仓 → 检查反手/平仓条件
            if self.position and sig != "none":
                if sig != self.position.direction:
                    # 正常交易时段: 反手(平旧+开新)
                    if self.session.can_open(bar):
                        self._close(bar, i, "reverse")
                        self._open(sig, bar, i)
                    # 收盘缓冲期: 只平仓, 不反手
                    elif self.session.can_close_only(bar):
                        self._close(bar, i, "close_buffer")

            # 无持仓 → 检查开仓条件
            elif not self.position and sig != "none":
                if self.session.can_open(bar):
                    self._open(sig, bar, i)

        # 回测结束强平
        if self.position:
            self._close(bars[-1], len(bars)-1, "end_of_data")

        return self.trades

    def _open(self, direction, bar, idx):
        price = bar.close
        tick = self.cfg.slippage_ticks * self._tick_size(bar)
        if direction == "long":
            price += tick
        else:
            price -= tick
        self.position = Position(direction, price, idx, bar)
        self.cash -= price * self.cfg.contract_multiplier * self.cfg.commission_pct

    def _close(self, bar, idx, reason):
        price = bar.close
        tick = self.cfg.slippage_ticks * self._tick_size(bar)
        if self.position.direction == "long":
            price -= tick
        else:
            price += tick

        raw_pnl = self.position.pnl(price, self.cfg.contract_multiplier)
        comm = price * self.cfg.contract_multiplier * self.cfg.commission_pct
        net_pnl = raw_pnl - comm
        self.cash += net_pnl

        self.trades.append(Trade(
            direction=self.position.direction,
            entry_price=self.position.entry_price,
            exit_price=price,
            entry_idx=self.position.entry_idx,
            exit_idx=idx,
            pnl=net_pnl,
            reason=reason,
            entry_dt=self.position.entry_bar.datetime,
            exit_dt=bar.datetime))
        self.position = None

    def _tick_size(self, bar) -> float:
        """从品种代码推断最小变动价位(简化版)"""
        return 1.0  # 后续按品种精确设置
```

### 3.6 analyzer.py

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

        # 出场原因统计
        reasons = {}
        for t in self.trades:
            reasons[t.reason] = reasons.get(t.reason, 0) + 1

        # 最大回撤
        cum = [0]
        for t in self.trades:
            cum.append(cum[-1] + t.pnl)
        peak = 0
        max_dd = 0
        for v in cum:
            peak = max(peak, v)
            max_dd = max(max_dd, peak - v)

        win_pnl = sum(t.pnl for t in wins)
        loss_pnl = abs(sum(t.pnl for t in losses))

        # 每日统计
        daily = {}
        for t in self.trades:
            d = t.entry_dt.date()
            daily.setdefault(d, 0)
            daily[d] += t.pnl

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
            "出场原因分布": reasons,
            "交易天数": len(daily),
            "日均盈亏": f"{total_pnl/len(daily):.2f}" if daily else "0",
        }

    def equity_curve(self) -> list[tuple]:
        """(datetime, equity) 序列, 用于绘图"""
        curve = [(self.trades[0].entry_dt if self.trades else None, self.initial)]
        for t in self.trades:
            curve.append((t.exit_dt, curve[-1][1] + t.pnl))
        return curve
```

### 3.7 data_loader.py

```python
import csv
from strategy.bar import Bar

def load_1min_csv(path: str) -> list[Bar]:
    bars = []
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append(Bar(
                dt=row["datetime"],
                o=row["open"], h=row["high"], l=row["low"],
                c=row["close"], v=row["volume"]))
    return bars
```

---

## 4. 调用流程

```python
from strategy.config import Config
from strategy.data_loader import load_1min_csv
from strategy.engine import BacktestEngine
from strategy.analyzer import Analyzer

cfg = Config()
bars = load_1min_csv(cfg.data_file)
engine = BacktestEngine(cfg)
trades = engine.run(bars)
result = Analyzer(trades, cfg.initial_capital).summary()

for k, v in result.items():
    print(f"{k}: {v}")
```

---

## 5. 关键逻辑示例(逐根推进时序)

以某日为例，展示引擎决策流程:

```
09:01 ~ 09:10  [时段A] 不开仓, 跳过所有信号
09:11           close=3080, upper=3078 → 做多信号 → 开多@3080
09:12 ~ 09:30   close在区间内 → 持仓不动
09:31           close=3065, lower=3068 → 做空信号 → 反手: 平多@3065, 开空@3065
14:31           close=3050, lower=3052 → 做空信号 → [时段C]只平仓不反手:
                 若持多 → 平多@3050, 不开空(收盘缓冲期)
                 若持空 → 无操作(同方向无触发)
                 若无仓 → 不开仓(收盘缓冲期)
14:55           [时段D] → 强平当前持仓@当前收盘价
```

---

## 6. 回测陷阱与注意事项

| 陷阱 | 说明 | 本策略如何处理 |
|---|---|---|
| 未来函数 | 用了未产生的数据 | lookback = bars[i-10:i], 不含当前bar |
| 滑点 | 实盘成交价≠信号价 | 开仓方向+1tick, 平仓方向-1tick; 反手=两笔各加滑点 |
| 手续费 | 必须计入 | 开仓+平仓各扣一次; 反手=平一笔+开一笔=两笔手续费 |
| 同根K线开平 | 同bar触发反手 | 先平旧仓再开新仓, 同根执行, 无矛盾 |
| 收盘缓冲 | 收盘30min内触发反向信号 | 只平仓不反手, 防止尾盘新仓位被强平 |
| 隔夜仓 | 日内策略不允许 | force_close保证14:55前清仓 |
| 反手滑点叠加 | 反手=平旧+开新, 两次滑点 | 引擎先close再open, 各独立加滑点 |

### 参数敏感性

| 参数 | 默认值 | 敏感度 | 说明 |
|---|---|---|---|
| lookback | 10 | 高 | 短→信号频繁假突破多; 长→滞后但稳定 |
| 开盘缓冲 | 10min | 低 | 避开开盘波动, 一般不需调整 |
| 收盘缓冲 | 30min | 中 | 过长减少交易机会; 过短可能来不及平仓 |
| 强平倒数 | 5min | 低 | 保证能平仓, 一般不需调整 |

建议: 回测时对 lookback 做 5/10/15/20/30 参数扫描, 其余固定。
