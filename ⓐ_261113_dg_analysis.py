# -*- coding: utf-8 -*-
"""
ⓐ_261113_dg_analysis.py — BID RADAR 대구·경북 기획사 심층 분석 리포트 생성기
입력: data.json(2026 정제 6,149건) + g2b_history_2021_2025_cache.json + g2b_2026_cache.json
출력: dg_report.json, dg_report.js, ⓐ_261113_대구경북_기획사_수주분석리포트.md
"""
import json
import os
import re
import sys
import importlib
from collections import defaultdict, Counter
from datetime import datetime

APP = r'G:\내 드라이브\00_AgenticAI_Share\03-이벤트기획 사업부\ⓐ_수주현황웹앱'
sys.path.insert(0, APP)
E = importlib.import_module('ⓐ_261113_export_data')
R = E.R

D = json.load(open(os.path.join(APP, 'data.json'), encoding='utf-8'))
WON = D['won_rows']
PROF = D.get('corp_profiles', {})

DG_PLACES = [
    '대구', '경상북도', '경북', '포항', '경주', '김천', '안동', '구미', '영주', '영천', '상주', '문경', '경산',
    '의성', '청송', '영양', '영덕', '청도', '고령', '성주', '칠곡', '예천', '봉화', '울진', '울릉', '군위',
    '달성', '수성', '달서', '신라문화', '도청', '한국정신문화재단', '세계유교문화재단', '치맥산업협회', '엑스코',
    '팔공산', '보문', '비슬산', '낙동강세계평화',
]
OTHER_SIDOS = (
    '서울', '부산', '광주', '인천', '대전', '울산', '세종', '제주', '강원',
    '전라', '전북', '전남', '충청', '충북', '충남', '경기', '경남', '경상남도',
)
NOISE = (
    '조경', '시설관리', '청소', '경비', '보안', '유지보수', '공사', '설계', '감리',
    '급식', '폐기물', '보험', '차량', '임차', '인쇄', '물품', '구매',
)


def eok(v):
    return round((v or 0) / 1e8, 2)


def fmt_eok(v):
    v = v or 0
    if v >= 1e8:
        return f'{v/1e8:,.1f}억'
    if v >= 1e4:
        return f'{round(v/1e4):,}만'
    return f'{int(v):,}원'


def val(r):
    return r.get('value') or r.get('amt') or 0


def is_dg_org(org):
    org = org or ''
    if any(s in org for s in OTHER_SIDOS) and not any(p in org for p in ('대구', '경북', '경상북도')):
        return False
    return any(p in org for p in DG_PLACES)


def is_dg_event(org, title):
    org = org or ''
    title = title or ''
    if any(s in org for s in OTHER_SIDOS) and not any(p in org for p in ('대구', '경북', '경상북도')):
        return False
    if org.startswith('한국마사회') and '대구' not in title and '경북' not in title:
        return False
    if any(p in org for p in DG_PLACES):
        return True
    return any(p in title for p in DG_PLACES) and not any(s in title for s in OTHER_SIDOS)


# ───────────────────────── 업체명 정규화/소재지 마스터 구축 ─────────────────────────
KEY_TO_DISPLAY = {}
CORP_TO_SIDO = {}
for cn, pf in PROF.items():
    k = E.corp_norm_key(cn)
    if k and k not in KEY_TO_DISPLAY:
        KEY_TO_DISPLAY[k] = cn
    if pf.get('sido') and pf['sido'] != '미상':
        CORP_TO_SIDO[cn] = pf['sido']
for r in WON:
    rk = r.get('corp_raw_key') or E.corp_norm_key(r.get('corp_norm') or r.get('corp') or '')
    if rk and rk not in KEY_TO_DISPLAY and r.get('corp_norm'):
        KEY_TO_DISPLAY[rk] = r['corp_norm']
    if r.get('corp_sido') and r['corp_sido'] != '미상':
        CORP_TO_SIDO.setdefault(r['corp_norm'], r['corp_sido'])


def norm_corp(name: str) -> str:
    name = (name or '').strip()
    if not name:
        return '-'
    rk = E.corp_norm_key(name)
    return KEY_TO_DISPLAY.get(rk, name)


def sido_of_corp(name: str, adrs: str = '') -> str:
    if adrs:
        s = E.sido_of_adrs(adrs)
        if s and s != '미상':
            return s
    return CORP_TO_SIDO.get(name, '미상')


# ───────────────────────── PART A. 2026 대구·경북 기획사 수주 결과 ─────────────────────────
rows26 = [r for r in WON if str(r.get('year')) == '2026' and r.get('corp_sido') in ('대구', '경북')]


def bid_zone(r):
    if r.get('region') in ('대구', '경북'):
        return '대구·경북 발주'
    return '타지역 발주' if not is_dg_org(r.get('org')) else '대구·경북 발주'


A = {'count': len(rows26), 'total': sum(val(r) for r in rows26)}
zone_stat = defaultdict(lambda: {'count': 0, 'total': 0})
sido_stat = defaultdict(lambda: {'count': 0, 'total': 0, 'corps': set()})
for r in rows26:
    z = bid_zone(r)
    zone_stat[z]['count'] += 1
    zone_stat[z]['total'] += val(r)
    s = sido_stat[r['corp_sido']]
    s['count'] += 1
    s['total'] += val(r)
    s['corps'].add(r['corp_norm'])
A['zone'] = {k: v for k, v in zone_stat.items()}
A['sido'] = {k: {'count': v['count'], 'total': v['total'], 'corps': len(v['corps'])} for k, v in sido_stat.items()}

corp = defaultdict(lambda: {
    'n': 0, 'v': 0, 'dg_n': 0, 'dg_v': 0, 'out_n': 0, 'out_v': 0,
    'rates': [], 'orgs': Counter(), 'cats': Counter(), 'sido': '', 'hq': '', 'out_regions': Counter()
})
for r in rows26:
    c = corp[r['corp_norm']]
    c['n'] += 1
    c['v'] += val(r)
    if bid_zone(r) == '대구·경북 발주':
        c['dg_n'] += 1
        c['dg_v'] += val(r)
    else:
        c['out_n'] += 1
        c['out_v'] += val(r)
        c['out_regions'][(r.get('org') or '')[:8]] += 1
    if r.get('rate'):
        c['rates'].append(r['rate'])
    c['orgs'][r.get('org') or '-'] += 1
    c['cats'][r.get('cat') or '기타'] += 1
    c['sido'] = r['corp_sido']
    c['hq'] = r.get('corp_hq') or ''

corp_rank = sorted(([k, v] for k, v in corp.items()), key=lambda x: (-x[1]['v'], -x[1]['n']))
A['corp_count'] = len(corp_rank)
A['corps'] = [{
    'name': k, 'sido': v['sido'], 'hq': v['hq'], 'n': v['n'], 'v': v['v'],
    'dg_n': v['dg_n'], 'dg_v': v['dg_v'], 'out_n': v['out_n'], 'out_v': v['out_v'],
    'avg_rate': round(sum(v['rates']) / len(v['rates']), 2) if v['rates'] else None,
    'top_org': v['orgs'].most_common(1)[0][0], 'top_cat': v['cats'].most_common(1)[0][0],
    'ceo': (PROF.get(k) or {}).get('ceo'),
} for k, v in corp_rank]

# 월별 추이
mon = defaultdict(lambda: {'dg_n': 0, 'out_n': 0, 'v': 0})
for r in rows26:
    m = r.get('month') or (r.get('posted') or '')[:7]
    if bid_zone(r) == '대구·경북 발주':
        mon[m]['dg_n'] += 1
    else:
        mon[m]['out_n'] += 1
    mon[m]['v'] += val(r)
A['monthly'] = [{'month': m, **v} for m, v in sorted(mon.items())]

# 금액대 / 유형
bands = [('1억 미만', 0, 1e8), ('1~3억', 1e8, 3e8), ('3~5억', 3e8, 5e8), ('5~10억', 5e8, 10e8), ('10억 이상', 10e8, 1e15)]
A['bands'] = []
for nm, lo, hi in bands:
    rs = [r for r in rows26 if lo <= val(r) < hi]
    A['bands'].append({'band': nm, 'count': len(rs), 'total': sum(val(r) for r in rs)})
cat = defaultdict(lambda: {'count': 0, 'total': 0})
for r in rows26:
    cat[r.get('cat') or '기타']['count'] += 1
    cat[r.get('cat') or '기타']['total'] += val(r)
A['cats'] = sorted(({'cat': k, **v} for k, v in cat.items()), key=lambda x: -x['total'])

# 홈그라운드 방어율: 대구·경북 발주 이벤트 공고 중 지역업체 수주 비중
dg_orders26 = [r for r in WON if str(r.get('year')) == '2026' and (r.get('region') in ('대구', '경북'))]
home = [r for r in dg_orders26 if r.get('corp_sido') in ('대구', '경북')]
away = [r for r in dg_orders26 if r.get('corp_sido') not in ('대구', '경북')]
A['home_defense'] = {
    'dg_orders': len(dg_orders26), 'dg_orders_total': sum(val(r) for r in dg_orders26),
    'home_n': len(home), 'home_v': sum(val(r) for r in home),
    'away_n': len(away), 'away_v': sum(val(r) for r in away),
}
away_corp = defaultdict(lambda: {'n': 0, 'v': 0, 'sido': ''})
for r in away:
    a = away_corp[r['corp_norm']]
    a['n'] += 1
    a['v'] += val(r)
    a['sido'] = r.get('corp_sido') or '미상'
A['outsiders'] = sorted(({'name': k, **v} for k, v in away_corp.items()), key=lambda x: -x['v'])[:15]
A['big_wins'] = sorted(
    ({'title': r['title'], 'org': r['org'], 'corp': r['corp_norm'], 'v': val(r),
      'posted': r.get('posted'), 'zone': bid_zone(r), 'link': r.get('link')} for r in rows26),
    key=lambda x: -x['v']
)[:15]

# ───────────────────────── PART B. 대구·경북 주요 입찰 5개년 수주사 ─────────────────────────
hist = json.load(open(os.path.join(APP, 'g2b_history_2021_2025_cache.json'), encoding='utf-8'))['items']
c26 = json.load(open(os.path.join(APP, 'g2b_2026_cache.json'), encoding='utf-8'))
pool26 = c26.get('scsbid_pool') or {}
if isinstance(pool26, dict):
    pool26 = list(pool26.values())

allbids = {}
for it in hist + list(pool26):
    if it.get('no'):
        allbids[it['no']] = dict(it)
for r in WON:
    allbids[r['no']] = {
        'no': r['no'], 'title': r['title'], 'org': r['org'], 'corp': r['corp_norm'],
        'adrs': r.get('corp_adrs') or '', 'amt': val(r), 'rate': r.get('rate'),
        'n': r.get('n'), 'open_dt': r.get('posted') or '', 'link': r.get('link'),
    }


def year_of(it):
    s = re.sub(r'\D', '', str(it.get('open_dt') or it.get('fnl_dt') or it.get('rgst_dt') or ''))
    return int(s[:4]) if len(s) >= 4 else None


event_dg = []
for it in allbids.values():
    t = it.get('title') or ''
    if not t or any(ex in t for ex in R.EXCLUDE_KEYWORDS) or not R.is_event_bid(t):
        continue
    if any(n in t for n in NOISE):
        continue
    org = it.get('org') or ''
    if not is_dg_event(org, t):
        continue
    y = year_of(it)
    if not y or y < 2021 or y > 2026:
        continue
    cn = norm_corp(it.get('corp') or '')
    it['year'] = y
    it['corp_norm'] = cn
    it['corp_sido'] = sido_of_corp(cn, it.get('adrs') or '')
    event_dg.append(it)

SYMBOLIC = [
    ('치맥페스티벌', '대구치맥페스티벌'), ('대구치맥', '대구치맥페스티벌'),
    ('컬러풀', '컬러풀대구페스티벌'), ('파워풀대구', '파워풀대구페스티벌'), ('파워풀', '파워풀대구페스티벌'),
    ('뮤지컬페스티벌', '대구국제뮤지컬페스티벌(DIMF)'), ('오페라축제', '대구국제오페라축제'),
    ('약령시', '대구약령시한방문화축제'), ('대구약령시', '대구약령시한방문화축제'),
    ('대구국제재즈', '대구국제재즈축제'), ('수성못', '수성못페스티벌'),
    ('달성 대구현대미술제', '대구현대미술제'), ('참꽃문화제', '비슬산 참꽃문화제'),
    ('동성로', '동성로축제'), ('대구마라톤', '대구마라톤'), ('달구벌관등놀이', '형형색색 달구벌관등놀이'),
    ('탈춤', '안동국제탈춤페스티벌'), ('신라문화제', '경주 신라문화제'), ('불빛축제', '포항국제불빛축제'),
    ('스틸아트', '포항 스틸아트페스티벌'), ('찻사발', '문경찻사발축제'), ('풍기인삼', '영주 풍기인삼축제'),
    ('청송사과', '청송사과축제'), ('라면축제', '구미라면축제'), ('구미푸드', '구미 푸드페스티벌'),
    ('자인단오', '경산자인단오제'), ('참외', '성주참외페스티벌'), ('은어축제', '봉화은어축제'),
    ('대게축제', '울진·영덕 대게축제'), ('곶감', '상주곶감축제'), ('대가야축제', '고령 대가야축제'),
    ('마늘축제', '의성 슈퍼푸드마늘축제'), ('산나물축제', '영양 산나물축제'), ('활축제', '예천 활축제'),
    ('도민체육대회', '경북도민체육대회'), ('APEC', '2025 APEC 정상회의 관련'), ('산림박람회', '경북 산림박람회'),
    ('세계마스터즈육상', '대구세계마스터즈육상경기대회'), ('호국보훈', '칠곡 낙동강세계평화문화대축전'),
    ('세계평화문화대축전', '칠곡 낙동강세계평화문화대축전'), ('김천 김밥', '김천 김밥축제'), ('김밥축제', '김천 김밥축제'),
    ('보현산', '영천 보현산별빛축제'), ('한우축제', '경북 한우축제'),
    ('도시농업박람회', '대구 도시농업박람회'), ('세계유교', '안동 세계유교문화축전'),
    ('반시축제', '청도 반시축제'), ('소싸움', '청도 소싸움축제'),
]


def symbolic_key(t):
    for kw, nm in SYMBOLIC:
        if kw in t:
            return nm
    return None


series = defaultdict(list)
for it in event_dg:
    k = symbolic_key(it['title'])
    if k:
        series[k].append(it)


def norm_title(t):
    t = re.sub(r'\(.*?\)|\[.*?\]|「|」|“|”|"', ' ', t)
    t = re.sub(r'20\d\d년?|\d{2}년|제\s*\d+\s*회|\d+\s*회|재공고|긴급|변경|협상에 의한|용역|대행|운영|위탁|기획|및|행사|추진|개최|사업|연출|진행', ' ', t)
    t = re.sub(r'\s+', '', t)
    return t[:14]


auto = defaultdict(list)
for it in event_dg:
    if symbolic_key(it['title']):
        continue
    k = norm_title(it['title'])
    if len(k) >= 4:
        auto[k].append(it)
for k, its in auto.items():
    yrs = {i['year'] for i in its}
    avg = sum(i.get('amt') or 0 for i in its) / max(1, len(its))
    if len(yrs) >= 3 and avg >= 3e8:
        series['🔁 ' + its[0]['title'][:28]] = its

major = []
for name, its in series.items():
    by_year = defaultdict(list)
    for i in its:
        by_year[i['year']].append(i)
    yrs = sorted(by_year)
    total = sum(i.get('amt') or 0 for i in its)
    winners = Counter(i['corp_norm'] for i in its)
    cells = {}
    for y in range(2022, 2027):
        lst = sorted(by_year.get(y, []), key=lambda i: -(i.get('amt') or 0))
        cells[str(y)] = [{
            'corp': i['corp_norm'], 'amt': i.get('amt') or 0,
            'title': i['title'], 'org': i.get('org'), 'sido': i['corp_sido'],
        } for i in lst[:3]]
    max_amt = max((i.get('amt') or 0) for i in its)
    score = (len(yrs) * 2) + min(10, max_amt / 1e8) + (5 if not name.startswith('🔁') else 0)
    major.append({
        'name': name, 'years': yrs, 'bids': len(its), 'total': total, 'max_amt': max_amt,
        'org': Counter(i.get('org') for i in its).most_common(1)[0][0],
        'top_winner': winners.most_common(1)[0], 'unique_winners': len(winners),
        'cells': cells, 'score': round(score, 1), 'symbolic': not name.startswith('🔁'),
    })
major.sort(key=lambda m: -m['score'])
major = major[:30]

yearly = []
for y in range(2022, 2027):
    its = [i for i in event_dg if i['year'] == y]
    loc = [i for i in its if i['corp_sido'] in ('대구', '경북')]
    yearly.append({
        'year': y, 'count': len(its), 'total': sum(i.get('amt') or 0 for i in its),
        'local_n': len(loc), 'local_v': sum(i.get('amt') or 0 for i in loc),
    })

cum = defaultdict(lambda: {'n': 0, 'v': 0, 'years': Counter(), 'sido': '미상'})
for i in event_dg:
    if i['year'] < 2022:
        continue
    c = cum[i['corp_norm']]
    c['n'] += 1
    c['v'] += i.get('amt') or 0
    c['years'][i['year']] += 1
    if c['sido'] == '미상' and i['corp_sido'] != '미상':
        c['sido'] = i['corp_sido']
cum_top = sorted(
    ({'name': k, 'n': v['n'], 'v': v['v'], 'sido': v['sido'],
      'by_year': {str(y): v['years'].get(y, 0) for y in range(2022, 2027)}} for k, v in cum.items()),
    key=lambda x: -x['v']
)[:20]

rgst_months = Counter(re.sub(r'\D', '', i.get('rgst_dt') or '')[:6] for i in hist)
covered = sorted(m for m, n in rgst_months.items() if n >= 3000 and m >= '202111')
coverage = {
    'history_from': covered[0] if covered else None,
    'history_to': covered[-1] if covered else None,
    'gap_note': '2025-04 중순 ~ 2025-12 나라장터 낙찰정보는 수집 당일(2026-11-13) 공공데이터포털 일일 호출한도 초과로 미수집 — 2025년 수치는 1~4월분만 반영된 부분값',
}
report = {
    'generated_at': datetime.now().isoformat(timespec='seconds'),
    'A': A, 'major': major, 'yearly': yearly, 'cum_top': cum_top,
    'history_items': len(hist), 'event_dg_items': len(event_dg), 'coverage': coverage,
}
json.dump(report, open(os.path.join(APP, 'dg_report.json'), 'w', encoding='utf-8'), ensure_ascii=False, default=list)
with open(os.path.join(APP, 'dg_report.js'), 'w', encoding='utf-8') as f:
    f.write('window.__DG_REPORT__ = ' + json.dumps(report, ensure_ascii=False, default=list, separators=(',', ':')) + ';\n')


# ───────────────────────── 마크다운 리포트 생성 ─────────────────────────
def write_markdown_report():
    zdg = A['zone'].get('대구·경북 발주', {'count': 0, 'total': 0})
    zout = A['zone'].get('타지역 발주', {'count': 0, 'total': 0})
    H = A['home_defense']
    dg_s = A['sido'].get('대구', {'count': 0, 'total': 0, 'corps': 0})
    gb_s = A['sido'].get('경북', {'count': 0, 'total': 0, 'corps': 0})
    top5_share = sum(c['v'] for c in A['corps'][:5]) / max(1, A['total']) * 100

    md = []
    md.append('# 🎯 대구·경북 이벤트기획사 수주 결과 & 5개년 주요 입찰 심층 분석 리포트 ⓐ\n')
    md.append(f'- **생성일시**: {report["generated_at"].replace("T", " ")}  ')
    md.append('- **웹 리포트**: https://kaycomm21.github.io/bid-radar/dg_report.html  ')
    md.append('- **메인 웹앱**: https://kaycomm21.github.io/bid-radar/  ')
    md.append(f'- **데이터 범위**: 2026년 정제 데이터 `6,149건` (노션 Read-Only + 나라장터 2026 전수), 5개년 이력 `{len(hist):,}건` ({coverage["history_from"]}~{coverage["history_to"]} + 2026년)')
    md.append(f'- **주의사항**: {coverage["gap_note"]}\n')
    md.append('---\n')

    md.append('## Ⅰ. 2026년 대구·경북 본사 기획사 수주 총괄 요약\n')
    md.append('| 구분 | 건수 | 비중(건수) | 수주 총액 | 비중(금액) | 비고 |')
    md.append('|---|---:|---:|---:|---:|---|')
    md.append(f'| **대구·경북 발주 수주** | **{zdg["count"]:,}건** | {zdg["count"]/max(1,A["count"])*100:.1f}% | **{fmt_eok(zdg["total"])}** ({int(zdg["total"]):,}원) | {zdg["total"]/max(1,A["total"])*100:.1f}% | 지역 내 발주기관 |')
    md.append(f'| **타지역 발주 수주 (외부 진출)** | **{zout["count"]:,}건** | {zout["count"]/max(1,A["count"])*100:.1f}% | **{fmt_eok(zout["total"])}** ({int(zout["total"]):,}원) | {zout["total"]/max(1,A["total"])*100:.1f}% | 수도권·타시도·중앙부처 |')
    md.append(f'| **합계 (대구·경북 기획사 {A["corp_count"]}개사)** | **{A["count"]:,}건** | 100.0% | **{fmt_eok(A["total"])}** ({int(A["total"]):,}원) | 100.0% | 상위 5개사 금액 점유 **{top5_share:.1f}%** |\n')
    md.append(f'- **본사 소재지별**: 대구 본사 **{dg_s["corps"]}개사 · {dg_s["count"]}건 · {fmt_eok(dg_s["total"])}** / 경북 본사 **{gb_s["corps"]}개사 · {gb_s["count"]}건 · {fmt_eok(gb_s["total"])}**\n')

    md.append('## Ⅱ. 2026년 월별 수주 추이 (발주지역 구분)\n')
    md.append('| 월 | 대구·경북 발주 | 타지역 발주 | 합계 건수 | 수주 총액 |')
    md.append('|---|---:|---:|---:|---:|')
    for m in A['monthly']:
        tot_n = m['dg_n'] + m['out_n']
        md.append(f'| {m["month"]} | {m["dg_n"]}건 | {m["out_n"]}건 | {tot_n}건 | {fmt_eok(m["v"])} |')
    md.append('')

    md.append('## Ⅲ. 2026년 대구·경북 이벤트기획사 수주 순위 TOP 30\n')
    md.append('| 순위 | 기획사(대표자) | 본사 | 총 건수 | 총 수주액 | 대구·경북 발주 | 타지역 발주 | 평균낙찰률 | 주력 유형 | 대표 발주처 |')
    md.append('|---:|---|---|---:|---:|---:|---:|---:|---|---|')
    for idx, c in enumerate(A['corps'][:30], 1):
        nm = f'{c["name"]} ({c["ceo"]})' if c.get('ceo') else c['name']
        rt = f'{c["avg_rate"]:.1f}%' if c.get('avg_rate') else '-'
        md.append(f'| {idx} | **{nm}** | {c["hq"] or c["sido"]} | {c["n"]}건 | **{fmt_eok(c["v"])}** | {c["dg_n"]}건 ({fmt_eok(c["dg_v"])}) | {c["out_n"]}건 ({fmt_eok(c["out_v"])}) | {rt} | {c["top_cat"]} | {c["top_org"]} |')
    md.append('')

    md.append('## Ⅳ. 홈그라운드 방어율 & 외지(수도권 등) 침투 업체 TOP 15\n')
    md.append(f'- **대구·경북 발주 이벤트 공고 총 {H["dg_orders"]}건 ({fmt_eok(H["dg_orders_total"])})** 중:')
    md.append(f'  - 지역 기획사 방어 수주: **{H["home_n"]}건 ({H["home_n"]/max(1,H["dg_orders"])*100:.1f}%) · {fmt_eok(H["home_v"])} ({H["home_v"]/max(1,H["dg_orders_total"])*100:.1f}%)**')
    md.append(f'  - 외지 업체 수주 유출: **{H["away_n"]}건 ({H["away_n"]/max(1,H["dg_orders"])*100:.1f}%) · {fmt_eok(H["away_v"])} ({H["away_v"]/max(1,H["dg_orders_total"])*100:.1f}%)**\n')
    md.append('| 순위 | 외지 업체명 | 본사 | 수주 건수 | 수주액 |')
    md.append('|---:|---|---|---:|---:|')
    for idx, o in enumerate(A['outsiders'], 1):
        md.append(f'| {idx} | {o["name"]} | {o["sido"]} | {o["n"]}건 | {fmt_eok(o["v"])} |')
    md.append('')

    md.append('## Ⅴ. 금액대별 · 행사유형별 구조 (2026년)\n')
    md.append('| 금액대 | 건수 | 총액 | 비중 | | 행사유형 | 건수 | 총액 | 건당 평균 |')
    md.append('|---|---:|---:|---:|---|---|---:|---:|---:|')
    for i in range(max(len(A['bands']), len(A['cats']))):
        b = A['bands'][i] if i < len(A['bands']) else None
        ct = A['cats'][i] if i < len(A['cats']) else None
        left = f'| {b["band"]} | {b["count"]}건 | {fmt_eok(b["total"])} | {b["total"]/max(1,A["total"])*100:.1f}% |' if b else '| | | | |'
        right = f' | {ct["cat"]} | {ct["count"]}건 | {fmt_eok(ct["total"])} | {fmt_eok(ct["total"]/max(1,ct["count"]))} |' if ct else ' | | | | |'
        md.append(left + right)
    md.append('')

    md.append('## Ⅵ. 2026년 대구·경북 기획사 대형 수주 건 TOP 15\n')
    md.append('| 순위 | 게시일 | 공고명 | 발주처 | 수주 기획사 | 구분 | 금액 |')
    md.append('|---:|---|---|---|---|---|---:|')
    for idx, b in enumerate(A['big_wins'], 1):
        md.append(f'| {idx} | {b["posted"] or "-"} | {b["title"]} | {b["org"]} | **{b["corp"]}** | {b["zone"]} | **{fmt_eok(b["v"])}** |')
    md.append('')

    md.append('## Ⅶ. 대구·경북 주요 입찰(상징성·고유성·사업비 규모) & 5개년(2022~2026) 수주사 매트릭스\n')
    md.append('> 선정 점수 = `(참여 연도 수 × 2) + min(10, 최대 사업비/1억) + (대표행사 가산 +5)` · 칸 내 괄호는 낙찰금액, `2025`는 1~4월 부분 집계\n')
    md.append('| # | 주요 입찰 | 주 발주처 | 최대규모 | 2022 | 2023 | 2024 | 2025(부분) | 2026 | 최다 수주 |')
    md.append('|---:|---|---|---:|---|---|---|---|---|---|')
    for idx, m in enumerate(major, 1):
        row = [str(idx), m['name'].replace('🔁 ', ''), m['org'], fmt_eok(m['max_amt'])]
        for y in ('2022', '2023', '2024', '2025', '2026'):
            cs = m['cells'].get(y) or []
            row.append('<br>'.join(f'{c["corp"]} ({fmt_eok(c["amt"])})' for c in cs) if cs else '–')
        row.append(f'{m["top_winner"][0]} ({m["top_winner"][1]}회)')
        md.append('| ' + ' | '.join(row) + ' |')
    md.append('')

    md.append('## Ⅷ. 최근 5개년(2022~2026) 대구·경북 발주 시장 추이 & 누적 수주 강자 TOP 20\n')
    md.append('| 연도 | 발주 건수 | 발주 총액 | 지역업체 건수 | 지역업체 금액(비중) |')
    md.append('|---:|---:|---:|---:|---:|')
    for y in yearly:
        tag = f'{y["year"]} (부분)' if y['year'] == 2025 else str(y['year'])
        pct_v = y['local_v'] / max(1, y['total']) * 100
        md.append(f'| {tag} | {y["count"]}건 | {fmt_eok(y["total"])} | {y["local_n"]}건 | {fmt_eok(y["local_v"])} ({pct_v:.1f}%) |')
    md.append('')
    md.append('| 순위 | 업체명 | 본사 | 누적 건수 | 누적 수주액 | 22 | 23 | 24 | 25(부분) | 26 |')
    md.append('|---:|---|---|---:|---:|---:|---:|---:|---:|---:|')
    for idx, c in enumerate(cum_top, 1):
        by = c['by_year']
        md.append(f'| {idx} | **{c["name"]}** | {c["sido"]} | {c["n"]}건 | **{fmt_eok(c["v"])}** | {by["2022"]} | {by["2023"]} | {by["2024"]} | {by["2025"]} | {by["2026"]} |')
    md.append('')

    md.append('## Ⅸ. 실전 전략 시사점 (컨소시엄·파트너십·타깃 입찰 전략)\n')
    top1 = A['corps'][0] if A['corps'] else {'name': '-', 'n': 0, 'v': 0}
    top2 = A['corps'][1] if len(A['corps']) > 1 else {'name': '-', 'n': 0, 'v': 0}
    out_lead = sorted(A['corps'], key=lambda x: -x['out_v'])[0] if A['corps'] else {'name': '-', 'out_n': 0, 'out_v': 0}
    md.append(f'1. **타지역 원정 수주 비중 {zout["count"]/max(1,A["count"])*100:.1f}%**: 대구·경북 기획사 수주액 `{fmt_eok(A["total"])}` 중 `{fmt_eok(zout["total"])}`({zout["count"]}건)이 타지역·중앙부처 발주에서 나왔습니다. 지역 물량에만 묶이지 않고 타지역으로 나가는 기획사(**{out_lead["name"]}** `{out_lead["out_n"]}건·{fmt_eok(out_lead["out_v"])}` 등)가 외연 확장형 파트너 후보입니다.')
    md.append(f'2. **홈그라운드 대형 사업의 외지 유출**: 대구·경북 발주 건수 기준 지역 방어율은 `{H["home_n"]/max(1,H["dg_orders"])*100:.1f}%`이나 금액 기준 방어율은 `{H["home_v"]/max(1,H["dg_orders_total"])*100:.1f}%`로 낮습니다. 수억~수십억대 대형 국제행사·체전·대형축제는 서울/경기권 대형 대행사에 넘어가는 경향이 뚜렷합니다.')
    md.append(f'3. **양강 + 중견 허리층 구조**: **{top1["name"]}**(`{top1["n"]}건·{fmt_eok(top1["v"])}`)와 **{top2["name"]}**(`{top2["n"]}건·{fmt_eok(top2["v"])}`)가 1~2위를 형성하며 상위 5개사가 지역 수주액의 `{top5_share:.1f}%`를 차지합니다.')
    md.append('4. **인컴번트 vs 오픈형 입찰 구분 공략**: Ⅶ 매트릭스에서 동일 업체가 반복 수주한 행사(예: `문경찻사발축제` `(주)예일커뮤니케이션즈`)는 기존 수행사 텃밭 성격이 강해 공동수급·연출 참여가 유리하며, 매년 수주사가 교체되는 행사(예: `안동국제탈춤페스티벌`, `청송사과축제`, `구미/경산/성주`권 축제)가 신규 진입·단독/컨소시엄 공략 대상입니다.\n')

    md_path = os.path.join(APP, 'ⓐ_261113_대구경북_기획사_수주분석리포트.md')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(md))
    print(f'MD 리포트 생성 완료: {md_path}')


write_markdown_report()

print('A count', A['count'], 'total eok', eok(A['total']), 'corps', A['corp_count'])
print('zone', {k: (v['count'], eok(v['total'])) for k, v in A['zone'].items()})
print('sido', {k: (v['count'], eok(v['total']), v['corps']) for k, v in A['sido'].items()})
print('home_defense', {k: (eok(v) if 'v' in k or 'total' in k else v) for k, v in A['home_defense'].items()})
print('yearly', [(y['year'], y['count'], eok(y['total']), y['local_n'], eok(y['local_v'])) for y in yearly])
print('major_count', len(major), 'cum_top5', [(c['name'], c['sido'], c['n'], eok(c['v'])) for c in cum_top[:5]])
