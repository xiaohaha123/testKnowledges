# -*- coding: utf-8 -*-
import os
import sys
import datetime
from dataclasses import dataclass, field

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from strategy_futures.get_price_futures import VARIETIES, _chinese_to_contract


@dataclass
class Bar:
    date: str
    o: float = 0.0
    h: float = 0.0
    l: float = 0.0
    c: float = 0.0
    v: float = 0.0

    def __post_init__(self):
        self.o = float(self.o) if self.o else 0.0
        self.h = float(self.h) if self.h else 0.0
        self.l = float(self.l) if self.l else 0.0
        self.c = float(self.c) if self.c else 0.0
        self.v = float(self.v) if self.v else 0.0

    @property
    def open(self):
        return self.o

    @property
    def high(self):
        return self.h

    @property
    def low(self):
        return self.l

    @property
    def close(self):
        return self.c

    @property
    def volume(self):
        return self.v


@dataclass
class Config:
    entry_breakout: int = 20
    exit_breakout: int = 10
    tick_size: float = 1.0
    contract_multiplier: int = 10


@dataclass
class Trade:
    direction: str
    entry_date: str
    entry_price: float
    breakout_high: float = 0.0
    breakout_high_date: str = ""
    breakout_low: float = 0.0
    breakout_low_date: str = ""
    reason: str = ""


def fmt_price(value, tick):
    if tick >= 1:
        return f"{value:.0f}"
    digits = len(f"{tick}".rstrip("0").split(".")[-1]) if "." in f"{tick}" else 0
    return f"{value:.{digits}f}"


class BacktestEngine:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def run(self, bars: list[Bar]) -> list[Trade]:
        if len(bars) < self.cfg.entry_breakout + 1:
            return []

        trades = []
        position = None

        for i in range(self.cfg.entry_breakout, len(bars)):
            bar = bars[i]
            prev_bars = bars[i - self.cfg.entry_breakout : i]
            high_n = max(b.high for b in prev_bars)
            low_n = min(b.low for b in prev_bars)
            high_n_date = next(b.date for b in prev_bars if b.high == high_n)
            low_n_date = next(b.date for b in prev_bars if b.low == low_n)

            if position is None:
                if bar.high > high_n:
                    entry_price = high_n + self.cfg.tick_size
                    position = Trade(
                        direction="long",
                        entry_date=bar.date,
                        entry_price=entry_price,
                        breakout_high=high_n,
                        breakout_high_date=high_n_date,
                    )
                elif bar.low < low_n:
                    entry_price = low_n - self.cfg.tick_size
                    position = Trade(
                        direction="short",
                        entry_date=bar.date,
                        entry_price=entry_price,
                        breakout_low=low_n,
                        breakout_low_date=low_n_date,
                    )
            else:
                exit_bars = bars[max(i - self.cfg.exit_breakout, 0) : i]
                if len(exit_bars) >= self.cfg.exit_breakout:
                    exit_low = min(b.low for b in exit_bars)
                    exit_high = max(b.high for b in exit_bars)

                    if position.direction == "long" and bar.low < exit_low:
                        position.reason = "exit_breakout"
                        trades.append(position)
                        position = None
                    elif position.direction == "short" and bar.high > exit_high:
                        position.reason = "exit_breakout"
                        trades.append(position)
                        position = None

        if position is not None:
            position.reason = "end_of_data"
            trades.append(position)

        return trades


def load_variety_bars_from_master(master_path: str, variety_code: str) -> list[Bar]:
    bars = []
    with open(master_path, encoding="utf-8-sig") as f:
        for line in f:
            parts = line.strip().split(",")
            if len(parts) < 8:
                continue
            if parts[0] != variety_code:
                continue
            d, o, h, l, c, v = parts[2], parts[3], parts[4], parts[5], parts[6], parts[7]
            if len(d) == 8:
                d = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            if not o:
                continue
            bars.append(Bar(date=d, o=o, h=h, l=l, c=c, v=v))
    return bars


TICK_MAP = {
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

MUL_MAP = {
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


def _compute_exit_channel(bars, idx, exit_period):
    recent = bars[idx - exit_period : idx]
    e_high = max(b.high for b in recent)
    e_high_date = next(b.date for b in recent if b.high == e_high)
    e_low = min(b.low for b in recent)
    e_low_date = next(b.date for b in recent if b.low == e_low)
    return e_high, e_high_date, e_low, e_low_date


def run_latest_open(master_csv_path: str, output_dir: str = None):
    if not os.path.exists(master_csv_path):
        print(f"文件不存在: {master_csv_path}")
        return

    if output_dir is None:
        output_dir = os.path.join(BASE_DIR, "strategy_futures_output", "latest_open")
    os.makedirs(output_dir, exist_ok=True)

    name_dict = dict(VARIETIES)

    with open(master_csv_path, encoding="utf-8-sig") as f:
        codes = set()
        for line in f:
            parts = line.strip().split(",")
            if len(parts) >= 8 and parts[0]:
                codes.add(parts[0])

    sorted_codes = sorted(codes)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = []
    lines.append("# 最新开仓信号汇总")
    lines.append("")
    lines.append(f"- 数据文件: `{os.path.basename(master_csv_path)}`")
    lines.append(f"- 生成时间: {now}")
    lines.append("")

    holding_profit = []
    holding_loss = []
    closed = []
    no_trade = []
    all_dates = set()

    for code in sorted_codes:
        eng_code = _chinese_to_contract(code)
        variety = eng_code.rstrip("0123456789") or eng_code
        vname = name_dict.get(eng_code, name_dict.get(variety + "0", code))
        bars = load_variety_bars_from_master(master_csv_path, code)
        if not bars:
            continue

        for b in bars:
            all_dates.add(b.date)

        cfg = Config()
        cfg.tick_size = TICK_MAP.get(variety, 1)
        cfg.contract_multiplier = MUL_MAP.get(variety, 10)
        tick = cfg.tick_size

        engine = BacktestEngine(cfg)
        trades = engine.run(bars)

        if not trades:
            no_trade.append((code, vname))
            continue

        last = trades[-1]
        is_open = last.reason == "end_of_data"

        d = "多" if last.direction == "long" else "空"
        cur_price = bars[-1].close

        if last.direction == "long":
            floating = (cur_price - last.entry_price) * cfg.contract_multiplier
            basis = (f"突破20日最高{fmt_price(last.breakout_high, tick)}"
                     f"({last.breakout_high_date})+{tick}tick")
        else:
            floating = (last.entry_price - cur_price) * cfg.contract_multiplier
            basis = (f"突破20日最低{fmt_price(last.breakout_low, tick)}"
                     f"({last.breakout_low_date})-{tick}tick")

        exit_channel = ""
        if is_open and len(bars) >= cfg.exit_breakout:
            e_high, e_high_date, e_low, e_low_date = _compute_exit_channel(
                bars, len(bars) - 1, cfg.exit_breakout)
            if last.direction == "long":
                exit_channel = (f"10日最低{fmt_price(e_low, tick)}({e_low_date})"
                                f" → 跌破则平仓")
            else:
                exit_channel = (f"10日最高{fmt_price(e_high, tick)}({e_high_date})"
                                f" → 涨破则平仓")

        row = (code, vname, d, last.entry_date,
               fmt_price(last.entry_price, tick),
               fmt_price(cur_price, tick),
               f"{floating:,.2f}", basis, exit_channel)

        if is_open:
            if floating >= 0:
                holding_profit.append(row)
            else:
                holding_loss.append(row)
        else:
            closed.append(row)

    lines.append("## 盈利持仓")
    lines.append("")
    lines.append("| 品种 | 名称 | 方向 | 开仓日期 | 开仓价 | 当前价 | 浮盈 | 开仓依据 | 当前10日出场通道 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in holding_profit:
        lines.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} | {r[6]} | {r[7]} | {r[8]} |")

    lines.append("")
    lines.append("## 亏损持仓")
    lines.append("")
    lines.append("| 品种 | 名称 | 方向 | 开仓日期 | 开仓价 | 当前价 | 浮亏 | 开仓依据 | 当前10日出场通道 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in holding_loss:
        lines.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} | {r[6]} | {r[7]} | {r[8]} |")

    lines.append("")
    lines.append(f"- 盈利持仓: {len(holding_profit)} 个品种")
    lines.append(f"- 亏损持仓: {len(holding_loss)} 个品种")
    lines.append(f"- 已平仓: {len(closed)} 个品种")
    lines.append(f"- 无交易: {len(no_trade)} 个品种")
    lines.append("")

    last5_dates = sorted(all_dates)[-5:]
    recent_rows = []
    for r in holding_profit + holding_loss:
        if r[3] in last5_dates:
            recent_rows.append(r)
    if recent_rows:
        lines.append("## 最近5个交易日开仓汇总")
        lines.append("")
        lines.append(f"最近5个交易日: {', '.join(last5_dates)}")
        lines.append("")
        lines.append("| 品种 | 名称 | 方向 | 开仓日期 | 开仓价 | 当前价 | 浮盈亏 | 开仓依据 | 当前10日出场通道 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        total_float = 0.0
        for r in recent_rows:
            pnl_val = float(r[6].replace(",", ""))
            total_float += pnl_val
            lines.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} | {r[6]} | {r[7]} | {r[8]} |")
        lines.append("")
        lines.append(f"| | | | | | **合计** | **{total_float:,.2f}** | | |")
        lines.append("")
    else:
        lines.append("## 最近5个交易日开仓汇总")
        lines.append("")
        lines.append("最近5个交易日无新开仓品种")
        lines.append("")

    out_path = os.path.join(output_dir, "latest_open.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"盈利持仓: {len(holding_profit)} 个品种")
    print(f"亏损持仓: {len(holding_loss)} 个品种")
    print(f"已平仓: {len(closed)} 个品种")
    print(f"无交易: {len(no_trade)} 个品种")
    if recent_rows:
        print(f"最近5个交易日开仓: {len(recent_rows)} 个品种")
    print(f"报告: {out_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python daily_20_latest_open_futures.py <汇总CSV文件路径> [输出目录]")
        print("示例: python daily_20_latest_open_futures.py output_futures/futures_main_daily_20260730.csv")
        sys.exit(1)

    csv_path = sys.argv[1]
    if not os.path.isabs(csv_path):
        csv_path = os.path.abspath(csv_path)

    output_dir = sys.argv[2] if len(sys.argv) > 2 else None
    run_latest_open(csv_path, output_dir)
