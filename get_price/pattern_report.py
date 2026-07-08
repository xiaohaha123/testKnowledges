# -*- coding: utf-8 -*-
"""
期货K线形态分析报告生成器
==========================
读取 get_price.py 输出的汇总长表 CSV(含全部品种), 对每个品种在
**最新一根K线**完成的所有形态进行识别(规则对照 patterns.md), 输出
Markdown 报告: 开头给出各形态量化描述; 各品种列出命中的方向形态
(看多/看空参考); 中性及无形态品种不输出。同时为每个方向形态生成
带形态高亮+信号箭头的K线图(输出到 image_<日期>/ 目录)。

用法:
  python pattern_report.py <数据文件.csv>
例:
  python pattern_report.py output/futures_main_daily_20260706.csv
"""

import os
import sys
import math
import datetime

try:
    import pandas as pd
except ImportError as e:
    sys.exit(f"缺少依赖: {e.name}\n请运行: pip install pandas")

# ---------- 合约最小变动价位(按品种基础代码; 仅供参考, 如有变动请更正) ----------
TICK = {
    # 黑色
    "RB": 1, "HC": 1, "I": 0.5, "J": 0.5, "JM": 0.5, "ZC": 0.2,
    # 化工
    "MA": 1, "TA": 2, "PP": 1, "V": 1, "EG": 1, "SA": 1, "FG": 1, "L": 1,
    "BU": 2, "RU": 5, "FU": 1, "SC": 0.1, "LPG": 1, "LU": 1, "SP": 2, "UR": 1,
    "SH": 1, "EB": 1, "PF": 2, "PX": 2, "PR": 2, "BR": 5,
    # 有色
    "CU": 10, "AL": 5, "ZN": 5, "NI": 10, "PB": 5, "SN": 10, "AU": 0.02, "AG": 1,
    "SI": 5, "LC": 50, "AO": 1, "PS": 10,
    # 农产品
    "C": 1, "CS": 1, "M": 1, "Y": 2, "P": 2, "A": 1, "B": 1, "SR": 1, "CF": 5, "CY": 5,
    "OI": 1, "RM": 1, "AP": 1, "CJ": 5, "JD": 1, "PK": 2, "LH": 5,
    # 金融
    "IF": 0.2, "IC": 0.2, "IH": 0.2,
}

TREND_N = 5       # 趋势判定回看根数
IMG_BARS = 60     # 图表展示的最近K线根数
ATR_N = 14        # ATR 计算周期
BIG_K = 1.3       # "大K线"量级阈值: 当日/形态K区间 ≥ BIG_K × ATR(ATR_N)


def base_code(code: str) -> str:
    """RB0 -> RB, I0 -> I, IF0 -> IF"""
    return code[:-1] if code.endswith("0") and len(code) > 1 else code


def tick_of(code: str) -> float:
    return TICK.get(base_code(code), 1)


def roundp(price, tick):
    if price is None or math.isnan(price):
        return None
    return round(price / tick) * tick


def fmt(price, tick):
    if price is None:
        return "—"
    p = roundp(price, tick)
    if p is None:
        return "—"
    if tick >= 1:
        return str(int(round(p)))
    dec = max(0, len(str(tick).split(".")[-1]))
    return f"{p:.{dec}f}"


def bar(df, i):
    """取第 i 根 K 线的各分量(浮点)。"""
    r = df.iloc[i]
    O = float(r["开盘价"]); H = float(r["最高价"]); L = float(r["最低价"]); C = float(r["收盘价"])
    V = float(r["成交量"]); OI = float(r["持仓量"])
    body = abs(C - O)
    upper = H - max(O, C)
    lower = min(O, C) - L
    rng = H - L
    return O, H, L, C, V, OI, body, upper, lower, rng, (C > O), (C < O)


def trend(df, i, n=TREND_N):
    """信号前 n 根的趋势: 上/下/震荡。"""
    if i < n:
        return "震荡"
    c = df["收盘价"].iloc[i - n:i].astype(float).values
    sma = c.mean()
    if c[-1] > sma and c[-1] > c[0]:
        return "上"
    if c[-1] < sma and c[-1] < c[0]:
        return "下"
    return "震荡"


def atr(df, i, n=ATR_N):
    """信号日前 n 根的平均真实波幅(不含信号日); 数据不足返回 None。"""
    if i < n + 1:
        return None
    H = df["最高价"]; L = df["最低价"]; C = df["收盘价"]
    trs = []
    for t in range(i - n, i):
        h = float(H.iloc[t]); l = float(L.iloc[t]); pc = float(C.iloc[t - 1])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / n


def is_big(df, i, rng):
    """判断第 i 根是否为"大K线": 区间 ≥ BIG_K×ATR; ATR 不足时放行(不滤)。"""
    a = atr(df, i)
    return a is None or rng >= BIG_K * a


def M(name, direction, phigh, plow, note=""):
    return {"name": name, "direction": direction,
            "phigh": phigh, "plow": plow, "note": note}


# ---------------- 单根形态 ----------------

def p_hammer(df, i):
    if i < 1 or trend(df, i) != "下":
        return []
    O, H, L, C, V, OI, body, upper, lower, rng, bull, bear = bar(df, i)
    if rng <= 0 or body <= 0:
        return []
    if lower >= 2 * body and upper <= 0.3 * body and body <= 0.3 * rng:
        return [M("锤子线", "多", H, L, f"下影{lower:.1f}≥2×实体, 上影{upper:.1f}")]
    return []


def p_hanging(df, i):
    if i < 1 or trend(df, i) != "上":
        return []
    O, H, L, C, V, OI, body, upper, lower, rng, bull, bear = bar(df, i)
    if rng <= 0 or body <= 0:
        return []
    if lower >= 2 * body and upper <= 0.3 * body and body <= 0.3 * rng:
        return [M("上吊线", "空", H, L, f"上涨末端, 结构同锤子")]
    return []


def p_shooting(df, i):
    if i < 1 or trend(df, i) != "上":
        return []
    O, H, L, C, V, OI, body, upper, lower, rng, bull, bear = bar(df, i)
    if rng <= 0 or body <= 0:
        return []
    if upper >= 2 * body and lower <= 0.3 * body and body <= 0.3 * rng:
        return [M("流星线", "空", H, L, f"上影{upper:.1f}≥2×实体")]
    return []


def p_inverted(df, i):
    if i < 1 or trend(df, i) != "下":
        return []
    O, H, L, C, V, OI, body, upper, lower, rng, bull, bear = bar(df, i)
    if rng <= 0 or body <= 0:
        return []
    if upper >= 2 * body and lower <= 0.3 * body and body <= 0.3 * rng:
        return [M("倒锤子线", "多", H, L, f"下跌末端, 长上影")]
    return []


def p_doji(df, i):
    O, H, L, C, V, OI, body, upper, lower, rng, bull, bear = bar(df, i)
    if rng <= 0:
        return []
    if body > 0.05 * rng:
        return []
    sub = "普通十字"
    if lower > 3 * body and upper > 3 * body:
        sub = "长腿十字"
    elif lower <= 0.1 * rng and upper > 2 * body:
        sub = "墓碑十字"
    elif upper <= 0.1 * rng and lower > 2 * body:
        sub = "蜻蜓十字"
    return [M(f"十字星({sub})", "中性", H, L, "需次根K线确认方向")]


def p_bigbull(df, i):
    O, H, L, C, V, OI, body, upper, lower, rng, bull, bear = bar(df, i)
    if rng <= 0 or not bull:
        return []
    if body >= 0.7 * rng and is_big(df, i, rng):
        return [M("大阳线", "多", H, L, f"实体占区间{body/rng*100:.0f}%, 区间≥{BIG_K}×ATR")]
    return []


def p_bigbear(df, i):
    O, H, L, C, V, OI, body, upper, lower, rng, bull, bear = bar(df, i)
    if rng <= 0 or not bear:
        return []
    if body >= 0.7 * rng and is_big(df, i, rng):
        return [M("大阴线", "空", H, L, f"实体占区间{body/rng*100:.0f}%, 区间≥{BIG_K}×ATR")]
    return []


def p_spinning(df, i):
    O, H, L, C, V, OI, body, upper, lower, rng, bull, bear = bar(df, i)
    if rng <= 0 or body <= 0:
        return []
    if body <= 0.3 * rng and upper >= body and lower >= body:
        return [M("纺锤线", "中性", H, L, "多空分歧, 震荡预警")]
    return []


def p_engulf_bull(df, i):
    if i < 1 or trend(df, i) != "下":
        return []
    o1, h1, l1, c1, _, _, b1, _, _, r1, bull1, bear1 = bar(df, i - 1)
    o2, h2, l2, c2, _, _, b2, _, _, r2, bull2, _ = bar(df, i)
    if not (bear1 and bull2):
        return []
    if o2 < c1 and c2 > o1:
        ph, pl = max(h1, h2), min(l1, l2)
        return [M("看涨吞没", "多", ph, pl, "K2阳实体包裹K1阴实体")]
    return []


def p_engulf_bear(df, i):
    if i < 1 or trend(df, i) != "上":
        return []
    o1, h1, l1, c1, _, _, b1, _, _, r1, bull1, _ = bar(df, i - 1)
    o2, h2, l2, c2, _, _, b2, _, _, r2, _, bear2 = bar(df, i)
    if not (bull1 is True and bear2 is True):
        return []
    if o2 > c1 and c2 < o1:
        ph, pl = max(h1, h2), min(l1, l2)
        return [M("看跌吞没", "空", ph, pl, "K2阴实体包裹K1阳实体")]
    return []


def p_piercing(df, i):
    if i < 1 or trend(df, i) != "下":
        return []
    o1, h1, l1, c1, _, _, b1, _, _, r1, bull1, bear1 = bar(df, i - 1)
    o2, h2, l2, c2, _, _, b2, _, _, r2, bull2, _ = bar(df, i)
    if not (bear1 and bull2):
        return []
    if r1 <= 0:
        return []
    if not (is_big(df, i - 1, r1) and b1 >= 0.5 * r1):
        return []
    if o2 < l1 and c2 > (o1 + c1) / 2 and c2 < o1:
        ph, pl = max(h1, h2), min(l1, l2)
        return [M("刺透形态", "多", ph, pl, "K1大阴, K2低开创新低, 收盘过K1实体中线")]
    return []


def p_darkcloud(df, i):
    if i < 1 or trend(df, i) != "上":
        return []
    o1, h1, l1, c1, _, _, b1, _, _, r1, bull1, _ = bar(df, i - 1)
    o2, h2, l2, c2, _, _, b2, _, _, r2, _, bear2 = bar(df, i)
    if not (bull1 is True and bear2 is True):
        return []
    if r1 <= 0:
        return []
    if not (is_big(df, i - 1, r1) and b1 >= 0.5 * r1):
        return []
    if o2 > h1 and c2 < (o1 + c1) / 2 and c2 > o1:
        ph, pl = max(h1, h2), min(l1, l2)
        return [M("乌云盖顶", "空", ph, pl, "K1大阳, K2高开创新高, 收盘跌破K1实体中线")]
    return []


def p_harami(df, i):
    if i < 1:
        return []
    o1, h1, l1, c1, _, _, b1, u1, lo1, r1, bull1, bear1 = bar(df, i - 1)
    o2, h2, l2, c2, _, _, b2, u2, lo2, r2, _, _ = bar(df, i)
    if r1 <= 0 or b1 <= 0:
        return []
    contained = max(o2, c2) < max(o1, c1) and min(o2, c2) > min(o1, c1)
    if not contained or b2 >= b1:
        return []
    doji2 = (r2 > 0 and b2 <= 0.05 * r2)
    sub = "孕十字" if doji2 else "孕线"
    ph, pl = max(h1, h2), min(l1, l2)
    # 按 K1 阴阳分类(对照形态.md): K1阳→看跌(多头乏力), K1阴→看涨(趋势衰竭)
    if bull1:
        return [M(f"看跌{sub}", "空", ph, pl, "K1长阳+K2小实体嵌套, 多头乏力")]
    if bear1:
        return [M(f"看涨{sub}", "多", ph, pl, "K1长阴+K2小实体嵌套, 趋势衰竭")]
    return [M(sub, "中性", ph, pl, "K1十字, 嵌套成立但方向不明")]


# ---------------- 三根及多根形态 ----------------

def p_morning_star(df, i):
    if i < 2 or trend(df, i) != "下":
        return []
    o1, h1, l1, c1, _, _, b1, _, _, r1, bull1, bear1 = bar(df, i - 2)
    o2, h2, l2, c2, _, _, b2, _, _, r2, _, _ = bar(df, i - 1)
    o3, h3, l3, c3, _, _, b3, _, _, r3, bull3, _ = bar(df, i)
    if not (bear1 and bull3):
        return []
    if r1 <= 0 or r2 <= 0:
        return []
    big1 = b1 >= 0.5 * r1 and is_big(df, i - 2, r1)
    small2 = b2 <= 0.3 * r2
    gap = max(o2, c2) < min(o1, c1)
    if big1 and small2 and gap and c3 > (o1 + c1) / 2:
        ph, pl = max(h1, h2, h3), min(l1, l2, l3)
        return [M("早晨之星", "多", ph, pl, "大阴+跳空小实体+大阳刺入K1过半")]
    return []


def p_evening_star(df, i):
    if i < 2 or trend(df, i) != "上":
        return []
    o1, h1, l1, c1, _, _, b1, _, _, r1, bull1, _ = bar(df, i - 2)
    o2, h2, l2, c2, _, _, b2, _, _, r2, _, _ = bar(df, i - 1)
    o3, h3, l3, c3, _, _, b3, _, _, r3, _, bear3 = bar(df, i)
    if not (bull1 is True and bear3 is True):
        return []
    if r1 <= 0 or r2 <= 0:
        return []
    big1 = b1 >= 0.5 * r1 and is_big(df, i - 2, r1)
    small2 = b2 <= 0.3 * r2
    gap = min(o2, c2) > max(o1, c1)
    if big1 and small2 and gap and c3 < (o1 + c1) / 2:
        ph, pl = max(h1, h2, h3), min(l1, l2, l3)
        return [M("黄昏之星", "空", ph, pl, "大阳+跳空小实体+大阴刺入K1过半")]
    return []


def p_three_soldiers(df, i):
    if i < 2:
        return []
    o1, h1, l1, c1, _, _, b1, u1, _, r1, bull1, _ = bar(df, i - 2)
    o2, h2, l2, c2, _, _, b2, u2, _, r2, bull2, _ = bar(df, i - 1)
    o3, h3, l3, c3, _, _, b3, u3, _, r3, bull3, _ = bar(df, i)
    if not (bull1 and bull2 and bull3):
        return []
    if not (c1 < c2 < c3):
        return []
    if not (o1 <= o2 <= c1 and o2 <= o3 <= c2):
        return []
    if u3 > 0.3 * r3:
        return [M("受阻红三兵", "多", max(h1, h2, h3), min(l1, l2, l3),
                 "第三根长上影, 动能衰竭(谨慎)")]
    return [M("红三兵", "多", max(h1, h2, h3), min(l1, l2, l3), "三连阳, 高点持续上移")]


def p_three_crows(df, i):
    if i < 2:
        return []
    o1, h1, l1, c1, _, _, b1, _, lo1, r1, _, bear1 = bar(df, i - 2)
    o2, h2, l2, c2, _, _, b2, _, lo2, r2, _, bear2 = bar(df, i - 1)
    o3, h3, l3, c3, _, _, b3, _, lo3, r3, _, bear3 = bar(df, i)
    if not (bear1 and bear2 and bear3):
        return []
    if not (c1 > c2 > c3):
        return []
    if not (c1 <= o2 <= o1 and c2 <= o3 <= o2):
        return []
    return [M("三乌鸦", "空", max(h1, h2, h3), min(l1, l2, l3), "三连阴, 低点持续下移")]


def p_rising_three(df, i):
    if i < 4:
        return []
    o1, h1, l1, c1, _, _, b1, _, _, r1, bull1, _ = bar(df, i - 4)
    o5, h5, l5, c5, _, _, b5, _, _, r5, bull5, _ = bar(df, i)
    if not (bull1 and bull5 and r1 > 0):
        return []
    if b1 < 0.5 * r1:
        return []
    inside = True
    for k in (i - 3, i - 2, i - 1):
        ok, hk, lk, ck, _, _, _, _, _, _, _, beark = bar(df, k)
        if not (hk <= h1 and lk >= l1 and beark):
            inside = False
            break
    if inside and c5 > c1:
        return [M("上升三法", "多", max(h1, h5), min(l1, l5), "长阳包裹回调小阴, 末根创新高")]
    return []


def p_falling_three(df, i):
    if i < 4:
        return []
    o1, h1, l1, c1, _, _, b1, _, _, r1, _, bear1 = bar(df, i - 4)
    o5, h5, l5, c5, _, _, b5, _, _, r5, _, bear5 = bar(df, i)
    if not (bear1 and bear5 and r1 > 0):
        return []
    if b1 < 0.5 * r1:
        return []
    inside = True
    for k in (i - 3, i - 2, i - 1):
        ok, hk, lk, ck, _, _, _, _, _, _, bullk, _ = bar(df, k)
        if not (hk <= h1 and lk >= l1 and bullk):
            inside = False
            break
    if inside and c5 < c1:
        return [M("下跌三法", "空", max(h1, h5), min(l1, l5), "长阴包裹反弹小阳, 末根创新低")]
    return []


# ---------------- 跳空缺口形态 ----------------

def p_gap_up(df, i):
    if i < 1:
        return []
    o1, h1, l1, c1, *_ = bar(df, i - 1)
    o2, h2, l2, c2, *_ = bar(df, i)
    if l2 > h1:
        return [M("向上跳空缺口", "多", h2, h1, f"支撑窗口 [{h1}, {l2}]")]
    return []


def p_gap_down(df, i):
    if i < 1:
        return []
    o1, h1, l1, c1, *_ = bar(df, i - 1)
    o2, h2, l2, c2, *_ = bar(df, i)
    if h2 < l1:
        return [M("向下跳空缺口", "空", l1, l2, f"压力窗口 [{h2}, {l1}]")]
    return []


def p_island(df, i):
    if i < 2:
        return []
    o1, h1, l1, c1, *_ = bar(df, i - 2)
    o2, h2, l2, c2, *_ = bar(df, i - 1)
    o3, h3, l3, c3, *_ = bar(df, i)
    # 底部岛形: 前向下跳空进入孤岛 + 当日向上跳空离开
    if h2 < l1 and l3 > h2:
        return [M("底部岛形反转", "多", h2, l2, "双向跳空, 中间孤岛")]
    # 顶部岛形: 前向上跳空进入孤岛 + 当日向下跳空离开
    if l2 > h1 and h3 < l2:
        return [M("顶部岛形反转", "空", h2, l2, "双向跳空, 中间孤岛")]
    return []


# ---------------- 量价形态 ----------------

def p_vol_oi_bigcandle(df, i):
    if i < 1:
        return []
    o1, h1, l1, c1, v1, oi1, b1, *_ = bar(df, i - 1)
    o2, h2, l2, c2, v2, oi2, b2, _, _, r2, bull2, bear2 = bar(df, i)
    if b1 <= 0 or v1 <= 0:
        return []
    if b2 >= 3 * b1 and v2 >= 2 * v1 and oi2 > oi1:
        d = "多" if bull2 else ("空" if bear2 else "中性")
        return [M("放量增仓长K线", d, h2, l2,
                  f"实体{b2:.1f}≥3×{b1:.1f}; 量{int(v2)}≥2×{int(v1)}; 持仓{int(oi1)}→{int(oi2)}")]
    return []


PATTERNS = [
    ("锤子线", p_hammer), ("上吊线", p_hanging), ("流星线", p_shooting),
    ("倒锤子线", p_inverted), ("十字星", p_doji), ("大阳线", p_bigbull),
    ("大阴线", p_bigbear), ("纺锤线", p_spinning), ("看涨吞没", p_engulf_bull),
    ("看跌吞没", p_engulf_bear), ("刺透形态", p_piercing), ("乌云盖顶", p_darkcloud),
    ("孕线", p_harami), ("早晨之星", p_morning_star), ("黄昏之星", p_evening_star),
    ("红三兵", p_three_soldiers), ("三乌鸦", p_three_crows),
    ("上升三法", p_rising_three), ("下跌三法", p_falling_three),
    ("向上跳空", p_gap_up), ("向下跳空", p_gap_down), ("岛形反转", p_island),
    ("放量增仓长K线", p_vol_oi_bigcandle),
]

# 形态量化描述(方向偏好 + 量化条件), 用于报告开头参考表
PATTERN_DESC = [
    ("锤子线", "多", "下跌趋势; 下影≥2×实体, 上影≤0.3×实体, 实体≤0.3×区间"),
    ("上吊线", "空", "上涨趋势; 结构同锤子线"),
    ("流星线", "空", "上涨趋势; 上影≥2×实体, 下影≤0.3×实体, 实体≤0.3×区间"),
    ("倒锤子线", "多", "下跌趋势; 上影≥2×实体, 下影≤0.3×实体, 实体≤0.3×区间"),
    ("十字星", "中性", "实体≤0.05×区间(普通/长腿/墓碑/蜻蜓)"),
    ("大阳线", "多", "阳线, 实体≥0.7×区间, 且区间≥1.3×ATR(14)"),
    ("大阴线", "空", "阴线, 实体≥0.7×区间, 且区间≥1.3×ATR(14)"),
    ("纺锤线", "中性", "实体≤0.3×区间, 上下影均≥实体"),
    ("看涨吞没", "多", "下跌趋势; K1阴K2阳, K2实体包裹K1实体(O2<C1, C2>O1)"),
    ("看跌吞没", "空", "上涨趋势; K1阳K2阴, K2实体包裹K1实体(O2>C1, C2<O1)"),
    ("刺透形态", "多", "下跌趋势; K1大阴(区间1≥1.3×ATR), K2低开创新低, 收盘过K1实体中线且<C1"),
    ("乌云盖顶", "空", "上涨趋势; K1大阳(区间1≥1.3×ATR), K2高开创高, 收盘跌破K1实体中线且>O1"),
    ("孕线", "多/空", "K2实体完全嵌套K1实体; K1阳→看跌, K1阴→看涨, K1十字→中性"),
    ("早晨之星", "多", "下跌趋势; K1大阴(区间1≥1.3×ATR)+跳空小实体+大阳刺入K1实体过半"),
    ("黄昏之星", "空", "上涨趋势; K1大阳(区间1≥1.3×ATR)+跳空小实体+大阴刺入K1实体过半"),
    ("红三兵", "多", "三连阳; 每根开盘落在前根实体内, 收盘持续新高, 上影短小"),
    ("三乌鸦", "空", "三连阴; 每根开盘落在前根实体内, 收盘持续新低, 下影短小"),
    ("上升三法", "多", "长阳+2~4小阴回调(全被首根包裹)+末根大阳创新高"),
    ("下跌三法", "空", "长阴+2~4小阳反弹(全被首根包裹)+末根大阴创新低"),
    ("向上跳空缺口", "多", "Low2>High1, 支撑窗口"),
    ("向下跳空缺口", "空", "High2<Low1, 压力窗口"),
    ("岛形反转", "多/空", "双向跳空+中间孤岛; 底部→多, 顶部→空"),
    ("放量增仓长K线", "多/空", "实体≥3×前日, 成交量≥2×前日, 持仓增加; 方向同K线阴阳"),
]


def analyze(df):
    """对 df(单品种, 按日期升序) 的最后一根做全形态扫描。"""
    df = df.sort_values("日期").reset_index(drop=True)
    n = len(df)
    if n == 0:
        return [], None
    i = n - 1
    out = []
    for _, fn in PATTERNS:
        try:
            out.extend(fn(df, i))
        except Exception:
            pass
    return out, i


def pattern_bars(name):
    """形态占用的K线根数(用于图表高亮区间)。"""
    if name in ("上升三法", "下跌三法"):
        return 5
    if ("早晨之星" in name or "黄昏之星" in name or "红三兵" in name
            or "三乌鸦" in name or "岛形" in name or "两黑" in name or "三川" in name):
        return 3
    if ("吞没" in name or "刺透" in name or "乌云" in name or "孕" in name
            or "跳空" in name or "缺口" in name or "分手" in name or "约会" in name):
        return 2
    return 1


def draw_chart(grp, idx, m, code, name, contract, date_str, out_dir):
    """为单个形态生成带标识的K线图(形态高亮+信号箭头), 返回图片路径或 None。"""
    try:
        import mplfinance as mpf
        import matplotlib
        matplotlib.use("Agg")
        matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
        matplotlib.rcParams["axes.unicode_minus"] = False
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    d = m["direction"]
    n = len(grp)
    start = max(0, n - IMG_BARS)
    pdf = grp.iloc[start:].copy()
    pdf["日期"] = pd.to_datetime(pdf["日期"])
    pdf = pdf.set_index("日期")[["开盘价", "最高价", "最低价", "收盘价", "成交量"]]
    pdf.columns = ["Open", "High", "Low", "Close", "Volume"]
    pdf = pdf.astype(float)
    M = len(pdf)
    sig_i = M - 1

    mc = mpf.make_marketcolors(up="#d32f2f", down="#2e7d32",
                               edge="inherit", wick="inherit", volume="inherit")
    style = mpf.make_mpf_style(base_mpf_style="charles", marketcolors=mc,
                               rc={"font.sans-serif": ["Microsoft YaHei", "SimHei"]})

    # 信号日箭头标记: 多头红色上箭头(LOW下方), 空头绿色下箭头(HIGH上方)
    mark = pd.Series(index=pdf.index, dtype=float)
    if d == "多":
        mark.iloc[-1] = pdf["Low"].iloc[-1] * 0.985
        sym, col = "^", "#b71c1c"
    else:
        mark.iloc[-1] = pdf["High"].iloc[-1] * 1.015
        sym, col = "v", "#1b5e20"
    aps = [mpf.make_addplot(mark, type="scatter", marker=sym, markersize=130, color=col)]

    title = f"{code} {name} {contract}  {m['name']}({d})  {date_str}"
    fig, axes = mpf.plot(pdf, type="candle", style=style, volume=True, addplot=aps,
                         title=title, figsize=(16, 9), returnfig=True, tight_layout=True)
    ax = axes[0]

    # 形态K线高亮带(橙色淡底)
    K = pattern_bars(m["name"])
    ax.axvspan(max(0, sig_i - K + 1) - 0.4, sig_i + 0.4, alpha=0.20, color="#ff9800")

    os.makedirs(out_dir, exist_ok=True)
    safe = m["name"].replace("/", "_").replace("\\", "_")
    fpath = os.path.join(out_dir, f"{code}_{safe}.png")
    fig.savefig(fpath, dpi=100)
    plt.close(fig)
    return fpath


def main():
    if len(sys.argv) < 2:
        sys.exit("用法: python pattern_report.py <数据文件.csv>")
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

    latest = str(df["日期"].max())
    latest_tag = latest.replace("-", "")
    img_dir = os.path.join(os.path.dirname(path), f"image_{latest_tag}")
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = []
    lines.append("# 期货K线形态分析报告")
    lines.append("")
    lines.append(f"- 数据文件: `{path}`")
    lines.append(f"- 生成时间: {now}")
    lines.append(f"- 数据最新日期: {latest}")
    lines.append("- 识别范围: 在**最新一根K线**完成的形态(对照 `形态.md`)")
    lines.append("- 输出范围: 仅列方向明确(看多/看空)的形态; 中性(十字星/纺锤)及无形态品种不输出")
    lines.append(f"- 形态图: 见 `image_{latest_tag}/` 目录(高亮形态K线+信号箭头), 详情内嵌")
    lines.append("")
    lines.append("## 形态量化描述")
    lines.append("")
    lines.append("| 形态 | 方向 | 量化条件 |")
    lines.append("| --- | --- | --- |")
    for nm, dr, qc in PATTERN_DESC:
        lines.append(f"| {nm} | {dr} | {qc} |")
    lines.append("")
    lines.append("## 汇总")
    lines.append("")
    lines.append("| 品种 | 名称 | 合约 | 最新日期 | 收盘 | 方向 | 命中形态 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")

    detail = []
    summary_rows = []
    n_total = df["品种代码"].nunique()
    for code, grp in df.groupby("品种代码", sort=False):
        grp = grp.sort_values("日期").reset_index(drop=True)
        if len(grp) == 0:
            continue
        r = grp.iloc[-1]
        name = r["品种名称"]; contract = r["合约代码"]; d = str(r["日期"])
        close = float(r["收盘价"]); tick = tick_of(code)
        matches, idx = analyze(grp)
        dmatches = [m for m in matches if m["direction"] in ("多", "空")]
        if not dmatches:
            continue  # 中性/无形态: 不输出
        dirs = [m["direction"] for m in dmatches]
        bias = "多" if dirs.count("多") >= dirs.count("空") else "空"
        names = "、".join(m["name"] for m in dmatches)
        summary_rows.append((code, name, contract, d, fmt(close, tick), bias, names))

        sec = []
        sec.append(f"## {code} {name}（合约 {contract}）")
        sec.append(f"- 最新日期: {d}　收盘: **{fmt(close, tick)}**　主方向: **{bias}**")
        sec.append("")
        sec.append("| 形态 | 方向 | 说明 |")
        sec.append("| --- | --- | --- |")
        img_lines = []
        for m in dmatches:
            sec.append(f"| {m['name']} | {m['direction']} | {m['note']} |")
            fpath = draw_chart(grp, idx, m, code, name, contract, d, img_dir)
            if fpath:
                rel = os.path.relpath(fpath, os.path.dirname(path)).replace("\\", "/")
                img_lines.append(f"![{m['name']}]({rel})")
        sec.append("")
        for il in img_lines:
            sec.append(il)
        sec.append("")
        detail.append("\n".join(sec))

    for row in summary_rows:
        lines.append("| " + " | ".join(str(x) for x in row) + " |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 各品种详情")
    lines.append("")
    lines.append("\n\n".join(detail))

    out_name = f"形态分析报告_{latest.replace('-', '')}.md"
    out_path = os.path.join(os.path.dirname(path), out_name)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"已生成: {out_path}")
    print(f"总品种数: {n_total}  方向品种(多/空): {len(summary_rows)}  "
          f"(已过滤中性/无形态)")
    print(f"形态图目录: {img_dir}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已中断")
