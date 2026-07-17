# -*- coding: utf-8 -*-
"""
获取国内主要活跃期货品种主力合约的历史日线数据
================================================
数据源  : akshare -> 新浪财经 (https://qhsz.huotaobi.cn / 新浪期货行情)
接口    : ak.futures_main_sina(symbol="<合约代码>")
例子    : RB2609 = 螺纹钢 2026年09月合约
说明    : 不再使用连续主力合约，而是抓取当前最活跃的单一期货主力合约月份。
          对每个品种会自动选择最新成交量/持仓量最大的合约月份，例如豆一会选2609，沪金会选2608。
列字段  : 品种代码 / D(市场) / 日期(YYYYMMDD) / 开盘价 / 最高价 / 最低价 / 收盘价 / 成交量

输出 (运行后在同目录 output/ 下):
  1) 每个品种一个 CSV   : <代码>.csv  (MetaStock ASCII 8列, 无表头)
  2) 汇总 CSV           : futures_main_daily_<日期>.csv (8列, 无表头)
  3) 汇总 Excel (多sheet): futures_main_daily_<日期>.xlsx  (需加 --excel)

用法:
  python get_price.py            # 抓取全部品种(默认只输出CSV)
  python get_price.py RB0 I0     # 只抓指定品种(可选)
  python get_price.py RB2609     # 只抓指定合约月份(可选)
  python get_price.py --excel    # 额外生成汇总 Excel

依赖:
  pip install akshare pandas openpyxl
"""

import os
import sys
import re
import json
import time
import datetime
import traceback

try:
    import akshare as ak
    import pandas as pd
except ImportError as e:
    sys.exit(f"缺少依赖: {e.name}\n请运行: pip install akshare pandas openpyxl")


# 主要活跃期货品种 (主力连续合约代码, 中文名)
# 代码末尾的 "0" 表示主力连续; 想加新品种照此格式追加即可
VARIETIES = [
    # 黑色系
    ("RB0", "螺纹钢"),
    ("HC0", "热轧卷板"),
    ("I0",  "铁矿石"),
    ("J0",  "焦炭"),
    ("JM0", "焦煤"),
    # 化工
    ("MA0", "甲醇"),
    ("TA0", "PTA"),
    ("PP0", "聚丙烯"),
    ("V0",  "PVC"),
    ("EG0", "乙二醇"),
    ("SA0", "纯碱"),
    ("FG0", "玻璃"),
    ("L0",  "塑料"),
    ("BU0", "沥青"),
    ("RU0", "橡胶"),
    ("FU0", "燃料油"),
    ("SC0", "原油"),
    # ("LPG0", "液化石油气"),  # Sina无数据, DCE直连被456/412封锁, 暂不可用
    ("LU0", "低硫燃料油"),
    ("SP0", "纸浆"),
    ("UR0", "尿素"),
    ("SH0", "烧碱"),
    ("EB0", "苯乙烯"),
    ("PF0", "短纤"),
    ("PX0", "对二甲苯"),
    ("PR0", "瓶片"),
    ("BR0", "合成橡胶"),
    # 有色金属
    ("CU0", "铜"),
    ("AL0", "铝"),
    ("ZN0", "锌"),
    ("NI0", "镍"),
    ("PB0", "铅"),
    ("SN0", "锡"),
    ("AU0", "黄金"),
    ("AG0", "白银"),
    ("SI0", "工业硅"),
    ("LC0", "碳酸锂"),
    ("AO0", "氧化铝"),
    ("PS0", "多晶硅"),
    # 农产品
    ("C0",  "玉米"),
    ("CS0", "淀粉"),
    ("M0",  "豆粕"),
    ("Y0",  "豆油"),
    ("P0",  "棕榈油"),
    ("A0",  "豆一"),
    ("B0",  "豆二"),
    ("SR0", "白糖"),
    ("CF0", "棉花"),
    ("CY0", "棉纱"),
    ("OI0", "菜油"),
    ("RM0", "菜粕"),
    ("AP0", "苹果"),
    ("CJ0", "红枣"),
    ("JD0", "鸡蛋"),
    ("PK0", "花生"),
    ("LH0", "生猪"),
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
CONTRACTS_META = os.path.join(OUTPUT_DIR, "contracts.json")


def load_contracts_meta() -> dict:
    """读取 contracts.json, 返回 {品种代码: 合约代码} 字典"""
    if not os.path.exists(CONTRACTS_META):
        return {}
    try:
        with open(CONTRACTS_META, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_contracts_meta(meta: dict):
    """保存 contracts.json"""
    with open(CONTRACTS_META, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)

# 请求间隔(秒), 避免被限流; sina 接口较敏感, 建议保持
SLEEP_BETWEEN = 1.0
# 失败重试次数
MAX_RETRY = 3
# 疑似限流(返回456/空)时的长退避秒数
RATELIMIT_WAIT = 60
# 主循环连续失败N次后整体暂停, 等限流恢复
CONSEC_FAIL_PAUSE = 3
CONSEC_FAIL_WAIT = 120
# 数据源最新日期落后今天超过此天数, 视为可能换月/异常, 强制重抓
STALE_DAYS = 7


def build_candidate_contract_codes(base_code: str) -> list[str]:
    """为一个品种生成近期主力合约候选, 按可能性排序。
    主力合约通常是近1~2月, 少数品种3~5月, 极少更远。
    返回顺序: +1月(最常见), 当前月, +2, -1, +3, +4, +5"""
    today = datetime.date.today()
    yy = today.year % 100
    mm = today.month
    offsets = [1, 0, 2, -1, 3, 4, 5]
    codes = []
    for off in offsets:
        total = mm + off
        y = yy + (total - 1) // 12
        m = ((total - 1) % 12) + 1
        codes.append(f"{base_code}{y:02d}{m:02d}")
    return codes


def select_main_contract_code(base_code: str) -> str:
    """选择持仓量最高的主力合约代码, 智能提前退出。
    主力合约持仓量通常远超非主力(10倍以上), 找到明显赢家即停。"""
    candidates = build_candidate_contract_codes(base_code)
    recent_start = (datetime.date.today() - datetime.timedelta(days=60)).strftime("%Y%m%d")
    best_code = None
    best_oi = 0
    second_oi = 0
    checked = 0

    for contract_code in candidates:
        try:
            df = fetch_main_daily(contract_code, start_date=recent_start, quiet=True)
        except Exception:
            continue
        if df is None or len(df) == 0 or "日期" not in df.columns:
            continue

        last_row = df.iloc[-1]
        oi = pd.to_numeric(last_row.get("持仓量"), errors="coerce")
        oi = 0 if pd.isna(oi) else float(oi)
        checked += 1

        if oi > best_oi:
            second_oi = best_oi
            best_code = contract_code
            best_oi = oi
        elif oi > second_oi:
            second_oi = oi

        if checked >= 3 and best_oi > 0 and second_oi > 0 and best_oi >= 3 * second_oi:
            break

    return best_code or candidates[0]


def build_contract_codes(raw_code: str) -> list[str]:
    """把输入代码转换成需要抓取的合约代码列表。"""
    code = raw_code.strip().upper()
    if len(code) > 4 and code[-4:].isdigit():
        return [code]

    base_code = code[:-1] if code.endswith("0") and len(code) > 1 else code
    return [select_main_contract_code(base_code)]


# 品种 -> 交易所(用于交易所直连备用源)
EXCHANGE = {}
def _init_exchange():
    shfe = "CU AL ZN NI PB SN AU AG RU FU BU SP AO BR SH".split()
    dce  = "I J JM M Y P A B C CS L V PP EG EB JD LH LPG".split()
    czce = "MA TA SA FG SR CF CY OI RM AP CJ PF PX PR UR".split()
    gfex = "SI LC PS".split()
    ine  = "SC LU".split()
    for c in shfe: EXCHANGE[c] = "SHFE"
    for c in dce:  EXCHANGE[c] = "DCE"
    for c in czce: EXCHANGE[c] = "CZCE"
    for c in gfex: EXCHANGE[c] = "GFEX"
    for c in ine:  EXCHANGE[c] = "INE"
_init_exchange()

_EX_CACHE = {}  # (market,start,end) -> df, 避免同交易所重复拉


def _to_exchange_symbol(code: str, market: str) -> str:
    """新浪4位合约码 -> 交易所码(CZCE用3位, 其余4位)。SA2609->SA609(CZCE) / RB2609->RB2609。"""
    m = re.match(r"^([A-Za-z]+)(\d+)$", code)
    if not m:
        return code
    base, digits = m.group(1), m.group(2)
    if market == "CZCE" and len(digits) == 4:
        return base + digits[1:]   # 去掉首位年份"2", 4位->3位
    return code


def fetch_via_exchange(contract_code: str, start_date: str, end_date: str):
    """备用源: 交易所直连(get_futures_daily), 不受新浪456影响。
    只取近180天(全历史太重), 旧历史由main的merge保留。返回列名同新浪格式。"""
    m = re.match(r"^([A-Za-z]+)", contract_code)
    if not m:
        return None
    market = EXCHANGE.get(m.group(1))
    if not market:
        return None
    sym = _to_exchange_symbol(contract_code, market)
    fb_start = max(start_date, (datetime.date.today() - datetime.timedelta(days=180)).strftime("%Y%m%d"))
    key = (market, fb_start, end_date)
    if key not in _EX_CACHE:
        try:
            _EX_CACHE[key] = ak.get_futures_daily(start_date=fb_start, end_date=end_date, market=market)
        except Exception:
            _EX_CACHE[key] = None
    df = _EX_CACHE[key]
    if df is None or len(df) == 0:
        return None
    df = df[df["symbol"].astype(str) == sym]
    if len(df) == 0:
        return None
    df = df.rename(columns={"date": "日期", "open": "开盘价", "high": "最高价",
                            "low": "最低价", "close": "收盘价", "volume": "成交量",
                            "open_interest": "持仓量"})
    df = df[["日期", "开盘价", "最高价", "最低价", "收盘价", "成交量", "持仓量"]].copy()
    df["日期"] = pd.to_datetime(df["日期"].astype(str).str.split(".").str[0],
                                format="%Y%m%d", errors="coerce").dt.strftime("%Y-%m-%d")
    for c in ["开盘价", "最高价", "最低价", "收盘价", "成交量", "持仓量"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["收盘价"]).sort_values("日期").reset_index(drop=True)
    return df


def fetch_main_daily(contract_code: str, start_date: str = "19900101", quiet: bool = False) -> pd.DataFrame:
    """抓取单个合约历史日线。主源新浪, 超时/限流则转交易所直连备用源。
    quiet=True 时静默且跳过重试(用于选合约/探测), 大幅提速。"""
    today = datetime.date.today().strftime("%Y%m%d")
    sina_err = None
    # 1) 主源: 新浪; quiet模式只试1次
    attempts = (1,) if quiet else (1, 2)
    for attempt in attempts:
        try:
            df = ak.futures_main_sina(symbol=contract_code, start_date=start_date, end_date=today)
            if df is None or len(df) == 0:
                raise RuntimeError("返回空数据")
            return df
        except Exception as e:
            sina_err = e
            if not quiet and attempt == 1:
                time.sleep(2)
    # 2) 备用源: 交易所直连(不受新浪456影响)
    try:
        df = fetch_via_exchange(contract_code, start_date, today)
        if df is not None and len(df) > 0:
            if not quiet:
                print("[转交易所直连]", end=" ", flush=True)
            return df
    except Exception as e:
        sina_err = e
    raise sina_err


def safe_sheet_name(name: str) -> str:
    """Excel sheet 名限制: <=31 字符, 不能含 []:*?/\\ """
    for ch in '[]:*?/\\':
        name = name.replace(ch, "_")
    return name[:31]


def find_latest_summary(ext: str) -> str | None:
    """找到最近的汇总文件(按文件名日期后缀降序), 返回完整路径或 None。"""
    prefix = "futures_main_daily_"
    files = [f for f in os.listdir(OUTPUT_DIR)
             if f.startswith(prefix) and f.endswith(f".{ext}")]
    if not files:
        return None
    files.sort(reverse=True)
    return os.path.join(OUTPUT_DIR, files[0])


def write_metastock_csv(df, path):
    """将 DataFrame 写入 8列 MetaStock ASCII CSV(无表头)。
    格式: 品种代码,D,YYYYMMDD,开,高,低,收,成交量"""
    codes = df["品种代码"].astype(str).values
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


def load_metastock_df(csv_path: str):
    """读取 8列 MetaStock ASCII CSV(无表头), 返回带中文列名的 DataFrame 或 None。
    格式: 品种代码,D,YYMMDD,开,高,低,收,成交量"""
    if not os.path.exists(csv_path):
        return None
    try:
        df = pd.read_csv(csv_path, header=None, encoding="utf-8-sig",
                         usecols=[0, 2, 3, 4, 5, 6, 7],
                         names=["品种代码", "日期", "开盘价", "最高价",
                                "最低价", "收盘价", "成交量"])
    except Exception:
        return None
    if df is None or len(df) == 0:
        return None
    d = df["日期"].astype(str)
    df["日期"] = d.str[:4] + "-" + d.str[4:6] + "-" + d.str[6:8]
    name_dict = dict(VARIETIES)
    df["品种名称"] = df["品种代码"].map(name_dict).fillna(df["品种代码"])
    df["合约代码"] = ""
    df["持仓量"] = 0
    for c in ["开盘价", "最高价", "最低价", "收盘价", "成交量", "持仓量"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def check_latest_date(csv_path: str):
    """轻量检查已有 CSV 的最新日期, 返回 'YYYY-MM-DD' 或 None。
    只读最后一行, 不做全量加载。"""
    if not os.path.exists(csv_path):
        return None
    try:
        with open(csv_path, encoding="utf-8-sig") as f:
            lines = f.readlines()
        if not lines:
            return None
        # 最后一行的第3列是日期(YYYYMMDD)
        last_line = lines[-1].strip()
        parts = last_line.split(",")
        if len(parts) < 3:
            return None
        d = parts[2]  # YYYYMMDD
        if len(d) == 8:
            return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    except Exception:
        return None
    return None


def probe_latest_date(contract_code: str):
    """轻量探测数据源最新日期(只取近30天), 失败返回 None。"""
    start = (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
    try:
        df = fetch_main_daily(contract_code, start_date=start, quiet=True)
    except Exception:
        return None
    if df is None or len(df) == 0 or "日期" not in df.columns:
        return None
    return pd.to_datetime(df["日期"]).max().strftime("%Y-%m-%d")


def main():
    # 命令行可选: 指定品种代码或合约代码
    no_excel = "--excel" not in sys.argv
    args = [a for a in sys.argv[1:] if a != "--excel"]
    if args:
        targets = [c.strip().upper() for c in args]
        target = []
        for c in targets:
            if c.endswith("0") and len(c) > 1:
                target.append((c, dict(VARIETIES).get(c, c)))
            else:
                target.append((c, c))
    else:
        target = VARIETIES

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    today = datetime.date.today().strftime("%Y%m%d")
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    meta = load_contracts_meta()
    print(f"共 {len(target)} 个品种, 数据源: akshare(新浪), 输出目录: {OUTPUT_DIR}\n")

    frames = {}
    success, failed = [], []
    consec_fail = 0

    for idx, (code, name) in enumerate(target, 1):
        tag = f"{code} {name}"
        csv_path = os.path.join(OUTPUT_DIR, f"{code}.csv")
        print(f"[{idx}/{len(target)}] {tag} 抓取中...", end=" ", flush=True)

        # 已有 CSV 且已是今天日期 → 跳过
        csv_latest = check_latest_date(csv_path)
        if csv_latest is not None and csv_latest >= today_str:
            old_df = load_metastock_df(csv_path)
            if old_df is not None:
                print(f"SKIP  已是最新 {csv_latest}")
                frames[tag] = old_df
                success.append(tag)
                time.sleep(SLEEP_BETWEEN)
                continue

        try:
            # ========== 增量追加: 合约未换月时只抓新日期的数据 ==========
            incremental_ok = False
            if csv_latest is not None:
                old_contract = meta.get(code)
                if old_contract:
                    # 计算增量起始日期(csv_latest的次日)
                    last_dt = datetime.datetime.strptime(csv_latest, "%Y-%m-%d").date()
                    next_dt = last_dt + datetime.timedelta(days=1)
                    start_inc = next_dt.strftime("%Y%m%d")
                    try:
                        inc_df = fetch_main_daily(old_contract, start_date=start_inc)
                    except Exception:
                        inc_df = None

                    if inc_df is not None and len(inc_df) > 0:
                        # 检查最后一行的持仓量, 判断合约是否还有活力
                        last_oi = pd.to_numeric(inc_df.iloc[-1].get("持仓量", 0), errors="coerce")
                        if pd.isna(last_oi):
                            last_oi = 0
                        if last_oi > 0:
                            # 合约仍有持仓 → 增量追加
                            inc_df = inc_df.copy()
                            if "日期" in inc_df.columns:
                                inc_df["日期"] = pd.to_datetime(inc_df["日期"]).dt.strftime("%Y-%m-%d")
                            if "动态结算价" in inc_df.columns:
                                inc_df = inc_df.drop(columns=["动态结算价"])
                            inc_df.insert(0, "合约代码", old_contract)
                            inc_df.insert(0, "品种代码", code)
                            inc_df.insert(1, "品种名称", name)

                            old_df = load_metastock_df(csv_path)
                            if old_df is not None and len(old_df) > 0:
                                combined = pd.concat([old_df, inc_df], ignore_index=True, sort=False)
                                combined = combined.drop_duplicates(subset=["日期"], keep="last")
                                combined = combined.sort_values(["日期"], kind="mergesort").reset_index(drop=True)
                            else:
                                combined = inc_df

                            write_metastock_csv(combined, csv_path)
                            n_new = len(inc_df)
                            print(f"INC  {n_new} 行追加  {csv_latest}→{combined['日期'].iloc[-1]}  合约 {old_contract}")
                            frames[tag] = combined
                            meta[code] = old_contract
                            success.append(tag)
                            consec_fail = 0
                            incremental_ok = True

            # ========== 全量抓取: 首次/换月/增量失败时 ==========
            if not incremental_ok:
                contract_codes = build_contract_codes(code)
                pieces = []
                for contract_code in contract_codes:
                    df = fetch_main_daily(contract_code)
                    if df is None or len(df) == 0:
                        continue
                    df = df.copy()
                    if "日期" in df.columns:
                        df["日期"] = pd.to_datetime(df["日期"]).dt.strftime("%Y-%m-%d")
                    if "动态结算价" in df.columns:
                        df = df.drop(columns=["动态结算价"])
                    df.insert(0, "合约代码", contract_code)
                    df.insert(0, "品种代码", code)
                    df.insert(1, "品种名称", name)
                    pieces.append(df)

                if not pieces:
                    raise RuntimeError("没有获取到任何数据")

                combined = pd.concat(pieces, ignore_index=True, sort=False)
                combined = combined.sort_values(["日期", "合约代码"], kind="mergesort").reset_index(drop=True)
                # 与旧CSV合并(备用源只回近180天, 合并保留旧历史)
                old = load_metastock_df(csv_path)
                if old is not None and len(old) > 0:
                    combined = pd.concat([old, combined], ignore_index=True, sort=False)
                    combined = combined.drop_duplicates(subset=["日期"], keep="last")
                    combined = combined.sort_values(["日期"], kind="mergesort").reset_index(drop=True)

                write_metastock_csv(combined, csv_path)
                actual_contract = contract_codes[0]
                print(f"FULL {len(combined)} 行  日期 {combined['日期'].iloc[0]}~{combined['日期'].iloc[-1]}  合约 {', '.join(contract_codes)} -> {os.path.basename(csv_path)}")

                frames[tag] = combined
                meta[code] = actual_contract
                success.append(tag)
                consec_fail = 0

        except Exception as e:
            print(f"FAIL  {e}")
            failed.append((tag, str(e)))
            consec_fail += 1
            if consec_fail >= CONSEC_FAIL_PAUSE:
                print(f"\n连续 {consec_fail} 个失败, 疑似新浪限流, 暂停 {CONSEC_FAIL_WAIT}s 等待IP解封...")
                time.sleep(CONSEC_FAIL_WAIT)
                consec_fail = 0
        time.sleep(SLEEP_BETWEEN)

    save_contracts_meta(meta)

    if frames:
        is_partial = len(args) > 0
        big_csv = os.path.join(OUTPUT_DIR, f"futures_main_daily_{today}.csv")

        if is_partial:
            # 部分抓取: 合并到已有汇总(找最近的, 跨日期也能合并), 只替换目标品种
            target_codes = [code for code, _ in target]
            old_csv = find_latest_summary("csv")
            if old_csv:
                try:
                    old_big = load_metastock_df(old_csv)
                    if old_big is not None:
                        old_big = old_big[~old_big["品种代码"].astype(str).isin(target_codes)]
                        big = pd.concat([old_big] + list(frames.values()), ignore_index=True, sort=False)
                    else:
                        big = pd.concat(frames.values(), ignore_index=True, sort=False)
                except Exception:
                    big = pd.concat(frames.values(), ignore_index=True, sort=False)
            else:
                big = pd.concat(frames.values(), ignore_index=True, sort=False)
            big = big.sort_values(["品种代码", "日期"], kind="mergesort").reset_index(drop=True)
            write_metastock_csv(big, big_csv)
            print(f"\n汇总 CSV  : {big_csv}  ({len(big)} 行, 已合并 {len(target)} 个品种)")
        else:
            # 全量抓取: 直接覆盖
            big = pd.concat(frames.values(), ignore_index=True, sort=False)
            write_metastock_csv(big, big_csv)
            print(f"\n汇总 CSV  : {big_csv}  ({len(big)} 行)")

        if not no_excel:
            xlsx_path = os.path.join(OUTPUT_DIR, f"futures_main_daily_{today}.xlsx")
            if is_partial:
                old_xlsx = find_latest_summary("xlsx")
                sheets = {}
                if old_xlsx:
                    try:
                        sheets = pd.read_excel(old_xlsx, sheet_name=None)
                    except Exception:
                        pass
                sheets.update({safe_sheet_name(tag): df for tag, df in frames.items()})
                with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
                    for sn, df in sheets.items():
                        df.to_excel(writer, sheet_name=sn, index=False)
                print(f"汇总 Excel : {xlsx_path}  (已合并 {len(sheets)} 个 sheet)")
            else:
                with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
                    for tag, df in frames.items():
                        df.to_excel(writer, sheet_name=safe_sheet_name(tag), index=False)
                print(f"汇总 Excel : {xlsx_path}")

    print(f"\n完成: 成功 {len(success)} / 失败 {len(failed)}")
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