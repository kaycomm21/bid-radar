# -*- coding: utf-8 -*-
"""
ⓒ_261117_fetch_ranks.py — 공고별 「참가 업체 전체 순위 + 기술·가격·종합 점수」 수집기 (이어받기 가능)
API: 나라장터 낙찰정보서비스 getOpengResultListInfoOpengCompt (공고번호 1건당 1회 호출, 읽기 전용)
입력: data.json(2026) + history_rows.json(2020~2025)   출력: g2b_ranks_cache.json(로컬), ranks.js(공개)
실행: python "ⓒ_261117_fetch_ranks.py" [최대 호출 수=4000]
  - 이미 받은 공고는 건너뛴다. 일일 호출 한도에 걸리면 그때까지 저장하고 멈춘다 → 다음 날 다시 실행하면 이어받는다.
  - 우선순위: 대구·경북 관련 → 2026년 → 과거 연도(금액 큰 순). 참가 1개사(단독응찰)는 순위가 의미 없어 건너뛴다.
  - `--build-only` : 호출 없이 캐시로 ranks.js 만 다시 만든다.
"""
import importlib
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import urllib3

urllib3.disable_warnings()
APP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP)
E = importlib.import_module('ⓐ_261113_export_data')
R = E.R
URL = 'https://apis.data.go.kr/1230000/as/ScsbidInfoService/getOpengResultListInfoOpengCompt'
CACHE = os.path.join(APP, 'g2b_ranks_cache.json')
MAX_BIDDERS = 12          # 가격입찰은 참가자가 수백 곳일 수 있어 상위 12곳만 저장(전체 참가 수는 따로 기록)
BUILD_ONLY = '--build-only' in sys.argv
MAX_CALLS = next((int(a) for a in sys.argv[1:] if a.isdigit()), 4000)


class QuotaExceeded(Exception):
    pass


def num(v):
    try:
        x = float(str(v).replace(',', '').strip())
        return round(x, 4) if x else None
    except Exception:
        return None


def fetch(no):
    """한 공고의 전체 순위. 반환: {'t': 참가 수, 'r': [[순위, 업체, 사업자번호, 투찰금액, 기술, 가격, 종합, 비고]]}"""
    p = {'serviceKey': R.G2B_API_KEY, 'bidNtceNo': no, 'pageNo': '1', 'numOfRows': '100', 'type': 'json'}
    delay = 2.0
    for attempt in range(4):
        try:
            r = requests.get(URL, params=p, verify=False, timeout=45)
            if r.status_code == 429:
                raise QuotaExceeded('HTTP 429')
            js = r.json()
            if 'OpenAPI_ServiceResponse' in js:
                h = js['OpenAPI_ServiceResponse'].get('cmmMsgHeader', {})
                if str(h.get('returnReasonCode')) in ('22', '23') or 'LIMITED' in str(h.get('errMsg')):
                    raise QuotaExceeded(str(h.get('returnAuthMsg') or h.get('errMsg')))
                raise RuntimeError(f"게이트웨이 오류 {h.get('returnReasonCode')}")
            if 'response' not in js:
                raise RuntimeError('오류 응답 ' + json.dumps(js, ensure_ascii=False)[:80])
            body = js['response'].get('body', {}) or {}
            items = body.get('items') or []
            if isinstance(items, dict):
                items = [items]
            # 재입찰·차수가 여러 개면 가장 마지막 차수·재입찰 번호만 쓴다
            if items:
                last = max((str(i.get('bidNtceOrd') or ''), str(i.get('rbidNo') or '')) for i in items)
                items = [i for i in items if (str(i.get('bidNtceOrd') or ''), str(i.get('rbidNo') or '')) == last]
            rows = []
            for i in items:
                rk = num(i.get('opengRank'))
                rows.append([int(rk) if rk else None, str(i.get('prcbdrNm') or '').strip(), str(i.get('prcbdrBizno') or '').strip(),
                             num(i.get('bidprcAmt')), num(i.get('techEvlVal')), num(i.get('bidPrceEvlVal')),
                             num(i.get('totalEvlAmtVal')), str(i.get('rmrk') or '').strip()])
            rows.sort(key=lambda x: (x[0] is None, x[0] or 0))
            return {'t': int(body.get('totalCount') or len(rows)), 'r': rows[:MAX_BIDDERS]}
        except QuotaExceeded:
            raise
        except Exception:
            if attempt == 3:
                raise
            time.sleep(delay)
            delay *= 1.8


def load_targets():
    cur = json.load(open(os.path.join(APP, 'data.json'), encoding='utf-8'))['won_rows']
    hp = os.path.join(APP, 'history_rows.json')
    hist = json.load(open(hp, encoding='utf-8')) if os.path.exists(hp) else []
    dg = ('대구', '경북')

    def prio(r, is_cur):
        is_dg = r.get('region') in dg or r.get('corp_sido') in dg
        return (0 if is_dg else (1 if is_cur else 2), -(r.get('value') or 0))
    pool = [(prio(r, True), r) for r in cur] + [(prio(r, False), r) for r in hist]
    pool = [x for x in pool if (x[1].get('n') or 0) != 1 and x[1].get('no')]
    pool.sort(key=lambda x: x[0])
    return [r['no'] for _, r in pool], {r['no'] for r in cur} | {r['no'] for r in hist}


def build_js(cache, valid_nos):
    """공개본: 사업자번호는 빼고 업체명·점수만. {공고번호: [참가 수, [[순위, 업체, 투찰금액, 기술, 가격, 종합, 비고]]]}"""
    out = {}
    for no, v in cache.items():
        if no in valid_nos and v and v.get('r'):
            out[no] = [v['t'], [[x[0], x[1], x[3], x[4], x[5], x[6], '' if x[7] == '정상' else x[7]] for x in v['r']]]
    path = os.path.join(APP, 'ranks.js')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('window.__BID_RANKS__ = ' + json.dumps(out, ensure_ascii=False, separators=(',', ':')) + ';\n')
    scored = sum(1 for v in out.values() if any(x[5] is not None for x in v[1]))
    print(f'ranks.js: 공고 {len(out):,}건 (종합점수 있는 공고 {scored:,}건) / {os.path.getsize(path)/1e6:.2f} MB')


def main():
    cache = json.load(open(CACHE, encoding='utf-8')) if os.path.exists(CACHE) else {}
    targets, valid = load_targets()
    todo = [no for no in targets if no not in cache]
    print(f'대상 {len(targets):,}건 / 수집 완료 {len(targets) - len(todo):,}건 / 남음 {len(todo):,}건')
    if not BUILD_ONLY and todo:
        todo = todo[:MAX_CALLS]
        lock, stop = threading.Lock(), threading.Event()
        done = fail = 0
        t0 = time.time()

        def work(no):
            if stop.is_set():
                return no, None, 'skip'
            try:
                return no, fetch(no), None
            except QuotaExceeded as e:
                stop.set()
                return no, None, f'quota: {e}'
            except Exception as e:
                return no, None, str(e)[:60]

        with ThreadPoolExecutor(max_workers=6) as ex:
            for fut in as_completed([ex.submit(work, no) for no in todo]):
                no, res, err = fut.result()
                with lock:
                    if res is not None:
                        cache[no] = res
                        done += 1
                        if done % 500 == 0:
                            json.dump(cache, open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
                            print(f'  · {done:,}건 수집 ({time.time() - t0:.0f}초)')
                    elif err and err != 'skip':
                        fail += 1
                        if err.startswith('quota'):
                            print(f'  [한도 도달] {err} — 여기까지 저장하고 멈춥니다. 내일 다시 실행하면 이어받습니다.')
        json.dump(cache, open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
        print(f'이번 실행: 수집 {done:,}건 / 실패 {fail:,}건 / {time.time() - t0:.0f}초 / 남음 {sum(1 for n in targets if n not in cache):,}건')
    build_js(cache, valid)


if __name__ == '__main__':
    main()
