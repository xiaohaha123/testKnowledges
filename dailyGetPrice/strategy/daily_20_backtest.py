# -*- coding: utf-8 -*-
import os
import sys
import datetime

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from get_price import VARIETIES


class Bar:
    __slots__ = ["date", "open", "high", "low", "close", "volume"]

    def __init__(self, date: str, o, h, l, c, v):
        self.date = date
        self.open = float(o)
        self.high = float(h)
        self.low = float(l)
        self.close = float(c)
        self.volume = int(v)


class Config:
    entry_breakout = 20
    exit_breakout = 10
    tick_size = 1
    initial_capital = 1000000
    commission_pct = 0.0001
    contract_multiplier = 10
    lots = 1


class BreakoutSignal:
    def __init__(self, entry_period: int = 20, exit_period: int = 10):
        self.entry_period = entry_period
        self.exit_period = exit_period

    def entry_signal(self, bars: list[Bar], idx: int) -> str:
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
        if idx < self.exit_period:
            return False
        recent = bars[idx - self.exit_period : idx]
        cur = bars[idx]
        if direction == "long" and cur.low < min(b.low for b in recent):
            return True
        if direction == "short" and cur.high > max(b.high for b in recent):
            return True
        return False


class Position:
    def __init__(self, direction: str, entry_price: float, entry_date: str,
                 breakout_high: float, breakout_high_date: str,
                 breakout_low: float, breakout_low_date: str):
        self.direction = direction
        self.entry_price = entry_price
        self.entry_date = entry_date
        self.breakout_high = breakout_high
        self.breakout_high_date = breakout_high_date
        self.breakout_low = breakout_low
        self.breakout_low_date = breakout_low_date

    def pnl(self, exit_price: float, mul: int) -> float:
        if self.direction == "long":
            return (exit_price - self.entry_price) * mul
        return (self.entry_price - exit_price) * mul


class Trade:
    __slots__ = ["direction", "entry_price", "exit_price", "pnl",
                 "reason", "entry_date", "exit_date",
                 "breakout_high", "breakout_high_date",
                 "breakout_low", "breakout_low_date",
                 "exit_high", "exit_high_date",
                 "exit_low", "exit_low_date"]

    def __init__(self, direction, entry_price, exit_price, pnl,
                 reason, entry_date, exit_date,
                 breakout_high, breakout_high_date,
                 breakout_low, breakout_low_date,
                 exit_high, exit_high_date,
                 exit_low, exit_low_date):
        self.direction = direction
        self.entry_price = entry_price
        self.exit_price = exit_price
        self.pnl = pnl
        self.reason = reason
        self.entry_date = entry_date
        self.exit_date = exit_date
        self.breakout_high = breakout_high
        self.breakout_high_date = breakout_high_date
        self.breakout_low = breakout_low
        self.breakout_low_date = breakout_low_date
        self.exit_high = exit_high
        self.exit_high_date = exit_high_date
        self.exit_low = exit_low
        self.exit_low_date = exit_low_date


def load_from_metastock_csv(path: str) -> list[Bar]:
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


class BacktestEngine:
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

            if self.position and self.signal.exit_signal(bars, i, self.position.direction):
                self._close(bars, i, "exit_signal")
                continue

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
        bh = max(b.high for b in recent)
        bh_date = next(b.date for b in recent if b.high == bh)
        bl = min(b.low for b in recent)
        bl_date = next(b.date for b in recent if b.low == bl)
        if direction == "long":
            price = bh + tick
        else:
            price = bl - tick
        self.position = Position(direction, price, bars[idx].date,
                                bh, bh_date, bl, bl_date)

    def _close(self, bars, idx, reason):
        tick = self.cfg.tick_size
        bar = bars[idx]
        exit_high = None
        exit_high_date = None
        exit_low = None
        exit_low_date = None
        if reason == "exit_signal":
            recent = bars[idx - self.cfg.exit_breakout : idx]
            exit_high = max(b.high for b in recent)
            exit_high_date = next(b.date for b in recent if b.high == exit_high)
            exit_low = min(b.low for b in recent)
            exit_low_date = next(b.date for b in recent if b.low == exit_low)
            if self.position.direction == "long":
                price = exit_low - tick
            else:
                price = exit_high + tick
        else:
            price = bar.close

        raw_pnl = self.position.pnl(price, self.cfg.contract_multiplier)
        net_pnl = raw_pnl
        self.equity += net_pnl

        self.trades.append(Trade(
            direction=self.position.direction,
            entry_price=self.position.entry_price,
            exit_price=price,
            pnl=net_pnl,
            reason=reason,
            entry_date=self.position.entry_date,
            exit_date=bar.date,
            breakout_high=self.position.breakout_high,
            breakout_high_date=self.position.breakout_high_date,
            breakout_low=self.position.breakout_low,
            breakout_low_date=self.position.breakout_low_date,
            exit_high=exit_high,
            exit_high_date=exit_high_date,
            exit_low=exit_low,
            exit_low_date=exit_low_date))
        self.position = None


def fmt_price(price, tick=1):
    if tick >= 1:
        return f"{int(round(price))}"
    decimals = len(str(tick).rstrip("0").split(".")[-1])
    return f"{price:.{decimals}f}"


def _plot_price_chart(bars, trades, cfg, out_png, title):
    import mplfinance as mpf
    import matplotlib
    matplotlib.use("Agg")
    matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
    matplotlib.rcParams["axes.unicode_minus"] = False
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    dates = [b.date for b in bars]
    opens = [b.open for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    volumes = [b.volume for b in bars]

    pdf = pd.DataFrame({
        "Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": volumes
    }, index=pd.to_datetime(dates))

    mc = mpf.make_marketcolors(up="#d32f2f", down="#2e7d32",
                               edge="inherit", wick="inherit")
    style = mpf.make_mpf_style(base_mpf_style="charles", marketcolors=mc,
                               rc={"font.sans-serif": ["Microsoft YaHei", "SimHei"]})
    fig, axes = mpf.plot(pdf, type="candle", style=style, figsize=(22, 10),
                         returnfig=True, tight_layout=True, volume=True)
    ax = axes[0]

    date_to_idx = {}
    for i, d in enumerate(pdf.index):
        date_to_idx[d.strftime("%Y-%m-%d")] = i

    y_min, y_max = ax.get_ylim()
    gap = (y_max - y_min) * 0.02

    for idx_t, t in enumerate(trades, 1):
        ei = date_to_idx.get(t.entry_date)
        xi = date_to_idx.get(t.exit_date)
        if ei is None or xi is None:
            continue

        e_low = bars[ei].low - gap
        e_high = bars[ei].high + gap
        x_low = bars[xi].low - gap
        x_high = bars[xi].high + gap

        if t.direction == "long":
            ax.scatter([ei], [e_low], marker="^", color="#d32f2f",
                       s=80, zorder=5, edgecolors="black", linewidths=0.8)
            ax.annotate(f"开{idx_t}多 {t.entry_date}", (ei, e_low),
                        textcoords="offset points", xytext=(0, -14),
                        fontsize=6, fontweight="bold", color="#d32f2f",
                        ha="center", va="top",
                        bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="#d32f2f", alpha=0.8))
            ax.scatter([xi], [x_high], marker="v", color="#d32f2f",
                       s=80, zorder=5, edgecolors="black", linewidths=0.8)
            ax.annotate(f"平{idx_t} {t.exit_date}", (xi, x_high),
                        textcoords="offset points", xytext=(0, 14),
                        fontsize=6, fontweight="bold", color="#d32f2f",
                        ha="center", va="bottom",
                        bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="#d32f2f", alpha=0.8))
        else:
            ax.scatter([ei], [e_high], marker="v", color="#2e7d32",
                       s=80, zorder=5, edgecolors="black", linewidths=0.8)
            ax.annotate(f"开{idx_t}空 {t.entry_date}", (ei, e_high),
                        textcoords="offset points", xytext=(0, 14),
                        fontsize=6, fontweight="bold", color="#2e7d32",
                        ha="center", va="bottom",
                        bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="#2e7d32", alpha=0.8))
            ax.scatter([xi], [x_low], marker="^", color="#2e7d32",
                       s=80, zorder=5, edgecolors="black", linewidths=0.8)
            ax.annotate(f"平{idx_t} {t.exit_date}", (xi, x_low),
                        textcoords="offset points", xytext=(0, -14),
                        fontsize=6, fontweight="bold", color="#2e7d32",
                        ha="center", va="top",
                        bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="#2e7d32", alpha=0.8))

    legend = [
        Line2D([0], [0], marker="^", color="w", markerfacecolor="#d32f2f",
               markersize=10, label="做多开仓/空头平仓"),
        Line2D([0], [0], marker="v", color="w", markerfacecolor="#2e7d32",
               markersize=10, label="做空开仓/多头平仓"),
    ]
    ax.legend(handles=legend, loc="upper left", fontsize=8)
    ax.set_title(title, fontsize=12, fontweight="bold")

    fig.savefig(out_png, dpi=150)
    plt.close(fig)




def run_backtest(csv_path: str, output_dir: str = None):
    """运行回测并输出 Markdown 报告"""
    cfg = Config()

    # 从品种代码推断参数
    basename = os.path.splitext(os.path.basename(csv_path))[0]
    variety = basename.rstrip("0123456789") or basename
    name_dict = dict(VARIETIES)
    variety_name = name_dict.get(basename, name_dict.get(variety + "0", basename))

    # 品种tick映射
    tick_map = {
        "RB": 1, "HC": 1, "I": 0.5, "J": 0.5, "JM": 0.5,
        "MA": 1, "TA": 2, "PP": 1, "V": 5, "EG": 1,
        "SA": 1, "FG": 1, "L": 5, "BU": 1, "RU": 5,
        "FU": 1, "SC": 0.1, "LU": 1, "SP": 1, "UR": 1,
        "SH": 1, "EB": 1, "PF": 2, "PX": 2, "PR": 2, "BR": 5,
        "CU": 10, "AL": 5, "ZN": 5, "NI": 10, "PB": 5,
        "SN": 10, "AU": 0.02, "AG": 1, "SI": 5, "LC": 50, "AO": 1, "PS": 5,
        "C": 1, "CS": 1, "M": 1, "Y": 2, "P": 2,
        "A": 1, "B": 1, "SR": 1, "CF": 5, "CY": 5,
        "OI": 1, "RM": 1, "AP": 1, "CJ": 5, "JD": 1,
        "PK": 2, "LH": 5,
    }
    cfg.tick_size = tick_map.get(variety, 1)

    # 合约乘数映射
    mul_map = {
        "RB": 10, "HC": 10, "I": 100, "J": 100, "JM": 60,
        "MA": 10, "TA": 5, "PP": 5, "V": 5, "EG": 10,
        "SA": 20, "FG": 20, "L": 5, "BU": 10, "RU": 10,
        "FU": 10, "SC": 1000, "LU": 10, "SP": 10, "UR": 20, "SH": 30,
        "EB": 5, "PF": 5, "PX": 5, "PR": 5, "BR": 5,
        "CU": 5, "AL": 5, "ZN": 5, "NI": 1, "PB": 5,
        "SN": 1, "AU": 1000, "AG": 15, "SI": 5, "LC": 1, "AO": 20, "PS": 5,
        "C": 10, "CS": 10, "M": 10, "Y": 10, "P": 10,
        "A": 10, "B": 10, "SR": 10, "CF": 5, "CY": 5,
        "OI": 10, "RM": 10, "AP": 10, "CJ": 5, "JD": 10,
        "PK": 5, "LH": 16,
    }
    cfg.contract_multiplier = mul_map.get(variety, 10)

    bars = load_from_metastock_csv(csv_path)
    if not bars:
        print(f"错误: 无法读取数据 {csv_path}")
        return

    engine = BacktestEngine(cfg)
    trades = engine.run(bars)
    tick = cfg.tick_size

    # ---- 生成 Markdown 报告 ----
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    data_start = bars[0].date
    data_end = bars[-1].date
    n_bars = len(bars)

    lines = []
    lines.append(f"# 海龟策略回测报告 — {basename} {variety_name}")
    lines.append("")
    lines.append(f"- 数据文件: `{os.path.basename(csv_path)}`")
    lines.append(f"- 数据范围: {data_start} ~ {data_end}  ({n_bars} 根日线)")
    lines.append(f"- 生成时间: {now}")
    lines.append(f"- 策略参数: 入场突破{cfg.entry_breakout}日, 出场突破{cfg.exit_breakout}日, "
                 f"tick={cfg.tick_size}, 合约乘数={cfg.contract_multiplier}")
    lines.append("")

    # 统计
    total = len(trades)
    if total == 0:
        lines.append("无交易记录")
        report = "\n".join(lines)
        _save_report(report, out_path)
        return

    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    total_pnl = sum(t.pnl for t in trades)
    win_pnl = sum(t.pnl for t in wins)
    loss_pnl = abs(sum(t.pnl for t in losses))

    cum = [0]
    for t in trades:
        cum.append(cum[-1] + t.pnl)
    peak = 0
    max_dd = 0
    for v in cum:
        peak = max(peak, v)
        max_dd = max(max_dd, peak - v)

    reasons = {}
    for t in trades:
        reasons[t.reason] = reasons.get(t.reason, 0) + 1

    long_trades = [t for t in trades if t.direction == "long"]
    short_trades = [t for t in trades if t.direction == "short"]
    long_wins = [t for t in long_trades if t.pnl > 0]
    short_wins = [t for t in short_trades if t.pnl > 0]

    # 汇总统计
    lines.append("## 汇总统计")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("| --- | --- |")
    lines.append(f"| 总交易次数 | {total} |")
    lines.append(f"| 盈利次数 | {len(wins)} |")
    lines.append(f"| 亏损次数 | {len(losses)} |")
    lines.append(f"| 胜率 | {len(wins)/total*100:.1f}% |")
    lines.append(f"| 总盈亏 | {total_pnl:,.2f} |")
    lines.append(f"| 盈利总额 | {win_pnl:,.2f} |")
    lines.append(f"| 亏损总额 | {loss_pnl:,.2f} |")
    lines.append(f"| 盈亏比 | {win_pnl/loss_pnl:.2f} |" if loss_pnl else "| 盈亏比 | N/A |")
    lines.append(f"| 单笔最大盈利 | {max(t.pnl for t in trades):,.2f} |")
    lines.append(f"| 单笔最大亏损 | {min(t.pnl for t in trades):,.2f} |")
    lines.append(f"| 最大回撤 | {max_dd:,.2f} |")
    lines.append(f"| 收益率 | {total_pnl/cfg.initial_capital*100:.1f}% |")
    lines.append(f"| 出场原因分布 | {reasons} |")
    lines.append("")

    # 逐笔交易明细
    lines.append("## 逐笔交易明细")
    lines.append("")
    lines.append("| # | 事件 | 方向 | 日期 | 价格 | 通道最高 | 最高日期 | 通道最低 | 最低日期 | 盈亏 | 持仓天数 | 备注 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")

    for i, t in enumerate(trades, 1):
        d = "多" if t.direction == "long" else "空"
        # 开仓行
        if t.direction == "long":
            src = f"20日最高{fmt_price(t.breakout_high, tick)}+{cfg.tick_size}tick"
        else:
            src = f"20日最低{fmt_price(t.breakout_low, tick)}-{cfg.tick_size}tick"
        lines.append(
            f"| {i} | 开仓 | {d} | {t.entry_date} | {fmt_price(t.entry_price, tick)} | "
            f"{fmt_price(t.breakout_high, tick)} | {t.breakout_high_date} | "
            f"{fmt_price(t.breakout_low, tick)} | {t.breakout_low_date} | | | {src} |")
        # 平仓行
        pnl_str = f"{t.pnl:,.2f}"
        pnl_str = f"**{pnl_str}**" if t.pnl > 0 else pnl_str
        try:
            d1 = datetime.datetime.strptime(t.entry_date, "%Y-%m-%d").date()
            d2 = datetime.datetime.strptime(t.exit_date, "%Y-%m-%d").date()
            hold_days = f"{(d2 - d1).days}天"
        except Exception:
            hold_days = "-"
        reason_map = {"exit_signal": "10日突破", "end_of_data": "数据结束"}
        reason_str = reason_map.get(t.reason, t.reason)
        if t.reason == "exit_signal":
            if t.direction == "long":
                src = f"{reason_str} 10日最低{fmt_price(t.exit_low, tick)}({t.exit_low_date})"
            else:
                src = f"{reason_str} 10日最高{fmt_price(t.exit_high, tick)}({t.exit_high_date})"
        else:
            src = reason_str
        lines.append(
            f"| {i} | 平仓 | | {t.exit_date} | {fmt_price(t.exit_price, tick)} | "
            f"{fmt_price(t.exit_high, tick) if t.exit_high else ''} | {t.exit_high_date or ''} | "
            f"{fmt_price(t.exit_low, tick) if t.exit_low else ''} | {t.exit_low_date or ''} | "
            f"{pnl_str} | {hold_days} | {src} |")
    lines.append("")

    # ---- 输出路径 ----
    if output_dir is None:
        output_dir = os.path.join(BASE_DIR, "strategy_output")
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"backtest_{basename}.md")

    # ---- 生成图表 ----
    img_dir = os.path.join(output_dir, f"backtest_{basename}_img")
    os.makedirs(img_dir, exist_ok=True)

    try:
        price_png = os.path.join(img_dir, "price_chart.png")
        _plot_price_chart(bars, trades, cfg, price_png,
                          f"{basename} {variety_name} 海龟20日突破")
        lines.append("## K线图 + 唐奇安通道 + 开平仓标注")
        lines.append("")
        lines.append(f"![K线图]({os.path.relpath(price_png, os.path.dirname(out_path))})")
        lines.append("")
        lines.append("- 蓝色线: 20日最高/最低(入场通道)")
        lines.append("- 橙色线: 10日最高/最低(出场通道)")
        lines.append("- 红色▲: 做多开仓, 红色×: 多头平仓")
        lines.append("- 绿色▼: 做空开仓, 绿色×: 空头平仓")
        lines.append("")
    except Exception as e:
        lines.append(f"## K线图\n\n*(绘图失败: {e})*\n")

    report = "\n".join(lines)
    _save_report(report, out_path)


def _save_report(report: str, out_path: str):
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n回测报告: {out_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python daily_20_backtest.py <CSV文件路径> [输出目录]")
        print("示例: python daily_20_backtest.py output/RB2609.csv")
        sys.exit(1)

    csv_path = sys.argv[1]
    if not os.path.isabs(csv_path):
        csv_path = os.path.abspath(csv_path)
    if not os.path.exists(csv_path):
        print(f"文件不存在: {csv_path}")
        sys.exit(1)

    output_dir = sys.argv[2] if len(sys.argv) > 2 else None
    run_backtest(csv_path, output_dir)
