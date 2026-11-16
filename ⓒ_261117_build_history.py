# -*- coding: utf-8 -*-
"""
ⓒ_261117_build_history.py — 과거 연도(2020~2025) 이벤트성 낙찰 이력을 웹앱용 history.js 로 만든다.
입력: g2b_history_2021_2025_cache.json (ⓐ_261113_fetch_history.py 가 모은 나라장터 낙찰정보), data.json (업체명 표기 맞춤용)
출력: history.js (공개, 화면에서 「과거 연도 불러오기」를 누를 때만 내려받음), history_rows.json (로컬, 순위 수집기 입력)
실행: python "ⓒ_261117_build_history.py"      ← 나라장터·노션 호출 없음(로컬 파일만 읽음)
"""
import importlib
import json
import os
import re
import sys
from collections import Counter

APP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP)
E = importlib.import_module('ⓐ_261113_export_data')
DGA_NOISE = re.compile(   # ⓐ_261113_dg_analysis.py · index.html 의 NOISE_RE 와 같은 규칙
    r'(?:^|[^가-힣])조경(?![제상])|시설\s?관리(?!공단)|시설물\s?(?:유지|관리)|유지\s?보수|유지\s?관리'
    r'|(?:^|[^가-힣])청소(?!년)|미화\s?관리|폐기물|급식\s?(?:일부\s?)?위탁|보험\s?가입|종합보험|자동차보험|건설사업관리'
    r'|전기공사|세부설계|실시설계|기본설계|정비사업|태양광|승강기|통근버스|소모성물품|환경영향평가|군관리계획'
    r'|채용\s?(?:업무\s?)?대행|직원\s?채용|공용차량|주거래여행사|수목\s?납품|항공권\s?구매'
)
R, A, ABI = E.R, E.A, E.ABI

data = json.load(open(os.path.join(APP, 'data.json'), encoding='utf-8'))
cur_nos = {r['no'] for r in data['won_rows']}
key_to_display = {}
for cn in data.get('corp_profiles', {}):
    k = E.corp_norm_key(cn)
    if k and k not in key_to_display:
        key_to_display[k] = cn

hist = json.load(open(os.path.join(APP, 'g2b_history_2021_2025_cache.json'), encoding='utf-8'))['items']
print(f'이력 캐시 {len(hist):,}건')

# 같은 업체의 주소가 비어 있는 행을 채우기 위한 사전 (사업자번호 → 가장 최근 주소)
adrs_by_biz = {}
for it in hist:
    if it.get('biz_no') and it.get('adrs'):
        adrs_by_biz[it['biz_no']] = it['adrs']

rows, names = [], Counter()
for it in hist:
    no = it.get('no')
    title = it.get('title') or ''
    if not no or no in cur_nos or not title or not it.get('corp'):
        continue
    if any(ex in title for ex in R.EXCLUDE_KEYWORDS) or not R.is_event_bid(title) or DGA_NOISE.search(title):
        continue
    val = int(it.get('amt') or 0)
    if val <= 0:
        continue
    if val > 50_000_000_000:
        # 행사 용역이 500억을 넘는 경우는 원천 입력 오류로 본다(실측: 2024 「충장 라온페스타」 4,136억 1건). 합계를 왜곡하므로 제외.
        print(f'  [이상값 제외] {val/1e8:,.0f}억 | {title[:40]} | {it.get("corp")}')
        continue
    dt = R.parse_dt(it.get('open_dt') or it.get('fnl_dt') or it.get('rgst_dt') or '')
    if not dt or not (2020 <= dt.year <= 2025):
        continue
    org = it.get('org') or ''
    reg = R.region_of(f'{title} {org}') or ''
    adrs = it.get('adrs') or adrs_by_biz.get(it.get('biz_no')) or ''
    month = f'{dt:%Y-%m}'
    yr, hf, qt = E.period_fields(month)
    sido = E.sido_of_adrs(adrs)
    corp = it['corp']
    names[corp] += 1
    rows.append({
        'no': no, 'title': title, 'org': org,
        'region': reg if reg in ('대구', '경북') else '',
        'corp_hq': E.short_hq_label(adrs), 'corp_hq_region': E.hq_region_of(adrs),
        'corp_sido': sido, 'corp_zone': E.zone_of_sido(sido),
        'posted': f'{dt:%Y-%m-%d}', 'month': month, 'year': yr, 'half': hf, 'quarter': qt,
        'budget': val, 'value': val, 'rate': it.get('rate'), 'n': it.get('n'),
        'corp': corp, 'ceo': it.get('ceo'), 'biz_no': it.get('biz_no'),
        'cat': ABI.categorize(title), 'band': A.band(val), 'band_ui': E.ui_amount_band(val),
        'link': R.bid_detail_url(no, it.get('ord') or '000') or '',
    })

# 업체명 표기: 2026 데이터의 대표 표기를 우선, 없으면 과거 이력 안에서 가장 흔한 표기
hist_display, _ = E.normalize_corp_display_map(list(names.elements()))
for r in rows:
    k = E.corp_norm_key(r['corp'])
    r['corp_norm'] = key_to_display.get(k) or hist_display.get(k) or r['corp']

rows.sort(key=lambda r: (r['posted'], r['no']), reverse=True)
by_year = Counter(r['year'] for r in rows)
print('연도별 이벤트성 낙찰:', dict(sorted(by_year.items())), '합계', f'{len(rows):,}')

json.dump(rows, open(os.path.join(APP, 'history_rows.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))

# 공개본: 키 목록 1번 + 값 배열(용량 절감). 사업자번호·대표자는 2026 데이터와 같은 수준으로 포함(공공 낙찰 정보)
KEYS = ['no', 'title', 'org', 'region', 'corp_hq', 'corp_hq_region', 'corp_sido', 'corp_zone', 'posted', 'value',
        'rate', 'n', 'corp', 'corp_norm', 'ceo', 'biz_no', 'cat', 'link']
pub = {
    'meta': {'years': sorted(by_year), 'count': len(rows),
             'generated_at': __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')},
    'keys': KEYS,
    'rows': [[r.get(k) for k in KEYS] for r in rows],
}
out = os.path.join(APP, 'history.js')
with open(out, 'w', encoding='utf-8') as f:
    f.write('window.__BID_HIST__ = ' + json.dumps(pub, ensure_ascii=False, separators=(',', ':')) + ';\n')
print(f'history.js {os.path.getsize(out)/1e6:.2f} MB')
