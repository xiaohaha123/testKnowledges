# -*- coding: utf-8 -*-
"""
全量形态识别(可视化 + md)
==========================
读取单品种 CSV, 逐根扫描 summary.md 全部 24 种形态, 标出每一处识别结果。
输出: 1 张 K 线图 + 1 份 md。
图例标识不遮 K 线实体: 多/中性标于当日低点下方, 空标于当日高点上方。
用法: python pattern_fullscan.py output/MA0_甲醇.csv
"""

import os
import sys
from collections import defaultdict

import pandas as pd

from pattern_report import PATTERNS, tick_of


def bar_of(df, i):
    r = df.iloc[i]
    return float(r["开盘价"]), float(r["最高价"]), float(r["最低价"]), float(r["收盘价"])


def plot_fullscan(df, hits, out_png, title, tick):
    import mplfinance as mpf
    import matplotlib
    matplotlib.use("Agg")
    matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
    matplotlib.rcParams["axes.unicode_minus"] = False
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    pdf = df.set_index("日期")[["开盘价", "最高价", "最低价", "收盘价", "成交量"]]
    pdf.columns = ["Open", "High", "Low", "Close", "Volume"]
    pdf = pdf.astype(float)

    mc = mpf.make_marketcolors(up="#d32f2f", down="#2e7d32",
                               edge="inherit", wick="inherit")
    style = mpf.make_mpf_style(base_mpf_style="charles", marketcolors=mc,
                               rc={"font.sans-serif": ["Microsoft YaHei", "SimHei"]})
    fig, axes = mpf.plot(pdf, type="candle", style=style, figsize=(16, 8),
                         returnfig=True, tight_layout=True)
    ax = axes[0]

    # 按bar分组, 多/中性标低点下方, 空标高点上方(不遮实体)
    by_bar = defaultdict(list)
    for i, nm, d, note in hits:
        by_bar[i].append((nm, d))
    dates = df["日期"].values
    for i, lst in by_bar.items():
        O, H, L, C = bar_of(df, i)
        rng = H - L
        off = max(rng * 0.20, C * 0.0008, tick * 2)
        below = [x for x in lst if x[1] in ("多", "中性")]
        above = [x for x in lst if x[1] == "空"]
        for idx, (nm, d) in enumerate(below):
            y = L - off * (idx + 1)
            m = "^" if d == "多" else "o"
            c = "#d32f2f" if d == "多" else "#9e9e9e"
            ax.scatter([dates[i]], [y], marker=m, color=c, s=55, zorder=5)
        for idx, (nm, d) in enumerate(above):
            y = H + off * (idx + 1)
            ax.scatter([dates[i]], [y], marker="v", color="#2e7d32", s=55, zorder=5)

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
        sys.exit("用法: python pattern_fullscan.py <单品种CSV>")
    path = sys.argv[1]
    if not os.path.isabs(path):
        path = os.path.abspath(path)
    if not os.path.exists(path):
        sys.exit(f"文件不存在: {path}")

    df = pd.read_csv(path, encoding="utf-8-sig")
    df["日期"] = pd.to_datetime(df["日期"])
    df = df.sort_values("日期").reset_index(drop=True)
    code = df.iloc[0]["品种代码"]
    name = df.iloc[0]["品种名称"]
    contract = df.iloc[0]["合约代码"]
    tick = tick_of(code)
    N = len(df)
    start = df["日期"].iloc[0].strftime("%Y-%m-%d")
    end = df["日期"].iloc[-1].strftime("%Y-%m-%d")

    # 逐根全量扫描
    hits = []
    for i in range(1, N):
        for nm, fn in PATTERNS:
            try:
                ms = fn(df, i)
            except Exception:
                continue
            for m in ms:
                hits.append((i, nm, m["direction"], m.get("note", "")))
    hits.sort(key=lambda x: (x[0], x[1]))

    # 统计
    by_dir = defaultdict(int)
    by_form = defaultdict(list)
    for i, nm, d, note in hits:
        by_dir[d] += 1
        by_form[nm].append((i, d, note))

    base = os.path.splitext(os.path.basename(path))[0]
    out_dir = os.path.join(os.path.dirname(path), "fullscan")
    os.makedirs(out_dir, exist_ok=True)
    out_png = os.path.join(out_dir, f"fullscan_{base}.png")
    out_md = os.path.join(out_dir, f"fullscan_{base}.md")

    # 画图
    title = f"{code} {name} {contract}  全量形态识别  {start}~{end}  共{len(hits)}处"
    try:
        plot_fullscan(df, hits, out_png, title, tick)
        has_img = True
    except Exception as e:
        print(f"绘图失败: {e}")
        has_img = False

    # md
    md = []
    md.append(f"# 全量形态识别 — {code} {name}")
    md.append("")
    md.append(f"- 合约: {contract}  最小变动价位: {tick}")
    md.append(f"- 数据: {start}~{end}  共{N}根")
    md.append("- 识别: 对照 `summary.md` 全部 24 种形态, 逐根扫描")
    md.append("- 图例: 多/中性标于当日**低点下方**, 空标于当日**高点上方**(不遮 K 线实体)")
    md.append("")
    if has_img:
        md.append(f"![全量识别](fullscan_{base}.png)")
        md.append("")
    md.append("## 汇总")
    md.append("")
    md.append("| 方向 | 次数 |")
    md.append("| --- | --- |")
    for d in ("多", "空", "中性"):
        md.append(f"| {d} | {by_dir.get(d, 0)} |")
    md.append(f"| 合计 | {len(hits)} |")
    md.append("")
    md.append("## 按形态")
    md.append("")
    md.append("| 形态 | 次数 | 方向 |")
    md.append("| --- | --- | --- |")
    for nm in [p[0] for p in PATTERNS]:
        lst = by_form.get(nm)
        if not lst:
            continue
        dirs = "/".join(sorted(set(x[1] for x in lst)))
        md.append(f"| {nm} | {len(lst)} | {dirs} |")
    md.append("")
    md.append("## 全部识别结果(按日期)")
    md.append("")
    md.append("| 日期 | 形态 | 方向 | 说明 |")
    md.append("| --- | --- | --- | --- |")
    for i, nm, d, note in hits:
        md.append(f"| {df['日期'].iloc[i]:%Y-%m-%d} | {nm} | {d} | {note} |")
    md.append("")

    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print(f"品种: {code} {name}  合约: {contract}  数据: {start}~{end}  共{N}根")
    print(f"识别: 共 {len(hits)} 处  (多{by_dir.get('多',0)}/空{by_dir.get('空',0)}/中性{by_dir.get('中性',0)})")
    print(f"图片: {out_png}")
    print(f"报告: {out_md}")


if __name__ == "__main__":
    main()
