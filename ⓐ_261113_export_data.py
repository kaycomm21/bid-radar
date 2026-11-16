# -*- coding: utf-8 -*-
"""
ⓐ_261113_export_data.py  (ⓐAntiGravity 2026-11-13 / v2.0 전국 확장 + G2B 2026 보강)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
나라장터 입찰자동화 노션 DB(일반 + 아카이브)를 읽기 전용으로 조회하고,
G2B OpenAPI(URL_SCSBID / URL_OPENG / URL_BID)를 6일 23시간 59분 청크(resultCode:07 회피)로
병렬 보강하여 「전국·대구경북 이벤트기획사 입찰 수주 현황」 웹앱용 data.json / data.js 를 생성한다.

[§0 준수사항]
- 노션 DB에 쓰기(POST/PATCH/DELETE) 호출 0건 (절대 읽기 전용, meta_before == meta_after 검증).
- 정본 엔진(00_입찰자동화_엔진)의 기존 .py 파일을 수정하지 않고 import 재사용.
- 생성된 JSON/JS에 NOTION_API_KEY / NARA_JANGTER_API_KEY 등 비밀키 0건 포함.
"""
import argparse
import importlib
import json
import math
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import requests
import urllib3

urllib3.disable_warnings()

ENGINE_DIR = r'G:\내 드라이브\00_AgenticAI_Share\03-이벤트기획 사업부\00_입찰자동화_엔진'
OUT_DIR = r'G:\내 드라이브\00_AgenticAI_Share\03-이벤트기획 사업부\ⓐ_수주현황웹앱'

if ENGINE_DIR not in sys.path:
    sys.path.insert(0, ENGINE_DIR)

import run_bid_automation_full as R
A = importlib.import_module('award_report_v2_\u24d2')
import analyze_bid_intelligence as ABI
CP = importlib.import_module('corp_parse_\u24d0')

NOW = datetime.now()
CACHE_PATH = os.path.join(OUT_DIR, 'g2b_2026_cache.json')
CACHE_TTL_HOURS = 12  # 당일 재실행 시 G2B 전수 캐시 재사용 (필요 시 --refresh-g2b 로 강제 갱신)

# 법인격 접두/접미어 및 공백 제거 패턴 (업체명 정규화용)
_CORP_PREFIX_RE = re.compile(
    r'(?:주식회사|\(주\)|㈜|유한회사|\(유\)|사단법인|\(사\)|재단법인|\(재\)|협동조합|합자회사|\(합\)|합명회사|영농조합법인|사회적협동조합)'
)

# 2026년 G2B 보강 시 '대구·경북 본사 소재지' 및 17개 시·도/권역 판별용
_HQ_DG_RE = re.compile(r'^(대구광역시|대구시|대구\s)')
_HQ_GB_RE = re.compile(r'^(경상북도|경북\s)')

_SIDO_PREFIXES = [
    ('대구광역시', '대구'), ('대구시', '대구'), ('대구', '대구'),
    ('경상북도', '경북'), ('경북', '경북'),
    ('서울특별시', '서울'), ('서울시', '서울'), ('서울', '서울'),
    ('경기도', '경기'), ('경기', '경기'),
    ('인천광역시', '인천'), ('인천시', '인천'), ('인천', '인천'),
    ('부산광역시', '부산'), ('부산시', '부산'), ('부산', '부산'),
    ('울산광역시', '울산'), ('울산시', '울산'), ('울산', '울산'),
    ('경상남도', '경남'), ('경남', '경남'),
    ('대전광역시', '대전'), ('대전시', '대전'), ('대전', '대전'),
    ('세종특별자치시', '세종'), ('세종시', '세종'), ('세종', '세종'),
    ('충청남도', '충남'), ('충남', '충남'),
    ('충청북도', '충북'), ('충북', '충북'),
    ('광주광역시', '광주'), ('광주시', '광주'), ('광주', '광주'),
    ('전라남도', '전남'), ('전남', '전남'),
    ('전북특별자치도', '전북'), ('전라북도', '전북'), ('전북', '전북'),
    ('강원특별자치도', '강원'), ('강원도', '강원'), ('강원', '강원'),
    ('제주특별자치도', '제주'), ('제주도', '제주'), ('제주', '제주'),
]

_ZONE_MAP = {
    '대구': 'DG', '경북': 'DG',
    '서울': 'CAPITAL', '경기': 'CAPITAL', '인천': 'CAPITAL',
    '부산': 'PK', '울산': 'PK', '경남': 'PK',
    '대전': 'CC', '세종': 'CC', '충남': 'CC', '충북': 'CC',
    '광주': 'HN', '전남': 'HN', '전북': 'HN',
    '강원': 'GWJJ', '제주': 'GWJJ',
}


def sido_of_adrs(adrs: str) -> str:
    s = str(adrs or '').strip()
    if not s:
        return '미상'
    tok = s.split()[0]
    for pref, norm in _SIDO_PREFIXES:
        if tok.startswith(pref):
            return norm
    return '미상'


def zone_of_sido(sido: str) -> str:
    return _ZONE_MAP.get(sido or '', 'UNKNOWN')


def period_fields(month_str: str) -> tuple[str, str, str]:
    """'YYYY-MM' -> (year, half, quarter) 반환."""
    if not month_str or not re.match(r'^\d{4}-\d{2}$', month_str):
        return '미상', '미상', '미상'
    y, m_str = month_str.split('-')
    m = int(m_str)
    q = f'{y}-Q{(m - 1) // 3 + 1}'
    h = f'{y}-H{1 if m <= 6 else 2}'
    return y, h, q


def build_hq_directory(scsbid_pool: dict, won_rows: list) -> tuple[dict, dict, dict]:
    """9.5만 건 G2B SCSBID + 기존 행에서 사업자 소재지 마스터 사전 구축 (대구·경북 본사 우선)."""
    dir_biz, dir_kc, dir_k = {}, {}, {}

    def _register(it):
        adrs = str(it.get('adrs') or it.get('corp_adrs') or '').strip()
        if not adrs:
            return
        rk = corp_norm_key(it.get('corp') or '')
        if not rk:
            return
        ceo = str(it.get('ceo') or '').strip()
        biz = it.get('biz_no')
        is_dg = sido_of_adrs(adrs) in ('대구', '경북')
        rec = {'adrs': adrs, 'ceo': ceo, 'biz_no': biz}
        if biz and (biz not in dir_biz or is_dg):
            dir_biz[biz] = rec
        if ceo and ((rk, ceo) not in dir_kc or is_dg):
            dir_kc[(rk, ceo)] = rec
        if rk not in dir_k or is_dg:
            dir_k[rk] = rec

    for it in scsbid_pool.values():
        _register(it)
    for r in won_rows:
        _register(r)
    return dir_biz, dir_kc, dir_k


def hq_region_of(adrs: str) -> str:
    """업체 본사 소재지 주소에서 '대구' / '경북' / '타지역' / '' 판정."""
    s = str(adrs or '').strip()
    if not s:
        return ''
    if _HQ_DG_RE.search(s) or '대구광역시' in s[:15]:
        return '대구'
    if _HQ_GB_RE.search(s) or '경상북도' in s[:15]:
        return '경북'
    return '타지역'


def short_hq_label(adrs: str) -> str:
    """주소에서 시/도 + 시/군/구 간략 라벨 추출 (예: '대구 수성구', '대전 유성구')."""
    s = str(adrs or '').strip()
    if not s:
        return ''
    tokens = s.split()
    if len(tokens) >= 2:
        p1 = tokens[0].replace('광역시', '').replace('특별시', '').replace('특별자치시', '').replace('특별자치도', '')
        p1 = {'경상북도': '경북', '경상남도': '경남', '전라남도': '전남', '전북특별자치도': '전북', '충청남도': '충남', '충청북도': '충북'}.get(p1, p1)
        return f'{p1} {tokens[1]}'
    return tokens[0]


def corp_norm_key(name: str) -> str:
    """법적 형태 표기(주식회사/(주)/㈜ 등)와 모든 공백을 제거해 매칭용 정규화 키를 반환."""
    if not name:
        return ''
    s = _CORP_PREFIX_RE.sub('', str(name))
    s = re.sub(r'\s+', '', s).strip()
    return s or str(name).strip()


def normalize_corp_display_map(names):
    """동일 norm_key 를 가진 원본 표기 중 가장 자주 쓰인 표기(또는 가장 간결한 표기)를 대표명으로 매핑."""
    groups = defaultdict(Counter)
    for n in names:
        if not n:
            continue
        k = corp_norm_key(n)
        groups[k][n] += 1
    key_to_display = {}
    key_to_aliases = {}
    for k, cnt in groups.items():
        best = sorted(cnt.items(), key=lambda kv: (-kv[1], len(kv[0]), kv[0]))[0][0]
        key_to_display[k] = best
        key_to_aliases[k] = [name for name, _ in cnt.most_common()]
    return key_to_display, key_to_aliases


def get_db_meta(db_id: str) -> dict:
    """노션 DB 메타데이터(읽기 전용 GET)로 last_edited_time 확인."""
    r = R.notion_request('GET', f'https://api.notion.com/v1/databases/{db_id}')
    if r is not None and r.status_code == 200:
        d = r.json()
        title = ''.join(t.get('plain_text', '') for t in d.get('title', []))
        return {
            'id': db_id,
            'title': title,
            'last_edited_time': d.get('last_edited_time'),
        }
    return {'id': db_id, 'title': '', 'last_edited_time': None}


def ui_amount_band(val: float) -> str:
    """§5-3 #5 필터 기준: 1~2억(1~3억 미만) / 3~5억(3~6억 미만) / 6~10억(6~11억 미만) / 그 외"""
    if not val or val <= 0:
        return '그 외'
    eok = val / 100_000_000
    if 1 <= eok < 3:
        return '1~2억'
    if 3 <= eok < 6:
        return '3~5억'
    if 6 <= eok < 11:
        return '6~10억'
    return '그 외'


def _g2b_get_safe(url: str, params: dict, retries: int = 4) -> dict:
    """G2B API 호출 (resultCode 07 방어 + 빈응답/타임아웃 지수 백오프)."""
    delay = 1.5
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, params=params, verify=False, timeout=45)
            txt = (r.text or '').strip()
            if not txt:
                raise ValueError('empty response body')
            js = r.json()
            if 'OpenAPI_ServiceResponse' in js:
                hdr0 = js['OpenAPI_ServiceResponse'].get('cmmMsgHeader', {})
                raise RuntimeError(f"G2B 게이트웨이 오류 {hdr0.get('returnReasonCode')}: {hdr0.get('returnAuthMsg') or hdr0.get('errMsg')}")
            if 'nkoneps.com.response.ResponseError' in js:
                err = js['nkoneps.com.response.ResponseError'].get('header', {})
                raise RuntimeError(f"G2B error {err.get('resultCode')}: {err.get('resultMsg')}")
            resp = js.get('response', {})
            hdr = resp.get('header', {})
            if hdr.get('resultCode') not in (None, '00'):
                raise RuntimeError(f"G2B resultCode {hdr.get('resultCode')}: {hdr.get('resultMsg')}")
            return resp.get('body', {}) or {}
        except Exception as e:
            if attempt == retries:
                raise
            time.sleep(delay)
            delay *= 1.8
    return {}


def _fetch_one_chunk(url: str, cs: datetime, ce: datetime, extra_params=None) -> list:
    """단일 7일 이하 청크(모든 페이지) 수집."""
    base = {
        'serviceKey': R.G2B_API_KEY,
        'inqryDiv': '1',
        'inqryBgnDt': cs.strftime('%Y%m%d%H%M'),
        'inqryEndDt': ce.strftime('%Y%m%d%H%M'),
        'numOfRows': '999',
        'type': 'json',
    }
    if extra_params:
        base.update(extra_params)

    p1 = {**base, 'pageNo': '1'}
    body = _g2b_get_safe(url, p1)
    total = int(body.get('totalCount') or 0)
    items = body.get('items') or []
    if isinstance(items, dict):
        items = [items]
    out = list(items)
    pages = math.ceil(total / 999)
    for pg in range(2, pages + 1):
        pp = {**base, 'pageNo': str(pg)}
        b2 = _g2b_get_safe(url, pp)
        it2 = b2.get('items') or []
        if isinstance(it2, dict):
            it2 = [it2]
        if not it2:
            break
        out.extend(it2)
    return out


def fetch_chunked_7d(url: str, start_dt: datetime, end_dt: datetime, label: str = '', max_workers: int = 8) -> tuple[list, list]:
    """G2B API의 7일 제한(resultCode:07)을 피하기 위해 00:00~23:59 기준 6일(days=5) 청크로 병렬 전수 수집."""
    chunks = []
    cs = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    end_aligned = end_dt.replace(hour=23, minute=59, second=0, microsecond=0)
    while cs <= end_aligned:
        ce = min((cs + timedelta(days=5)).replace(hour=23, minute=59), end_aligned)
        chunks.append((cs, ce))
        cs = (ce + timedelta(minutes=1)).replace(hour=0, minute=0)

    collected = []
    failed = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        fut_map = {ex.submit(_fetch_one_chunk, url, c0, c1): (c0, c1) for c0, c1 in chunks}
        for fut in as_completed(fut_map):
            c0, c1 = fut_map[fut]
            try:
                res = fut.result()
                collected.extend(res)
            except Exception as e:
                tag = f'{label} {c0:%Y-%m-%d}~{c1:%Y-%m-%d}: {str(e)[:80]}'
                print(f'    [청크 경고] {tag}')
                failed.append(tag)
    print(f'    · {label}: {len(chunks)}개 청크 → {len(collected):,}건 수집 (실패 {len(failed)}건)')
    return collected, failed


def _compact_scsbid(it: dict) -> dict:
    return {
        'no': str(it.get('bidNtceNo') or '').strip(),
        'ord': str(it.get('bidNtceOrd') or '000').strip(),
        'title': str(it.get('bidNtceNm') or '').strip(),
        'org': str(it.get('dminsttNm') or it.get('ntceInsttNm') or '').strip(),
        'corp': str(it.get('bidwinnrNm') or '').strip(),
        'biz_no': CP.normalize_biz_no(it.get('bidwinnrBizno')),
        'ceo': str(it.get('bidwinnrCeoNm') or '').strip() or None,
        'adrs': str(it.get('bidwinnrAdrs') or '').strip(),
        'amt': A.money(it.get('sucsfbidAmt')),
        'rate': _parse_float(it.get('sucsfbidRate')),
        'n': _parse_int(it.get('prtcptCnum')),
        'open_dt': str(it.get('rlOpengDt') or '').strip(),
        'fnl_dt': str(it.get('fnlSucsfDate') or '').strip(),
        'rgst_dt': str(it.get('rgstDt') or '').strip(),
    }


def _parse_float(v):
    try:
        x = float(str(v).replace(',', '').strip())
        return x if x > 0 else None
    except Exception:
        return None


def _parse_int(v):
    try:
        x = int(float(str(v).replace(',', '').strip()))
        return x if x > 0 else None
    except Exception:
        return None


def _pick_better_scsbid(old: dict | None, new: dict) -> dict:
    """동일 공고번호에 여러 차수/재등록이 있을 경우 금액·최종일이 유효하고 최신인 레코드 선택."""
    if not old:
        return new
    # 더 최신 등록일/낙찰일, 금액 존재 우선
    o_key = (1 if old.get('corp') else 0, 1 if old.get('amt') else 0, old.get('rgst_dt') or '', old.get('ord') or '')
    n_key = (1 if new.get('corp') else 0, 1 if new.get('amt') else 0, new.get('rgst_dt') or '', new.get('ord') or '')
    return new if n_key >= o_key else old


def _parse_openg_corp(it: dict) -> dict | None:
    raw = str(it.get('opengCorpInfo') or '').strip()
    if not raw:
        return None
    f = raw.split('^')
    name = f[0].strip() if len(f) > 0 else ''
    if not name:
        return None
    return {
        'no': str(it.get('bidNtceNo') or '').strip(),
        'title': str(it.get('bidNtceNm') or '').strip(),
        'org': str(it.get('dminsttNm') or it.get('ntceInsttNm') or '').strip(),
        'corp': name,
        'biz_no': CP.normalize_biz_no(f[1] if len(f) > 1 else None),
        'ceo': (f[2].strip() if len(f) > 2 else '') or None,
        'amt': A.money(f[3] if len(f) > 3 else 0),
        'rate': _parse_float(f[4] if len(f) > 4 else None),
        'n': _parse_int(it.get('prtcptCnum')),
        'open_dt': str(it.get('opengDt') or '').strip(),
        'status': str(it.get('progrsDivCdNm') or '').strip(),
    }


def load_g2b_pools(force_refresh: bool = False) -> tuple[dict, dict, dict, dict]:
    """최근 120일 본공고 지역제한 풀 + 2026년 전수 SCSBID/OPENG 풀 로딩(로컬 TTL 캐시 활용)."""
    if not force_refresh and os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, 'r', encoding='utf-8') as f:
                cached = json.load(f)
            gen_str = cached.get('generated_at', '')
            gen_dt = datetime.strptime(gen_str, '%Y-%m-%d %H:%M:%S')
            if (NOW - gen_dt).total_seconds() < CACHE_TTL_HOURS * 3600 and cached.get('scsbid_pool') and not cached.get('failed_chunks'):
                print(f'  - 로컬 G2B 2026 캐시 적중 ({gen_str}, SCSBID {len(cached["scsbid_pool"]):,}건)')
                return (
                    cached.get('bid_scope_map', {}),
                    cached.get('scsbid_pool', {}),
                    cached.get('openg_pool', {}),
                    {'from_cache': True, 'failed_chunks': cached.get('failed_chunks', [])},
                )
        except Exception as e:
            print(f'  [경고] 캐시 읽기 실패 → G2B API 재수집: {e}')

    failed_all = []
    # 1) 최근 120일 본공고 지역제한 판정 풀
    bid_items, f_bid = fetch_chunked_7d(
        R.URL_BID, NOW - timedelta(days=R.LOOKBACK_DAY), NOW, label='본공고(최근120일)', max_workers=8
    )
    failed_all.extend(f_bid)
    bid_scope_map = {}
    for it in bid_items:
        no = str(it.get('bidNtceNo') or '').strip()
        if not no:
            continue
        is_local = bool((it.get('rgnLmtBidLocplcJdgmBssNm') or '').strip())
        bid_scope_map[no] = '지역제한' if is_local else '전국구'

    # 2) 2026-01-01 ~ 현재까지 SCSBID 전수 (7일 청크 병렬)
    y_start = datetime(2026, 1, 1, 0, 0)
    scsbid_items, f_scs = fetch_chunked_7d(
        R.URL_SCSBID, y_start, NOW, label='낙찰정보(SCSBID 2026전수)', max_workers=8
    )
    failed_all.extend(f_scs)
    scsbid_pool = {}
    for it in scsbid_items:
        c = _compact_scsbid(it)
        if not c['no'] or not c['corp']:
            continue
        scsbid_pool[c['no']] = _pick_better_scsbid(scsbid_pool.get(c['no']), c)

    # 3) 최근 120일 OPENG 보강 (노션 개찰결과 빈 행 보충용)
    openg_items, f_op = fetch_chunked_7d(
        R.URL_OPENG, NOW - timedelta(days=R.LOOKBACK_DAY), NOW, label='개찰결과(OPENG 최근120일)', max_workers=8
    )
    failed_all.extend(f_op)
    openg_pool = {}
    for it in openg_items:
        c = _parse_openg_corp(it)
        if c and c['no']:
            openg_pool[c['no']] = c

    cache_obj = {
        'generated_at': f'{NOW:%Y-%m-%d %H:%M:%S}',
        'bid_scope_map': bid_scope_map,
        'scsbid_pool': scsbid_pool,
        'openg_pool': openg_pool,
        'failed_chunks': failed_all,
    }
    with open(CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache_obj, f, ensure_ascii=False)
    print(f'  - G2B 2026 전수 캐시 저장 완료: SCSBID {len(scsbid_pool):,}건 / OPENG {len(openg_pool):,}건 / 지역제한맵 {len(bid_scope_map):,}건')
    return bid_scope_map, scsbid_pool, openg_pool, {'from_cache': False, 'failed_chunks': failed_all}


def is_agency_supplement_bid(item: dict, known_event_biznos: set) -> bool:
    """노션 미수집 G2B 2026 낙찰건 중 웹앱에 포함할 이벤트/홍보/기획사 관련 공고 판정."""
    title = item.get('title') or ''
    if not title:
        return False
    # 제외 키워드(시설·건설·단순물품 등) 우선 배제
    if any(ex in title for ex in R.EXCLUDE_KEYWORDS):
        return False
    # 1) 정본 엔진 이벤트 키워드 통과 시 무조건 채택
    if R.is_event_bid(title):
        return True
    # 2) 이미 노션 DB 이벤트 수주 실적이 검증된 사업자번호(예: 대구 주식회사 렛츠 8098700335)의 홍보/마케팅/박람/개최 용역
    biz_no = item.get('biz_no')
    adrs = item.get('adrs') or ''
    hq = hq_region_of(adrs)
    promo_words = ('홍보', '마케팅', '캠페인', '프로모션', '박람', '축제', '행사', '연출', '개폐회식', '시상식', '문화')
    if biz_no and biz_no in known_event_biznos:
        if any(w in title for w in promo_words):
            return True
    # 3) 대구·경북 소재 업체가 수주한 홍보/프로모션/전시/이벤트성 용역
    if hq in ('대구', '경북') and any(w in title for w in ('홍보 용역', '홍보대행', '홍보 대행', '프로모션', '문화행사', '콘텐츠 운영', '페스타', '페스티벌')):
        return True
    return False


def main():
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)
    force_refresh = '--refresh-g2b' in sys.argv

    print('▶ [1/6] 노션 DB 사전 메타데이터 조회 (읽기 전용)...')
    db_ids = [x for x in (R.DB_ID_GENERAL, R.DB_ID_ARCHIVE, R.DB_ID_PRESPEC) if x]
    meta_before = {db_id: get_db_meta(db_id) for db_id in db_ids}

    print('▶ [2/6] G2B 2026년 전수 SCSBID · 최근 120일 BID/OPENG 수집 (7일 이하 청크)...')
    bid_scope_map, scsbid_pool, openg_pool, g2b_info = load_g2b_pools(force_refresh=force_refresh)

    print('▶ [3/6] 노션 본공고 + 아카이브 DB 읽기 전용 조회 및 SCSBID 보정...')
    won_rows = []
    open_rows = []
    raw_names = []
    max_page_edited = {}
    seen_nos_won = set()
    known_event_biznos = set()

    # v2 호환(노션 원본 기준) 전용 리스트
    v2_orig_rows = []
    scsbid_overridden_count = 0
    openg_filled_count = 0

    for db_label, db_id in (('일반', R.DB_ID_GENERAL), ('아카이브', R.DB_ID_ARCHIVE)):
        if not db_id:
            continue
        pages = R.notion_query_all(db_id)
        max_ed = max((p.get('last_edited_time', '') for p in pages), default='')
        max_page_edited[db_id] = max_ed
        print(f'  - {db_label} DB ({db_id[:8]}…): {len(pages):,}행 조회 완료')

        for p in pages:
            pr = p['properties']
            title = R.get_text(pr, '입찰 공고명').strip()
            org = R.get_text(pr, '공고기관').strip()
            region = ((pr.get('지역') or {}).get('select') or {}).get('name') or ''
            region_inferred = R.region_of(f'{title} {org}') or ''

            posted = R.parse_dt(R.get_text(pr, '게시일시'))
            close_dt = R.parse_dt(R.get_text(pr, '제출일'))
            open_dt_str = R.get_text(pr, '개찰일시').strip()
            open_dt = R.parse_dt(open_dt_str)
            budget = A.money(R.get_text(pr, '사업금액'))
            no = R.get_text(pr, '공고번호').strip()
            link = (pr.get('공고링크') or {}).get('url') or R.bid_detail_url(no) or ''
            interest = bool((pr.get('관심') or {}).get('checkbox'))
            rank_checked = bool((pr.get('개찰확인') or {}).get('checkbox'))
            bid_submitted = bool((pr.get('투찰여부') or {}).get('checkbox'))
            proc_cat = R.get_text(pr, '조달분류').strip()

            scope = bid_scope_map.get(no, '판정불가')
            res_text = R.get_text(pr, '개찰결과')
            res_v2 = CP.parse_result_v2(res_text)
            rank_detail_raw = R.get_text(pr, '순위상세').strip()
            rank_parsed = CP.parse_rank_detail(rank_detail_raw) if rank_detail_raw else []

            month = f'{posted:%Y-%m}' if posted else '미상'
            posted_iso = f'{posted:%Y-%m-%d}' if posted else ''
            close_iso = f'{close_dt:%Y-%m-%d %H:%M}' if close_dt else ''
            open_iso = f'{open_dt:%Y-%m-%d}' if open_dt else ''
            cat = ABI.categorize(title)

            scs = scsbid_pool.get(no)
            opg = openg_pool.get(no)

            # v2 원본 스냅샷 기록
            if res_v2:
                v2_val = res_v2.get('amt') or budget
                v2_orig_rows.append({
                    'title': title,
                    'org': org,
                    'region': region if region else None,
                    'posted': posted,
                    'month': month,
                    'budget': int(budget or 0),
                    'cat': cat,
                    'scope': scope,
                    'no': no,
                    'close': None,
                    'link': link,
                    'corp': res_v2['corp'],
                    'rate': res_v2.get('rate'),
                    'n': res_v2.get('n'),
                    'amt': int(res_v2.get('amt') or 0),
                    'value': int(v2_val or 0),
                })

            # 최종 낙찰자 우선순위: SCSBID(최종낙찰결정) > 노션 개찰결과(res_v2) > OPENG(최근120일)
            eff_corp = None
            eff_ceo = None
            eff_biz_no = None
            eff_adrs = ''
            eff_amt = 0
            eff_rate = None
            eff_n = None
            scsbid_overridden = False
            source_tag = db_label

            if res_v2:
                eff_corp = res_v2['corp']
                eff_ceo = res_v2.get('ceo')
                eff_biz_no = res_v2.get('biz_no')
                eff_amt = res_v2.get('amt') or 0
                eff_rate = res_v2.get('rate')
                eff_n = res_v2.get('n')

                if scs and scs.get('corp'):
                    # 사업자번호·주소·대표자 항상 보강
                    eff_biz_no = scs.get('biz_no') or eff_biz_no
                    eff_ceo = scs.get('ceo') or eff_ceo
                    eff_adrs = scs.get('adrs') or ''
                    if corp_norm_key(scs['corp']) != corp_norm_key(eff_corp):
                        # OPENG 1순위 표기와 최종 낙찰결정(SCSBID)이 다른 경우 → 최종 낙찰자로 교정!
                        eff_corp = scs['corp']
                        scsbid_overridden = True
                        scsbid_overridden_count += 1
                    if scs.get('amt'):
                        eff_amt = scs['amt']
                    if scs.get('rate'):
                        eff_rate = scs['rate']
                    if scs.get('n'):
                        eff_n = eff_n or scs['n']
                elif opg:
                    eff_biz_no = opg.get('biz_no') or eff_biz_no
                    eff_ceo = opg.get('ceo') or eff_ceo
            elif scs and scs.get('corp'):
                # 노션 개찰결과가 비어 있었으나 G2B 최종낙찰에 결과 존재!
                eff_corp = scs['corp']
                eff_ceo = scs.get('ceo')
                eff_biz_no = scs.get('biz_no')
                eff_adrs = scs.get('adrs') or ''
                eff_amt = scs.get('amt') or 0
                eff_rate = scs.get('rate')
                eff_n = scs.get('n')
                openg_filled_count += 1
                source_tag = f'{db_label}(G2B낙찰보강)'
            elif opg and opg.get('corp'):
                eff_corp = opg['corp']
                eff_ceo = opg.get('ceo')
                eff_biz_no = opg.get('biz_no')
                eff_amt = opg.get('amt') or 0
                eff_rate = opg.get('rate')
                eff_n = opg.get('n')
                openg_filled_count += 1
                source_tag = f'{db_label}(G2B개찰보강)'

            if eff_corp:
                if eff_biz_no and (region in ('대구', '경북') or hq_region_of(eff_adrs) in ('대구', '경북')):
                    known_event_biznos.add(eff_biz_no)

                val = eff_amt or budget
                raw_names.append(eff_corp)
                if res_v2 and res_v2.get('corp'):
                    raw_names.append(res_v2['corp'])
                for rp in rank_parsed:
                    if rp.get('corp'):
                        raw_names.append(rp['corp'])

                seen_nos_won.add(no)
                hq_reg = hq_region_of(eff_adrs)
                won_rows.append({
                    'id': p.get('id'),
                    'no': no,
                    'title': title,
                    'org': org,
                    'region': region,
                    'region_inferred': region_inferred,
                    'corp_adrs': eff_adrs,
                    'corp_hq': short_hq_label(eff_adrs),
                    'corp_hq_region': hq_reg,
                    'scope': scope,
                    'posted': posted_iso,
                    'open_dt': open_iso or (scs['open_dt'][:10] if scs and scs.get('open_dt') else ''),
                    'month': month,
                    'budget': int(budget or 0),
                    'amt': int(eff_amt or 0),
                    'value': int(val or 0),
                    'rate': eff_rate,
                    'n': eff_n,
                    'corp': eff_corp,
                    'corp_raw_key': corp_norm_key(eff_corp),
                    'ceo': eff_ceo,
                    'biz_no': eff_biz_no,
                    'notion_corp': res_v2['corp'] if res_v2 else None,
                    'notion_value': int((res_v2.get('amt') or budget) or 0) if res_v2 else None,
                    'notion_rate': res_v2.get('rate') if res_v2 else None,
                    'is_notion_v2': bool(res_v2),
                    'scsbid_overridden': scsbid_overridden,
                    'cat': cat,
                    'proc_cat': proc_cat,
                    'band': A.band(val),
                    'band_ui': ui_amount_band(val),
                    'link': link,
                    'interest': interest,
                    'rank_checked': rank_checked,
                    'bid_submitted': bid_submitted,
                    'source_db': source_tag,
                    'rank_detail_raw': rank_detail_raw,
                    'ranks': [
                        {
                            'rank': rp.get('rank'),
                            'corp': rp.get('corp'),
                            'corp_raw_key': corp_norm_key(rp.get('corp') or ''),
                            'total_score': rp.get('total_score'),
                            'tech_score': rp.get('tech_score'),
                            'price_score': rp.get('price_score'),
                            'biz_no': rp.get('biz_no'),
                        }
                        for rp in rank_parsed
                    ],
                })
            elif close_dt and close_dt >= NOW:
                open_rows.append({
                    'id': p.get('id'),
                    'no': no,
                    'title': title,
                    'org': org,
                    'region': region,
                    'region_inferred': region_inferred,
                    'scope': scope,
                    'posted': posted_iso,
                    'close': close_iso,
                    'close_mmdd': f'{close_dt:%m-%d}',
                    'month': month,
                    'budget': int(budget or 0),
                    'cat': cat,
                    'proc_cat': proc_cat,
                    'band': A.band(budget),
                    'band_ui': ui_amount_band(budget),
                    'link': link,
                    'interest': interest,
                    'source_db': db_label,
                })

    print(f'  - 노션 행 보정 결과: SCSBID 최종낙찰자 교정 {scsbid_overridden_count}건 / 노션 미기재 결과 보강 {openg_filled_count}건')

    print('▶ [4/6] 2026년 G2B 공식 낙찰(SCSBID) 누락분 전국 보강...')
    # 노션에 이미 있는 대구·경북/전국 이벤트사의 biz_no 추가 수집
    for r in won_rows:
        if r.get('biz_no') and R.is_event_bid(r.get('title') or ''):
            known_event_biznos.add(r['biz_no'])

    g2b_added = 0
    for no, scs in scsbid_pool.items():
        if no in seen_nos_won:
            continue
        if not is_agency_supplement_bid(scs, known_event_biznos):
            continue

        title = scs['title']
        org = scs['org']
        reg_inf = R.region_of(f'{title} {org}') or ''
        # 발주기관/공고명 기반 지역 판정 (대구/경북이면 그대로, 아니면 '')
        eff_region = reg_inf if reg_inf in ('대구', '경북') else ''
        hq_reg = hq_region_of(scs.get('adrs'))

        dt_str = scs.get('open_dt') or scs.get('fnl_dt') or scs.get('rgst_dt') or ''
        dt_obj = R.parse_dt(dt_str)
        posted_iso = f'{dt_obj:%Y-%m-%d}' if dt_obj else ''
        month = f'{dt_obj:%Y-%m}' if dt_obj else '미상'
        val = int(scs.get('amt') or 0)
        if val <= 0:
            continue

        corp = scs['corp']
        raw_names.append(corp)
        seen_nos_won.add(no)
        g2b_added += 1

        won_rows.append({
            'id': f'g2b_{no}',
            'no': no,
            'title': title,
            'org': org,
            'region': eff_region,
            'region_inferred': reg_inf,
            'corp_adrs': scs.get('adrs') or '',
            'corp_hq': short_hq_label(scs.get('adrs')),
            'corp_hq_region': hq_reg,
            'scope': bid_scope_map.get(no, '판정불가'),
            'posted': posted_iso,
            'open_dt': posted_iso,
            'month': month,
            'budget': val,
            'amt': val,
            'value': val,
            'rate': scs.get('rate'),
            'n': scs.get('n'),
            'corp': corp,
            'corp_raw_key': corp_norm_key(corp),
            'ceo': scs.get('ceo'),
            'biz_no': scs.get('biz_no'),
            'notion_corp': None,
            'notion_value': None,
            'notion_rate': None,
            'is_notion_v2': False,
            'scsbid_overridden': False,
            'cat': ABI.categorize(title),
            'proc_cat': 'G2B 2026 보강',
            'band': A.band(val),
            'band_ui': ui_amount_band(val),
            'link': R.bid_detail_url(no, scs.get('ord') or '000') or '',
            'interest': False,
            'rank_checked': False,
            'bid_submitted': False,
            'source_db': 'G2B 2026 보강',
            'rank_detail_raw': '',
            'ranks': [],
        })
    print(f'  - 2026년 G2B(1~11월 전국 행사·대행사) 누락 수주건 {g2b_added:,}건 추가 반영 완료')

    print('▶ [5/6] 본사 소재지 마스터 전파 · 동명이사(대표 상이) 분리 · 정규화 매핑 & v2 검증...')
    dir_biz, dir_kc, dir_k = build_hq_directory(scsbid_pool, won_rows)

    # 전 행에 본사 주소/시도/권역/기간파생 전파 (98% 이상 커버리지 확보)
    for r in won_rows:
        rk = r['corp_raw_key']
        ceo = str(r.get('ceo') or '').strip()
        biz = r.get('biz_no')
        # 동일 대표자의 대구·경북 본사가 있으면 우선 적용 (지사 주소 보정 포함)
        rec_dg_ceo = dir_kc.get((rk, ceo)) if ceo else None
        if rec_dg_ceo and sido_of_adrs(rec_dg_ceo['adrs']) in ('대구', '경북'):
            r['corp_adrs'] = rec_dg_ceo['adrs']
            if rec_dg_ceo.get('biz_no'):
                r['biz_no'] = rec_dg_ceo['biz_no']
        elif not r.get('corp_adrs'):
            rec = (dir_biz.get(biz) if biz else None) or (dir_kc.get((rk, ceo)) if ceo else None) or dir_k.get(rk)
            if rec:
                r['corp_adrs'] = rec['adrs']
                r['ceo'] = r.get('ceo') or rec.get('ceo') or None
                r['biz_no'] = r.get('biz_no') or rec.get('biz_no') or None

        r['corp_hq'] = short_hq_label(r.get('corp_adrs'))
        r['corp_hq_region'] = hq_region_of(r.get('corp_adrs'))
        r['corp_sido'] = sido_of_adrs(r.get('corp_adrs'))
        r['corp_zone'] = zone_of_sido(r['corp_sido'])
        yr, hf, qt = period_fields(r.get('month'))
        r['year'] = yr
        r['half'] = hf
        r['quarter'] = qt

    # 동일 corp_raw_key 에 서로 다른 대표자(ceo)의 biz_no 가 2개 이상 존재할 때만 동명이사 분리!
    # (동일 대표자의 본/지사 사업자번호는 분리하지 않고 하나로 통합)
    key_ceo_map = defaultdict(set)
    key_biz_map = defaultdict(lambda: defaultdict(list))
    for r in won_rows:
        if r.get('biz_no'):
            key_biz_map[r['corp_raw_key']][r['biz_no']].append(r)
        if r.get('ceo'):
            key_ceo_map[r['corp_raw_key']].add(str(r['ceo']).strip())

    homonym_split_keys = {
        k for k, bmap in key_biz_map.items()
        if len(bmap) > 1 and len(key_ceo_map.get(k, set())) > 1
    }
    if homonym_split_keys:
        print(f'  - 대표자·사업자 기준 동명이사 분리 감지: {len(homonym_split_keys)}개 상호')

    key_to_display, key_to_aliases = normalize_corp_display_map(raw_names)
    corp_profiles = {}

    for r in won_rows:
        rk = r['corp_raw_key']
        base_disp = key_to_display.get(rk, r['corp'])
        biz = r.get('biz_no')

        if rk in homonym_split_keys and biz:
            hq_lbl = r.get('corp_hq') or '지역미상'
            ceo_lbl = r.get('ceo') or ''
            hq_reg = r.get('corp_hq_region')
            if hq_reg in ('대구', '경북'):
                r['corp_key'] = f'{rk}#{biz}'
                r['corp_norm'] = base_disp
            else:
                suffix = f' ({hq_lbl}·{ceo_lbl})' if ceo_lbl else f' ({hq_lbl})'
                r['corp_key'] = f'{rk}#{biz}'
                r['corp_norm'] = f'{base_disp}{suffix}'
        else:
            r['corp_key'] = rk
            r['corp_norm'] = base_disp

        for rp in r['ranks']:
            rrk = rp['corp_raw_key']
            rp['corp_key'] = rrk
            rp['corp_norm'] = key_to_display.get(rrk, rp['corp'])

        cn = r['corp_norm']
        prof = corp_profiles.setdefault(cn, {
            'biz_no': None, 'ceo': None, 'adrs': '', 'hq': '', 'hq_region': '', 'sido': '미상', 'zone': 'UNKNOWN'
        })
        is_dg_row = r.get('corp_sido') in ('대구', '경북')
        if r.get('biz_no') and (not prof['biz_no'] or is_dg_row):
            prof['biz_no'] = r['biz_no']
        if r.get('ceo') and not prof['ceo']:
            prof['ceo'] = r['ceo']
        if r.get('corp_adrs') and (not prof['adrs'] or is_dg_row):
            prof['adrs'] = r['corp_adrs']
            prof['hq'] = r.get('corp_hq') or ''
            prof['hq_region'] = r.get('corp_hq_region') or ''
            prof['sido'] = r.get('corp_sido') or '미상'
            prof['zone'] = r.get('corp_zone') or 'UNKNOWN'

    # award_report_v2_ⓒ.py와 100% 동일한 방식으로 노션 원본 기준 검증용 스냅샷 계산
    dg_v2_rows = [r for r in v2_orig_rows if r['region'] in ('대구', '경북')]
    dg_stats = A.analyze(dg_v2_rows, v2_orig_rows)
    dg_monthly_summary = [
        {
            'month': m,
            'count': cnt,
            'total': int(tot),
            'top_corp': top[0],
            'top_count': top[1],
        }
        for m, cnt, tot, top in dg_stats.get('monthly', [])
    ]
    dg_top5_raw = [
        {
            'corp': k,
            'count': v['n'],
            'total': int(v['v']),
            'avg_rate': round(sum(v['rates']) / len(v['rates']), 2) if v['rates'] else None,
        }
        for k, v in sorted(dg_stats.get('corp', {}).items(), key=lambda kv: (-kv[1]['n'], -kv[1]['v']))[:5]
    ]

    print('▶ [6/6] 노션 DB 사후 무변경 확인 및 data.json / data.js 저장...')
    meta_after = {db_id: get_db_meta(db_id) for db_id in db_ids}
    db_unchanged = all(
        meta_before[d]['last_edited_time'] == meta_after[d]['last_edited_time']
        for d in db_ids
    )

    completed_months = sorted({
        r['month'] for r in won_rows if r['month'] not in ('미상', f'{NOW:%Y-%m}')
    })
    all_months = sorted({r['month'] for r in won_rows if r['month'] != '미상'})
    all_quarters = sorted({r['quarter'] for r in won_rows if r['quarter'] != '미상'})
    all_halves = sorted({r['half'] for r in won_rows if r['half'] != '미상'})
    all_years = sorted({r['year'] for r in won_rows if r['year'] != '미상'})
    all_sidos = sorted({r['corp_sido'] for r in won_rows if r['corp_sido'] and r['corp_sido'] != '미상'})
    all_cats = sorted({r['cat'] for r in won_rows if r['cat']})

    won_dg_all_count = sum(
        1 for r in won_rows
        if r['region'] in ('대구', '경북') or r.get('corp_hq_region') in ('대구', '경북')
    )

    payload = {
        'meta': {
            'generated_at': f'{NOW:%Y-%m-%d %H:%M:%S}',
            'current_month': f'{NOW:%Y-%m}',
            'lookback_days': R.LOOKBACK_DAY,
            'won_count': len(won_rows),
            'won_v2_count': len(v2_orig_rows),
            'won_dg_count': len(dg_v2_rows),
            'won_dg_all_count': won_dg_all_count,
            'won_nat_count': sum(1 for r in won_rows if r['scope'] == '전국구'),
            'g2b_added_count': g2b_added,
            'scsbid_overridden_count': scsbid_overridden_count,
            'openg_filled_count': openg_filled_count,
            'open_count': len(open_rows),
            'open_dg_count': sum(1 for r in open_rows if r['region'] in ('대구', '경북')),
            'rank_detail_count': sum(1 for r in won_rows if r['ranks']),
            'completed_months': completed_months,
            'all_months': all_months,
            'all_quarters': all_quarters,
            'all_halves': all_halves,
            'all_years': all_years,
            'all_sidos': all_sidos,
            'categories': all_cats,
            'db_unchanged': db_unchanged,
            'db_meta_before': meta_before,
            'db_meta_after': meta_after,
            'max_page_edited': max_page_edited,
            'corp_alias_count': sum(1 for v in key_to_aliases.values() if len(v) > 1),
            'g2b_failed_chunks': g2b_info.get('failed_chunks', []),
        },
        'corp_profiles': corp_profiles,
        'corp_aliases': {
            key_to_display[k]: aliases
            for k, aliases in key_to_aliases.items()
            if len(aliases) > 1
        },
        'v2_validation': {
            'dg_total_count': dg_stats.get('n', 0),
            'dg_total_value': int(dg_stats.get('total', 0)),
            'dg_avg_rate': round(dg_stats.get('rate', 0), 2),
            'dg_avg_comp': round(dg_stats.get('comp', 0), 2) if dg_stats.get('comp') else None,
            'dg_hhi': round(dg_stats.get('hhi', 0), 1),
            'dg_cr4': round(dg_stats.get('cr4', 0), 1),
            'dg_one_win_pct': round(dg_stats.get('one_win', 0), 1),
            'dg_top5_raw': dg_top5_raw,
            'dg_monthly': dg_monthly_summary,
        },
        'won_rows': sorted(won_rows, key=lambda r: (r['posted'] or '', r['no']), reverse=True),
        'open_rows': sorted(open_rows, key=lambda r: (r['close'] or '9999', r['no'])),
    }

    json_path = os.path.join(OUT_DIR, 'data.json')
    js_path = os.path.join(OUT_DIR, 'data.js')

    # data.json = 로컬 분석용 전체본(.gitignore, dg_analysis 입력) / data.js = 공개 배포본(내부 식별자 제거)
    json_text = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    with open(json_path, 'w', encoding='utf-8') as f:
        f.write(json_text)
    write_public_js(payload, js_path)

    elapsed = round(time.time() - t0, 2)
    print(f'\n✅ 내보내기 완료 ({elapsed}초)')
    print(f'   - data.json: {json_path} ({os.path.getsize(json_path)/1024:.1f} KB)')
    print(f'   - data.js  : {js_path} ({os.path.getsize(js_path)/1024:.1f} KB)')
    print(f'   - 개찰결과 : 총 {len(won_rows):,}건 (대구·경북 발주 {len(dg_v2_rows):,}건 / 발주+소재지 통합 {won_dg_all_count:,}건 / 순위상세 {payload["meta"]["rank_detail_count"]}건)')
    print(f'   - 진행중   : 총 {len(open_rows):,}건 (대구·경북 {payload["meta"]["open_dg_count"]}건)')
    print(f'   - 노션 무변경 확인: {db_unchanged}')
    print('   - [v2 대조 검증] 대구·경북 발주처 원본 월별 요약:')
    for m in dg_monthly_summary:
        print(f"     · {m['month']}: {m['count']}건 / {m['total']/1e8:.1f}억 / 최다 {m['top_corp']} ({m['top_count']})")


# 공개 저장소(GitHub Pages)에 올리지 않는 필드 (2026-11-16 ⓒ 검수)
#   id = 노션 페이지 ID, bid_submitted·rank_checked = 사용자의 투찰·개찰확인 활동, 나머지는 화면이 쓰지 않는 필드
PUBLIC_DROP_ROW_KEYS = ('id', 'bid_submitted', 'rank_checked', 'corp_key', 'corp_raw_key', 'open_dt', 'proc_cat', 'region_inferred')
PUBLIC_DROP_META_KEYS = ('db_meta_before', 'db_meta_after', 'max_page_edited')


def write_public_js(payload: dict, js_path: str) -> None:
    """data.js(공개 배포본) 저장 — 노션 DB·페이지 ID 등 내부 식별자와 화면 미사용 필드를 뺀다."""
    pub = {
        'meta': {k: v for k, v in payload['meta'].items() if k not in PUBLIC_DROP_META_KEYS},
        'corp_profiles': payload.get('corp_profiles', {}),
        'won_rows': [{k: v for k, v in r.items() if k not in PUBLIC_DROP_ROW_KEYS} for r in payload['won_rows']],
        'open_rows': [{k: v for k, v in r.items() if k not in PUBLIC_DROP_ROW_KEYS} for r in payload['open_rows']],
    }
    with open(js_path, 'w', encoding='utf-8') as f:
        f.write('window.__BID_DATA__ = ')
        f.write(json.dumps(pub, ensure_ascii=False, separators=(',', ':')))
        f.write(';\n')


def verify_no_secrets():
    """배포 파일에 API 키/비밀 토큰이 포함되지 않았는지 검증한다."""
    patterns = [
        r'ntn_[A-Za-z0-9]{10,}',
        r'secret_[A-Za-z0-9]{10,}',
        r'NOTION_API_KEY',
        r'NARA_JANGTER_API_KEY',
        r'DATA_GO_KR_API_KEY',
        r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',   # 노션 DB·페이지 ID
        r'serviceKey=[A-Za-z0-9%+/=]{20,}',
    ]
    # 손으로 적은 목록 대신 git 이 실제로 올릴 파일 전부를 검사한다 (스크립트 자신은 패턴 문자열을 담고 있어 제외)
    ls = subprocess.run(['git', '-C', OUT_DIR, '-c', 'core.quotepath=false', 'ls-files', '--cached', '--others', '--exclude-standard'],
                        capture_output=True, text=True, encoding='utf-8')
    targets = [t for t in ls.stdout.splitlines() if t and not t.endswith('.py')]
    for fname in targets:
        fpath = os.path.join(OUT_DIR, fname)
        if not os.path.exists(fpath):
            continue
        with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
            txt = f.read()
        for pat in patterns:
            if re.search(pat, txt):
                raise RuntimeError(f'보안 검증 실패: {fname} 내 금지 패턴 발견 ({pat})')
    print('🔒 보안 검증 통과: 비밀키/토큰 노출 0건')


def deploy_to_github():
    """비밀키 0건 검증 후 GitHub(bid-radar)에 커밋 및 푸시한다."""
    verify_no_secrets()
    subprocess.run(['git', '-C', OUT_DIR, 'add', '-A'], check=True)
    status = subprocess.run(['git', '-C', OUT_DIR, 'status', '--porcelain'], capture_output=True, text=True, encoding='utf-8')
    if not status.stdout.strip():
        print('ℹ️ 변경된 파일이 없어 Git 커밋/푸시를 건너뜁니다.')
        return
    msg = f"chore: update bid-radar data ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
    subprocess.run(['git', '-C', OUT_DIR, 'commit', '-m', msg], check=True)
    subprocess.run(['git', '-C', OUT_DIR, 'push', 'origin', 'main'], check=True)
    print('🚀 GitHub Pages(https://kaycomm21.github.io/bid-radar/) 푸시 완료!')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='BID RADAR 데이터 추출 및 GitHub Pages 배포기')
    parser.add_argument('--refresh-g2b', action='store_true', help='G2B 캐시를 무시하고 새로 수집')
    parser.add_argument('--deploy', action='store_true', help='추출 후 비밀키 검증 및 GitHub(main) 자동 푸시')
    args, _ = parser.parse_known_args()
    main()
    if args.deploy:
        deploy_to_github()
