# -*- coding: utf-8 -*-
"""
最新K线形态扫描(多品种批量, 单文件输出)
========================================
读取 get_price.py 输出的**汇总 CSV**(8列 MetaStock ASCII, 含全部品种), 对每个品种
仅扫描**最新一根K线**完成的形态(对照 summary.md), 列出全部命中
形态(多/空/中性)。
输出: 1 份 fullscan_index.md(含全部品种汇总表 + 命中品种详情+图表)。
无命中品种不生成图表。
图例: 多标于当日低点下方(^红), 空标于当日高点上方(v绿), 中性标低点下方(o灰)。
用法: python pattern_fullscan.py output/futures_main_daily_20260708.csv
(8列 MetaStock ASCII 格式, 无表头)
"""

import os
import sys
import datetime
from collections import defaultdict

import pandas as pd

from get_price import VARIETIES, load_metastock_df

IMG_BARS = 60

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


def tick_of(code: str) -> float:
    code = code.upper()
    if code.endswith("0"):
        code = code[:-1]
    return TICK_MAP.get(code, 1.0)


def fmt(price, tick=1):
    if pd.isna(price):
        return ""
    p = float(price)
    t = float(tick)
    if t >= 1:
        return f"{int(round(p))}"
    decimals = max(0, -len(str(t).rstrip("0").split(".")[-1]) + 1)
    decimals = max(decimals, len(str(t).rstrip("0").split(".")[-1]))
    return f"{p:.{decimals}f}"


# ---------- 形态检测辅助 ----------
def _body(r):
    return abs(r["收盘价"] - r["开盘价"])

def _upper_shadow(r):
    return r["最高价"] - max(r["收盘价"], r["开盘价"])

def _lower_shadow(r):
    return min(r["收盘价"], r["开盘价"]) - r["最低价"]

def _range(r):
    return r["最高价"] - r["最低价"]

def _is_yang(r):
    return r["收盘价"] > r["开盘价"]

def _is_yin(r):
    return r["收盘价"] < r["开盘价"]

def _midpoint(r):
    return (r["收盘价"] + r["开盘价"]) / 2

def _atr(df, idx, period=14):
    start = max(0, idx - period + 1)
    trs = []
    for i in range(start, idx + 1):
        h = df.iloc[i]["最高价"]
        l = df.iloc[i]["最低价"]
        pc = df.iloc[i - 1]["收盘价"] if i > 0 else df.iloc[i]["开盘价"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs) if trs else 0

def _trend_up(df, idx, n=5):
    if idx < n * 2:
        return True
    recent = df.iloc[idx - n + 1: idx + 1]["收盘价"].mean()
    prev = df.iloc[idx - n * 2 + 1: idx - n + 1]["收盘价"].mean()
    return recent > prev

def _trend_down(df, idx, n=5):
    if idx < n * 2:
        return True
    recent = df.iloc[idx - n + 1: idx + 1]["收盘价"].mean()
    prev = df.iloc[idx - n * 2 + 1: idx - n + 1]["收盘价"].mean()
    return recent < prev


def _detect_patterns(df, idx):
    """检测第 idx 根 K 线的全部形态"""
    if idx < 1:
        return []
    r = df.iloc[idx]
    k1 = df.iloc[idx - 1] if idx >= 1 else None
    k2 = r
    body = _body(r)
    rng = _range(r)
    ushadow = _upper_shadow(r)
    lshadow = _lower_shadow(r)
    atr = _atr(df, idx)
    results = []

    if rng == 0:
        return []

    # 锤子线 / 上吊线
    if lshadow >= 2 * body and ushadow <= 0.3 * body and body <= 0.3 * rng:
        if _trend_down(df, idx - 1):
            results.append({"name": "锤子线", "direction": "多", "note": "下影≥2×实体, 下跌末端信号"})
        elif _trend_up(df, idx - 1):
            results.append({"name": "上吊线", "direction": "空", "note": "上影短小, 上涨末端预警"})

    # 流星线 / 倒锤子线
    if ushadow >= 2 * body and lshadow <= 0.3 * body and body <= 0.3 * rng:
        if _trend_up(df, idx - 1):
            results.append({"name": "流星线", "direction": "空", "note": f"上影{ushadow:.1f}≥2×实体"})
        elif _trend_down(df, idx - 1):
            results.append({"name": "倒锤子线", "direction": "多", "note": "下跌末端, 长上影"})

    # 十字星
    if body <= 0.05 * rng:
        sub = ""
        if ushadow > 2 * lshadow and ushadow > 0.3 * rng:
            sub = "墓碑十字"
        elif lshadow > 2 * ushadow and lshadow > 0.3 * rng:
            sub = "蜻蜓十字"
        elif ushadow > 0.3 * rng and lshadow > 0.3 * rng:
            sub = "长腿十字"
        else:
            sub = "十字"
        results.append({"name": f"十字星({sub})" if sub != "十字" else "十字星",
                        "direction": "中性", "note": "需次根K线确认方向"})

    # 大阳线 / 大阴线
    if body >= 0.7 * rng and rng >= 1.3 * atr:
        if _is_yang(r):
            results.append({"name": "大阳线", "direction": "多", "note": f"实体占区间{int(body/rng*100)}%, 区间≥1.3×ATR"})
        else:
            results.append({"name": "大阴线", "direction": "空", "note": f"实体占区间{int(body/rng*100)}%, 区间≥1.3×ATR"})

    # 纺锤线
    if body <= 0.3 * rng and lshadow >= body and ushadow >= body:
        results.append({"name": "纺锤线", "direction": "中性", "note": "多空分歧, 震荡预警"})

    # --- 双根形态 ---
    if k1 is not None:
        b1 = _body(k1)
        r1 = _range(k1)
        # 看涨吞没
        if _is_yin(k1) and _is_yang(k2) and k2["开盘价"] < k1["收盘价"] and k2["收盘价"] > k1["开盘价"]:
            b2 = _body(k2)
            if b2 > b1:
                results.append({"name": "看涨吞没", "direction": "多", "note": "K2阳实体包裹K1阴实体"})
        # 看跌吞没
        if _is_yang(k1) and _is_yin(k2) and k2["开盘价"] > k1["收盘价"] and k2["收盘价"] < k1["开盘价"]:
            b2 = _body(k2)
            if b2 > b1:
                results.append({"name": "看跌吞没", "direction": "空", "note": "K2阴实体包裹K1阳实体"})
        # 刺透形态
        if _is_yin(k1) and _is_yang(k2) and k2["开盘价"] < k1["最低价"] and k2["收盘价"] > _midpoint(k1) and k2["收盘价"] < k1["收盘价"]:
            results.append({"name": "刺透形态", "direction": "多", "note": "K1大阴, K2低开创新低, 收盘过K1实体中线"})
        # 乌云盖顶
        if _is_yang(k1) and _is_yin(k2) and k2["开盘价"] > k1["最高价"] and k2["收盘价"] < _midpoint(k1) and k2["收盘价"] > k1["开盘价"]:
            results.append({"name": "乌云盖顶", "direction": "空", "note": "K1大阳, K2高开创高, 收盘跌破K1实体中线"})
        # 孕线
        if (k2["开盘价"] >= k1["开盘价"] and k2["收盘价"] <= k1["收盘价"]
                or k2["开盘价"] <= k1["开盘价"] and k2["收盘价"] >= k1["收盘价"]):
            inner_o = min(k2["开盘价"], k2["收盘价"])
            inner_c = max(k2["开盘价"], k2["收盘价"])
            outer_o = min(k1["开盘价"], k1["收盘价"])
            outer_c = max(k1["开盘价"], k1["收盘价"])
            if inner_o > outer_o and inner_c < outer_c:
                b2 = _body(k2)
                if _is_yang(k1) and _is_yin(k2):
                    if b2 <= 0.05 * r1:
                        results.append({"name": "看跌孕十字", "direction": "空", "note": "K1长阳+K2十字嵌套, 多头乏力"})
                    else:
                        results.append({"name": "看跌孕线", "direction": "空", "note": "K1长阳+K2小实体嵌套, 多头乏力"})
                elif _is_yin(k1) and _is_yang(k2):
                    if b2 <= 0.05 * r1:
                        results.append({"name": "看涨孕十字", "direction": "多", "note": "K1长阴+K2十字嵌套, 空头乏力"})
                    else:
                        results.append({"name": "看涨孕线", "direction": "多", "note": "K1长阴+K2小实体嵌套, 趋势衰竭"})
        # 早晨之星
        if idx >= 2:
            k0 = df.iloc[idx - 2]
            if (_is_yin(k0) and _body(k0) >= 0.7 * _range(k0) and _range(k0) >= 1.3 * atr
                    and _body(k1) <= 0.3 * _range(k1) and k2["收盘价"] > _midpoint(k0) and _is_yang(k2)):
                results.append({"name": "早晨之星", "direction": "多", "note": "下跌趋势+星线+阳线刺入"})
        # 黄昏之星
        if idx >= 2:
            k0 = df.iloc[idx - 2]
            if (_is_yang(k0) and _body(k0) >= 0.7 * _range(k0) and _range(k0) >= 1.3 * atr
                    and _body(k1) <= 0.3 * _range(k1) and k2["收盘价"] < _midpoint(k0) and _is_yin(k2)):
                results.append({"name": "黄昏之星", "direction": "空", "note": "上涨趋势+星线+阴线刺入"})

    # --- 三根形态 ---
    if idx >= 2:
        k0 = df.iloc[idx - 2]
        # 红三兵
        if all(_is_yang(df.iloc[idx - j]) for j in range(3)):
            if df.iloc[idx]["收盘价"] > df.iloc[idx - 1]["收盘价"] > k0["收盘价"] and all(_body(df.iloc[idx - j]) > 0 for j in range(3)):
                results.append({"name": "红三兵", "direction": "多", "note": "三连阳, 收盘持续新高"})
        # 三乌鸦
        if all(_is_yin(df.iloc[idx - j]) for j in range(3)):
            if df.iloc[idx]["收盘价"] < df.iloc[idx - 1]["收盘价"] < k0["收盘价"] and all(_body(df.iloc[idx - j]) > 0 for j in range(3)):
                results.append({"name": "三乌鸦", "direction": "空", "note": "三连阴, 低点持续下移"})
        # 上升三法
        if _is_yang(k0) and _is_yang(k2) and all(_range(df.iloc[idx - j]) < _body(k0) for j in [1]) and k2["收盘价"] > k0["收盘价"]:
            results.append({"name": "上升三法", "direction": "多", "note": "长阳+小回调+末根大阳创新高"})
        # 下跌三法
        if _is_yin(k0) and _is_yin(k2) and all(_range(df.iloc[idx - j]) < _body(k0) for j in [1]) and k2["收盘价"] < k0["收盘价"]:
            results.append({"name": "下跌三法", "direction": "空", "note": "长阴+小反弹+末根大阴创新低"})

    # --- 跳空缺口 ---
    if k1 is not None:
        if k2["最低价"] > k1["最高价"]:
            results.append({"name": "向上跳空缺口", "direction": "多", "note": f"支撑窗口 [{k1['最高价']}, {k2['最低价']}]"})
        if k2["最高价"] < k1["最低价"]:
            results.append({"name": "向下跳空缺口", "direction": "空", "note": f"压力窗口 [{k2['最高价']}, {k1['最低价']}]"})

    # --- 岛形反转 ---
    if idx >= 2:
        k0 = df.iloc[idx - 2]
        if k1["最低价"] > k0["最高价"] and k2["最高价"] < k1["最低价"]:
            results.append({"name": "岛形反转", "direction": "空", "note": "双向跳空, 顶部孤岛"})
        elif k1["最高价"] < k0["最低价"] and k2["最低价"] > k1["最高价"]:
            results.append({"name": "岛形反转", "direction": "多", "note": "双向跳空, 底部孤岛"})

    return results


def analyze(df):
    """扫描全部 K 线, 返回 (matches, last_idx)。
    matches: [{name, direction, note, idx}]"""
    matches = []
    for i in range(1, len(df)):
        hits = _detect_patterns(df, i)
        for h in hits:
            h["idx"] = i
            matches.append(h)
    return matches, len(df) - 1

# ---------- 输出目录(与 get_price 的 output/ 分开) ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PATTERN_OUTPUT_DIR = os.path.join(BASE_DIR, "pattern_output")


def bar_of(df, i):
    r = df.iloc[i]
    return float(r["开盘价"]), float(r["最高价"]), float(r["最低价"]), float(r["收盘价"])


def plot_fullscan(df, hits, out_png, title, tick):
    """绘制最近 IMG_BARS 根K线, 在命中根标注方向箭头。
    hits: [(bar_idx_in_df, name, direction, note), ...]"""
    import mplfinance as mpf
    import matplotlib
    matplotlib.use("Agg")
    matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
    matplotlib.rcParams["axes.unicode_minus"] = False
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    n = len(df)
    start = max(0, n - IMG_BARS)
    dc = df.iloc[start:].copy()
    dc["日期"] = pd.to_datetime(dc["日期"])
    pdf = dc.set_index("日期")[["开盘价", "最高价", "最低价", "收盘价", "成交量"]]
    pdf.columns = ["Open", "High", "Low", "Close", "Volume"]
    pdf = pdf.astype(float)

    mc = mpf.make_marketcolors(up="#d32f2f", down="#2e7d32",
                               edge="inherit", wick="inherit")
    style = mpf.make_mpf_style(base_mpf_style="charles", marketcolors=mc,
                               rc={"font.sans-serif": ["Microsoft YaHei", "SimHei"]})
    fig, axes = mpf.plot(pdf, type="candle", style=style, figsize=(16, 8),
                         returnfig=True, tight_layout=True)
    ax = axes[0]

    # 按bar分组(调整索引到切片内), 多标低点下方, 空标高点上方
    by_bar = defaultdict(list)
    for i, nm, d, note in hits:
        j = i - start
        if 0 <= j < len(dc):
            by_bar[j].append((nm, d))
    dates = dc["日期"].values
    for j, lst in by_bar.items():
        O, H, L, C = bar_of(dc, j)
        rng = H - L
        off = max(rng * 0.20, C * 0.0008, tick * 2)
        below = [x for x in lst if x[1] in ("多", "中性")]
        above = [x for x in lst if x[1] == "空"]
        for idx, (nm, d) in enumerate(below):
            y = L - off * (idx + 1)
            m = "^" if d == "多" else "o"
            c = "#d32f2f" if d == "多" else "#9e9e9e"
            ax.scatter([dates[j]], [y], marker=m, color=c, s=55, zorder=5)
        for idx, (nm, d) in enumerate(above):
            y = H + off * (idx + 1)
            ax.scatter([dates[j]], [y], marker="v", color="#2e7d32", s=55, zorder=5)

    legend = [
        Line2D([0], [0], marker="^", color="w", markerfacecolor="#d32f2f",
               markersize=10, label="多"),
        Line2D([0], [0], marker="v", color="w", markerfacecolor="#2e7d32",
               markersize=10, label="空"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#9e9e9e",
               markersize=8, label="中性"),
    ]
    ax.legend(handles=legend, loc="upper left", fontsize=9)
    ax.set_title(title, fontsize=12, fontweight="bold")

    fig.savefig(out_png, dpi=100)
    plt.close(fig)


def main():
    if len(sys.argv) < 2:
        sys.exit("用法: python pattern_fullscan.py <汇总CSV>")
    path = sys.argv[1]
    if not os.path.isabs(path):
        path = os.path.abspath(path)
    if not os.path.exists(path):
        sys.exit(f"文件不存在: {path}")

    df = load_metastock_df(path)

    out_dir = os.path.join(PATTERN_OUTPUT_DIR, "fullscan")
    os.makedirs(out_dir, exist_ok=True)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = []
    lines.append("# 最新K线形态扫描汇总")
    lines.append("")
    lines.append(f"- 数据文件: `{os.path.basename(path)}`")
    lines.append(f"- 生成时间: {now}")
    lines.append("- 识别: 对照 `summary.md` 全部 23 种形态, 仅扫描**最新一根K线**")
    lines.append("- 输出: 全部命中形态(多/空/中性); 无命中标—")
    lines.append("")
    lines.append("## 汇总")
    lines.append("")
    lines.append("| 品种 | 名称 | 合约 | 最新日期 | 收盘 | 方向 | 命中形态 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")

    detail = []
    n_var = df["品种代码"].nunique()
    var_done = 0
    n_hit = 0
    for code, grp in df.groupby("品种代码", sort=False):
        grp = grp.sort_values("日期").reset_index(drop=True)
        if len(grp) == 0:
            continue
        name = grp.iloc[0]["品种名称"]
        contract = grp.iloc[0]["合约代码"]
        tick = tick_of(code)
        n = len(grp)
        latest = str(grp["日期"].iloc[-1])
        close = float(grp.iloc[-1]["收盘价"])

        matches, idx = analyze(grp)
        last_idx = len(grp) - 1
        matches = [m for m in matches if m["idx"] == last_idx]
        dmatches = [m for m in matches if m["direction"] in ("多", "空")]

        if matches:
            if dmatches:
                dirs = [m["direction"] for m in dmatches]
                bias = "多" if dirs.count("多") >= dirs.count("空") else "空"
            else:
                bias = "中性"
            all_names = "、".join(m["name"] for m in matches)
            hits = [(n - 1, m["name"], m["direction"], m.get("note", ""))
                    for m in matches]
            n_hit += 1

            base = f"{code}_{name}"
            out_png = os.path.join(out_dir, f"fullscan_{base}.png")
            title = f"{code} {name} {contract}  {latest}  {all_names}"
            try:
                plot_fullscan(grp, hits, out_png, title, tick)
                has_img = True
            except Exception as e:
                print(f"  绘图失败: {e}")
                has_img = False

            dir_disp = f"**{bias}**" if bias != "中性" else "中性"
            lines.append(f"| {code} | {name} | {contract} | {latest} | "
                         f"{fmt(close, tick)} | {dir_disp} | {all_names} |")

            detail.append(f"### {code} {name}（{contract}）")
            detail.append("")
            detail.append(f"- 最新日期: {latest}　收盘: {fmt(close, tick)}　"
                          f"主方向: **{bias}**")
            detail.append("")
            if has_img:
                detail.append(f"![{code} {name}]({os.path.basename(out_png)})")
                detail.append("")
            detail.append("| 形态 | 方向 | 说明 |")
            detail.append("| --- | --- | --- |")
            for m in matches:
                detail.append(f"| {m['name']} | {m['direction']} | {m['note']} |")
            detail.append("")
        else:
            lines.append(f"| {code} | {name} | {contract} | {latest} | "
                         f"{fmt(close, tick)} | — | — |")

        var_done += 1
        if matches:
            print(f"[{var_done}/{n_var}] {code} {name}  {latest}  "
                  f"收盘{fmt(close, tick)}  命中: {all_names}  方向: {bias}")
        else:
            print(f"[{var_done}/{n_var}] {code} {name}  {latest}  "
                  f"收盘{fmt(close, tick)}  无形态命中")

    if detail:
        lines.append("")
        lines.append("## 命中品种详情")
        lines.append("")
        lines.extend(detail)

    index_md = os.path.join(out_dir, "fullscan_index.md")
    with open(index_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n汇总报告: {index_md}")
    print(f"完成: {var_done}/{n_var} 个品种, {n_hit} 个有方向形态命中")


if __name__ == "__main__":
    main()
