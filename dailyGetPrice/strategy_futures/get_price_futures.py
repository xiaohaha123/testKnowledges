# -*- coding: utf-8 -*-
"""
获取国内主要活跃期货品种主力合约的历史日线数据
============================================
使用 akshare (新浪数据源) 获取主力连续合约日线数据。
增量模式: 有本地数据的品种仅获取最近少量K线追加新行, 无数据的品种全量获取。

输出 (output_futures/ 下):
  1) 每个品种一个 CSV : 白银2610.csv (中文文件名, MetaStock ASCII 8列, 无表头)
  2) 汇总 CSV          : futures_main_daily_<日期>.csv
  3) 汇总 Excel (可选) : futures_main_daily_<日期>.xlsx  (需加 --excel)

数据源: akshare - futures_main_sina (新浪主力连续日线)

用法:
  python get_price_futures.py            # 抓取全部品种
  python get_price_futures.py RB0 I0     # 只抓指定品种
  python get_price_futures.py --excel    # 额外生成汇总 Excel
  python get_price_futures.py --force    # 强制全量刷新所有品种

依赖:
  pip install akshare pandas openpyxl
"""

import os
import sys
import re
import json
import csv
import time
import datetime
import traceback

try:
    import akshare as ak
    import pandas as pd
except ImportError as e:
    sys.exit(f"缺少依赖: {e.name}\n请运行: pip install akshare pandas openpyxl")


VARIETIES = [
    ("RB0", "螺纹钢"), ("HC0", "热轧卷板"), ("I0",  "铁矿石"), ("J0",  "焦炭"), ("JM0", "焦煤"),
    ("MA0", "甲醇"), ("TA0", "PTA"), ("PP0", "聚丙烯"), ("V0",  "PVC"), ("EG0", "乙二醇"),
    ("SA0", "纯碱"), ("FG0", "玻璃"), ("L0",  "塑料"), ("BU0", "沥青"), ("RU0", "橡胶"),
    ("FU0", "燃料油"), ("SC0", "原油"), ("LU0", "低硫燃料油"), ("SP0", "纸浆"), ("UR0", "尿素"),
    ("SH0", "烧碱"), ("EB0", "苯乙烯"), ("PF0", "短纤"), ("PX0", "对二甲苯"), ("PR0", "瓶片"),
    ("BR0", "合成橡胶"),
    ("CU0", "铜"), ("AL0", "铝"), ("ZN0", "锌"), ("NI0", "镍"), ("PB0", "铅"),
    ("SN0", "锡"), ("AU0", "黄金"), ("AG0", "白银"), ("SI0", "工业硅"), ("LC0", "碳酸锂"),
    ("AO0", "氧化铝"), ("PS0", "多晶硅"),
    ("C0",  "玉米"), ("CS0", "淀粉"), ("M0",  "豆粕"), ("Y0",  "豆油"), ("P0",  "棕榈油"),
    ("A0",  "豆一"), ("B0",  "豆二"), ("SR0", "白糖"), ("CF0", "棉花"), ("CY0", "棉纱"),
    ("OI0", "菜油"), ("RM0", "菜粕"), ("AP0", "苹果"), ("CJ0", "红枣"), ("JD0", "鸡蛋"),
    ("PK0", "花生"), ("LH0", "生猪"),
]

EXCHANGE_MAP = {
    "RB": "SHFE", "HC": "SHFE", "CU": "SHFE", "AL": "SHFE", "ZN": "SHFE",
    "NI": "SHFE", "PB": "SHFE", "SN": "SHFE", "AU": "SHFE", "AG": "SHFE",
    "BU": "SHFE", "RU": "SHFE", "FU": "SHFE", "SP": "SHFE", "AO": "SHFE",
    "BR": "SHFE",
    "SC": "INE", "LU": "INE",
    "I": "DCE", "J": "DCE", "JM": "DCE", "C": "DCE", "CS": "DCE",
    "M": "DCE", "Y": "DCE", "P": "DCE", "A": "DCE", "B": "DCE",
    "V": "DCE", "L": "DCE", "PP": "DCE", "EB": "DCE", "EG": "DCE",
    "JD": "DCE", "LH": "DCE",
    "MA": "CZCE", "TA": "CZCE", "SR": "CZCE", "CF": "CZCE", "CY": "CZCE",
    "OI": "CZCE", "RM": "CZCE", "AP": "CZCE", "CJ": "CZCE", "SA": "CZCE",
    "FG": "CZCE", "PF": "CZCE", "PK": "CZCE", "UR": "CZCE", "PX": "CZCE",
    "PR": "CZCE", "SH": "CZCE",
    "SI": "GFEX", "LC": "GFEX", "PS": "GFEX",
}

_CODE_TO_CHINESE = {code: name for code, name in VARIETIES}

AK_COL_MAP = {
    "日期": "日期",
    "开盘价": "开盘价",
    "最高价": "最高价",
    "最低价": "最低价",
    "收盘价": "收盘价",
    "成交量": "成交量",
    "持仓量": "持仓量",
}

INC_MAX_DAYS = 120

MAX_RETRY = 3
RETRY_DELAY = 3


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output_futures")
CONTRACTS_META = os.path.join(OUTPUT_DIR, "contracts.json")


def _contract_to_chinese(contract_code: str) -> str:
    m = re.match(r"^([A-Za-z]+)(\d+)$", contract_code)
    if not m:
        return contract_code
    chinese = _CODE_TO_CHINESE.get(m.group(1) + "0", m.group(1))
    return f"{chinese}{m.group(2)}"


def _chinese_to_contract(chinese_code: str) -> str:
    if not isinstance(chinese_code, str) or not chinese_code:
        return ""
    for eng_code, chinese_name in sorted(VARIETIES, key=lambda x: -len(x[1])):
        if chinese_code.startswith(chinese_name):
            digits = chinese_code[len(chinese_name):]
            base = eng_code.rstrip("0")
            if digits:
                return f"{base}{digits}"
            return eng_code
    return chinese_code


def load_contracts_meta() -> dict:
    if not os.path.exists(CONTRACTS_META):
        return {}
    try:
        with open(CONTRACTS_META, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_contracts_meta(meta: dict):
    with open(CONTRACTS_META, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)


def write_metastock_csv(df, path, code_column="品种代码"):
    codes = [_contract_to_chinese(str(c)) for c in df[code_column].values]
    dates = df["日期"].astype(str).str.replace("-", "").values
    opens = df["开盘价"].values
    highs = df["最高价"].values
    lows = df["最低价"].values
    closes = df["收盘价"].values
    vols = df["成交量"].values
    lines = []
    for i in range(len(df)):
        o = "" if pd.isna(opens[i]) else str(float(opens[i]))
        h = "" if pd.isna(highs[i]) else str(float(highs[i]))
        lo = "" if pd.isna(lows[i]) else str(float(lows[i]))
        c = "" if pd.isna(closes[i]) else str(float(closes[i]))
        v = "" if pd.isna(vols[i]) else str(int(float(vols[i])))
        lines.append(f"{codes[i]},D,{dates[i]},{o},{h},{lo},{c},{v}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        if lines:
            f.write("\n")


def append_metastock_rows(df, path, code_column="品种代码"):
    codes = [_contract_to_chinese(str(c)) for c in df[code_column].values]
    dates = df["日期"].astype(str).str.replace("-", "").values
    opens = df["开盘价"].values
    highs = df["最高价"].values
    lows = df["最低价"].values
    closes = df["收盘价"].values
    vols = df["成交量"].values
    lines = []
    for i in range(len(df)):
        o = "" if pd.isna(opens[i]) else str(float(opens[i]))
        h = "" if pd.isna(highs[i]) else str(float(highs[i]))
        lo = "" if pd.isna(lows[i]) else str(float(lows[i]))
        c = "" if pd.isna(closes[i]) else str(float(closes[i]))
        v = "" if pd.isna(vols[i]) else str(int(float(vols[i])))
        lines.append(f"{codes[i]},D,{dates[i]},{o},{h},{lo},{c},{v}")
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")


def load_metastock_df(csv_path: str):
    if not os.path.exists(csv_path):
        return None
    try:
        df = pd.read_csv(csv_path, header=None, encoding="utf-8-sig",
                         usecols=[0, 2, 3, 4, 5, 6, 7],
                         names=["合约中文名", "日期", "开盘价", "最高价",
                                "最低价", "收盘价", "成交量"])
    except Exception:
        return None
    if df is None or len(df) == 0:
        return None
    df["合约中文名"] = df["合约中文名"].fillna("").astype(str)
    d = df["日期"].astype(str)
    df["日期"] = d.str[:4] + "-" + d.str[4:6] + "-" + d.str[6:8]
    df["合约代码"] = df["合约中文名"].apply(_chinese_to_contract)
    df["品种代码"] = df["合约代码"].apply(
        lambda x: re.match(r"^([A-Za-z]+)", str(x)).group(1) + "0"
        if re.match(r"^([A-Za-z]+)", str(x)) else str(x)
    )
    name_dict = dict(VARIETIES)
    df["品种名称"] = df["品种代码"].map(name_dict).fillna(df["品种代码"])
    df["持仓量"] = 0
    for c in ["开盘价", "最高价", "最低价", "收盘价", "成交量", "持仓量"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def check_latest_date(csv_path: str):
    if not os.path.exists(csv_path):
        return None
    try:
        with open(csv_path, encoding="utf-8-sig") as f:
            lines = f.readlines()
        if not lines:
            return None
        last_line = lines[-1].strip()
        if not last_line:
            if len(lines) > 1:
                last_line = lines[-2].strip()
            else:
                return None
        parts = last_line.split(",")
        if len(parts) < 3:
            return None
        d = parts[2]
        if len(d) == 8:
            return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    except Exception:
        return None
    return None


def safe_sheet_name(name: str) -> str:
    for ch in '[]:*?/\\':
        name = name.replace(ch, "_")
    return name[:31]


def _find_existing_csv(contract_code: str):
    cn = os.path.join(OUTPUT_DIR, f"{_contract_to_chinese(contract_code)}.csv")
    if os.path.exists(cn):
        return cn
    en = os.path.join(OUTPUT_DIR, f"{contract_code}.csv")
    if os.path.exists(en):
        return en
    return cn


def _fetch_contract_kline(contract, start_date=None, end_date=None):
    for attempt in range(1, MAX_RETRY + 1):
        try:
            if start_date and end_date:
                df = ak.futures_zh_daily_sina(symbol=contract,
                                              start_date=start_date, end_date=end_date)
            else:
                df = ak.futures_zh_daily_sina(symbol=contract)
            if df is not None and len(df) > 0:
                return df
        except Exception:
            if attempt < MAX_RETRY:
                time.sleep(RETRY_DELAY)
    return None


def _czce_3to4(contract_code: str) -> str:
    m = re.match(r"^([A-Za-z]+)(\d)(\d{2})$", contract_code)
    if not m:
        return contract_code
    base, y_digit, month = m.group(1), int(m.group(2)), m.group(3)
    decade = (datetime.date.today().year // 10) * 10
    year = decade + y_digit
    if year < datetime.date.today().year - 5:
        year += 10
    return f"{base}{year % 100:02d}{month}"


def _detect_main_contract(code):
    base = code[:-1] if code.endswith("0") and len(code) > 1 else code
    base_upper = base.upper()
    exchange = EXCHANGE_MAP.get(base_upper)
    if not exchange:
        return ""

    if exchange == "DCE":
        return _find_dce_main(base)

    today = datetime.date.today()
    date_str = today.strftime("%Y%m%d")

    for attempt in range(1, MAX_RETRY + 1):
        try:
            df = ak.get_futures_daily(start_date=date_str, end_date=date_str, market=exchange)
            if df is None or len(df) == 0:
                prev = today - datetime.timedelta(days=1)
                while prev.weekday() >= 5:
                    prev -= datetime.timedelta(days=1)
                df = ak.get_futures_daily(start_date=prev.strftime("%Y%m%d"),
                                          end_date=prev.strftime("%Y%m%d"), market=exchange)
            if df is None or len(df) == 0:
                return ""

            variety_col = None
            for c in df.columns:
                if c.lower() in ("variety", "品种"):
                    variety_col = c
                    break
            if variety_col is None:
                variety_col = df.columns[-1]

            sym_col = None
            for c in df.columns:
                if c.lower() in ("symbol", "合约"):
                    sym_col = c
                    break
            if sym_col is None:
                sym_col = df.columns[0]

            oi_col = None
            for c in df.columns:
                cl = c.lower()
                if "open_interest" in cl or "持仓" in cl:
                    oi_col = c
                    break

            mask = df[variety_col].astype(str).str.upper() == base_upper
            subset = df[mask]

            if len(subset) == 0:
                return ""

            if oi_col and oi_col in subset.columns:
                subset_copy = subset.copy()
                subset_copy[oi_col] = pd.to_numeric(subset_copy[oi_col], errors="coerce")
                main_row = subset_copy.loc[subset_copy[oi_col].idxmax()]
                contract = str(main_row[sym_col]).upper()
            else:
                contract = str(subset.iloc[0][sym_col]).upper()

            if exchange == "CZCE":
                contract = _czce_3to4(contract)

            return contract
        except Exception:
            if attempt < MAX_RETRY:
                time.sleep(RETRY_DELAY)
    return ""


def _find_dce_main(base):
    today = datetime.date.today()
    candidates = []
    for delta in range(0, 7):
        y = today.year
        m = today.month + delta
        while m > 12:
            y += 1
            m -= 12
        sym = f"{base}{y % 100:02d}{m:02d}"
        candidates.append(sym)

    best_contract = ""
    best_oi = 0
    for sym in candidates:
        try:
            df = ak.futures_zh_daily_sina(symbol=sym)
            if df is not None and len(df) > 0:
                last = df.iloc[-1]
                oi = int(last["hold"]) if not pd.isna(last["hold"]) else 0
                if oi > best_oi:
                    best_oi = oi
                    best_contract = sym.upper()
        except Exception:
            pass
        time.sleep(0.08)

    return best_contract


def _kline_to_df(raw_df, code, name, current_contract):
    if raw_df is None or len(raw_df) == 0:
        return None

    col_map = {}
    for c in raw_df.columns:
        b = c.encode("utf-8") if isinstance(c, str) else c
        if b == b'\xe6\x97\xa5\xe6\x9c\x9f':
            col_map[c] = "日期"
        elif b == b'\xe5\xbc\x80\xe7\x9b\x98\xe4\xbb\xb7':
            col_map[c] = "开盘价"
        elif b == b'\xe6\x9c\x80\xe9\xab\x98\xe4\xbb\xb7':
            col_map[c] = "最高价"
        elif b == b'\xe6\x9c\x80\xe4\xbd\x8e\xe4\xbb\xb7':
            col_map[c] = "最低价"
        elif b == b'\xe6\x94\xb6\xe7\x9b\x98\xe4\xbb\xb7':
            col_map[c] = "收盘价"
        elif b == b'\xe6\x88\x90\xe4\xba\xa4\xe9\x87\x8f':
            col_map[c] = "成交量"
        elif b == b'\xe6\x8c\x81\xe4\xbb\x93\xe9\x87\x8f':
            col_map[c] = "持仓量"
        elif c.lower() == "date":
            col_map[c] = "日期"
        elif c.lower() == "open":
            col_map[c] = "开盘价"
        elif c.lower() == "high":
            col_map[c] = "最高价"
        elif c.lower() == "low":
            col_map[c] = "最低价"
        elif c.lower() == "close":
            col_map[c] = "收盘价"
        elif c.lower() == "volume":
            col_map[c] = "成交量"
        elif c.lower() in ("hold", "open_interest"):
            col_map[c] = "持仓量"

    df = raw_df.rename(columns=col_map)

    need = ["日期", "开盘价", "最高价", "最低价", "收盘价", "成交量", "持仓量"]
    avail = [c for c in need if c in df.columns]
    if "日期" not in avail or "收盘价" not in avail:
        return None

    df = df[avail].copy()

    df["日期"] = pd.to_datetime(df["日期"]).dt.strftime("%Y-%m-%d")

    for c in ["开盘价", "最高价", "最低价", "收盘价", "成交量", "持仓量"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["收盘价"]).sort_values("日期").reset_index(drop=True)

    if "持仓量" not in df.columns:
        df["持仓量"] = 0

    df.insert(0, "合约代码", current_contract)
    df.insert(0, "品种代码", code)
    df.insert(1, "品种名称", name)

    return df


def _classify_variety(code, current_contract, meta):
    old_contract = meta.get(code)
    contract_changed = (current_contract != old_contract) if old_contract else True
    existing_csv = _find_existing_csv(current_contract)
    csv_latest = check_latest_date(existing_csv)

    if contract_changed or csv_latest is None:
        return "full", old_contract, csv_latest

    try:
        last_dt = datetime.datetime.strptime(csv_latest, "%Y-%m-%d").date()
        days_gap = (datetime.date.today() - last_dt).days
    except Exception:
        return "full", old_contract, csv_latest

    if days_gap > INC_MAX_DAYS:
        return "full", old_contract, csv_latest

    if days_gap <= 0:
        return "skip", old_contract, csv_latest

    return "inc", old_contract, csv_latest


def main():
    force = "--force" in sys.argv
    no_excel = "--excel" not in sys.argv
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    today = datetime.date.today().strftime("%Y%m%d")
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    meta = load_contracts_meta()

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    target = list(VARIETIES)
    if args:
        target = [(code, name) for code, name in target if code in args]

    print(f"获取主力合约信息...")
    contract_map = {}
    for code, name in target:
        base = code[:-1] if code.endswith("0") and len(code) > 1 else code
        contract = _detect_main_contract(code)
        if contract:
            contract_map[code] = contract
            print(f"  {code} {name} → {contract}")
        else:
            print(f"  {code} {name} → 未检测到, 将使用品种代码作为合约")
            contract_map[code] = base.upper() + "0"
    print()

    mc_path = os.path.join(OUTPUT_DIR, "main_contracts.csv")
    with open(mc_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["品种代码", "品种名称", "主力合约", "数据日期"])
        writer.writeheader()
        for code, name in target:
            writer.writerow({
                "品种代码": code,
                "品种名称": name,
                "主力合约": contract_map.get(code, ""),
                "数据日期": today,
            })
    print(f"主力合约列表: {mc_path}")

    # --- 第一轮: 分类 (full / inc / skip) ---
    full_list, inc_list, skip_list = [], [], []
    info = {}

    for code, name in target:
        current_contract = contract_map.get(code)
        if not current_contract:
            continue
        if force:
            mode, old_contract, csv_latest = "full", meta.get(code), None
        else:
            mode, old_contract, csv_latest = _classify_variety(code, current_contract, meta)
        info[code] = {"contract": current_contract, "old_contract": old_contract, "csv_latest": csv_latest}

        if mode == "skip":
            skip_list.append((code, name))
        elif mode == "inc":
            inc_list.append((code, name))
        else:
            full_list.append((code, name))

    print(f"共 {len(target)} 个品种: 全量 {len(full_list)}, 增量 {len(inc_list)}, 已最新 {len(skip_list)}")
    if skip_list and not force:
        for code, name in skip_list:
            print(f"  SKIP  {code} {name}  已是最新 {info[code]['csv_latest']}")
    print()

    # --- 第二轮: 逐品种获取K线数据 ---
    kline_data = {}
    fetch_list = list(full_list) + list(inc_list)

    if fetch_list:
        print(f"开始获取 {len(fetch_list)} 个品种日线数据...")
        for code, name in fetch_list:
            current_contract = contract_map.get(code, "")
            csv_latest = info[code]["csv_latest"]
            if code in inc_list and csv_latest:
                try:
                    last_dt = datetime.datetime.strptime(csv_latest, "%Y-%m-%d").date()
                    start = (last_dt - datetime.timedelta(days=10)).strftime("%Y%m%d")
                except Exception:
                    start = None
                end = today
                raw = _fetch_contract_kline(current_contract, start_date=start, end_date=end)
            else:
                raw = _fetch_contract_kline(current_contract)

            if raw is not None and len(raw) > 0:
                kline_data[code] = raw
                last_date = str(raw.iloc[-1]["date"])
                print(f"  {code} {name}  OK  {len(raw)} 行  最新 {last_date}")
            else:
                print(f"  {code} {name}  FAIL  无数据")

            time.sleep(0.3)
        print()

    # --- 第三轮: 处理各品种 ---
    frames = {}
    success, failed = [], []

    for idx, (code, name) in enumerate(target, 1):
        tag = f"{code} {name}"
        current_contract = contract_map.get(code)
        if not current_contract:
            print(f"[{idx}/{len(target)}] {tag}  跳过(无主力合约)")
            continue

        if code not in info:
            continue
        old_contract = info[code]["old_contract"]
        csv_latest = info[code]["csv_latest"]
        contract_changed = (current_contract != old_contract) if old_contract else True
        existing_csv = _find_existing_csv(current_contract)
        is_inc = (code, name) in inc_list

        if code in skip_list:
            continue

        if code not in kline_data:
            print(f"[{idx}/{len(target)}] {tag}  跳过(无K线数据)")
            continue

        try:
            df = _kline_to_df(kline_data[code], code, name, current_contract)
            if df is None or len(df) == 0:
                raise RuntimeError("K线数据为空")

            csv_path = os.path.join(OUTPUT_DIR, f"{_contract_to_chinese(current_contract)}.csv")

            if is_inc and csv_latest and not contract_changed:
                new_rows = df[df["日期"] > csv_latest].copy()
                if len(new_rows) == 0:
                    print(f"[{idx}/{len(target)}] {tag}  INC-0  无新数据, 最新 {csv_latest}")
                    meta[code] = current_contract
                    success.append(tag)
                    continue

                append_metastock_rows(new_rows, csv_path, code_column="合约代码")
                print(f"[{idx}/{len(target)}] {tag}  INC  +{len(new_rows)} 行  {csv_latest}→{new_rows['日期'].iloc[-1]}  合约 {current_contract}")
                meta[code] = current_contract
                success.append(tag)
                continue

            combined = df

            if contract_changed and old_contract:
                old_csv_path = _find_existing_csv(old_contract)
                if os.path.exists(old_csv_path):
                    old = load_metastock_df(old_csv_path)
                    if old is not None and len(old) > 0:
                        combined = pd.concat([old, df], ignore_index=True, sort=False)
                        combined = combined.drop_duplicates(subset=["日期"], keep="last")
                        combined = combined.sort_values(["日期"], kind="mergesort").reset_index(drop=True)
            elif os.path.exists(existing_csv):
                old_df = load_metastock_df(existing_csv)
                if old_df is not None and len(old_df) > 0:
                    combined = pd.concat([old_df, df], ignore_index=True, sort=False)
                    combined = combined.drop_duplicates(subset=["日期"], keep="last")
                    combined = combined.sort_values(["日期"], kind="mergesort").reset_index(drop=True)

            write_metastock_csv(combined, csv_path, code_column="合约代码")

            label = "换月FULL" if contract_changed else "FULL"
            print(f"[{idx}/{len(target)}] {tag}  {label} {len(combined)} 行  {combined['日期'].iloc[0]}~{combined['日期'].iloc[-1]}  合约 {current_contract}")

            frames[tag] = combined
            success.append(tag)
            meta[code] = current_contract

        except Exception as e:
            print(f"[{idx}/{len(target)}] {tag}  FAIL  {e}")
            failed.append((tag, str(e)))

    save_contracts_meta(meta)

    # --- 第四轮: 从本地CSV生成汇总 (包含所有品种) ---
    print(f"\n生成汇总文件...")
    for code, name in target:
        tag = f"{code} {name}"
        if tag in frames:
            continue
        current_contract = contract_map.get(code, "")
        existing_csv = _find_existing_csv(current_contract)
        old_df = load_metastock_df(existing_csv)
        if old_df is not None:
            frames[tag] = old_df

    if frames:
        big_csv = os.path.join(OUTPUT_DIR, f"futures_main_daily_{today}.csv")
        big = pd.concat(frames.values(), ignore_index=True, sort=False)
        write_metastock_csv(big, big_csv, code_column="合约代码")
        print(f"汇总 CSV  : {big_csv}  ({len(big)} 行)")

        if not no_excel:
            xlsx_path = os.path.join(OUTPUT_DIR, f"futures_main_daily_{today}.xlsx")
            with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
                for tag, df in frames.items():
                    df.to_excel(writer, sheet_name=safe_sheet_name(tag), index=False)
            print(f"汇总 Excel : {xlsx_path}")

    print(f"\n完成: 成功 {len(success)} / 失败 {len(failed)} / 跳过 {len(skip_list)}")
    if failed:
        print("失败列表:")
        for tag, err in failed:
            print(f"  - {tag}: {err}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已中断")
    except Exception:
        traceback.print_exc()
