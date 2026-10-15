"""
부서/과제간 협업 AI 요약(2026-10-14) — 보유 전문성 > 조직 분석 > 부서/과제간 협업 아래 "AI 협업 요약".

협업 그래프(collaboration_edges.csv)와 같은 기준(최근 5년, 현재 재직자, Staff·SAIT·Ideation Factory T/F(SAIT)
소속 제외)으로 공저 논문·공동발명 특허를 "문서 단위"로 모아 부서(1단계부서명)/과제(3단계부서명) 쌍별로 집계하고,
아래 항목을 만든다(부서 기준·과제 기준 각각):
  1) 협업 상위 쌍 Top 5 — 논문/특허 수, 최우수·우수 논문 수, LLM이 제목만 보고 요약한 협업 주제 2~3개,
     참여 인원(이름은 데이터에서 직접 붙임 — 최대 3명 + "외 N명")
  2) 허브 단위(협업 상대 단위 수가 많은 순) 3) 협업이 적은 단위
  4) 추세 — 최근 2년 vs 그 이전 3년(연평균) 증가/감소 쌍, 최근 2년에 처음 생긴 협업
  5) 협업 유형(논문 중심/특허 중심) 6) 최우수·우수 논문을 함께 쓴 쌍
  + LLM 개조식 총평(위 통계 + 상위 쌍 주제 기반)

(2026-10-15) 문서 작성 당시(논문 pub_date→announce_date, 특허 application_date) 인력현황 월별 이력상 같은 단위였던
협업은 그 단위 쌍에서 뺀다(pipeline/historical_units.py, 협업 그래프와 같은 기준). 뺀 건수 same_unit_excluded.

⚠️ LLM에는 연구원 이름·사번을 절대 넣지 않는다(부서/과제명, 논문·특허 제목, 건수만). 이름은 결과 JSON에
코드가 직접 붙인다. LLM 실패 시 주제·총평 없이 통계만으로 저장(화면은 통계 기반 문장으로 대체).

출력: data/processed/collab_summary.json — [{'level': 'level1'|'level3', ...}, ...] (load_to_db JSON_TABLES로 DB 적재)
캐시: data/processed/collab_summary_cache.json (프롬프트 해시 → LLM 응답)
실행: run_analysis 4/5(전문성 심화 지표) 직후 자동, 또는 python pipeline/process_collab_summary.py
"""
import hashlib
import json
import os
import sys
from datetime import date, datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT_DIR  # noqa: E402
from llm_client import call_llm, extract_json  # noqa: E402
import process_expertise_metrics as pem  # noqa: E402
from historical_units import doc_date  # noqa: E402

OUTPUT_FILE = 'collab_summary.json'
CACHE_FILE = 'collab_summary_cache.json'
RECENT_YEARS = pem.COLLAB_RECENT_YEARS   # 5년(그래프와 동일)
TREND_RECENT_YEARS = 2                   # 추세: 최근 2년 vs 그 이전 3년
TOP_PAIRS = 5
NAMES_SHOWN = 3
TITLES_PER_PAIR = 12
TOP_GRADES = ('최우수', '우수')

_SYSTEM_PROMPT = """# Role
당신은 R&D 조직의 협업 현황을 분석해 인사·기획 담당자에게 쉽게 설명하는 전문가입니다.

# Input
- 단위(부서 또는 과제) 쌍별 공동 논문·특허 제목과 건수, 그리고 전체 협업 통계가 주어집니다.
- 개인 정보(이름 등)는 주어지지 않으며, 출력에도 넣지 마세요.

# Guidelines
1. pairs: 각 쌍(idx)마다 제목들에서 드러나는 협업 주제를 쉬운 말의 짧은 명사구 2~3개로 쓰세요(제목에 없는 내용 금지).
2. overview: 전체 협업 현황을 개조식 5~7개 항목으로 쓰세요. 항목 하나는 60자 안팎의 명사형 문장으로,
   어떤 단위끼리 어떤 주제로 협업이 많은지, 허브 역할 단위, 협업이 적은 단위, 최근 늘거나 새로 생긴 협업,
   논문/특허 중 어느 쪽 중심인지, 최우수·우수 논문을 함께 낸 협업을 근거 숫자와 함께 다루세요.
3. 주어진 숫자를 바꾸거나 없는 사실을 지어내지 마세요.
4. 반드시 아래 JSON 형식으로만 출력하세요.

# Output Format (JSON)
{"pairs": [{"idx": 0, "topics": ["주제1", "주제2"]}], "overview": ["항목1", "항목2"]}
"""


def _documents(pubs: pd.DataFrame, pats: pd.DataFrame, since: int) -> list:
    """[{'kind':'논문'|'특허','title','year','grade','members':[rid,...]}] — 사내 2명 이상, since년 이후."""
    docs = []
    if not pubs.empty and 'title' in pubs.columns:
        p = pubs[pubs['title'].astype(str).str.strip() != '']
        p = p.assign(_key=p['title'].map(pem._norm) + '|' + pem._col(p, 'pub_date').astype(str).str[:10])
        for _, g in p.groupby('_key'):
            year = max((y for y in map(pem._year_of, list(pem._col(g, 'pub_year')) + list(pem._col(g, 'pub_date')))
                        if y), default=None)
            grades = [str(v).strip() for v in pem._col(g, 'grade_publication')]
            grade = next((gr for gr in TOP_GRADES + ('일반', '외부') if gr in grades), '')
            docs.append({'kind': '논문', 'title': str(g['title'].iloc[0]).strip(), 'year': year, 'grade': grade,
                         'members': sorted(set(g['researcher_id'])),
                         'date': next((x for x in (doc_date(r, 'paper') for r in g.to_dict('records')) if x), '')})
    if not pats.empty and 'application_id' in pats.columns:
        t = pats[pats['application_id'].astype(str).str.strip() != '']
        for _, g in t.groupby('application_id'):
            year = max((y for y in map(pem._year_of, pem._col(g, 'application_date')) if y), default=None)
            title = next((str(v).strip() for c in ('title_ko', 'title') for v in pem._col(g, c) if str(v).strip()), '')
            docs.append({'kind': '특허', 'title': title, 'year': year, 'grade': '',
                         'members': sorted(set(g['researcher_id'])),
                         'date': next((x for x in (doc_date(r, 'patent') for r in g.to_dict('records')) if x), '')})
    return [d for d in docs if d['year'] and d['year'] >= since and 2 <= len(d['members']) <= pem.COLLAB_MAX_GROUP]


def summarize_level(docs: list, unit_of: dict, name_of: dict, all_units: list, this_year: int,
                    same_then=None) -> dict:
    """한 기준(부서 또는 과제)의 통계. unit_of: rid -> 단위명(제외 대상은 없음). all_units: 현재 재직자가 있는 단위.
    same_then(rid_a, rid_b, date) -> bool(2026-10-15): 주면 단위 쌍의 연구원끼리 모두 "문서 작성 당시 같은 단위"였던
    건은 그 단위 쌍 협업에서 뺀다(한 쌍이라도 당시 다른 단위였거나 판정 불가면 포함). 뺀 건수는 same_unit_excluded."""
    pairs: dict = {}
    excluded = 0
    for d in docs:
        by_unit: dict = {}
        for rid in d['members']:
            u = unit_of.get(rid)
            if u:
                by_unit.setdefault(u, set()).add(rid)
        units = sorted(by_unit)
        for i, a in enumerate(units):
            for b in units[i + 1:]:
                if same_then is not None and d.get('date') and all(
                        same_then(x, y, d['date']) for x in by_unit[a] for y in by_unit[b]):
                    excluded += 1
                    continue
                p = pairs.setdefault((a, b), {'docs': [], 'people': {}})
                p['docs'].append(d)
                for rid in by_unit[a] | by_unit[b]:
                    p['people'][rid] = p['people'].get(rid, 0) + 1
    recent_from = this_year - TREND_RECENT_YEARS + 1

    def _pair_row(a, b, p):
        papers = sum(1 for d in p['docs'] if d['kind'] == '논문')
        patents = len(p['docs']) - papers
        recent = sum(1 for d in p['docs'] if d['year'] >= recent_from)
        people = sorted(p['people'], key=lambda r: (-p['people'][r], name_of.get(r, r)))
        names = [name_of.get(r, '') for r in people if name_of.get(r)]
        return {'a': a, 'b': b, 'total': len(p['docs']), 'papers': papers, 'patents': patents,
                'top_grade': sum(1 for d in p['docs'] if d['grade'] in TOP_GRADES),
                'recent': recent, 'prior': len(p['docs']) - recent,
                'people': names[:NAMES_SHOWN], 'people_more': max(len(names) - NAMES_SHOWN, 0),
                'titles': [f"[{d['kind']}] {d['title'][:80]}" for d in
                           sorted(p['docs'], key=lambda d: -d['year'])[:TITLES_PER_PAIR]]}

    rows = sorted((_pair_row(a, b, p) for (a, b), p in pairs.items()), key=lambda r: (-r['total'], r['a'], r['b']))
    partners: dict = {}
    for r in rows:
        for u, v in ((r['a'], r['b']), (r['b'], r['a'])):
            partners.setdefault(u, {})[v] = r['total']
    hubs = sorted(({'unit': u, 'partners': len(ps), 'docs': sum(ps.values())} for u, ps in partners.items()),
                  key=lambda h: (-h['partners'], -h['docs'], h['unit']))[:3]
    low = [u for u in all_units if u not in partners][:10]
    if len(low) < 3:   # 협업 0인 단위가 거의 없으면 협업 상대가 가장 적은 단위
        low += [h['unit'] for h in sorted(({'unit': u, 'n': sum(ps.values())} for u, ps in partners.items()),
                                          key=lambda h: (h['n'], h['unit']))[:3 - len(low)]]

    def _rate(r):   # 연평균 비교: 최근 2년 vs 그 이전 3년
        return r['recent'] / TREND_RECENT_YEARS, r['prior'] / (RECENT_YEARS - TREND_RECENT_YEARS)

    new_pairs = [r for r in rows if r['prior'] == 0 and r['recent'] > 0][:5]
    rising = [r for r in rows if r['prior'] > 0 and r['recent'] >= 2 and _rate(r)[0] >= 1.5 * _rate(r)[1]][:5]
    falling = [r for r in rows if r['prior'] >= 3 and _rate(r)[0] <= 0.5 * _rate(r)[1]][:5]
    involved = {id(d): d for p in pairs.values() for d in p['docs']}
    slim = lambda r: {k: r[k] for k in ('a', 'b', 'total', 'papers', 'patents', 'recent', 'prior', 'top_grade')}  # noqa: E731
    return {
        'pair_count': len(rows),
        'doc_count': len(involved),
        'same_unit_excluded': excluded,
        'papers': sum(1 for d in involved.values() if d['kind'] == '논문'),
        'patents': sum(1 for d in involved.values() if d['kind'] == '특허'),
        'top_pairs': rows[:TOP_PAIRS],
        'hubs': hubs, 'low': low[:5],
        'new_pairs': [slim(r) for r in new_pairs], 'rising': [slim(r) for r in rising],
        'falling': [slim(r) for r in falling],
        'top_grade_pairs': [slim(r) for r in sorted(rows, key=lambda r: -r['top_grade']) if r['top_grade']][:5],
    }


def _stats_text(s: dict, unit: str) -> str:
    """LLM 입력용 통계(이름 없음)."""
    fmt = lambda r: f"{r['a']} ↔ {r['b']}(총 {r['total']}: 논문 {r['papers']}·특허 {r['patents']}, 최근2년 {r['recent']}·이전3년 {r['prior']})"  # noqa: E731
    lines = [f'기준 단위: {unit}', f"단위 간 협업 쌍 {s['pair_count']}개, 협업 문서 {s['doc_count']}건(논문 {s['papers']}, 특허 {s['patents']})",
             '허브: ' + (', '.join(f"{h['unit']}(상대 {h['partners']}곳, {h['docs']}건)" for h in s['hubs']) or '없음'),
             '협업이 적은 단위: ' + (', '.join(s['low']) or '없음'),
             '최근 2년에 새로 생긴 협업: ' + ('; '.join(map(fmt, s['new_pairs'])) or '없음'),
             '최근 늘어난 협업: ' + ('; '.join(map(fmt, s['rising'])) or '없음'),
             '최근 줄어든 협업: ' + ('; '.join(map(fmt, s['falling'])) or '없음'),
             '최우수·우수 논문을 함께 낸 쌍: ' + ('; '.join(f"{r['a']} ↔ {r['b']}({r['top_grade']}편)" for r in s['top_grade_pairs']) or '없음')]
    for i, r in enumerate(s['top_pairs']):
        lines.append(f"\n[{i}] {fmt(r)}\n" + '\n'.join(f'  - {t}' for t in r['titles']))
    return '\n'.join(lines)


def fallback_overview(s: dict, unit: str) -> list:
    """LLM 실패 시 통계만으로 만든 개조식 문장."""
    out = []
    if s['top_pairs']:
        r = s['top_pairs'][0]
        out.append(f"가장 협업이 많은 {unit}: {r['a']} ↔ {r['b']} (최근 5년 {r['total']}건)")
    if s['hubs']:
        h = s['hubs'][0]
        out.append(f"허브 {unit}: {h['unit']} (협업 상대 {h['partners']}곳, {h['docs']}건)")
    if s['papers'] or s['patents']:
        out.append(f"협업 유형: 논문 {s['papers']}건 · 특허 {s['patents']}건 "
                   f"({'논문' if s['papers'] >= s['patents'] else '특허'} 중심)")
    if s['new_pairs']:
        out.append('최근 2년 새로 생긴 협업: ' + ', '.join(f"{r['a']} ↔ {r['b']}" for r in s['new_pairs'][:3]))
    if s['low']:
        out.append(f'협업이 적은 {unit}: ' + ', '.join(s['low'][:5]))
    return out


def _llm(s: dict, unit: str, cache: dict) -> dict | None:
    prompt = _stats_text(s, unit)
    key = hashlib.sha256((_SYSTEM_PROMPT + prompt).encode('utf-8')).hexdigest()
    if key in cache:
        return cache[key]
    raw = call_llm(prompt, _SYSTEM_PROMPT, temperature=0.2, max_tokens=3000)
    if not raw:
        return None
    try:
        data = json.loads(extract_json(raw))
    except json.JSONDecodeError:
        return None
    cache[key] = data
    return data


def build(researchers: pd.DataFrame, pubs: pd.DataFrame, pats: pd.DataFrame, levels: dict,
          use_llm: bool = True, cache: dict | None = None, today: date | None = None, history=None) -> list:
    today = today or date.today()
    since = today.year - RECENT_YEARS + 1
    docs = _documents(pubs, pats, since)
    name_of = dict(zip(researchers['researcher_id'], researchers.get('name', pd.Series(dtype=str)).astype(str))) \
        if not researchers.empty else {}
    cache = {} if cache is None else cache
    out = []
    for level, idx, unit in (('level1', 0, '부서'), ('level3', 1, '과제')):
        unit_of = {rid: lv[idx] for rid, lv in levels.items() if lv[idx]}
        if level == 'level3':   # 구성원 1명인 과제는 제외(2026-10-15, 화면 그래프와 같은 기준)
            from collections import Counter
            size = Counter(unit_of.values())
            unit_of = {rid: u for rid, u in unit_of.items() if size[u] > 1}
        all_units = sorted(set(unit_of.values()))
        same_then = None
        if history is not None and getattr(history, 'available', False):   # 당시 같은 단위였던 협업 제외(2026-10-15)
            same_then = (lambda x, y, dt, k=idx: history.same_at(x, y, dt)[0 if k == 0 else 1])
        s = summarize_level(docs, unit_of, name_of, all_units, today.year, same_then)
        res = _llm(s, unit, cache) if use_llm and s['top_pairs'] else None
        topics = {}
        for p in (res or {}).get('pairs') or []:
            try:
                topics[int(p.get('idx'))] = [str(t).strip() for t in p.get('topics') or [] if str(t).strip()][:3]
            except (TypeError, ValueError):
                continue
        for i, r in enumerate(s['top_pairs']):
            r['topics'] = topics.get(i, [])
            r.pop('titles', None)   # 화면엔 주제만(제목 목록은 저장하지 않음)
        overview = [str(x).strip().lstrip('-•· ').strip() for x in (res or {}).get('overview') or [] if str(x).strip()]
        out.append({'level': level, 'unit': unit, 'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
                    'period': f'{since}~{today.year}', 'llm': bool(overview),
                    'overview': overview or fallback_overview(s, unit), **s})
    return out


def process() -> bool:
    researchers = pem._read_csv('researchers')
    pubs, pats = pem._read_csv('publications'), pem._read_csv('patents')
    if pubs.empty and pats.empty:
        print('  [WARN] publications/patents.csv 없음 — 협업 AI 요약 생략')
        return False
    levels = pem.current_levels(researchers)
    if not levels:
        print('  [WARN] 팀/리더 참조 매칭 없음 — 협업 AI 요약 생략')
        return False
    cache = pem._read_json(CACHE_FILE, {})
    import historical_units
    result = build(researchers, pubs, pats, levels, cache=cache, history=historical_units.load())
    pem._write_json(CACHE_FILE, cache)
    pem._write_json(OUTPUT_FILE, result)
    for r in result:
        print(f"[OK]   {OUTPUT_FILE} — {r['unit']} 기준 협업 쌍 {r['pair_count']}개, 상위 {len(r['top_pairs'])}쌍"
              f"{'' if r['llm'] else ' (LLM 응답 없음 — 통계 기반 요약으로 저장)'}")
    return True


if __name__ == '__main__':
    process()
