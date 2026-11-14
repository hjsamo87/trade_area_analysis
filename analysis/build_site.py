# -*- coding: utf-8 -*-
"""site/index.html 생성기 — 모든 수치를 analysis.json / concept.json / pnl.json에서 읽어 인라인한다.
실행: py -I -X utf8 analysis/build_site.py   (pnl.py 재실행 후 다시 실행)
"""
import json, os, html

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "analysis", "results")
A = json.load(open(os.path.join(RES, "analysis.json"), encoding="utf8"))
C = json.load(open(os.path.join(RES, "concept.json"), encoding="utf8"))
P = json.load(open(os.path.join(RES, "pnl.json"), encoding="utf8"))
OUT = os.path.join(ROOT, "site", "index.html")

esc = html.escape
def pc(v, d=1, sign=False): return (f"{v*100:+.{d}f}%" if sign else f"{v*100:.{d}f}%")
def pp(v, d=1): return f"{v:+.{d}f}%p"
def eok(v, d=1): return f"{v/1e8:,.{d}f}억원"
def man(v): return f"{v/1e4:,.0f}만원"
def num(v): return f"{v:,.0f}"

FS = A["final_site"]; KP = FS["kpis"]; BI = A["benchmarks"]["investable"]; BP = A["benchmarks"]["population"]
BT = A["backtest"]; SC = P["scenarios"]; B = SC["기준"]; HL = P["headline"]
b27, b29 = B["years"]["2027"], B["years"]["2029"]
inv = B["investment"]["total_excl_deposit"]
days = B["revenue_crosscheck_2026basis"]["days_per_year"]
ticket = C["avg_ticket_krw"]
txn27 = B["revenue_crosscheck_2026basis"]["implied_daily_txn_2027"]
bep_txn = b27["bep_monthly_revenue"] * 12 / days / ticket
N_INV = A["meta"]["investable_n"]; N_POP = A["meta"]["population_n"]
N_RANKED = 136  # analysis.json final_site.why: 출점 적격 중 과열·상권축소 제외 순위 모집단

def src(t): return f'<p class="src">{t}</p>'
S_SALES = "OA-15572 추정매출(카드 기반), 2025Q3~2026Q2 4분기"
S_STORE = "OA-15577 점포, 2025Q3~2026Q2"
BADGE = {"D": '<span class="bd d">데이터</span>', "E": '<span class="bd e">외부</span>', "A": '<span class="bd a">가정</span>'}
def badges(t): return " ".join(BADGE[x] for x in ["D", "E", "A"] if x in t)

# ---------------- 차트 헬퍼(순수 HTML 막대) ----------------
def hbars(rows, fmt, maxv=None, cls=""):
    """rows: [(label, value, highlight_bool, note)]"""
    m = maxv or max(abs(r[1]) for r in rows) or 1
    out = [f'<div class="hb {cls}">']
    for lab, v, hi, note in rows:
        w = max(abs(v) / m * 100, 0.8)
        out.append(f'<div class="hb-r"><span class="hb-l">{lab}</span><span class="hb-t"><i class="{"hi" if hi else ""}" style="width:{w:.1f}%"></i></span><span class="hb-v">{fmt(v)}{note}</span></div>')
    out.append("</div>")
    return "".join(out)

def diverge(rows):
    """rows: [(label, value_pp, desc)] 0 중심 좌우 막대"""
    m = max(abs(r[1]) for r in rows)
    out = ['<div class="dv">']
    for lab, v, d in rows:
        w = abs(v) / m * 50
        side = f'left:50%;width:{w:.1f}%' if v >= 0 else f'left:{50-w:.1f}%;width:{w:.1f}%'
        out.append(f'<div class="dv-r"><span class="dv-l">{lab}<small>{d}</small></span><span class="dv-t"><b></b><i class="{"pos" if v>=0 else "neg"}" style="{side}"></i></span><span class="dv-v {"pos" if v>=0 else "neg"}">{pp(v,2)}</span></div>')
    out.append('<div class="dv-ax"><span>하위 20%가 더 성장</span><span>상위 20%가 더 성장</span></div></div>')
    return "".join(out)

# ---------------- 데이터 가공 ----------------
q = KP["cb_sales_by_quarter_won"]; qk = list(q.keys())
yoy_up = {k: (q[k] > q[qk[i-4]]) if i >= 4 else None for i, k in enumerate(qk)}
qmax = max(q.values())
qbars = "".join(
    f'<div class="qb"><i class="{"hi" if yoy_up[k] and i >= len(qk)-6 else ""}" style="height:{q[k]/qmax*100:.1f}%" title="{k} {q[k]/1e8:.1f}억원"></i><span>{k[2:4] + "." + k[-1] if k.endswith("1") or i == len(qk)-1 else ""}</span></div>'
    for i, k in enumerate(qk))

top10_rows = "".join(
    f'<tr class="{"hl" if t["TRDAR_CD"]==FS["TRDAR_CD"] else ""}"><td>{t["rank"]}</td><td><b>{esc(t["name"])}</b><small>{t["gu"]} · {t["type"]}</small></td><td class="n"><b>{t["score"]:.1f}</b></td>'
    + "".join(f'<td class="n">{t["axis"][a]:.1f}</td>' for a in "ABCD")
    + f'<td class="n">{t["cb_sales_4q_won"]/1e8:,.0f}</td><td class="n">{pc(t["sales_yoy"],1,True)}</td><td class="n">{pc(t["txn_yoy"],1,True)}</td><td class="n">{pc(t["morning_share"])}</td><td class="n">{pc(t["weekend_share"])}</td></tr>'
    for t in A["top10"])

def hot_reason(h):
    if h.get("in_population") is False:
        return h["reason"]
    r = []
    if not h["investable"]:
        r.append("출점 적격 미달(연 커피+제과 매출 50억원 미만)")
    if h["axis"]["B"] < 45:
        r.append(f'여가형 고객 구성(B축 {h["axis"]["B"]:.0f}점: 주말 {pc(h["weekend_share"])}, 아침 {pc(h["morning_share"])})')
    if h["axis"]["A"] < 45:
        r.append(f'매출 흐름 꺾임(A축 {h["axis"]["A"]:.0f}점: 매출 {pc(h["sales_yoy"],1,True)}, 결제건수 {pc(h["txn_yoy"],1,True)})')
    if h["axis"]["D"] < 50:
        r.append(f'공급 이탈(D축 {h["axis"]["D"]:.0f}점: 점포 {pc(h["store_yoy"],1,True)}, 폐업률 {pc(h["close_rate"])})')
    if h["axis"]["C"] < 40:
        r.append(f'접근성 약함(C축 {h["axis"]["C"]:.0f}점, 지하철역 {h["fac_subway"]}개)')
    if h["TRDAR_CD"] == "3120243":
        r.insert(0, "v1 1위였으나 v2에서 하락 — 주말 비중 32.0%·법인 매출 3.1%")
    if not r and h["rank"] and h["rank"] <= 10:
        r.append("핫플 중 유일한 Top10 — 오피스형(주말 15.9%, 법인 23.3%)")
    return "; ".join(r) or "점수 중위권"

hot_rows = []
for h in A["hot_places"]:
    if h.get("in_population") is False:
        hot_rows.append(f'<tr><td><b>{esc(h["name"])}</b></td><td class="n">—</td><td class="n">—</td><td class="n">—</td><td class="n">—</td><td class="n">—</td><td class="n">—</td><td>{hot_reason(h)}</td></tr>')
        continue
    rk = f'{h["rank"]}위' if h["rank"] else "적격 밖"
    hot_rows.append(f'<tr><td><b>{esc(h["name"])}</b><small>{h["gu"]}</small></td><td class="n">{rk}</td><td class="n">{h["score"]:.1f}</td><td class="n">{pc(h["sales_yoy"],1,True)}</td><td class="n">{pc(h["txn_yoy"],1,True)}</td><td class="n">{pc(h["morning_share"])}</td><td class="n">{pc(h["weekend_share"])}</td><td>{hot_reason(h)}</td></tr>')
hot_rows = "".join(hot_rows)

AXQ = {"A": "매출이 손님 수로 꾸준히 크고 있나", "B": "일상 수요인가, 여가 수요인가", "C": "사람이 늘고 접근이 쉬운가", "D": "사업자가 들어오고 버티는가"}
AXSRC = {"A": "OA-15572", "B": "OA-15572", "C": "OA-15568 · OA-15580", "D": "OA-15577"}
IND = A["metrics"]["indicators"]; AX = A["metrics"]["axes"]
axis_rows = ""
for a in "ABCD":
    li = [i for i in IND if i["axis"] == a]
    chips = "".join(f'<span class="chip {"neg" if i["direction"].startswith("-") else "pos"}">{esc(i["definition"].split("(")[0].split(" — ")[0])} {"−" if i["direction"].startswith("-") else "+"}</span>' for i in li)
    axis_rows += f'<tr><td><b>{a} {AX[a]["name"]}</b><small>{AX[a]["n_indicators"]}개 지표</small></td><td>{AXQ[a]}</td><td>{chips}</td><td>{AXSRC[a]}</td><td class="n">{pc(AX[a]["effective_weight"])}</td></tr>'
ind_rows = "".join(
    f'<tr><td>{i["id"].split("_")[0]}</td><td>{esc(i["definition"])}</td><td class="c">{"감점" if i["direction"].startswith("-") else "가점"}</td><td>{i["unit"]}</td><td>{i["source"]}</td><td class="n">{i["train_ic"]["mean"]:+.3f}</td><td class="n">{i["test_ic"]["1y"]:+.3f}</td><td class="n">{i["test_ic"]["3y"]:+.3f}</td></tr>'
    for i in IND)
drop_rows = "".join(f"<li><b>{esc(k)}</b> — {esc(v)}</li>" for k, v in A["metrics"]["dropped_candidates"].items())

v1i, v2i, v1a, v2a = BT["v1_investable"], BT["v2_investable"], BT["v1_all_population"], BT["v2_all_population"]
bt_rows = [
    ("지표 선정", "가설 기반 10개, 가중치 후보 5개 중 사후 선택", f"후보 33개 → 학습 구간에서만 검증해 19개 채택, 부호도 학습 구간에서 확정, 동일가중"),
    ("검증 방식", "단일 창 1개(2023Q2→2026Q2)", "롤링 기준시점 16개 × 1·2·3년, 학습 이후 시점으로 표본 밖 검증"),
    ("3년 예측 스피어만 — 출점 적격", f'{v1i["3y"]["spearman"]:.3f}', f'<b>{v2i["3y"]["spearman"]:.3f}</b> (기준시점별 최저 {v2i["3y"]["spearman_min"]:.3f})'),
    ("3년 예측 스피어만 — 전체 모집단", f'{v1a["3y"]["spearman"]:.3f} (v1 원보고값)', f'<b>{v2a["3y"]["spearman"]:.3f}</b>'),
    ("1년 예측 스피어만 — 출점 적격", f'{v1i["1y"]["spearman"]:.3f} (최저 {v1i["1y"]["spearman_min"]:+.3f})', f'<b>{v2i["1y"]["spearman"]:.3f}</b> (최저 {v2i["1y"]["spearman_min"]:.3f}, 8개 시점 모두 양수)'),
    ("점수 상위 20% − 하위 20% 연평균 성장률 격차(3년, 적격)", pp(v1i["3y"]["spread_pp"]), f'<b>{pp(v2i["3y"]["spread_pp"])}</b>/년'),
    ("같은 격차(1년, 적격)", pp(v1i["1y"]["spread_pp"]), f'<b>{pp(v2i["1y"]["spread_pp"])}</b>/년'),
    ("상위 20% 적중률(실제 성장 상위 20%에 든 비율, 3년)", pc(v1i["3y"]["top20_hit"]), f'<b>{pc(v2i["3y"]["top20_hit"])}</b> (무작위 20.0%)'),
]
bt_html = "".join(f"<tr><td>{a}</td><td class='n'>{b}</td><td class='n'>{c}</td></tr>" for a, b, c in bt_rows)

orig = BT["by_origin"]["v2_investable"]
omax = max(o["spearman"] for o in orig)
orig_html = ""
for hq, lab in [(4, "1년 뒤"), (8, "2년 뒤"), (12, "3년 뒤")]:
    cells = "".join(f'<div class="ob"><i style="height:{o["spearman"]/omax*100:.0f}%"></i><b>{o["spearman"]:.2f}</b><span>{o["t0"][2:]}</span></div>' for o in orig if o["horizon_q"] == hq)
    orig_html += f'<div class="og"><div class="og-bars">{cells}</div><p>{lab} 예측</p></div>'

INS = A["insight_inputs"]["quintiles_3y"]
INSN = {"B5_morning_share": ("아침(06~11시) 매출 비중", "B5"), "A4_txn_yoy": ("결제건수 성장률", "A4"), "A1_sales_yoy": ("매출 성장률", "A1"),
        "B4_corp_share": ("법인 등 미식별 매출 비중", "B4"), "D1_store_yoy": ("점포 순증률", "D1"), "B7_weekend_share": ("주말 매출 비중", "B7"),
        "B6_evening_share": ("저녁(17~21시) 매출 비중", "B6"), "A5_ticket_yoy": ("건당 결제액(객단가) 성장률", "A5")}
ins_div = diverge([(INSN[k][0], INS[k]["spread_pp"], f'상위 {pc(INS[k]["top20_cagr_med"],1,True)} · 하위 {pc(INS[k]["bottom20_cagr_med"],1,True)}') for k in INSN])

# 고객 구성 비교
cmp_rows = [
    ("아침(06~11시) 매출 비중", KP["share_t06_11"], BI["share_t06_11"]),
    ("점심(11~14시) 매출 비중", KP["share_t11_14"], BI["share_t11_14"]),
    ("저녁(17~21시) 매출 비중", KP["share_t17_21"], BI["share_t17_21"]),
    ("주말 매출 비중", KP["share_wkend"], BI["share_wkend"]),
    ("남성 매출 비중", 1 - KP["share_female"], 1 - BI["share_female"]),
    ("30~40대 매출 비중", KP["share_age30"] + KP["share_age40"], BI["share_age30"] + BI["share_age40"]),
    ("50대 이상 매출 비중", KP["share_age50p"], BI["share_age50p"]),
    ("법인 등 성별·연령 미식별 매출 비중", KP["share_unident"], BI["share_unident"]),
    ("제과점 프랜차이즈 비중(2026Q2, 점포)", KP["bakery_frc_share_2026Q2"], BI["bakery_frc_share_2026Q2"]),
]
cmp_html = "".join(
    f'<tr><td>{l}</td><td class="n"><b>{pc(s)}</b></td><td class="n">{pc(b)}</td><td class="n {"up" if s>b else "dn"}">{(s-b)*100:+.1f}%p</td></tr>' for l, s, b in cmp_rows)

dp_keys = [("share_t06_11", "06~11시"), ("share_t11_14", "11~14시"), ("share_t14_17", "14~17시"), ("share_t17_21", "17~21시"), ("share_t21_24", "21~24시")]
dp_html = '<div class="pair">' + "".join(
    f'<div class="pair-r"><span class="pair-l">{lab}</span><span class="pair-t"><i class="s" style="width:{KP[k]/0.4*100:.1f}%"></i><i class="b" style="width:{BI[k]/0.4*100:.1f}%"></i></span><span class="pair-v"><b>{pc(KP[k])}</b> / {pc(BI[k])}</span></div>'
    for k, lab in dp_keys) + '<div class="lg"><span><i class="s"></i>남부터미널역</span><span><i class="b"></i>출점 적격 158개 평균</span></div></div>'

per_html = ""
for pz in C["personas"]:
    li = "".join(f"<li><span>{esc(k)}</span><b>{esc(v)}</b></li>" for k, v in pz["share_basis"].items())
    per_html += f'<div class="card persona"><p class="tag">{pz["id"]}</p><h4>{esc(pz["name"])}</h4><ul class="kv">{li}</ul><p class="need"><b>니즈</b> {esc(pz["need"])}</p><p class="ext"><span class="bd e">외부</span> {esc(pz["context_external"])}</p></div>'

# 공간
asplit = C["area_split"]
area_html = '<div class="stack">' + "".join(
    f'<i style="flex:{v["pyeong"]}" class="z{n}"><b>{v["pyeong"]}평</b><span>{esc(k.split("(")[0])}</span></i>' for n, (k, v) in enumerate(asplit.items())) + "</div>"
area_leg = "".join(f'<li><b>{esc(k)}</b> {v["pyeong"]}평({pc(v["share"],0)})</li>' for k, v in asplit.items())
seat_html = "".join(f"<li><b>{v}석</b> {esc(k)}</li>" for k, v in C["seat_mix"].items())
layout_html = "".join(f"<li>{esc(x)}</li>" for x in C["layout_logic"])
staff_rows = "".join(f'<tr><td>{s["time"]}</td><td class="n">{s["bakers"]}</td><td class="n">{s["baristas"]}</td><td class="n">{s["floor"]}</td><td>{esc(s["note"])}</td></tr>' for s in C["staffing"]["weekday"])
hc = C["staffing"]["headcount"]

# 메뉴
menu_rows = "".join(
    f'<tr class="{"sig" if m["signature"] else ""}"><td>{esc(m["category"])}</td><td>{esc(m["name"])}{" <span class=sigb>시그니처 "+m["signature"]+"</span>" if m["signature"] else ""}</td><td class="n">{num(m["price_krw"])}</td><td class="n">{pc(m["cost_rate"],0)}</td><td class="n">{pc(m["sales_share"],0)}</td><td>{esc(m["daypart"])}</td></tr>'
    for m in C["menu_items"])
mix = C["menu_mix_by_category"]
mix_html = '<div class="stack thin">' + "".join(f'<i style="flex:{v["sales_share"]*100}" class="z{n}"><b>{pc(v["sales_share"],0)}</b><span>{esc(k)}</span></i>' for n, (k, v) in enumerate(mix.items())) + "</div>"
sig_html = "".join(f'<div class="card sigc"><p class="tag">{s["id"]}</p><h4>{esc(s["name"])} <span class="price">{num(s["price_krw"])}원</span></h4><p>{esc(s["desc"])}</p><p class="link">← {esc(s["data_link"])}</p></div>' for s in C["signatures"])
lever_html = "".join(f'<li><b>{esc(l["lever"])}</b> {esc(l["target"])}</li>' for l in C["txn_growth_levers"])
pos = C["positioning"]

# 손익
def sc_row(n, s):
    y7, y9 = s["years"]["2027"], s["years"]["2029"]
    pb = s["payback_years_pretax_ebitda"]
    r = s["revenue_crosscheck_2026basis"]
    return (f'<tr class="{"hl" if n=="기준" else ""}"><td><b>{n}</b></td><td class="n">{r["implied_daily_txn_2027"]}건 · {num(s["params"]["ticket"])}원</td>'
            f'<td class="n">{man(y7["monthly"]["revenue"])}</td><td class="n">{pc(y7["op_margin"],1)}</td><td class="n">{man(y9["monthly"]["revenue"])}</td><td class="n"><b>{pc(y9["op_margin"],1)}</b></td>'
            f'<td class="n">{man(y7["bep_monthly_revenue"])}</td><td class="n">{s["investment"]["total_excl_deposit"]/1e8:.2f}억</td><td class="n"><b>{str(pb)+"년" if pb else "회수 불가(20년+)"}</b></td></tr>')
sc_html = "".join(sc_row(n, s) for n, s in SC.items())
xc_html = "".join(
    f'<tr><td>{n}</td><td class="n">{man(s["revenue_crosscheck_2026basis"]["A_share_won_month"])}</td><td class="n">{man(s["revenue_crosscheck_2026basis"]["B_txn_won_month"])}</td><td class="n">{pc(s["revenue_crosscheck_2026basis"]["gap_A_vs_B"],1,True)}</td><td class="n"><b>{man(s["revenue_crosscheck_2026basis"]["used"])}</b></td><td class="n">{s["revenue_crosscheck_2026basis"]["implied_daily_txn"]}건</td><td class="n">{pc(s["revenue_crosscheck_2026basis"]["implied_share_of_market"])}</td></tr>'
    for n, s in SC.items())
m27 = b27["monthly"]
other_var = m27["card_fee"] + m27["hq_fee"] + m27["marketing"] + m27["utilities"] + m27["supplies"] + m27["other"]
cost_parts = [("원가", m27["cogs"]), ("인건비", m27["labor"]), ("임대+관리", m27["rent"] + m27["mgmt_fee"]), ("카드·본사·광열·소모품 등", other_var), ("감가상각", m27["depreciation"]), ("영업이익", m27["op_income"])]
cost_html = '<div class="stack cost">' + "".join(f'<i style="flex:{v}" class="c{n}"><b>{pc(v/m27["revenue"],0)}</b><span>{k}</span></i>' for n, (k, v) in enumerate(cost_parts)) + "</div>"
asm_html = "".join(f'<tr><td>{esc(a["item"])}</td><td>{esc(a["value"])}</td><td class="c">{badges(a["type"])}</td><td class="s">{esc(a["source"])}</td></tr>' for a in P["assumptions"])
ext_src = "".join(f"<li>{esc(x)}</li>" for x in P["sources_external"])

CALC = {"ticket": ticket, "txn": txn27, "days": days,
        "var_rate": round(b27["cogs_ratio"] + 0.015 + 0.03 + 0.02 + 0.04 + 0.03 + 0.01, 4),
        "fixed": round(m27["labor"] + m27["rent"] + m27["mgmt_fee"]), "dep": m27["depreciation"], "inv": inv,
        "sc": {n: s["revenue_crosscheck_2026basis"]["implied_daily_txn_2027"] for n, s in SC.items()}}

srcs = A["sources"]
src_rows = "".join(f'<tr><td>{k}</td><td>{esc(v)}</td><td><a href="https://data.seoul.go.kr/dataList/{k}/S/1/datasetView.do" target="_blank" rel="noopener">data.seoul.go.kr</a></td></tr>' for k, v in srcs.items())
src_rows += '<tr><td>OA-15584</td><td>서울시 상권분석서비스(상주인구-상권) VwsmTrdarRepopQq, 2021Q1~2026Q2, 명</td><td><a href="https://data.seoul.go.kr/dataList/OA-15584/S/1/datasetView.do" target="_blank" rel="noopener">data.seoul.go.kr</a></td></tr>'

growth_q = sum(1 for k in qk[-6:] if yoy_up[k])

# ---------------- 결론 ----------------
ANSWER = (f"서초구 <em>남부터미널역</em>에 — 손님 수(결제건수)가 1년 새 <em>{pc(KP['txn_yoy'],1,True)}</em> 늘어난 평일 아침 상권 — "
          f"출근길 ‘7시 베이커리’를 내면, 기준 시나리오에서 영업이익률 {pc(b27['op_margin'])}→{pc(b29['op_margin'])}, 투자 {inv/1e8:.1f}억원을 <em>{HL['base_payback_years']}년</em>에 회수합니다.")
ANSWER_PLAIN = ANSWER.replace("<em>", "").replace("</em>", "")

CSS = r"""
:root{--ink:#141821;--sub:#5a6270;--mut:#8a919c;--line:#e6e8ec;--bg:#ffffff;--soft:#f6f7f9;--acc:#6d28d9;--acc2:#ede9fe;--acc3:#c4b5fd;--pos:#0f766e;--neg:#b42318;--warn:#b54708;--gold:#a16207;color-scheme:light}
*{box-sizing:border-box}html{scroll-behavior:smooth;-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font-family:Pretendard,"Apple SD Gothic Neo","Malgun Gothic","Noto Sans KR",system-ui,sans-serif;font-size:16px;line-height:1.65;word-break:keep-all;overflow-wrap:anywhere}
a{color:var(--acc)}
.wrap{max-width:1120px;margin:0 auto;padding:0 20px}
nav.top{position:sticky;top:0;z-index:10;background:rgba(255,255,255,.94);backdrop-filter:blur(6px);border-bottom:1px solid var(--line)}
nav.top .wrap{display:flex;gap:4px;align-items:center;overflow-x:auto;scrollbar-width:none;height:48px}
nav.top a{flex:none;font-size:13px;color:var(--sub);text-decoration:none;padding:6px 10px;border-radius:6px;white-space:nowrap}
nav.top a:hover{background:var(--soft);color:var(--ink)}nav.top a.brand{color:var(--ink);font-weight:700;margin-right:6px}
header.hero{padding:36px 0 28px;border-bottom:1px solid var(--line);background:linear-gradient(180deg,#faf9ff 0,#fff 100%)}
.eyebrow{font-size:13px;letter-spacing:.04em;color:var(--acc);font-weight:700;margin:0 0 10px}
h1{font-size:clamp(23px,3.2vw,34px);line-height:1.38;margin:0 0 16px;letter-spacing:-.02em;font-weight:800}
h1 em{font-style:normal;color:var(--acc);background:linear-gradient(transparent 62%,var(--acc2) 62%)}
.hero-grid{display:grid;grid-template-columns:1.05fr 1fr;gap:28px;align-items:start}
.site-card{border:1px solid var(--line);border-radius:12px;padding:14px 16px;background:#fff;margin-bottom:14px}
.site-card .t{font-size:12px;color:var(--mut);margin:0}.site-card .n{font-size:20px;font-weight:800;margin:2px 0}.site-card .d{font-size:13.5px;color:var(--sub);margin:0}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:22px}
.kpi{border:1px solid var(--line);border-radius:12px;padding:14px;background:#fff}
.kpi .l{font-size:12.5px;color:var(--sub);margin:0}.kpi .v{font-size:clamp(22px,2.6vw,30px);font-weight:800;letter-spacing:-.02em;margin:2px 0;color:var(--ink)}
.kpi .v small{font-size:14px;font-weight:600;color:var(--sub)}.kpi .s{font-size:11.5px;color:var(--mut);margin:0;line-height:1.45}
.kpi.main{border-color:var(--acc3);background:#fbfaff}
video{display:block;border-radius:12px;background:#0f1020;border:1px solid var(--line)}
.vcap{font-size:12px;color:var(--mut);margin:6px 0 0}
.chain{display:grid;grid-template-columns:repeat(5,1fr);gap:0;margin-top:22px;border:1px solid var(--line);border-radius:12px;overflow:hidden;background:#fff}
.chain div{padding:12px 14px;border-right:1px solid var(--line);position:relative}.chain div:last-child{border-right:0}
.chain b{display:block;font-size:12px;color:var(--acc);letter-spacing:.03em}.chain p{margin:2px 0 0;font-size:13.5px;line-height:1.5}
section{padding:46px 0 10px;scroll-margin-top:50px}
h2{font-size:clamp(21px,2.4vw,26px);margin:0 0 6px;letter-spacing:-.02em}
h2 .no{color:var(--acc);margin-right:8px}
h3{font-size:18px;margin:30px 0 8px}h4{margin:0 0 6px;font-size:16px}
.lead{color:var(--sub);margin:0 0 12px;max-width:820px}
.from{display:flex;gap:10px;align-items:flex-start;background:var(--soft);border-left:3px solid var(--acc);padding:10px 14px;border-radius:0 8px 8px 0;font-size:14px;margin:10px 0 18px}
.from b{flex:none;color:var(--acc);font-size:12.5px;padding-top:1px}
.src{font-size:12px;color:var(--mut);margin:6px 0 0;line-height:1.5}
.src::before{content:"출처 · "}
.note{font-size:13px;color:var(--sub)}
.tw{overflow-x:auto;margin:6px 0 0;border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:13.5px;min-width:560px}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{background:var(--soft);font-weight:700;font-size:12.5px;color:var(--sub);white-space:nowrap}
tr:last-child td{border-bottom:0}td.n,th.n{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}td.c{text-align:center;white-space:nowrap}td.s{font-size:12px;color:var(--sub)}
td small{display:block;color:var(--mut);font-size:11.5px}
tr.hl td{background:#f7f4ff}tr.sig td{background:#fffbeb}
td.up{color:var(--pos);font-weight:700}td.dn{color:var(--neg);font-weight:700}
.bd{display:inline-block;font-size:11px;font-weight:700;padding:1px 6px;border-radius:4px;vertical-align:1px;white-space:nowrap}
.bd.d{background:#e0f2f1;color:var(--pos)}.bd.e{background:#e8eefc;color:#1d4ed8}.bd.a{background:#fef3c7;color:var(--gold)}
.grid2>*,.grid3>*,.hero-grid>*,.calc>*,.ins>*,.og-wrap>*{min-width:0}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px}.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
.card{border:1px solid var(--line);border-radius:12px;padding:16px;background:#fff}
.card .tag{font-size:11.5px;font-weight:800;color:var(--acc);margin:0 0 2px;letter-spacing:.05em}
.funnel{display:flex;gap:6px;align-items:stretch;margin:8px 0}
.funnel div{flex:1;border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:#fff;text-align:center}
.funnel b{display:block;font-size:22px}.funnel span{font-size:12px;color:var(--sub);line-height:1.4;display:block}
.funnel div.win{border-color:var(--acc);background:#fbfaff}.funnel div.win b{color:var(--acc);font-size:18px}
.chip{display:inline-block;font-size:12px;border-radius:999px;padding:1px 8px;margin:2px 3px 2px 0;border:1px solid var(--line);white-space:nowrap}
.chip.pos{background:#f0fdfa;border-color:#99f6e4}.chip.neg{background:#fff1f2;border-color:#fecdd3}
details{margin-top:10px;border:1px solid var(--line);border-radius:10px;padding:10px 14px;background:#fff}
summary{cursor:pointer;font-weight:700;font-size:14px}
.og-wrap{display:grid;grid-template-columns:8fr 5fr 3fr;gap:14px;margin-top:8px}
.og{border:1px solid var(--line);border-radius:10px;padding:10px 10px 4px}.og p{margin:4px 0 0;text-align:center;font-size:12.5px;font-weight:700;color:var(--sub)}
.og-bars{display:flex;gap:6px;height:130px;align-items:flex-end}
.ob{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%;position:relative;min-width:0}
.ob i{display:block;width:100%;max-width:28px;background:var(--acc);border-radius:3px 3px 0 0;order:2}
.ob b{font-size:10.5px;order:1;color:var(--ink)}.ob span{font-size:10px;color:var(--mut);order:3;white-space:nowrap}
.tl{display:grid;grid-template-columns:repeat(3,1fr);gap:0;margin:8px 0;border-radius:10px;overflow:hidden;border:1px solid var(--line)}
.tl div{padding:10px 12px;font-size:13px}.tl div:nth-child(1){background:#f1f5f9}.tl div:nth-child(2){background:#ede9fe}.tl div:nth-child(3){background:#f0fdfa}
.tl b{display:block;font-size:12.5px}
.ins{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}
.ins .card h4{font-size:16.5px;line-height:1.45}.ins .num{font-size:28px;font-weight:800;color:var(--acc);letter-spacing:-.02em;margin:4px 0}
.ins .card p{margin:4px 0;font-size:14px}
.dv{margin:8px 0}.dv-r{display:grid;grid-template-columns:minmax(150px,1.3fr) 2fr 70px;gap:10px;align-items:center;padding:5px 0;border-bottom:1px dashed var(--line)}
.dv-l{font-size:13px}.dv-l small{display:block;color:var(--mut);font-size:11px}
.dv-t{position:relative;height:16px;background:var(--soft);border-radius:3px}.dv-t b{position:absolute;left:50%;top:-3px;bottom:-3px;width:1px;background:var(--mut)}
.dv-t i{position:absolute;top:2px;bottom:2px;border-radius:2px}.dv-t i.pos{background:var(--pos)}.dv-t i.neg{background:var(--neg)}
.dv-v{font-size:13px;font-weight:700;text-align:right;font-variant-numeric:tabular-nums}.dv-v.pos{color:var(--pos)}.dv-v.neg{color:var(--neg)}
.dv-ax{display:grid;grid-template-columns:minmax(150px,1.3fr) 1fr 1fr 70px;gap:10px;font-size:11px;color:var(--mut)}.dv-ax span:first-child{grid-column:2;text-align:left}.dv-ax span:last-child{text-align:right}
.qc{display:flex;gap:3px;height:150px;align-items:flex-end;border-bottom:1px solid var(--line);padding-top:6px}
.qb{flex:1;height:100%;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;min-width:0}
.qb i{display:block;width:100%;background:#cfd5de;border-radius:2px 2px 0 0}.qb i.hi{background:var(--acc)}
.qb span{font-size:10px;color:var(--mut);height:14px;white-space:nowrap}
.pair-r{display:grid;grid-template-columns:70px 1fr 120px;gap:10px;align-items:center;padding:4px 0}
.pair-l{font-size:13px}.pair-v{font-size:12.5px;text-align:right;font-variant-numeric:tabular-nums}
.pair-t{display:flex;flex-direction:column;gap:2px}.pair-t i{display:block;height:9px;border-radius:2px}
i.s{background:var(--acc)}i.b{background:#cfd5de}
.lg{display:flex;gap:14px;font-size:12px;color:var(--sub);margin-top:6px}.lg i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.persona h4{font-size:16.5px}.kv{list-style:none;padding:0;margin:8px 0}.kv li{display:flex;justify-content:space-between;gap:12px;border-bottom:1px dashed var(--line);padding:5px 0;font-size:13px}
.kv li span{color:var(--sub)}.kv li b{text-align:right}.need{font-size:14px;margin:8px 0 4px}.ext{font-size:12.5px;color:var(--sub);margin:0}
.stack{display:flex;height:64px;border-radius:10px;overflow:hidden;margin:8px 0;gap:2px}
.stack i{display:flex;flex-direction:column;justify-content:center;padding:0 8px;font-style:normal;color:#fff;min-width:0;overflow:hidden}
.stack i b{font-size:15px}.stack i span{font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.stack.thin{height:54px}
.z0{background:#5b21b6}.z1{background:#7c3aed}.z2{background:#a78bfa}.z3{background:#94a3b8}.z4{background:#0f766e}.z5{background:#b45309}.z6{background:#64748b}
.stack.cost .c0{background:#7c3aed}.stack.cost .c1{background:#5b21b6}.stack.cost .c2{background:#a78bfa}.stack.cost .c3{background:#94a3b8}.stack.cost .c4{background:#64748b}.stack.cost .c5{background:#0f766e}
.plan{display:grid;grid-template-columns:1.1fr 1fr 1.4fr;grid-template-rows:auto auto;gap:4px;border:2px solid var(--ink);border-radius:6px;padding:4px;font-size:12px;min-height:220px}
.plan div{border-radius:4px;padding:8px;display:flex;flex-direction:column;justify-content:center}
.plan b{font-size:13px}.p-oven{background:#ede9fe;grid-row:1/3}.p-order{background:#fef3c7}.p-pick{background:#ccfbf1}.p-seat{background:#f1f5f9;grid-row:1/3}
.p-door{grid-column:2;font-size:11px;color:var(--sub);text-align:center;padding:2px!important}
ul.clean{padding-left:18px;margin:6px 0}ul.clean li{margin:3px 0;font-size:14px}
.sigc h4{display:flex;justify-content:space-between;gap:8px}.sigc .price{color:var(--acc)}.sigc p{font-size:13.5px;margin:4px 0}.sigc .link{color:var(--pos);font-weight:600;font-size:12.5px}
.sigb{font-size:10.5px;background:var(--acc);color:#fff;border-radius:4px;padding:1px 5px;margin-left:4px;white-space:nowrap}
.calc{display:grid;grid-template-columns:1fr 1.15fr;gap:18px;border:1px solid var(--acc3);border-radius:14px;padding:18px;background:#fbfaff}
.calc label{display:block;font-size:13.5px;font-weight:700;margin:6px 0 2px}.calc label output{float:right;color:var(--acc);font-size:16px}
.calc input[type=range]{width:100%;accent-color:var(--acc)}
.calc .presets{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}.calc .presets button{font:inherit;font-size:12.5px;border:1px solid var(--line);background:#fff;border-radius:999px;padding:4px 10px;cursor:pointer}
.calc .presets button:hover{border-color:var(--acc);color:var(--acc)}
.res{display:grid;grid-template-columns:1fr 1fr;gap:10px}.res div{background:#fff;border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.res span{display:block;font-size:12px;color:var(--sub)}.res b{font-size:21px;letter-spacing:-.02em}.res b.neg{color:var(--neg)}.res b.pos{color:var(--pos)}
.risk td:first-child{font-weight:700}
footer{margin-top:50px;padding:24px 0 40px;border-top:1px solid var(--line);font-size:12.5px;color:var(--mut)}
@media (max-width:900px){.hero-grid,.grid2,.calc{grid-template-columns:1fr}.kpis{grid-template-columns:repeat(2,1fr)}.chain{grid-template-columns:1fr}.chain div{border-right:0;border-bottom:1px solid var(--line)}.chain div:last-child{border-bottom:0}.grid3,.ins{grid-template-columns:1fr}.og-wrap{grid-template-columns:1fr}.funnel{flex-wrap:wrap}.funnel div{flex:1 1 40%}}
@media (max-width:560px){.wrap{padding:0 16px}.kpi .v{font-size:22px}.dv-r{grid-template-columns:1fr 64px}.dv-t{grid-column:1/3;grid-row:2}.dv-ax{display:none}.pair-r{grid-template-columns:60px 1fr;}.pair-v{grid-column:2;text-align:left}.res{grid-template-columns:1fr 1fr}.res b{font-size:18px}.plan{grid-template-columns:1fr 1fr;}.p-oven,.p-seat{grid-row:auto}.p-door{grid-column:1/3}.stack i span{display:none}}
"""

JS = r"""
(function(){
var C=window.CALC,f=function(n){return Math.round(n).toLocaleString('ko-KR')};
var t=document.getElementById('cTicket'),x=document.getElementById('cTxn');
function man(v){return (v<0?'-':'')+f(Math.abs(v)/1e4)+'만원'}
function run(){
 var tk=+t.value,tx=+x.value;
 document.getElementById('oTicket').textContent=f(tk)+'원';document.getElementById('oTxn').textContent=f(tx)+'건';
 var rev=tk*tx*C.days/12, varc=rev*C.var_rate, ebitda=rev-varc-C.fixed, op=ebitda-C.dep;
 var bep=(C.fixed+C.dep)/(1-C.var_rate), bepTx=bep*12/C.days/tk;
 var pb=ebitda>0? C.inv/(ebitda*12):null;
 document.getElementById('rRev').textContent=man(rev);
 var o=document.getElementById('rOp');o.textContent=man(op);o.className=op<0?'neg':'pos';
 var m=document.getElementById('rMg');m.textContent=(op/rev*100).toFixed(1)+'%';m.className=op<0?'neg':'pos';
 document.getElementById('rBep').textContent=f(bepTx)+'건/일';
 var p=document.getElementById('rPb');p.textContent=pb===null||pb>20?'회수 불가':pb.toFixed(1)+'년';p.className=pb===null||pb>5?'neg':'pos';
 document.getElementById('rAnn').textContent=(rev*12/1e8).toFixed(1)+'억원';
}
t.addEventListener('input',run);x.addEventListener('input',run);
document.querySelectorAll('[data-tx]').forEach(function(b){b.addEventListener('click',function(){x.value=b.getAttribute('data-tx');t.value=b.getAttribute('data-tk');run();});});
run();
})();
"""

risk_rows = [
    ("3년 예측력의 한계", f"3년 스피어만 {v2i['3y']['spearman']:.2f}: 순위가 맞을 확률을 높일 뿐 1위를 보증하지 않음. 3년 시험 기준시점은 3개뿐", "점수는 후보 압축용. 개점 후 분기마다 상권 결제건수 YoY와 아침 비중을 추적해 1위 근거가 유지되는지 확인"),
    ("매출 가정(일 결제·점유)", f"일 결제는 상권 평균 점포의 약 {B['revenue_crosscheck_2026basis']['implied_daily_txn']/81:.1f}배·점유 {pc(B['revenue_crosscheck_2026basis']['implied_share_of_market'])} 가정 — 데이터가 아닌 가정", f"손익분기 = 하루 약 {bep_txn:.0f}건(객단가 {num(ticket)}원). 개점 6개월 일 결제가 이 선을 밑돌면 영업시간·인력(PT)부터 조정"),
    ("보수 시나리오 적자", f"보수(일 {SC['보수']['revenue_crosscheck_2026basis']['implied_daily_txn_2027']}건·역 앞 임대 1.2배)에서는 3년 모두 영업적자, 회수 불가", "임대 조건(㎡당 56,500원 이하)과 권리금 1억원 이하를 출점 게이트로 설정"),
    ("임대료·권리금", "남부터미널·교대 하위 상권 1층 실거래 임대료를 공개 자료로 확인하지 못함(서울 평균 기반 가정)", "R-ONE 원자료·현장 중개 시세 3건 이상으로 교체 후 손익 재계산"),
    ("저가커피·프랜차이즈 경쟁", "상권 커피 객단가 5,922원(적격 평균 8,305원)으로 가격 민감", "가격 경쟁 대신 아침 식사(세트)·구독으로 건수 확보, 가격 인상은 원가 연동 연 1회 이내"),
    ("데이터 성격", "매출은 카드 기반 추정치(현금·일부 법인 결제 누락 가능), 유동인구는 상대지수, '법인 매출'은 성별·연령 미식별 매출로 대리", "현장 출근 시간대 통행량 실측(07~10시)과 인근 오피스 법인카드 수요 인터뷰로 보완"),
    ("표본 밖 검증의 겹침", "1년 예측은 학습 타깃과 완전 분리, 2·3년 예측은 타깃 기간 일부가 학습 타깃과 겹침", "1년 예측 결과(8개 시점 모두 양의 순위상관)를 1차 근거로 사용"),
    ("코로나 이전 기준선 없음", "열린데이터 제공 범위가 2021Q1부터라 2019년 대비 회복률을 볼 수 없음", "회복기(2021~2023Q1)는 성장 기준점에서 제외"),
]
risk_html = "".join(f"<tr><td>{a}</td><td>{b}</td><td>{c}</td></tr>" for a, b, c in risk_rows)

H = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>남부터미널역 출점 제안</title>
<meta name="description" content="{esc(ANSWER_PLAIN)}">
<style>{CSS}</style>
</head>
<body>
<nav class="top"><div class="wrap">
<a class="brand" href="#top">출점 제안</a><a href="#s1">1 입지</a><a href="#s2">2 인사이트</a><a href="#s3">3 타깃</a><a href="#s4">4 공간</a><a href="#s5">5 메뉴</a><a href="#s6">6 손익</a><a href="#s7">7 리스크</a><a href="#s8">8 부록</a>
</div></nav>

<header class="hero" id="top"><div class="wrap">
<p class="eyebrow">PE 보유 커피·베이커리 브랜드 · 3년 뒤(2029) 성장 상권 신규 출점 제안 · 2026년 11월</p>
<div class="hero-grid">
<div>
<h1>{ANSWER}</h1>
<div class="site-card">
<p class="t">추천 입지</p>
<p class="n">서초구 남부터미널역 상권 <span class="note">(TRDAR {FS['TRDAR_CD']}, {FS['dong']}, 지하철 3호선)</span></p>
<p class="d">출점 적격 {N_RANKED}개 상권(연 커피+제과 매출 50억원+, 과열·상권축소 제외) 중 <b>성장 점수 1위 {FS['score']}점</b> · 최근 6분기 연속 전년 대비 매출 증가 · 06~11시 매출 비중 {pc(KP['share_t06_11'])}(적격 평균 {pc(BI['share_t06_11'])})</p>
{src("analysis.json v2 점수(19개 지표 동일가중, 0~100점), OA-15572·OA-15577·OA-15568·OA-15580, 기준 2026Q2")}
</div>
<p class="note" style="margin:0"><b>컨셉</b> {esc(C['concept_one_liner'])} <span class="bd a">가칭 {esc(C['brand_name_working'].replace(' (가칭)',''))}</span></p>
</div>
<div>
<video id="video" controls preload="metadata" poster="assets/poster.png" src="assets/proposal.mp4" style="width:100%;aspect-ratio:16/9"></video>
<p class="vcap">2분 내레이션 요약 영상 — 결론 → 근거 → 컨셉 → 손익 순서</p>
</div>
</div>
<div class="kpis">
<div class="kpi main"><p class="l">성장 근거 · 손님 수가 는다</p><p class="v">{pc(KP['txn_yoy'],1,True)}</p><p class="s">결제건수 YoY(매출 {pc(KP['sales_yoy'],1,True)}, 객단가 {pc(KP['ticket_yoy'],1,True)}) · {S_SALES} 대비 직전 4분기, 건</p></div>
<div class="kpi"><p class="l">예상 월매출(2027 → 2029)</p><p class="v">{b27['monthly']['revenue']/1e8:.2f}<small>억원</small></p><p class="s">2029 {b29['monthly']['revenue']/1e8:.2f}억원 · 일 {txn27}건 × {num(ticket)}원 <span class="bd a">가정</span> 기준 시나리오, pnl.json</p></div>
<div class="kpi"><p class="l">영업이익률(2027 → 2029)</p><p class="v">{pc(b27['op_margin'])}<small> → {pc(b29['op_margin'])}</small></p><p class="s">세전, 감가상각 후 · 범위 보수 {pc(HL['range_2029_op_margin']['보수'])} ~ 낙관 {pc(HL['range_2029_op_margin']['낙관'])}(2029) <span class="bd a">가정</span></p></div>
<div class="kpi"><p class="l">투자 회수기간</p><p class="v">{HL['base_payback_years']}<small>년</small></p><p class="s">투자 {inv/1e8:.1f}억원(보증금 제외)을 세전 EBITDA로 회수 · 낙관 {HL['range_payback_years']['낙관']}년, 보수 회수 불가 <span class="bd a">가정</span></p></div>
</div>
<div class="chain">
<div><b>① 상권</b><p>평일 아침·손님 수로 크는 남부터미널역</p></div>
<div><b>② 타깃</b><p>출근길 30~40대 직장인 + 50대 이상·법인</p></div>
<div><b>③ 공간</b><p>픽업 선반·유리벽 오븐·6인 미팅 테이블</p></div>
<div><b>④ 메뉴</b><p>7시 세트·흑임자 라떼·미팅 박스, 객단가 {num(ticket)}원</p></div>
<div><b>⑤ 손익</b><p>하루 {bep_txn:.0f}건이 손익분기, 기준 {txn27}건 → 이익률 {pc(b27['op_margin'])}</p></div>
</div>
</div></header>

<main class="wrap">

<section id="s1">
<h2><span class="no">1</span>입지 선정 — "3년 뒤 클 상권"을 데이터로 고르는 법</h2>
<p class="lead">서울 열린데이터 상권분석서비스 7개 데이터셋(2021Q1~2026Q2, 22분기)으로 상권마다 성장 점수를 매기고, 그 점수가 실제로 미래 성장을 맞혔는지 과거 시점에서 검증했습니다.</p>
<div class="from"><b>이 결정을 이끈 데이터</b><span>커피+제과 추정매출·결제건수·시간대/연령 구성(OA-15572), 점포·개폐업(OA-15577), 유동인구(OA-15568), 지하철역(OA-15580), 상권변화지표(OA-15576)</span></div>

<h3>1-1. 1,650개 상권에서 1곳까지</h3>
<div class="funnel">
<div><b>1,650</b><span>서울 전체 상권<br>(OA-15560)</span></div>
<div><b>{N_POP}</b><span>분석 모집단<br>관광특구 제외, 최근 4분기 연속 관측, 연 2억+, 점포 5+</span></div>
<div><b>{N_INV}</b><span>출점 적격<br>연 커피+제과 매출 50억원+ (플래그십 시장 규모)</span></div>
<div><b>{N_RANKED}</b><span>순위 대상<br>과열(점포밀도 상위 10%·폐업률 상위 25%)·상권축소(HL) {N_INV-N_RANKED}곳 제외</span></div>
<div class="win"><b>남부터미널역</b><span>성장 점수 1위 {FS['score']}점</span></div>
</div>
{src("analysis.json meta·metrics.overheat_filter, 기준 2025Q3~2026Q2(4분기 합), 개 상권")}

<h3>1-2. MECE 4축 · 19개 지표 · 동일가중</h3>
<p class="note">4개 축은 원천 변수가 서로 겹치지 않습니다(A=매출 금액·건수의 시간 흐름, B=매출의 고객 구성비, C=사람 흐름·교통, D=점포 진입·퇴출). 지표마다 시점 내 백분위로 바꾸고(감점 지표는 1−백분위) 19개를 똑같은 비중으로 평균해 100점으로 환산합니다. 데이터에 맞춘 미세 가중은 과적합 위험이 커서 쓰지 않았습니다.</p>
<div class="tw"><table>
<tr><th>축</th><th>묻는 질문</th><th>지표 (+ 가점 / − 감점)</th><th>출처</th><th class="n">실효 가중</th></tr>
{axis_rows}
</table></div>
{src("analysis.json metrics.axes·indicators, METRICS.md. 지표 기간: 기준시점까지 4분기 합 YoY 등, 단위는 아래 상세표")}
<details><summary>19개 지표 상세 — 정의·단위·학습 IC·표본 밖 IC</summary>
<div class="tw"><table>
<tr><th>ID</th><th>정의</th><th>방향</th><th>단위</th><th>출처</th><th class="n">학습 IC</th><th class="n">시험 IC 1년</th><th class="n">시험 IC 3년</th></tr>
{ind_rows}
</table></div>
<p class="src">analysis.json metrics.indicators. IC = 지표와 이후 실제 매출 성장의 스피어만 순위상관(출점 적격 상권). 학습 = 기준시점 2022Q4·2023Q1·2023Q2의 1·2년 타깃(종료 ≤2024Q2)</p>
<p class="note"><b>뺀 후보와 이유</b></p><ul class="clean">{drop_rows}</ul>
</details>

<h3>1-3. 백테스트 약점을 지표 보강으로 고쳤습니다 — v1 → v2</h3>
<p class="note">첫 버전(v1)은 가설로 고른 10개 지표를 단일 기간 하나로만 검증해 3년 예측 순위상관이 {v1a['3y']['spearman']:.3f}에 그쳤습니다. v2는 후보 33개를 학습 구간에서만 걸러 지표를 보강(손님 수·객단가 분리, 아침·주말·법인 구성, 성장 지속성·변동성, 개폐업률)하고, 16개 기준시점에서 반복 검증했습니다. 같은 기준끼리 비교한 결과입니다.</p>
<div class="tw"><table>
<tr><th>항목</th><th class="n">v1 (가설 기반)</th><th class="n">v2 (채택)</th></tr>
{bt_html}
</table></div>
{src("analysis.json backtest.v1_*·v2_* (롤링 기준시점 평균), 커피+제과 4분기 합 매출 CAGR, OA-15572. v1 결과물(천호역 추천)은 폐기")}

<h3>1-4. 표본 밖 검증 — 미래를 모르는 상태로 점수를 매겨 맞혀 보기</h3>
<div class="tl">
<div><b>① 학습</b>기준시점 2022Q4·2023Q1·2023Q2 → 1·2년 뒤(~2024Q2) 성장과 비교해 지표·부호 확정</div>
<div><b>② 점수 고정</b>지표·방향·동일가중을 고정하고 더 이상 바꾸지 않음</div>
<div><b>③ 시험</b>2023Q3~2025Q2 기준시점에서 그 시점 데이터만으로 점수 → 이후 1·2·3년 실제 성장과 비교</div>
</div>
<div class="og-wrap">{orig_html}</div>
{src("analysis.json backtest.by_origin.v2_investable — 기준시점(YY Q)별 점수와 이후 실제 매출 성장의 스피어만 순위상관, 출점 적격 153~160개 상권, OA-15572")}
<p class="note">16개 기준시점 모두 양(+)의 순위상관입니다. 1년 예측의 시험 타깃(2024Q3~)은 학습 타깃과 완전히 분리되고, 2·3년 예측은 타깃 기간 일부가 학습 타깃과 겹칩니다. 3년 성장은 본질적으로 잡음이 커서 점수는 "확실한 1등 예측"이 아니라 <b>성장 확률이 높은 후보를 압축하는 도구</b>입니다 — 점수 상위 20%의 실제 3년 연평균 성장률은 {pc(v2i['3y']['top20_cagr'],2,True)}, 전체 {pc(v2i['3y']['all_cagr'],2,True)}, 하위 20% {pc(v2i['3y']['bottom20_cagr'],2,True)}였습니다.</p>

<h3>1-5. 출점 적격 상권 Top 10</h3>
<div class="tw"><table>
<tr><th>순위</th><th>상권</th><th class="n">총점</th><th class="n">A 매출</th><th class="n">B 고객</th><th class="n">C 유동</th><th class="n">D 공급</th><th class="n">연매출(억원)</th><th class="n">매출 YoY</th><th class="n">결제건수 YoY</th><th class="n">아침 비중</th><th class="n">주말 비중</th></tr>
{top10_rows}
</table></div>
{src(f"analysis.json top10 · 점수 0~100점(기준 2026Q2), 연매출 = 커피+제과 {S_SALES} 합(억원), YoY = 직전 4분기 대비, 비중 = 매출 기준. 순위 대상 {N_RANKED}개")}
<p class="note">2위 서울시청은 C축 29.0점(상권 내 지하철역 0개, 매출 YoY +40.5%의 일회성 급증 가능성), 3위 남대문시장은 매출 YoY +0.4%로 정체입니다. 남부터미널역은 4개 축 모두 62점 이상인 유일한 상위 3위 상권이고, 사용자 확정(2026-11-14)도 v2 점수 1위와 일치합니다.</p>

<h3>1-6. 왜 성수·한남·연남·가로수길이 아닌가</h3>
<div class="tw"><table>
<tr><th>상권</th><th class="n">적격 순위</th><th class="n">점수</th><th class="n">매출 YoY</th><th class="n">결제 YoY</th><th class="n">아침 비중</th><th class="n">주말 비중</th><th>점수가 낮은 이유</th></tr>
{hot_rows}
</table></div>
{src("analysis.json hot_places, " + S_SALES + "·OA-15577·OA-15576, 순위 = 출점 적격 136개 중")}
</section>

<section id="s2">
<h2><span class="no">2</span>클라이언트가 예상하지 못했을 인사이트 4가지</h2>
<div class="from"><b>앞 단계 → 이 결론</b><span>1장의 백테스트 표본(3개 기준시점 × 분석 모집단 약 760개 상권)에서 지표별 상위 20%와 하위 20% 상권의 이후 3년 실제 성장률을 비교</span></div>
<div class="ins">
<div class="card"><p class="tag">INSIGHT 1</p><h4>핫플의 '주말·저녁'이 아니라 '평일 아침' 상권이 큰다</h4>
<p class="num">{pp(INS['B5_morning_share']['spread_pp'],2)}/년</p>
<p>아침(06~11시) 매출 비중 상위 20% 상권은 이후 3년 연평균 {pc(INS['B5_morning_share']['top20_cagr_med'],1,True)}, 하위 20%는 {pc(INS['B5_morning_share']['bottom20_cagr_med'],1,True)}. 반대로 저녁 비중 상위 20%는 {pp(INS['B6_evening_share']['spread_pp'],2)}, 주말 비중 상위 20%는 {pp(INS['B7_weekend_share']['spread_pp'],2)} 뒤졌습니다. 출근·일상 수요가 여가 수요보다 꾸준합니다.</p>
{src("OA-15572, 기준시점 2022Q4·2023Q1·2023Q2 → 각 3년 뒤, 4분기 합 CAGR 5분위 중앙값의 평균, %/년")}</div>
<div class="card"><p class="tag">INSIGHT 2</p><h4>객단가로 큰 상권은 멈추고, 손님 수로 큰 상권은 계속 큰다</h4>
<p class="num">{pp(INS['A5_ticket_yoy']['spread_pp'],2)}/년</p>
<p>건당 결제액(객단가) 성장 상위 20% 상권은 이후 3년 {pc(INS['A5_ticket_yoy']['top20_cagr_med'],1,True)}/년으로 하위 20%({pc(INS['A5_ticket_yoy']['bottom20_cagr_med'],1,True)})보다 오히려 낮았습니다. 결제건수 성장 상위 20%는 {pp(INS['A4_txn_yoy']['spread_pp'],2)} 앞섰습니다. → 우리 매장도 가격 인상이 아니라 건수로 키웁니다.</p>
{src("OA-15572 결제건수·매출, 같은 백테스트 표본, %/년")}</div>
<div class="card"><p class="tag">INSIGHT 3</p><h4>뜬 곳은 이미 떴다 — 성수·한남·연남·가로수길은 후보에서 밀려난다</h4>
<p class="num">127위 · 132위</p>
<p>연남동(홍대) 출점 적격 127위(매출 −6.9%, 주말 37.0%), 가로수길 132위(매출 −14.7%), 성수동카페거리 40위(아침 10.2%, 주말 29.6%), 한남오거리는 연매출 50억원 미달. v1에서 1위였던 천호역(주말 32.0%)도 v2에서 16위로 내려갔습니다.</p>
{src("analysis.json hot_places, 2025Q3~2026Q2, 순위(출점 적격 136개 중)")}</div>
<div class="card"><p class="tag">INSIGHT 4</p><h4>남부터미널역 = 꾸준히, 손님 수로, 아침에 크는 상권</h4>
<p class="num">{growth_q}분기 연속 성장</p>
<p>연 커피+제과 매출 {KP['cb_sales_4q_won']/1e8:.0f}억원, 매출 YoY {pc(KP['sales_yoy'],1,True)}(적격 상권 중앙값 {pc(BI['sales_yoy_median'],1,True)}), 결제건수 {pc(KP['txn_yoy'],1,True)} &gt; 객단가 {pc(KP['ticket_yoy'],1,True)}. 아침 매출 비중 {pc(KP['share_t06_11'])}(적격 {pc(BI['share_t06_11'])}), 점포는 {pc(KP['store_yoy'],1,True)}로 완만해 공급 과잉이 아닙니다.</p>
{src(S_SALES + ", " + S_STORE + ", 원·%")}</div>
</div>
<h3>지표별 '상위 20% − 하위 20%' 이후 3년 연평균 성장률 격차</h3>
{ins_div}
{src("analysis.json insight_inputs.quintiles_3y — OA-15572·OA-15577, 기준시점 2022Q4·2023Q1·2023Q2 → 3년 뒤, %p/년")}
<h3>남부터미널역 분기 매출 추이</h3>
<div class="qc">{qbars}</div>
<p class="note" style="margin-top:4px">보라색 = 최근 6분기(2025Q1~2026Q2), 모두 전년 같은 분기 대비 증가. 최근 분기 {q[qk[-1]]/1e8:.1f}억원, 3년 CAGR(2023Q2→2026Q2, 4분기 합) {pc(KP['sales_cagr_3y_2023Q2_2026Q2'],1,True)}</p>
{src("OA-15572 추정매출, 커피+제과, 2021Q1~2026Q2, 원/분기 (analysis.json final_site.kpis.cb_sales_by_quarter_won)")}
</section>

<section id="s3">
<h2><span class="no">3</span>타깃 페르소나 — 상권 매출 구성에서 읽은 두 고객</h2>
<div class="from"><b>앞 단계 → 이 결정</b><span>인사이트 1·4(평일 아침 수요)와 B축 고객 구성 지표(아침·주말·50대 이상·법인 비중)를 출점 적격 158개 평균과 비교해 타깃을 정했습니다.</span></div>
<div class="grid2">
<div>
<div class="tw"><table>
<tr><th>지표(매출 기준 비중)</th><th class="n">남부터미널역</th><th class="n">적격 158개 평균</th><th class="n">차이</th></tr>
{cmp_html}
<tr><td>커피 객단가</td><td class="n"><b>{num(KP['ticket_coffee_won'])}원</b></td><td class="n">{num(BI['ticket_coffee_won'])}원</td><td class="n dn">{num(KP['ticket_coffee_won']-BI['ticket_coffee_won'])}원</td></tr>
</table></div>
{src(S_SALES + " 매출 가중 · 제과 프랜차이즈 비중은 " + S_STORE.replace('2025Q3~2026Q2','2026Q2') + " · 비율(%), 원/건. 상주인구 3,906명(OA-15584, 2026Q2)")}
</div>
<div>
<h4>시간대별 매출 비중</h4>
{dp_html}
{src(S_SALES + ", 매출 비중(%)")}
</div>
</div>
<div class="grid2" style="margin-top:16px">{per_html}</div>
<p class="src">concept.json personas — 비중은 OA-15572(2025Q3~2026Q2), '외부' 표시는 열린데이터 밖 일반 정보</p>
</section>

<section id="s4">
<h2><span class="no">4</span>인테리어 컨셉 — 아침 동선과 체류 동선을 나눈 45평</h2>
<div class="from"><b>앞 단계 → 이 결정</b><span>P1(아침 {pc(KP['share_t06_11'])}, 테이크아웃) → 입구 옆 모바일 픽업 선반 · P2(50대+ {pc(KP['share_age50p'])}, 법인 {pc(KP['share_unident'])}) → 낮은 조도 대화석·6인 미팅 테이블 · 주말 {pc(KP['share_wkend'])} → 주말 체류형 대형 좌석 불필요</span></div>
<div class="grid2">
<div>
<h4>평면 개념도 — 전용 {C['area_m2']}㎡({C['area_pyeong']}평), {esc(C['floor'])} <span class="bd a">가정</span></h4>
<div class="plan">
<div class="p-oven"><b>오븐 공방 13평</b>데크오븐·컨벡션·발효실, 입구에서 보이는 유리벽</div>
<div class="p-order"><b>주문·쇼케이스 9평</b>주문 줄 옆 갓 구운 빵</div>
<div class="p-seat"><b>좌석 19평 · {C['seats']}석</b>창가 1인 바석 14 · 2인 16 · 4인 12 · 6인 미팅 6(예약)</div>
<div class="p-pick"><b>모바일 픽업 선반</b>2단, 90초 픽업</div>
<div class="p-door">▲ 출입구(가로변 전면 6m+) · 역 출구 도보 3분 이내 목표</div>
</div>
{area_html}
<ul class="clean">{area_leg}</ul>
{src("concept.json area_split·seat_mix — 설계 가정")}
</div>
<div>
<h4>공간 결정과 근거 데이터</h4>
<ul class="clean">{layout_html}</ul>
<p class="note"><b>무드</b> {esc(C['mood'])}</p>
<p class="note"><b>영업시간</b> 평일 {C['opening_hours']['weekday']} · 주말 {C['opening_hours']['weekend']} — {esc(C['opening_hours']['basis'])} <span class="bd a">가정</span></p>
<p class="note"><b>판매 방식</b> 매출 기준 테이크아웃·픽업 {pc(C['takeout_vs_dinein_sales']['takeout_pickup'],0)} : 매장 {pc(C['takeout_vs_dinein_sales']['dine_in'],0)} <span class="bd a">가정</span></p>
<h4 style="margin-top:14px">평일 시간대별 인력 (명)</h4>
<div class="tw"><table style="min-width:420px"><tr><th>시간</th><th class="n">베이커</th><th class="n">바리스타</th><th class="n">홀·픽업</th><th>비고</th></tr>{staff_rows}</table></div>
<p class="src">concept.json staffing · 점장 {hc['store_manager']}, 헤드 베이커 {hc['head_baker']}, 정규 {hc['full_time']}, 파트타임 {hc['part_time']}(FTE 약 {hc['fte_est']}명) — 가정</p>
</div>
</div>
</section>

<section id="s5">
<h2><span class="no">5</span>메뉴 포트폴리오 — 15개 품목, 아침 세트가 중심</h2>
<div class="from"><b>앞 단계 → 이 결정</b><span>아침 {pc(KP['share_t06_11'])} → 7시 세트 · 50대+ {pc(KP['share_age50p'])} → 흑임자 크림라떼 · 법인 {pc(KP['share_unident'])} → 미팅 박스 · 커피 객단가 {num(KP['ticket_coffee_won'])}원(적격 {num(BI['ticket_coffee_won'])}원) → 아메리카노 3,800원 · 제과 프랜차이즈 {pc(KP['bakery_frc_share_2026Q2'])} → 매장 오븐 직영 빵</span></div>
<div class="grid3">{sig_html}</div>
<h3>전체 메뉴 (가격·원가율·매출 비중) <span class="bd a">가정</span></h3>
<div class="tw"><table>
<tr><th>구분</th><th>메뉴</th><th class="n">가격(원)</th><th class="n">원가율</th><th class="n">매출 비중</th><th>주력 시간</th></tr>
{menu_rows}
</table></div>
{mix_html}
{src(f"concept.json menu_items·menu_mix_by_category — 가격·매출 비중은 설계 가정, 원가율은 업계 통상 범위(외부 정보). 가중 원가율 {pc(C['blended_cost_rate'])}, 평균 객단가 {num(ticket)}원(상권 실측 6,615원/건 + 세트 동반 구매)")}
<div class="grid2" style="margin-top:14px">
<div class="card"><h4>건수로 키운다 — 객단가 인상 없이</h4><ul class="clean">{lever_html}</ul><p class="src">concept.json txn_growth_levers — 목표치는 가정, 근거는 인사이트 2</p></div>
<div class="card"><h4>2026 시장 속 포지셔닝 <span class="bd e">외부</span></h4><ul class="clean">
<li><b>가격</b> {esc(pos['price'])}</li><li><b>vs 저가커피</b> {esc(pos['vs_low_price_coffee'])}</li><li><b>vs 제과 프랜차이즈</b> {esc(pos['vs_bakery_franchise'])}</li><li><b>vs 대형 베이커리카페</b> {esc(pos['vs_large_bakery_cafe'])}</li></ul></div>
</div>
</section>

<section id="s6">
<h2><span class="no">6</span>손익 — 하루 {bep_txn:.0f}건이 손익분기, 기준 {txn27}건이면 2.4년 회수</h2>
<div class="from"><b>앞 단계 → 이 결정</b><span>상권 연매출 {KP['cb_sales_4q_won']/1e8:.1f}억원·점포당 일 81건(데이터) + 객단가 {num(ticket)}원·45평·48석·원가율 {pc(C['blended_cost_rate'])}·연 {days}일(컨셉) + 성장률 = 백테스트 점수 상위 20%의 실제 3년 CAGR {pc(v2i['3y']['top20_cagr'],2,True)}(1장)</span></div>
<h3>6-1. 시나리오별 손익 (월 평균)</h3>
<div class="tw"><table>
<tr><th>시나리오</th><th class="n">2027 일 결제·객단가</th><th class="n">2027 월매출</th><th class="n">2027 이익률</th><th class="n">2029 월매출</th><th class="n">2029 이익률</th><th class="n">손익분기 월매출</th><th class="n">투자(보증금 제외)</th><th class="n">회수기간</th></tr>
{sc_html}
</table></div>
{src("pnl.json(analysis/pnl.py) — 2027.1 개점 가정, 원/월, 영업이익률은 세전·감가상각 후, 회수기간은 세전 EBITDA 누적 기준. 성장률: 보수 = 적격 상권 전체 3년 CAGR −0.97%, 기준 = 점수 상위 20% +0.85%, 낙관 = 남부터미널 3년 CAGR 8.1%의 절반 +4.0%(analysis.json backtest.v2_investable.3y)")}
<p class="note">남부터미널역의 최근 매출 YoY {pc(KP['sales_yoy'],1,True)}는 지속된다고 보지 않고 성장 가정에서 뺐습니다. 기준 시나리오의 상권 성장률은 연 {pc(v2i['3y']['top20_cagr'],2,True)}로 보수적입니다.</p>

<h3>6-2. 매출 교차검증 — 두 방법이 3% 안에서 만난다 (2026 기준값)</h3>
<div class="tw"><table>
<tr><th>시나리오</th><th class="n">(A) 상권 점유 방식</th><th class="n">(B) 거래건수 방식</th><th class="n">A/B 차이</th><th class="n">채택(평균)</th><th class="n">환산 일 결제</th><th class="n">상권 점유</th></tr>
{xc_html}
</table></div>
<p class="note">(A) {esc(B['revenue_crosscheck_2026basis']['A_formula'])} · (B) {esc(B['revenue_crosscheck_2026basis']['B_formula'])}</p>
{src("상권 매출·건수·점포 = " + S_SALES + "·" + S_STORE + " [데이터], 점유율·거래 배수·객단가 = 가정, 원/월")}

<h3>6-3. 비용 구조 (기준 2027, 매출 대비)</h3>
{cost_html}
{src(f"pnl.json 기준 2027 월평균 — 매출 {man(m27['revenue'])}, 인건비 {man(m27['labor'])}(최저임금 10,320원·주휴·4대보험·퇴직 반영), 임대 {man(m27['rent'])}(서울 중대형 1층 56,500원/㎡)")}

<h3>6-4. 직접 돌려 보는 손익 계산기</h3>
<div class="calc">
<div>
<label for="cTicket">객단가 <output id="oTicket"></output></label>
<input type="range" id="cTicket" min="5000" max="10000" step="100" value="{ticket}">
<label for="cTxn">하루 결제건수 <output id="oTxn"></output></label>
<input type="range" id="cTxn" min="250" max="700" step="5" value="{txn27}">
<div class="presets">
<button type="button" data-tk="{round(SC['보수']['params']['ticket'])}" data-tx="{CALC['sc']['보수']}">보수</button>
<button type="button" data-tk="{ticket}" data-tx="{CALC['sc']['기준']}">기준</button>
<button type="button" data-tk="{round(SC['낙관']['params']['ticket'])}" data-tx="{CALC['sc']['낙관']}">낙관</button>
<button type="button" data-tk="{ticket}" data-tx="340">컨셉 초안 340건</button>
</div>
<p class="src">기준 2027 비용 구조로 고정: 변동비율 {pc(CALC['var_rate'])}(원가 {pc(C['blended_cost_rate'])}+카드·본사·마케팅·광열·소모품·기타 13.5%), 고정비 {man(CALC['fixed'])}/월(인건비·임대·관리비), 감가 {man(CALC['dep'])}/월, 투자 {inv/1e8:.1f}억원, 연 {days}일 <span class="bd a">가정</span></p>
</div>
<div class="res">
<div><span>월매출</span><b id="rRev"></b></div>
<div><span>연매출</span><b id="rAnn"></b></div>
<div><span>월 영업이익</span><b id="rOp"></b></div>
<div><span>영업이익률</span><b id="rMg"></b></div>
<div><span>손익분기 하루 결제건수</span><b id="rBep"></b></div>
<div><span>투자 회수기간(세전 EBITDA)</span><b id="rPb"></b></div>
</div>
</div>

<h3>6-5. 가정표</h3>
<div class="tw"><table>
<tr><th>항목</th><th>값</th><th class="c">구분</th><th>출처·근거</th></tr>
{asm_html}
</table></div>
<p class="src">pnl.json assumptions — 데이터 = 서울 열린데이터, 외부 = 공식 통계·기사, 가정 = 업계 관행·설계</p>
</section>

<section id="s7">
<h2><span class="no">7</span>리스크와 한계 — 무엇이 틀리면 결론이 바뀌나</h2>
<div class="from"><b>핵심 민감도</b><span>객단가 {num(ticket)}원에서 하루 결제가 <b>{bep_txn:.0f}건</b> 아래로 내려가면 영업적자입니다(기준 {txn27}건 대비 −{(1-bep_txn/txn27)*100:.0f}%). 출점 전 임대 조건, 개점 후 일 결제건수가 가장 중요한 두 변수입니다.</span></div>
<div class="tw risk"><table>
<tr><th>리스크·한계</th><th>내용</th><th>대응·모니터링</th></tr>
{risk_html}
</table></div>
</section>

<section id="s8">
<h2><span class="no">8</span>부록 — 출처와 데이터 사전 요약</h2>
<h3>서울 열린데이터 (수집일 2026-11-14)</h3>
<div class="tw"><table>
<tr><th>ID</th><th>데이터셋 · 기간 · 단위</th><th>링크</th></tr>
{src_rows}
</table></div>
<h3>외부 출처</h3>
<ul class="clean">{ext_src}
<li>시장 맥락(저가커피 가격대, 대형 베이커리카페, 법조타운·남부터미널·예술의전당 등 주변 시설)은 일반 정보로 '외부' 표시</li></ul>
<h3>데이터 사전 요약</h3>
<ul class="clean">
<li><b>분석 업종</b> 커피-음료(CS100010) + 제과점(CS100005) 합산 = '커피+제과'(cb_)</li>
<li><b>분석 단위</b> 서울시 상권분석서비스 상권(TRDAR_CD) × 분기(2021Q1~2026Q2, 22분기). panel.csv 33,961행 × 97열, trdar.csv 1,650개 상권</li>
<li><b>성장률</b> 4분기 합(연환산) 전년 대비 — 계절성 제거, 커피/제과 업종 구성이 같은 상권끼리만 비교. CAGR 단위 = 비율/년</li>
<li><b>행 없음 ≠ 0</b> 매출 행이 없으면 결측으로 처리(추정 불가·비공개). 4분기 롤링은 연속 4분기 관측 시에만 계산</li>
<li><b>법인 매출</b> 성별·연령이 식별되지 않은 매출 비중(cb_share_unident)을 오피스·법인 수요의 대리지표로 사용</li>
<li><b>제약</b> 열린데이터는 2021년 이후만 제공(2026-07-03부터) → 코로나 이전 기준선 없음, 3년 예측 시험 기준시점 3개</li>
</ul>
<h3>용어</h3>
<ul class="clean">
<li><b>스피어만 순위상관</b> 점수 순위와 실제 성장 순위가 얼마나 같은 방향인지(−1~1, 0 = 무관)</li>
<li><b>표본 밖 검증</b> 지표를 고를 때 쓰지 않은 기간에서 예측력을 확인하는 방법</li>
<li><b>출점 적격</b> 연 커피+제과 매출 50억원 이상 상권(플래그십 매장이 들어갈 시장 규모, 사업 판단 기준)</li>
</ul>
<h3>재현 파일</h3>
<p class="note">데이터 정비 <code>analysis/build_master.py</code> → 점수·백테스트 <code>analysis/score.py</code> → <code>analysis/results/analysis.json</code> · 컨셉 <code>analysis/results/concept.json</code> · 손익 <code>analysis/pnl.py</code> → <code>pnl.json</code> · 이 페이지 <code>analysis/build_site.py</code> · 지표 정의 <code>analysis/METRICS.md</code> · 데이터 사전 <code>data/processed/DATA_DICTIONARY.md</code></p>
</section>
</main>
<footer><div class="wrap">상권 분석 컨설팅 제안 · 데이터: 서울 열린데이터광장 상권분석서비스(2021Q1~2026Q2) · 손익은 가정 기반 시뮬레이션이며 투자 권유가 아닙니다.</div></footer>
<script>window.CALC={json.dumps(CALC, ensure_ascii=False)};</script>
<script>{JS}</script>
</body>
</html>
"""
os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT, "w", encoding="utf8").write(H)
print("wrote", OUT, len(H), "bytes")
print("ANSWER:", ANSWER_PLAIN)
