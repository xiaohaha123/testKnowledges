# -*- coding: utf-8 -*-
"""
Dual Thrust 日线策略（A股适配版）
================================
基于前N日波动Range, 在当日开盘价上下设置突破阈值:
  收盘价 > 上轨(开盘 + K1*Range) → 买入信号
  收盘价 < 下轨(开盘 - K2*Range) → 卖出信号
输出: dual_thrust.md (买入信号股票列表)

用法:
  python -m strategy_stocks.Dual_Thrust
  python -m strategy_stocks.Dual_Thrust 000852        # 指定指数
  python -m strategy_stocks.Dual_Thrust --style 保守   # 保守/均衡/激进
"""

import os
import sys
import datetime
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import akshare as ak
except ImportError as e:
    sys.exit(f"缺少依赖: {e.name}\n请运行: pip install akshare")


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output_stocks")

MAX_RETRY = 2
DEFAULT_INDEX = "932000"
WORKERS = 20

STYLE_PRESETS = {
    "保守": {"N": 5, "K1": 0.3, "K2": 0.7},
    "均衡": {"N": 4, "K1": 0.5, "K2": 0.5},
    "激进": {"N": 3, "K1": 0.7, "K2": 0.3},
}


def _to_sina_symbol(code: str) -> str:
    if code.startswith(("6", "9")):
        return f"sh{code}"
    return f"sz{code}"


def _fetch_stock_daily(code: str, start_date: str, end_date: str):
    sina_sym = _to_sina_symbol(code)
    for attempt in range(1, MAX_RETRY + 1):
        try:
            df = ak.stock_zh_a_daily(symbol=sina_sym, start_date=start_date,
                                     end_date=end_date, adjust="qfq")
            if df is not None and len(df) > 0:
                return df
        except Exception:
            if attempt < MAX_RETRY:
                time.sleep(2)
    return None


MIN_CHG_PCT = 2.0
MAX_PRICE = 30.0
MIN_ABOVE_PCT = 0.5
VOL_RATIO = 1.5


def _check_buy(code, name, start_date, end_date, N, K1, K2):
    df = _fetch_stock_daily(code, start_date, end_date)
    if df is None or len(df) < N + 1:
        return None
    df = df.sort_values("date").reset_index(drop=True)

    last = df.iloc[-1]
    prev = df.iloc[-2]
    cur_close = last["close"]
    cur_open = last["open"]
    cur_vol = last["volume"]
    latest_date = str(last["date"])
    cur_chg = (cur_close - prev["close"]) / prev["close"] * 100

    lookback = df.iloc[-(N + 1) : -1]
    HH = lookback["high"].max()
    HC = lookback["close"].max()
    LC = lookback["close"].min()
    LL = lookback["low"].min()
    range_val = max(HH - LC, HC - LL)
    if range_val <= 0:
        return None

    buy_line = cur_open + K1 * range_val
    sell_line = cur_open - K2 * range_val

    if cur_close <= buy_line:
        return None

    pct_above = (cur_close - buy_line) / buy_line * 100

    if cur_chg < MIN_CHG_PCT:
        return None
    if cur_close > MAX_PRICE:
        return None
    if pct_above < MIN_ABOVE_PCT:
        return None

    avg_vol = lookback["volume"].mean()
    vol_r = cur_vol / avg_vol if avg_vol > 0 else 0
    if vol_r < VOL_RATIO:
        return None

    risk_pct = K2 * range_val / cur_close * 100

    return (code, name, latest_date, cur_close, cur_open, cur_chg,
            buy_line, sell_line, range_val, HH, HC, LC, LL, pct_above, risk_pct,
            vol_r, avg_vol)


def _load_cons_from_csv(csv_path: str):
    codes = []
    name_dict = {}
    with open(csv_path, encoding="utf-8-sig") as f:
        header = f.readline()
        for line in f:
            parts = line.strip().split(",")
            if len(parts) < 6:
                continue
            code = parts[4].strip()
            name = parts[5].strip()
            if code and code.startswith(("00", "60")):
                codes.append(code)
                name_dict[code] = name
    return codes, name_dict


def run_dual_thrust(cons_csv_path: str = None, style: str = "均衡",
                    N: int = None, K1: float = None, K2: float = None):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if N is not None and K1 is not None and K2 is not None:
        pass
    elif style in STYLE_PRESETS:
        p = STYLE_PRESETS[style]
        N, K1, K2 = p["N"], p["K1"], p["K2"]
    else:
        p = STYLE_PRESETS["均衡"]
        N, K1, K2 = p["N"], p["K1"], p["K2"]

    today = datetime.date.today()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    start_date = (today - datetime.timedelta(days=60)).strftime("%Y%m%d")
    end_date = today.strftime("%Y%m%d")

    if cons_csv_path and os.path.exists(cons_csv_path):
        print(f"从本地文件读取成分股: {cons_csv_path}")
        codes, name_dict = _load_cons_from_csv(cons_csv_path)
    else:
        print(f"联网获取中证2000({DEFAULT_INDEX})成分股...")
        try:
            cons_df = ak.index_stock_cons_csindex(symbol=DEFAULT_INDEX)
        except Exception as e:
            sys.exit(f"获取成分股失败: {e}")
        codes = cons_df.iloc[:, 4].astype(str).tolist()
        names = cons_df.iloc[:, 5].astype(str).tolist()
        name_dict = dict(zip(codes, names))
        codes = [c for c in codes if c.startswith(("00", "60"))]
    total = len(codes)
    print(f"共 {total} 只成分股, {WORKERS}线程并发检查...")
    print(f"参数: N={N}, K1={K1}, K2={K2} (风格: {style})\n")

    signals = []
    done = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {}
        for code in codes:
            sname = name_dict.get(code, code)
            f = pool.submit(_check_buy, code, sname, start_date, end_date, N, K1, K2)
            futures[f] = (code, sname)

        for f in as_completed(futures):
            code, sname = futures[f]
            done += 1
            try:
                result = f.result()
            except Exception:
                result = None

            if result is not None:
                signals.append(result)
                print(f"[{done}/{total}] {code} {sname}  BUY  "
                      f"收盘{result[3]:.2f} > 上轨{result[6]:.2f}  "
                      f"止损{result[7]:.2f}  涨幅{result[5]:.2f}%  量比{result[15]:.1f}x")
            else:
                print(f"[{done}/{total}] {code} {sname}  —")

    out_path = os.path.join(OUTPUT_DIR, "dual_thrust.md")
    with open(out_path, "w", encoding="utf-8") as f:
        if signals:
            signals.sort(key=lambda x: (-x[14], x[5]))
            f.write("# Dual Thrust 买入信号\n\n")
            f.write(f"- 风格: {style} (N={N}, K1={K1}, K2={K2})\n")
            f.write(f"- 生成时间: {now}\n")
            f.write(f"- 检查股票数: {total}\n")
            f.write(f"- 信号股票数: {len(signals)}\n")
            f.write(f"- 筛选条件: 涨幅>={MIN_CHG_PCT}%, 价格<={MAX_PRICE}, 超上轨>={MIN_ABOVE_PCT}%, 量比>={VOL_RATIO}x\n\n")
            f.write("| 股票代码 | 名称 | 最新日期 | 收盘价 | 当日涨幅 | 开盘价 | "
                    "上轨 | 下轨(止损线) | Range | 超上轨% | 止损空间% | 量比 |\n")
            f.write("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n")
            for (code, sname, date, close, cur_open, chg,
                 buy_line, sell_line, range_val, HH, HC, LC, LL,
                 pct_above, risk_pct, vol_r, avg_vol) in signals:
                f.write(f"| {code} | {sname} | {date} | {close:.2f} | {chg:.2f}% | "
                        f"{cur_open:.2f} | {buy_line:.2f} | {sell_line:.2f} | "
                        f"{range_val:.2f} | +{pct_above:.2f}% | {risk_pct:.2f}% | "
                        f"{vol_r:.1f}x |\n")
            f.write(f"\n**买入信号股票:** "
                    f"{','.join(sname for _, sname, *_ in signals)}\n\n")
            f.write("## 计算明细\n\n")
            f.write("| 股票代码 | 名称 | HH | HC | LC | LL | "
                    "HH-LC | HC-LL | Range |\n")
            f.write("| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n")
            for (code, sname, date, close, cur_open, chg,
                 buy_line, sell_line, range_val, HH, HC, LC, LL,
                 pct_above, risk_pct, vol_r, avg_vol) in signals:
                f.write(f"| {code} | {sname} | {HH:.2f} | {HC:.2f} | "
                        f"{LC:.2f} | {LL:.2f} | {HH-LC:.2f} | {HC-LL:.2f} | "
                        f"{range_val:.2f} |\n")
            f.write("\n## 字段说明\n\n")
            f.write("- **上轨** = 开盘价 + K1 × Range，收盘价突破上轨时买入\n")
            f.write("- **下轨(止损线)** = 开盘价 - K2 × Range，持仓时收盘价跌破则卖出\n")
            f.write("- **Range** = Max(HH-LC, HC-LL)，N日价格波动范围\n")
            f.write(f"- **HH** N={N}日最高价的最高价，**HC** N日收盘价的最高价\n")
            f.write(f"- **LC** N={N}日收盘价的最低价，**LL** N日最低价的最低价\n")
            f.write("- **超上轨%** 收盘价超出上轨的百分比，越大突破力度越强\n")
            f.write("- **止损空间%** 下轨距收盘价的百分比，即买入后最大潜在亏损\n")
            f.write(f"- **量比** 当日成交量 / 前N日平均成交量，>={VOL_RATIO}x 为放量突破\n")
        else:
            f.write("")

    print(f"\n{'='*60}")
    print(f"检查完成: {total}只, 买入信号{len(signals)}只")
    if signals:
        signals.sort(key=lambda x: (-x[14], x[5]))
        print(f"\nDual Thrust 买入信号: {len(signals)} 只")
        for (code, sname, date, close, cur_open, chg,
             buy_line, sell_line, range_val, HH, HC, LC, LL,
             pct_above, risk_pct, vol_r, avg_vol) in signals:
            print(f"  {code} {sname}  收盘{close:.2f} > 上轨{buy_line:.2f}  "
                  f"止损{sell_line:.2f}  涨幅{chg:.2f}%  量比{vol_r:.1f}x")
    else:
        print("无买入信号")
    print(f"报告: {out_path}")


if __name__ == "__main__":
    style = "均衡"
    csv_path = None
    custom_N, custom_K1, custom_K2 = None, None, None

    for arg in sys.argv[1:]:
        if arg.startswith("--style="):
            style = arg.split("=", 1)[1]
        elif arg.startswith("--N="):
            custom_N = int(arg.split("=", 1)[1])
        elif arg.startswith("--K1="):
            custom_K1 = float(arg.split("=", 1)[1])
        elif arg.startswith("--K2="):
            custom_K2 = float(arg.split("=", 1)[1])
        else:
            csv_path = arg

    run_dual_thrust(csv_path, style=style, N=custom_N, K1=custom_K1, K2=custom_K2)
