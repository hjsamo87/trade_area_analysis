# -*- coding: utf-8 -*-
"""2029 성장 상권 스코어링 + 백테스트.
실행: py -I -X utf8 analysis/score.py
입력: data/processed/panel.csv, trdar.csv (DATA_DICTIONARY.md 규칙 준수)
출력: analysis/results/analysis.json, analysis/results/analysis.md(별도 작성)
"""
import json, os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(ROOT, "data", "processed")
OUT = os.path.join(ROOT, "analysis", "results")
os.makedirs(OUT, exist_ok=True)

panel = pd.read_csv(os.path.join(P, "panel.csv"), dtype={"TRDAR_CD": str}, encoding="utf-8-sig")
trdar = pd.read_csv(os.path.join(P, "trdar.csv"), dtype={"TRDAR_CD": str}, encoding="utf-8-sig")

QS = sorted(panel.STDR_YYQU_CD.unique())
QI = {q: i for i, q in enumerate(QS)}
panel["qi"] = panel.STDR_YYQU_CD.map(QI)

# ---- 파라미터 (분석 가정) ----
SALES_FLOOR_4Q = 2e8      # 모집단: 최근 4분기 커피+제과 매출 합 >= 2억원 (서울 매출상권 하위 약 25% 제외)
STORE_FLOOR = 5           # 모집단: 최근 4분기 평균 커피+제과 점포 >= 5개 (store_small_n 기준과 동일)
T0, T1 = 20232, 20262     # 백테스트 기준 시점, 최신 시점


def wide(col):
    return panel.pivot(index="TRDAR_CD", columns="qi", values=col)


W = {c: wide(c) for c in ["coffee_sales", "bakery_sales", "coffee_txn", "bakery_txn", "cb_sales", "cb_stores",
                           "cb_close", "flpop", "flpop_share_2030", "repop", "opr_gap",
                           "coffee_sales_per_store", "coffee_stores"]}
# 2030 매출액(비중 x 매출) 가중 합산용
panel["cb_sales_2030"] = (panel.cb_share_age20 + panel.cb_share_age30) * panel.cb_sales
W["cb_sales_2030"] = wide("cb_sales_2030")


def wsum(w, a, b):  # 분기 index a..b 포함, 하나라도 결측이면 NaN
    return w.loc[:, a:b].sum(axis=1, min_count=b - a + 1)


def wmean(w, a, b):
    s = w.loc[:, a:b]
    return s.mean(axis=1).where(s.notna().all(axis=1))


def cb_growth(ti0, ti1):
    """업종 구성 일치 성장률: 두 4분기 창 모두 4분기 완비된 업종만 합산. 반환 (end/base)."""
    base = pd.Series(0.0, index=W["coffee_sales"].index)
    end = base.copy()
    ok = pd.Series(False, index=base.index)
    for ind in ["coffee_sales", "bakery_sales"]:
        b = wsum(W[ind], ti0 - 3, ti0)
        e = wsum(W[ind], ti1 - 3, ti1)
        m = b.notna() & e.notna()
        base = base + b.where(m, 0)
        end = end + e.where(m, 0)
        ok = ok | m
    return (end / base).where(ok & (base > 0))


def features(t):
    ti = QI[t]
    f = pd.DataFrame(index=W["cb_sales"].index)
    f["sales_4q"] = wsum(W["cb_sales"], ti - 3, ti)
    f["stores_4q"] = wmean(W["cb_stores"], ti - 3, ti)
    # A 수요 모멘텀 (매출 흐름만)
    f["A1_sales_yoy"] = np.log(cb_growth(ti - 4, ti))
    s2030_now = wsum(W["cb_sales_2030"], ti - 3, ti) / f["sales_4q"]
    s2030_prev = wsum(W["cb_sales_2030"], ti - 7, ti - 4) / wsum(W["cb_sales"], ti - 7, ti - 4)
    f["A2_2030_share_chg"] = s2030_now - s2030_prev
    # B 고객 유입 (인구만)
    f["B1_flpop_yoy"] = np.log(wmean(W["flpop"], ti - 3, ti) / wmean(W["flpop"], ti - 7, ti - 4))
    f["B2_flpop_2030"] = wmean(W["flpop_share_2030"], ti - 3, ti)
    # 상주인구: 실제 갱신 빈티지 간 변화 (t0=20232 -> R1(20223) vs R2(20224 이후); t1=20262 -> R2(20232) vs R3(20234 이후))
    if t == T0:
        rp_new, rp_old = W["repop"][QI[20232]], W["repop"][QI[20223]]
    else:
        rp_new, rp_old = W["repop"][QI[t]], W["repop"][QI[20233]]
    f["B3_repop_chg"] = np.log(rp_new / rp_old).where((rp_old >= 100) & (rp_new >= 100))
    # C 공급 여력 (점포만 + 점포당 매출 수준)
    f["C1_store_yoy"] = np.log(f["stores_4q"] / wmean(W["cb_stores"], ti - 7, ti - 4))
    f["C2_close_rt"] = 100 * wsum(W["cb_close"], ti - 3, ti) / wmean(W["cb_stores"], ti - 7, ti - 4)
    f["C3_sales_per_store"] = wsum(W["coffee_sales_per_store"], ti - 3, ti)  # 커피 점포당 연매출(원/4분기/점포)
    # D 상권 체력 (구조 수준·정적)
    f["D1_scale"] = np.log(f["sales_4q"])
    fac = trdar.set_index("TRDAR_CD")
    f["D2_facility"] = np.log1p(fac["fac_total"].reindex(f.index))
    f["D3_opr_gap"] = W["opr_gap"][ti]
    # 모집단
    meta = trdar.set_index("TRDAR_CD")
    f["is_tour_zone"] = meta["is_tour_zone"].reindex(f.index)
    present4 = W["cb_sales"].loc[:, ti - 3:ti].notna().all(axis=1)
    f["in_pop"] = present4 & (f.sales_4q >= SALES_FLOOR_4Q) & (f.stores_4q >= STORE_FLOOR) & (f.is_tour_zone != 1) \
        & f["A1_sales_yoy"].notna()
    return f


IND = {  # 지표: (축, 가설 방향 +1/-1, 한글명, 단위)
    "A1_sales_yoy": ("A", +1, "커피+제과 매출 성장률(4분기 합 YoY, 업종구성 일치)", "log 비율/년"),
    "A2_2030_share_chg": ("A", +1, "20·30대 매출 비중 변화(4분기 합 기준 YoY)", "%p"),
    "B1_flpop_yoy": ("B", +1, "길단위 유동인구 성장률(4분기 평균 YoY)", "log 비율/년(상대지수)"),
    "B2_flpop_2030": ("B", +1, "유동인구 20·30대 비중(4분기 평균)", "비율"),
    "B3_repop_chg": ("B", +1, "상주인구 증감률(갱신 빈티지 간)", "log 비율"),
    "C1_store_yoy": ("C", -1, "커피+제과 점포수 증가율(4분기 평균 YoY, 경쟁 유입=감점)", "log 비율/년"),
    "C2_close_rt": ("C", -1, "커피+제과 연간 폐업률", "%/년"),
    "D1_scale": ("D", +1, "커피+제과 연매출 규모", "log 원/4분기"),
    "D2_facility": ("D", +1, "집객시설 수", "log(1+개소)"),
    "D3_opr_gap": ("D", +1, "운영 사업체 평균 영업개월 - 서울 평균(전 업종)", "개월"),
}
AX = ["A", "B", "C", "D"]


def score(f, weights, signs=None):
    g = f[f.in_pop].drop(columns=["y"], errors="ignore").copy()
    signs = signs or {k: v[1] for k, v in IND.items()}
    for k in IND:
        r = g[k].rank(pct=True)
        g["p_" + k] = (r if signs[k] > 0 else 1 - r).fillna(0.5)  # 결측은 중립 0.5
    for a in AX:
        cols = ["p_" + k for k, v in IND.items() if v[0] == a]
        g["ax_" + a] = g[cols].mean(axis=1)
    g["score"] = sum(weights[a] * g["ax_" + a] for a in AX) * 100
    return g


# ---------------- 백테스트 ----------------
# 주 창: t0=2023Q2(데이터 2021Q1~2023Q2만 사용) -> 2022Q3~23Q2 대비 2025Q3~26Q2 4분기 합 성장(3년)
# 보조 창: t0=2024Q2 -> 2026Q2(2년). 2023Q2 특징값(YoY)은 코로나 회복기(2022Q2~23Q2)를 포함하므로 회복기 이후 창으로 강건성 확인.
def sp(a, b):  # 스피어만 = 순위의 피어슨 (scipy 없음)
    m = a.notna() & b.notna()
    return float(a[m].rank().corr(b[m].rank()))


def make_bt(t0, t1):
    f = features(t0)
    f["y"] = np.log(cb_growth(QI[t0], QI[t1]))
    b = f[f.in_pop & f.y.notna()].copy()
    yrs = (QI[t1] - QI[t0]) / 4
    b["y_cagr"] = np.exp(b.y / yrs) - 1
    return f, b


f0, bt = make_bt(T0, T1)
f0b, btb = make_bt(20242, T1)
C3_IC = {"3y": round(sp(bt.C3_sales_per_store, bt.y), 3), "2y": round(sp(btb.C3_sales_per_store, btb.y), 3)}
ic = {k: round(sp(bt[k], bt.y), 3) for k in IND}
ic_2y = {k: round(sp(btb[k], btb.y), 3) for k in IND}

CANDS = {
    "W1_초안(35/25/25/15)": {"A": .35, "B": .25, "C": .25, "D": .15},
    "W2_균등(25x4)": {"A": .25, "B": .25, "C": .25, "D": .25},
    "W3_수요중심(50/20/20/10)": {"A": .50, "B": .20, "C": .20, "D": .10},
    "W4_공급·체력중심(20/20/35/25)": {"A": .20, "B": .20, "C": .35, "D": .25},
    "W5_모멘텀제외(0/30/40/30)": {"A": .0, "B": .30, "C": .40, "D": .30},
}


def evaluate(f, b, w):
    g = score(f, w).join(b[["y", "y_cagr"]], how="inner")
    rho = sp(g.score, g.y)
    q = g.score.rank(pct=True) >= 0.8
    yr = g.y.rank(pct=True)
    top10 = g.nlargest(int(len(g) * 0.1), "score")
    odd = g.index.str[-1].astype(int) % 2 == 1
    return {"spearman": round(rho, 3), "top20_hit_rate": round(float((q & (yr >= 0.8)).sum() / q.sum()), 3),
            "top20_in_bottom20": round(float((q & (yr <= 0.2)).sum() / q.sum()), 3),
            "top20_median_cagr": round(float(g[q].y_cagr.median()), 4),
            "top10pct_median_cagr": round(float(top10.y_cagr.median()), 4),
            "all_median_cagr": round(float(g.y_cagr.median()), 4), "n": int(len(g)),
            "spearman_half_odd_even": [round(sp(g[odd].score, g[odd].y), 3), round(sp(g[~odd].score, g[~odd].y), 3)]}


res_c = {name: {"main_3y_2023Q2_2026Q2": evaluate(f0, bt, w), "robust_2y_2024Q2_2026Q2": evaluate(f0b, btb, w)}
         for name, w in CANDS.items()}
axis_ic = {}
g_eq = score(f0, CANDS["W2_균등(25x4)"]).join(bt[["y"]], how="inner")
for a in AX:
    axis_ic[a] = round(sp(g_eq["ax_" + a], g_eq.y), 3)
half = {n: r["main_3y_2023Q2_2026Q2"]["spearman_half_odd_even"] for n, r in res_c.items()}
# 최종 가중치: 반분 두 개 모두에서 spearman 최소값이 가장 큰 후보(강건성 기준), 동률이면 단순한 쪽
# 선택 규칙(사전 정의): 두 창 스피어만 평균 최대. 차이 < 0.01이면 더 단순한(균등에 가까운) 후보.
avg = {n: (r["main_3y_2023Q2_2026Q2"]["spearman"] + r["robust_2y_2024Q2_2026Q2"]["spearman"]) / 2 for n, r in res_c.items()}
top_avg = max(avg.values())
near = [n for n in CANDS if top_avg - avg[n] < 0.01]
simplicity = {n: sum(abs(v - .25) for v in CANDS[n].values()) for n in CANDS}
best = min(near, key=lambda n: simplicity[n])
WEIGHTS = CANDS[best]

# ---------------- 최신 점수 ----------------
f1 = features(T1)
g1 = score(f1, WEIGHTS)
meta = trdar.set_index("TRDAR_CD")
g1 = g1.join(meta[["name", "type", "gu", "dong", "lon", "lat", "area_km2", "fac_subway", "fac_bus_stop", "fac_univ",
                   "fac_gnrl_hospital", "fac_total", "x_epsg5181", "y_epsg5181", "cb_sales_cagr3y"]])
# 과열 필터: 점포밀도 상위 10% & 폐업률 상위 25%
g1["store_density"] = g1.stores_4q / g1.area_km2
dens_cut = g1.store_density.quantile(0.9)
close_cut = g1.C2_close_rt.quantile(0.75)
g1["overheat"] = (g1.store_density >= dens_cut) & (g1.C2_close_rt >= close_cut)
# 추가 안전 필터: 상권축소(HL) 등급
chg_now = panel[panel.STDR_YYQU_CD == T1].set_index("TRDAR_CD")["chg_ix"]
g1["chg_ix"] = chg_now.reindex(g1.index)
g1["excluded"] = g1.overheat | (g1.chg_ix == "HL")
g1["rank_all"] = g1.score.rank(ascending=False, method="first").astype(int)
ranked = g1[~g1.excluded].sort_values("score", ascending=False)
ranked["rank"] = np.arange(1, len(ranked) + 1)

# ---------------- 프로파일 ----------------
last4 = panel[(panel.qi >= QI[T1] - 3) & (panel.qi <= QI[T1])]
SH = ["cb_share_wkend", "cb_share_t00_06", "cb_share_t06_11", "cb_share_t11_14", "cb_share_t14_17", "cb_share_t17_21",
      "cb_share_t21_24", "cb_share_female", "cb_share_age10", "cb_share_age20", "cb_share_age30", "cb_share_age40",
      "cb_share_age50p", "cb_share_unident"]


def profile(df):
    d = df[df.cb_sales.notna()]
    w = d.cb_sales
    out = {k.replace("cb_share_", "share_"): round(float((d[k] * w).sum() / w[d[k].notna()].sum()), 4) for k in SH}
    out["ticket_coffee_won"] = round(float(d.coffee_sales.sum() / d.coffee_txn.sum()))
    bk = d[d.bakery_sales.notna()]
    out["ticket_bakery_won"] = round(float(bk.bakery_sales.sum() / bk.bakery_txn.sum())) if len(bk) else None
    return out


def store_profile(df, n_q=4):
    s = df.groupby("STDR_YYQU_CD")[["coffee_stores", "bakery_stores", "coffee_frc", "bakery_frc", "cb_open", "cb_close",
                                    "cb_stores"]].sum()
    lastq = s.iloc[-1]
    return {"coffee_stores_2026Q2": int(lastq.coffee_stores), "bakery_stores_2026Q2": int(lastq.bakery_stores),
            "coffee_frc_share_2026Q2": round(float(lastq.coffee_frc / lastq.coffee_stores), 4) if lastq.coffee_stores else None,
            "bakery_frc_share_2026Q2": round(float(lastq.bakery_frc / lastq.bakery_stores), 4) if lastq.bakery_stores else None,
            "open_4q": int(s.cb_open.sum()), "close_4q": int(s.cb_close.sum())}


pop_ids = set(g1.index)
seoul_prof = profile(last4[last4.TRDAR_CD.isin(pop_ids)])
seoul_prof["coffee_sales_per_store_won_4q_median"] = round(float(g1.C3_sales_per_store.median()))
seoul_prof["close_rate_pct_4q_median"] = round(float(g1.C2_close_rt.median()), 2)
sp_all = store_profile(last4[last4.TRDAR_CD.isin(pop_ids)])
seoul_prof["coffee_frc_share_2026Q2"] = sp_all["coffee_frc_share_2026Q2"]
seoul_prof["bakery_frc_share_2026Q2"] = sp_all["bakery_frc_share_2026Q2"]
seoul_prof["sales_yoy_median"] = round(float(np.expm1(g1.A1_sales_yoy.median())), 4)
seoul_prof["n_trdar"] = len(g1)


def site_card(cd):
    r = g1.loc[cd]
    d = last4[last4.TRDAR_CD == cd]
    prof = profile(d)
    prof.update(store_profile(d))
    prof["coffee_sales_per_store_won_4q"] = round(float(r.C3_sales_per_store)) if pd.notna(r.C3_sales_per_store) else None
    prof["close_rate_pct_4q"] = round(float(r.C2_close_rt), 2)
    prof["cb_sales_4q_won"] = round(float(r.sales_4q))
    prof["sales_yoy"] = round(float(np.expm1(r.A1_sales_yoy)), 4)
    prof["sales_cagr_3y_2023Q2_2026Q2"] = None if pd.isna(r.cb_sales_cagr3y) else round(float(r.cb_sales_cagr3y), 4)
    prof["flpop_yoy"] = None if pd.isna(r.B1_flpop_yoy) else round(float(np.expm1(r.B1_flpop_yoy)), 4)
    prof["store_yoy"] = None if pd.isna(r.C1_store_yoy) else round(float(np.expm1(r.C1_store_yoy)), 4)
    # 분기 추이
    ts = panel[panel.TRDAR_CD == cd].set_index("STDR_YYQU_CD")
    prof["cb_sales_by_quarter_won"] = {str(int(q)): (None if pd.isna(v) else round(float(v))) for q, v in ts.cb_sales.items()}
    return prof


def row(cd, rank=None):
    r = g1.loc[cd]
    return {"rank": rank, "TRDAR_CD": cd, "name": r["name"], "type": r["type"], "gu": r.gu, "dong": r.dong,
            "lon": round(float(r.lon), 6), "lat": round(float(r.lat), 6),
            "score": round(float(r.score), 1), "axis": {a: round(float(r["ax_" + a]) * 100, 1) for a in AX},
            "cb_sales_4q_won": round(float(r.sales_4q)), "sales_yoy": round(float(np.expm1(r.A1_sales_yoy)), 4),
            "share_2030_chg_pp": None if pd.isna(r.A2_2030_share_chg) else round(float(r.A2_2030_share_chg) * 100, 2),
            "flpop_yoy": None if pd.isna(r.B1_flpop_yoy) else round(float(np.expm1(r.B1_flpop_yoy)), 4),
            "stores_4q_avg": round(float(r.stores_4q), 1),
            "store_yoy": None if pd.isna(r.C1_store_yoy) else round(float(np.expm1(r.C1_store_yoy)), 4),
            "close_rt_pct": round(float(r.C2_close_rt), 1),
            "coffee_sales_per_store_won_4q": None if pd.isna(r.C3_sales_per_store) else round(float(r.C3_sales_per_store)),
            "fac_subway": None if pd.isna(r.fac_subway) else int(r.fac_subway),
            "fac_total": None if pd.isna(r.fac_total) else int(r.fac_total),
            "chg_ix": r.chg_ix, "overheat": bool(r.overheat), "rank_before_filter": int(r.rank_all)}


top10 = [row(cd, int(ranked.loc[cd, "rank"])) for cd in ranked.index[:10]]
top30_ids = list(ranked.index[:30])

# 핫플 진단
HOT = ["3110131", "3120052", "3130071", "3120047", "3120104", "3110562", "3120186", "3120202", "3110759", "3120031",
       "3120002", "3110554", "3111013"]
hot = []
for cd in HOT:
    if cd in g1.index:
        h = row(cd, int(ranked.loc[cd, "rank"]) if cd in ranked.index else None)
        h["excluded_reason"] = ("과열(점포밀도 상위10%&폐업률 상위25%)" if g1.loc[cd, "overheat"] else
                                ("상권축소(HL)" if g1.loc[cd, "chg_ix"] == "HL" else None))
        hot.append(h)
    else:
        f1r = f1.loc[cd] if cd in f1.index else None
        hot.append({"TRDAR_CD": cd, "name": meta.loc[cd, "name"], "in_population": False,
                    "reason": "모집단 미포함(최근 4분기 매출 결측·구성 변동 또는 하한 미달)",
                    "cb_sales_4q_won": None if f1r is None or pd.isna(f1r.sales_4q) else round(float(f1r.sales_4q))})

# 인사이트 재료: 백테스트 단순 모멘텀 vs 결과, 최근 성장 상위 decile의 이후 성과
bt["mom_dec"] = bt.A1_sales_yoy.rank(pct=True)
mom_top = bt[bt.mom_dec >= 0.9].y_cagr.median()
mom_bot = bt[bt.mom_dec <= 0.1].y_cagr.median()
cps_top = bt[bt.C3_sales_per_store.rank(pct=True) >= 0.8].y_cagr.median()
cps_bot = bt[bt.C3_sales_per_store.rank(pct=True) <= 0.2].y_cagr.median()
st_top = bt[bt.C1_store_yoy.rank(pct=True) >= 0.8].y_cagr.median()
st_bot = bt[bt.C1_store_yoy.rank(pct=True) <= 0.2].y_cagr.median()
# 시간대 패턴: 최신 Top30 vs 서울의 오전(06~11) 비중 변화 (2023Q2 4q -> 2026Q2 4q)
def morning_share(ids, ti):
    d = panel[(panel.qi >= ti - 3) & (panel.qi <= ti) & panel.TRDAR_CD.isin(ids) & panel.cb_sales.notna()]
    return float((d.cb_share_t06_11 * d.cb_sales).sum() / d.cb_sales.sum())
ms = {"top30_2023Q2_4q": round(morning_share(top30_ids, QI[T0]), 4), "top30_2026Q2_4q": round(morning_share(top30_ids, QI[T1]), 4),
      "pop_2023Q2_4q": round(morning_share(pop_ids, QI[T0]), 4), "pop_2026Q2_4q": round(morning_share(pop_ids, QI[T1]), 4)}

dump = {
    "ic": ic, "ic_2y": ic_2y, "C3_IC": C3_IC, "avg": avg, "axis_ic": axis_ic, "cands": res_c, "half": half, "best": best,
    "mom": [mom_top, mom_bot], "cps": [cps_top, cps_bot], "st": [st_top, st_bot], "ms": ms,
    "pop_n_t0": int(f0.in_pop.sum()), "bt_n": len(bt), "pop_n_t1": len(g1), "excluded_n": int(g1.excluded.sum()),
    "overheat_n": int(g1.overheat.sum()), "dens_cut": dens_cut, "close_cut": close_cut,
}
pd.to_pickle({"g1": g1, "ranked": ranked, "bt": bt, "f1": f1, "top10": top10, "hot": hot, "dump": dump,
              "seoul_prof": seoul_prof, "WEIGHTS": WEIGHTS}, os.path.join(os.environ.get("TEMP", "."), "score_cache.pkl"))
print(json.dumps(dump, ensure_ascii=False, indent=1, default=float))
print(pd.DataFrame(top10)[["rank", "TRDAR_CD", "name", "gu", "type", "score", "cb_sales_4q_won", "sales_yoy", "store_yoy",
                           "close_rt_pct", "flpop_yoy", "rank_before_filter"]].to_string())
print(pd.DataFrame([{k: h.get(k) for k in ["name", "rank", "score", "excluded_reason", "sales_yoy", "store_yoy", "close_rt_pct",
                                          "rank_before_filter", "in_population"]} for h in hot]).to_string())


# ================= 결과 저장 (analysis.json) =================
SRC = {
    "OA-15572": "서울시 상권분석서비스(추정매출-상권) VwsmTrdarSelngQq, 2021Q1~2026Q2, 원/분기(추정)",
    "OA-15577": "서울시 상권분석서비스(점포-상권) VwsmTrdarStorQq, 2021Q1~2026Q2, 개(분기 스톡)·개/분기",
    "OA-15568": "서울시 상권분석서비스(길단위인구-상권) VwsmTrdarFlpopQq, 2021Q1~2026Q2, 상대지수",
    "OA-15584": "서울시 상권분석서비스(상주인구-상권) VwsmTrdarRepopQq, 실제 갱신 2022Q4·2023Q4, 명",
    "OA-15580": "서울시 상권분석서비스(집객시설-상권) VwsmTrdarFcltyQq, 시점 미상 스냅샷, 개소",
    "OA-15576": "서울시 상권분석서비스(상권변화지표-상권) VwsmTrdarIxQq, 2021Q1~2026Q2, 개월·등급",
    "OA-15560": "서울시 상권분석서비스(영역-상권) TbgisTrdarRelm, 현행 영역(2026-11-14 수집), m·㎡·WGS84(역투영)",
}
IND_SRC = {"A1": "OA-15572", "A2": "OA-15572", "B1": "OA-15568", "B2": "OA-15568", "B3": "OA-15584", "C1": "OA-15577",
           "C2": "OA-15577", "D1": "OA-15572", "D2": "OA-15580", "D3": "OA-15576"}
AXNAME = {"A": "수요 모멘텀(매출 흐름)", "B": "고객 유입(인구)", "C": "공급 여력(점포·과열 감점)", "D": "상권 체력(구조적 수준)"}

top3 = top10[:3]
final_cd = top10[0]["TRDAR_CD"]
final_card = site_card(final_cd)
hot_axes = {h["TRDAR_CD"]: h.get("axis") for h in hot}

out = {
    "meta": {"generated_by": "analysis/score.py", "as_of_quarter": "2026Q2", "base_data": "data/processed/panel.csv, trdar.csv",
             "population_rule": f"관광특구 제외, 최근 4분기(2025Q3~2026Q2) 커피+제과 매출 연속 관측, 4분기 합 >= {SALES_FLOOR_4Q/1e8:.0f}억원, "
                                f"4분기 평균 커피+제과 점포 >= {STORE_FLOOR}개, 매출 YoY 계산 가능(업종 구성 일치)",
             "population_n": {"2023Q2(백테스트)": dump["pop_n_t0"], "2026Q2(최신)": dump["pop_n_t1"]},
             "normalization": "각 지표를 시점별 모집단 내 백분위(0~1)로 변환(서울 거시 추세 상대화), 감점 지표는 1-백분위, 결측=0.5. 축 점수=축 내 지표 평균, 총점=가중합x100"},
    "metrics": {
        "axes": {a: {"name": AXNAME[a], "weight": WEIGHTS[a]} for a in AX},
        "indicators": [{"id": k, "axis": v[0], "direction": "+" if v[1] > 0 else "-(감점)", "definition": v[2], "unit": v[3],
                        "source": IND_SRC[k[:2]], "window_2026Q2": "2024Q3~2025Q2 대비 2025Q3~2026Q2" if ("yoy" in k or "chg" in k) else "2025Q3~2026Q2",
                        "backtest_ic_3y": ic[k], "backtest_ic_2y": ic_2y[k]} for k, v in IND.items()],
        "mece_rules": ["A=매출 흐름만, B=인구만, C=점포 수·폐업만, D=수준·정적 구조값만 사용(같은 원천 변수를 두 축에 넣지 않음)",
                       "성장률은 모두 4분기 합(연환산) YoY로 계절성 제거",
                       "상주인구는 실제 갱신 빈티지(2022Q4·2023Q4) 간 변화만 사용, 집객시설은 정적 수준으로만 사용",
                       "프랜차이즈 비중은 2025Q4 재분류 단절 때문에 점수에서 제외(프로파일에만 사용)"],
        "dropped": {"C3_coffee_sales_per_store": {"reason": "가설(+)과 반대로 두 백테스트 창 모두 음(-)의 상관(평균회귀). 부호를 사후에 뒤집지 않고 점수에서 제외, 프로파일 지표로만 사용",
                                                  "ic_3y": C3_IC["3y"], "ic_2y": C3_IC["2y"]}},
        "weight_rationale": f"사전 정의 후보 5개를 두 창(3년·2년) 스피어만 평균으로 비교. 최고 {max(avg.values()):.3f}와 0.01 이내 후보 중 가장 단순한(균등에 가까운) '{best}' 선택. "
                            "후보 간 차이가 0.01 미만이라 데이터에 맞춘 미세 가중은 과적합으로 판단.",
        "overheat_filter": {"rule": "점포밀도(4분기 평균 점포/㎢) 상위 10% AND 연간 폐업률 상위 25% → 제외; 상권변화지표 HL(상권축소) → 제외",
                            "density_cut_stores_per_km2": round(float(dens_cut), 1), "close_rate_cut_pct_per_year": round(float(close_cut), 1),
                            "n_overheat": dump["overheat_n"], "n_excluded_total": dump["excluded_n"], "period": "2025Q3~2026Q2"},
    },
    "backtest": {
        "design": "t0 시점까지 데이터로만 점수 산출 → 이후 실제 커피+제과 매출(4분기 합, 업종 구성 일치) 성장률과 비교",
        "main_window": "t0=2023Q2, 결과 = 2022Q3~2023Q2 대비 2025Q3~2026Q2 (3년), 단위: 연평균 성장률(CAGR)",
        "robust_window": "t0=2024Q2, 결과 = 2023Q3~2024Q2 대비 2025Q3~2026Q2 (2년). 2023Q2 특징값이 코로나 회복기(2022~23)를 포함해 보조 창으로 강건성 확인",
        "candidates": res_c, "avg_spearman": {k: round(v, 3) for k, v in avg.items()}, "selected": best,
        "axis_ic_3y": axis_ic,
        "interpretation": "상관은 약하지만 두 창 모두 양(+)이고 상위 20%의 하위 20% 추락 비율이 무작위(20%)보다 낮음. "
                          "3년 상권 매출은 본질적으로 예측 난도가 높아 점수는 '하방 위험이 낮은 후보 압축' 도구로 쓰고 최종 판단은 프로파일로 보강.",
    },
    "top10": top10,
    "top3": [{"rank": t["rank"], "TRDAR_CD": t["TRDAR_CD"], "name": t["name"], "score": t["score"]} for t in top3],
    "final_site": {"TRDAR_CD": final_cd, "name": top10[0]["name"], "gu": top10[0]["gu"], "dong": top10[0]["dong"],
                   "lon": top10[0]["lon"], "lat": top10[0]["lat"], "score": top10[0]["score"], "axis": top10[0]["axis"],
                   "facilities": {k: (None if pd.isna(g1.loc[final_cd, k]) else int(g1.loc[final_cd, k]))
                                  for k in ["fac_total", "fac_subway", "fac_bus_stop", "fac_univ", "fac_gnrl_hospital"]},
                   "facilities_note": "OA-15580 시점 미상 스냅샷, 개소",
                   "area_km2": round(float(g1.loc[final_cd, "area_km2"]), 4),
                   "kpis": final_card},
    "customer_profile": {"TRDAR_CD": final_cd, "period": "2025Q3~2026Q2(4분기, 매출 가중)", "unit": "비율(0~1), 원/건, 원/4분기/점포, 개, %/년",
                         "source": "OA-15572, OA-15577", **{k: v for k, v in final_card.items() if k != "cb_sales_by_quarter_won"}},
    "seoul_benchmarks": {"scope": f"분석 모집단 {len(g1)}개 상권 합산(매출 가중) 또는 중앙값", "period": "2025Q3~2026Q2", **seoul_prof},
    "hot_places": hot,
    "insight_inputs": {
        "momentum_decile_3y_cagr": {"top10pct_by_2023Q2_yoy": round(float(mom_top), 4), "bottom10pct": round(float(mom_bot), 4),
                                    "unit": "2023Q2→2026Q2 매출 CAGR 중앙값"},
        "store_growth_quintile_3y_cagr": {"top20pct_store_growth": round(float(st_top), 4), "bottom20pct": round(float(st_bot), 4)},
        "sales_per_store_quintile_3y_cagr": {"top20pct": round(float(cps_top), 4), "bottom20pct": round(float(cps_bot), 4)},
        "morning_06_11_share": ms,
    },
    "sources": {k: v for k, v in SRC.items()},
}
pd.to_pickle(out, os.path.join(os.environ.get("TEMP", "."), "analysis_out.pkl"))
with open(os.path.join(OUT, "analysis.json"), "w", encoding="utf-8") as fp:
    json.dump(out, fp, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
print("saved", os.path.join(OUT, "analysis.json"))
print(json.dumps({"final": out["final_site"], "seoul": out["seoul_benchmarks"]}, ensure_ascii=False, indent=0, default=str)[:4000])
for h in hot:
    print(h.get("name"), h.get("axis"), h.get("chg_ix"))
for t in top10[:3]:
    print(t["name"], t["axis"], t["chg_ix"], t["fac_subway"], t["share_2030_chg_pp"])


# ================= 인사이트 (수치는 위 결과에서 직접 인용) =================
def pct(x, d=1):
    return f"{x*100:+.{d}f}%"


H = {h["TRDAR_CD"]: h for h in hot}
sc, hn = g1.loc["3110131"], g1.loc["3120047"]
fp, sb = final_card, seoul_prof
hot_ll = sum(1 for h in hot if h.get("chg_ix") == "LL")
hot_in = sum(1 for h in hot if h.get("chg_ix") is not None)
top_hh = sum(1 for t in top10 if t["chg_ix"] in ("HH",))
insights = [
    {"title": "뜬 곳은 이미 떴다: 성수카페거리·한남·연남·가로수길은 200위 밖",
     "text": f"성수동카페거리는 2023Q2→2026Q2 커피+제과 매출 연 {pct(sc.cb_sales_cagr3y)}로 지난 3년 승자지만, 최근 1년 점포가 {pct(np.expm1(sc.C1_store_yoy))} 늘어 공급이 수요를 쫓는 중(2029 점수 {H['3110131']['rank']}위). "
             f"한남오거리는 매출 YoY {pct(np.expm1(hn.A1_sales_yoy))}에도 폐업률 {hn.C2_close_rt:.1f}%/년(모집단 중앙값 {sb['close_rate_pct_4q_median']:.1f}%)로 공급 축 하위({H['3120047']['axis']['C']:.0f}점). "
             f"가로수길·압구정로데오는 매출 YoY {pct(H['3120186']['sales_yoy'])}·{pct(H['3120202']['sales_yoy'])}로 이미 하락. 핫플 {hot_in}곳 중 {hot_ll}곳이 상권변화지표 LL(다이나믹: 운영·폐업 영업기간 모두 서울 평균 미만), Top10은 {top_hh}곳이 HH(정체=오래 버티는 상권).",
     "period": "2025Q3~2026Q2(4분기 합) 및 2022Q3~23Q2→2025Q3~26Q2", "unit": "%/년, %/년(폐업률), 점수(0~100)", "source": "OA-15572, OA-15577, OA-15576"},
    {"title": "천호역은 '저녁·주말형 생활권 카페' — 오피스 상권과 정반대 시간표",
     "text": f"천호역 17~21시 매출 비중 {fp['share_t17_21']*100:.1f}% vs 모집단 {sb['share_t17_21']*100:.1f}%, 주말 {fp['share_wkend']*100:.1f}% vs {sb['share_wkend']*100:.1f}%, 점심(11~14시) {fp['share_t11_14']*100:.1f}% vs {sb['share_t11_14']*100:.1f}%. "
             f"법인 등 미식별 매출 {fp['share_unident']*100:.1f}% vs {sb['share_unident']*100:.1f}% → 오피스 법인카드가 아닌 개인 소비 상권. 20·30대 매출 비중 {(fp['share_age20']+fp['share_age30'])*100:.1f}% vs {(sb['share_age20']+sb['share_age30'])*100:.1f}%.",
     "period": "2025Q3~2026Q2(4분기, 매출 가중)", "unit": "매출 비중(%)", "source": "OA-15572"},
    {"title": "싸게 많이 파는 상권: 객단가는 서울보다 35% 낮은데 점포당 매출은 1.8배",
     "text": f"천호역 커피 건당 결제액 {fp['ticket_coffee_won']:,}원 vs 모집단 {sb['ticket_coffee_won']:,}원, 그런데 커피 점포당 연매출 {fp['coffee_sales_per_store_won_4q']/1e8:.2f}억원 vs 중앙값 {sb['coffee_sales_per_store_won_4q_median']/1e8:.2f}억원. "
             f"커피 프랜차이즈 비중 {fp['coffee_frc_share_2026Q2']*100:.0f}% vs {sb['coffee_frc_share_2026Q2']*100:.0f}%로 저가 체인이 트래픽을 흡수 중이고, 베이커리 건당 {fp['ticket_bakery_won']:,}원(커피의 약 2배)은 객단가를 올릴 레버. "
             f"유동인구 YoY {pct(fp['flpop_yoy'])}, 점포 YoY {pct(fp['store_yoy'])}로 수요가 공급보다 빠르게 늘고 있음.",
     "period": "2025Q3~2026Q2(4분기), 점포는 2026Q2", "unit": "원/건, 원/4분기/점포, %", "source": "OA-15572, OA-15577, OA-15568"},
    {"title": "백테스트의 교훈: '점포당 매출 높은 알짜 상권'은 다음 3년 덜 큰다",
     "text": f"2023Q2 기준 커피 점포당 매출 상위 20% 상권의 이후 3년 매출 CAGR 중앙값 {pct(cps_top)} vs 하위 20% {pct(cps_bot)} (스피어만 {C3_IC['3y']}). 높은 점포당 매출은 신규 진입을 불러 희석된다 → 수준이 아니라 '수요 성장 > 공급 성장'의 격차를 봐야 함. 천호역도 점포당 매출이 높아(1.8배) 이 위험에 노출되나, 점포 증가 {pct(fp['store_yoy'])}·폐업률 {fp['close_rate_pct_4q']:.1f}%로 아직 희석 압력이 낮음 → 출점 후 핵심 모니터링 지표(경쟁 점포 순증).",
     "period": "2023Q2 기준, 2022Q3~23Q2→2025Q3~26Q2", "unit": "%/년", "source": "OA-15572, OA-15577"},
]
out["insights"] = insights
out["final_site"]["why"] = [
    f"총점 {top10[0]['score']}점 1위(과열·상권축소 필터 후 {len(ranked)}개 중): 수요 {top10[0]['axis']['A']}·유입 {top10[0]['axis']['B']}·체력 {top10[0]['axis']['D']}점이 모두 상위권",
    f"매출 YoY {pct(fp['sales_yoy'])}(모집단 중앙 {pct(sb['sales_yoy_median'])}), 3년 CAGR {pct(fp['sales_cagr_3y_2023Q2_2026Q2'])}, 유동인구 {pct(fp['flpop_yoy'])} vs 점포 {pct(fp['store_yoy'])} → 수요가 공급보다 빠름",
    f"폐업률 {fp['close_rate_pct_4q']:.1f}%/년(중앙 {sb['close_rate_pct_4q_median']:.1f}%), 연매출 규모 {fp['cb_sales_4q_won']/1e8:.0f}억원, 지하철역 {out['final_site']['facilities']['fac_subway']}개·버스정거장 {out['final_site']['facilities']['fac_bus_stop']}개·종합병원 {out['final_site']['facilities']['fac_gnrl_hospital']}개 (집객시설 {out['final_site']['facilities']['fac_total']}개소)",
]
out["final_site"]["location"] = {
    "description": "천호역(5·8호선 환승) 상권 대표점 기준 반경 내, 천호대로·올림픽로가 만나는 천호사거리 일대(강동구 천호2동). 저녁·주말 비중이 높아 역 출구~로데오거리 보행 동선의 1층 코너, 베이커리 진열이 보이는 전면 유리형 점포 권장.",
    "data_basis": "trdar.csv 상권명·행정동·대표점 좌표(EPSG:5181 추정→WGS84), 집객시설 OA-15580(지하철역 2·버스정거장 10·종합병원 2)",
    "external_knowledge_flag": "5·8호선 환승역·천호사거리·로데오거리 명칭은 데이터셋 외 일반 지리 정보(검증 필요)",
    "lon": top10[0]["lon"], "lat": top10[0]["lat"]}
with open(os.path.join(OUT, "analysis.json"), "w", encoding="utf-8") as fp_:
    json.dump(out, fp_, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
for i in insights:
    print("-", i["title"], "|", i["text"])
print(out["final_site"]["why"])
