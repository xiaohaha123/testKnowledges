# -*- coding: utf-8 -*-
"""
输出沪深主板当天收盘价突破前20日最高价的股票
============================================
联网获取中证2000成分股日线数据(不下载到本地), 对每只股票判断:
  最新收盘价 > 前20日最高价 → 突破
输出: beyond_daily20.md (突破股票列表, 无突破则输出空文件)

用法:
  python -m strategy_stocks.get_beyond_daily20
  python -m strategy_stocks.get_beyond_daily20 000852   # 也可指定其他指数代码
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


def _check_one(code, name, start_date, end_date):
    df = _fetch_stock_daily(code, start_date, end_date)
    if df is None or len(df) < 21:
        return None
    df = df.sort_values("date").reset_index(drop=True)
    last = df.iloc[-1]
    prev = df.iloc[-2]
    recent20 = df.iloc[-21:-1]
    high20 = recent20["high"].max()
    cur_close = last["close"]
    latest_date = str(last["date"])
    cur_chg = (cur_close - prev["close"]) / prev["close"] * 100
    if cur_close > high20 and cur_chg >= 2.0 and cur_close <= 30.0:
        pct = (cur_close - high20) / high20 * 100
        return (code, name, latest_date, cur_close, high20, pct, cur_chg)
    return None


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


def run_beyond_daily20(cons_csv_path: str = None):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    today = datetime.date.today()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    start_date = (today - datetime.timedelta(days=40)).strftime("%Y%m%d")
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
    print(f"共 {total} 只成分股, {WORKERS}线程并发检查...\n")

    beyond = []
    done = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {}
        for code in codes:
            sname = name_dict.get(code, code)
            f = pool.submit(_check_one, code, sname, start_date, end_date)
            futures[f] = (code, sname)

        for f in as_completed(futures):
            code, sname = futures[f]
            done += 1
            try:
                result = f.result()
            except Exception:
                result = None

            if result is not None:
                beyond.append(result)
                print(f"[{done}/{total}] {code} {sname}  突破! 收盘{result[3]:.2f} 涨幅{result[6]:.2f}% > 20日最高{result[4]:.2f}  +{result[5]:.2f}%")
            else:
                print(f"[{done}/{total}] {code} {sname}  —")

    out_path = os.path.join(OUTPUT_DIR, "beyond_daily20.md")
    with open(out_path, "w", encoding="utf-8") as f:
        if beyond:
            beyond.sort(key=lambda x: (-x[6], x[3]))
            f.write("# 收盘价突破20日最高价股票\n\n")
            f.write(f"- 指数: 中证2000\n")
            f.write(f"- 生成时间: {now}\n")
            f.write(f"- 检查股票数: {total}\n")
            f.write(f"- 突破股票数: {len(beyond)}\n\n")
            f.write("| 股票代码 | 名称 | 最新日期 | 收盘价 | 当日涨幅 | 20日最高价 | 突破幅度 |\n")
            f.write("| --- | --- | --- | --- | --- | --- | --- |\n")
            for code, sname, date, close, high, pct, chg in beyond:
                f.write(f"| {code} | {sname} | {date} | {close:.2f} | {chg:.2f}% | {high:.2f} | +{pct:.2f}% |\n")
            names = ",".join(sname for _, sname, *_ in beyond)
            f.write(f"\n**突破股票名称:** {names}\n")
        else:
            f.write("")

    print(f"\n{'='*60}")
    print(f"检查完成: {total}只, 突破{len(beyond)}只")
    if beyond:
        beyond.sort(key=lambda x: (-x[6], x[3]))
        print(f"\n突破20日最高价: {len(beyond)} 只")
        for code, sname, date, close, high, pct, chg in beyond:
            print(f"  {code} {sname}  收盘{close:.2f} 涨幅{chg:.2f}% > 20日最高{high:.2f}  +{pct:.2f}%")
    else:
        print("无股票突破20日最高价")
    print(f"报告: {out_path}")


if __name__ == "__main__":
    cons_csv = sys.argv[1] if len(sys.argv) > 1 else None
    run_beyond_daily20(cons_csv)
