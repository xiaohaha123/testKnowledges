# -*- coding: utf-8 -*-
"""
最新K线形态扫描(多品种批量, 单文件输出)
========================================
读取 get_price.py 输出的**汇总长表 CSV**(含全部品种), 对每个品种
仅扫描**最新一根K线**完成的形态(对照 summary.md), 列出全部命中
形态(多/空/中性)。
输出: 1 份 fullscan_index.md(含全部品种汇总表 + 命中品种详情+图表)。
无命中品种不生成图表。
图例: 多标于当日低点下方(^红), 空标于当日高点上方(v绿), 中性标低点下方(o灰)。
用法: python pattern_fullscan.py output/futures_main_daily_20260708.csv
"""

import os
import sys
import datetime
from collections import defaultdict

import pandas as pd

from pattern_report import tick_of, analyze, IMG_BARS, fmt

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

    df = pd.read_csv(path, encoding="utf-8-sig")
    need = ["品种代码", "品种名称", "合约代码", "日期", "开盘价", "最高价",
            "最低价", "收盘价", "成交量", "持仓量"]
    miss = [c for c in need if c not in df.columns]
    if miss:
        sys.exit(f"CSV 缺列: {miss}")

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
