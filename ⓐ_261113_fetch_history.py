# -*- coding: utf-8 -*-
"""ⓐ G2B SCSBID 과거 이력 수집/보충 (5개년 주요 입찰 수주사 분석용)
사용: python ⓐ_261113_fetch_history.py [시작 YYYY-MM-DD] [종료 YYYY-MM-DD]
- 기존 캐시에 병합(merge)하며, 일일 호출한도 초과(429) 등 실패 청크는 failed 목록에 기록된다.
- 기본값: 2025-04-01 ~ 2025-12-31 (2026-11-13 수집 시 일일 한도 초과로 누락된 구간 보충)
"""
import sys, os, json, time, importlib
from datetime import datetime
APP = r'G:\내 드라이브\00_AgenticAI_Share\03-이벤트기획 사업부\ⓐ_수주현황웹앱'
sys.path.insert(0, APP)
E = importlib.import_module('ⓐ_261113_export_data')

OUT = os.path.join(APP, 'g2b_history_2021_2025_cache.json')
start = datetime.strptime(sys.argv[1], '%Y-%m-%d') if len(sys.argv) > 1 else datetime(2025, 4, 1)
end = datetime.strptime(sys.argv[2], '%Y-%m-%d') if len(sys.argv) > 2 else datetime(2025, 12, 31)

old = {'items': [], 'failed': []}
if os.path.exists(OUT):
    old = json.load(open(OUT, encoding='utf-8'))
pool = {i['no']: i for i in old.get('items', []) if i.get('no')}

t0 = time.time()
rows, failed = E.fetch_chunked_7d(E.R.URL_SCSBID, start, end, f'SCSBID {start:%Y-%m-%d}~{end:%Y-%m-%d}', max_workers=6)
for it in rows:
    c = E._compact_scsbid(it)
    if c['no']:
        pool[c['no']] = E._pick_better_scsbid(pool.get(c['no']), c)
with open(OUT, 'w', encoding='utf-8') as f:
    json.dump({'generated_at': datetime.now().isoformat(timespec='seconds'), 'failed': failed, 'items': list(pool.values())},
              f, ensure_ascii=False, separators=(',', ':'))
print(f'DONE new_raw={len(rows):,} total_unique={len(pool):,} failed={len(failed)} elapsed={time.time()-t0:.1f}s')
