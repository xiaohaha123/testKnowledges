# -*- coding: utf-8 -*-
import os
import sys
import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from get_price import VARIETIES
from strategy.daily_20_backtest import (
    Bar, Config, BacktestEngine, fmt_price, _plot_price_chart,
)


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


def _build_variety_lines(code, vname, bars, cfg, output_dir, out_path):
    tick = cfg.tick_size
    engine = BacktestEngine(cfg)
    trades = engine.run(bars)

    lines = []
    lines.append(f"## {code} {vname}")
    lines.append("")
    lines.append(f"- 数据范围: {bars[0].date} ~ {bars[-1].date}  ({len(bars)} 根日线)")
    lines.append(f"- tick={cfg.tick_size}, 合约乘数={cfg.contract_multiplier}")
    lines.append("")

    total = len(trades)
    if total == 0:
        lines.append("无交易记录")
        lines.append("")
        return lines, total, 0

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

    lines.append("### 逐笔交易明细")
    lines.append("")
    lines.append("| # | 事件 | 方向 | 日期 | 价格 | 通道最高 | 最高日期 | 通道最低 | 最低日期 | 盈亏 | 持仓天数 | 备注 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")

    for i, t in enumerate(trades, 1):
        d = "多" if t.direction == "long" else "空"
        if t.direction == "long":
            src = f"20日最高{fmt_price(t.breakout_high, tick)}+{cfg.tick_size}tick"
        else:
            src = f"20日最低{fmt_price(t.breakout_low, tick)}-{cfg.tick_size}tick"
        lines.append(
            f"| {i} | 开仓 | {d} | {t.entry_date} | {fmt_price(t.entry_price, tick)} | "
            f"{fmt_price(t.breakout_high, tick)} | {t.breakout_high_date} | "
            f"{fmt_price(t.breakout_low, tick)} | {t.breakout_low_date} | | | {src} |")
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

    img_dir = os.path.join(output_dir, f"backtest_all_img")
    os.makedirs(img_dir, exist_ok=True)

    try:
        price_png = os.path.join(img_dir, f"price_chart_{code}.png")
        _plot_price_chart(bars, trades, cfg, price_png,
                          f"{code} {vname} 海龟20日突破")
        lines.append(f"![K线图]({os.path.relpath(price_png, os.path.dirname(out_path))})")
        lines.append("")
    except Exception as e:
        lines.append(f"*(绘图失败: {e})*\n")

    return lines, total, total_pnl


def run_all_backtest(master_csv_path: str, output_dir: str = None):
    if not os.path.exists(master_csv_path):
        print(f"文件不存在: {master_csv_path}")
        return

    if output_dir is None:
        output_dir = os.path.join(BASE_DIR, "strategy_output")
    os.makedirs(output_dir, exist_ok=True)

    name_dict = dict(VARIETIES)

    with open(master_csv_path, encoding="utf-8-sig") as f:
        codes = set()
        for line in f:
            parts = line.strip().split(",")
            if len(parts) >= 8 and parts[0]:
                codes.add(parts[0])

    sorted_codes = sorted(codes)
    print(f"共发现 {len(sorted_codes)} 个品种: {', '.join(sorted_codes)}")
    print("=" * 60)

    out_path = os.path.join(output_dir, "backtest_all.md")
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    header_lines = []
    header_lines.append("# 海龟策略回测报告 — 全品种")
    header_lines.append("")
    header_lines.append(f"- 数据文件: `{os.path.basename(master_csv_path)}`")
    header_lines.append(f"- 生成时间: {now}")
    header_lines.append(f"- 策略参数: 入场突破20日, 出场突破10日")
    header_lines.append("")

    summary = []
    total_trades = 0
    total_pnl_all = 0.0
    detail_lines = []

    for code in sorted_codes:
        variety = code.rstrip("0123456789") or code
        vname = name_dict.get(code, name_dict.get(variety + "0", code))
        bars = load_variety_bars_from_master(master_csv_path, code)
        if not bars:
            print(f"  {code} {vname}: 无数据，跳过")
            continue

        cfg = Config()
        cfg.tick_size = TICK_MAP.get(variety, 1)
        cfg.contract_multiplier = MUL_MAP.get(variety, 10)

        variety_lines, n_trades, pnl = _build_variety_lines(
            code, vname, bars, cfg, output_dir, out_path)
        detail_lines.extend(variety_lines)
        detail_lines.append("---")
        detail_lines.append("")

        summary.append((code, vname, n_trades, pnl))
        total_trades += n_trades
        total_pnl_all += pnl
        print(f"  {code} {vname}: {n_trades}笔交易, 总盈亏={pnl:,.2f}")

    header_lines.append("## 品种汇总")
    header_lines.append("")
    header_lines.append("| 品种 | 名称 | 交易次数 | 总盈亏 |")
    header_lines.append("| --- | --- | --- | --- |")
    for code, vname, n, pnl in summary:
        header_lines.append(f"| {code} | {vname} | {n} | {pnl:,.2f} |")
    header_lines.append(f"| **合计** | | **{total_trades}** | **{total_pnl_all:,.2f}** |")
    header_lines.append("")

    all_lines = header_lines + detail_lines

    report = "\n".join(all_lines)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print("=" * 60)
    print(f"回测报告: {out_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python daily_20_all.py <汇总CSV文件路径> [输出目录]")
        print("示例: python daily_20_all.py output/futures_main_daily_20260730.csv")
        sys.exit(1)

    csv_path = sys.argv[1]
    if not os.path.isabs(csv_path):
        csv_path = os.path.abspath(csv_path)

    output_dir = sys.argv[2] if len(sys.argv) > 2 else None
    run_all_backtest(csv_path, output_dir)
