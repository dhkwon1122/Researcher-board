"""
논문·특허 자산화 AI 요약(2026-10-15) — 보유 전문성 > 조직(플랫폼/과제) > 논문,특허(플랫폼/과제) 아래 "AI 자산화 요약".

화면 그래프(services/publication_quality.asset_counts)와 같은 기준 — 최근 5년(논문 실적일·특허 출원일), 현재 재직자,
Staff·SAIT·Ideation Factory T/F(SAIT) 소속 제외, 과제 기준은 구성원 1명 과제 제외, 같은 단위 안 공저·공동발명은 1건
(다른 단위끼리는 각 단위에 1건씩). 부서(1단계부서명)/과제(3단계부서명) 기준 각각 아래를 만든다(사용자 확정 항목):
  1) LLM 개조식 총평
  2) 상위 등급 실적 Top 5 — 최우수·우수 논문 + 전략·A1 특허 수 기준
  3) 추세 — 최근 2년 vs 그 이전 3년(연평균) 늘어난/줄어든 단위
  5) 실적이 적은 단위 — 최근 5년 논문+특허 1건 이하
  6) 인당 생산성 — 구성원 수 대비 논문+특허 건수(상위·하위)
  7) 주요 주제 — 상위 등급 Top 5 단위의 최우수·우수 논문 제목에서 LLM이 뽑은 주제 2~3개

⚠️ LLM에는 연구원 이름·사번을 넣지 않는다(부서/과제명, 논문 제목, 건수·인원 수만).
LLM 실패 시 주제·총평 없이 통계만으로 저장(화면은 통계 기반 문장으로 대체).

출력: data/processed/asset_summary.json — [{'level': 'level1'|'level3', ...}] (load_to_db JSON_TABLES로 DB 적재)
캐시: data/processed/asset_summary_cache.json (프롬프트 해시 → LLM 응답)
실행: run_analysis 4/5+(협업 AI 요약 다음) 자동, 또는 python pipeline/process_asset_summary.py
"""
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import date, datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT_DIR  # noqa: E402,F401
from llm_client import call_llm, extract_json  # noqa: E402
import process_expertise_metrics as pem  # noqa: E402

OUTPUT_FILE = 'asset_summary.json'
CACHE_FILE = 'asset_summary_cache.json'
RECENT_YEARS = 5
TREND_RECENT_YEARS = 2
TOP_N = 5
TITLES_PER_UNIT = 12
PAPER_GRADES = ['최우수', '우수', '일반', '외부']
PATENT_GRADES = ['전략', 'A1', 'A2', '기타']
TOP_PAPER = ('최우수', '우수')
TOP_PATENT = ('전략', 'A1')

_SYSTEM_PROMPT = """# Role
당신은 R&D 조직의 논문·특허 자산화 현황을 분석해 인사·기획 담당자에게 쉽게 설명하는 전문가입니다.

# Input
- 단위(부서 또는 과제)별 최근 5년 논문(등급: 최우수>우수>일반>외부)·특허(등급: 전략>A1>A2>기타) 건수,
  구성원 수, 추세 통계, 그리고 상위 단위의 최우수·우수 논문 제목이 주어집니다.
- 개인 정보(이름 등)는 주어지지 않으며, 출력에도 넣지 마세요.

# Guidelines
1. units: 각 단위(idx)마다 논문 제목들에서 드러나는 연구 주제를 쉬운 말의 짧은 명사구 2~3개로 쓰세요(제목에 없는 내용 금지).
2. overview: 전체 자산화 현황을 개조식 5~7개 항목으로 쓰세요. 항목 하나는 60자 안팎의 명사형 문장으로,
   전체 규모와 상위 등급 비중, 상위 등급 실적이 많은 단위와 그 주제, 최근 늘거나 줄어든 단위,
   실적이 적은 단위, 인당 생산성이 높은 단위를 근거 숫자와 함께 다루세요.
3. 주어진 숫자를 바꾸거나 없는 사실을 지어내지 마세요.
4. 반드시 아래 JSON 형식으로만 출력하세요.

# Output Format (JSON)
{"units": [{"idx": 0, "topics": ["주제1", "주제2"]}], "overview": ["항목1", "항목2"]}
"""


def _patent_grade(row) -> str:
    if str(row.get('patent_grade_a_sub') or '').strip() == '전략출원':
        return '전략'
    g = str(row.get('patent_grade') or '').strip().upper()
    return g if g in ('A1', 'A2') else '기타'


def unit_records(unit_of: dict, pubs: pd.DataFrame, pats: pd.DataFrame, since: int) -> dict:
    """단위 → {'papers': [(year, grade, title)], 'patents': [(year, grade)]} — 같은 단위 안 중복 제거."""
    out: dict = {}
    if not pubs.empty and 'title' in pubs.columns:
        seen = set()
        for r in pubs.fillna('').to_dict('records'):
            unit = unit_of.get(r.get('researcher_id'))
            grade = str(r.get('grade_publication') or '').strip()
            y = pem._year_of(r.get('pub_year')) or pem._year_of(r.get('pub_date'))
            title = str(r.get('title') or '').strip()
            if not unit or grade not in PAPER_GRADES or not y or y < since or not title:
                continue
            if (unit, title.lower()) in seen:
                continue
            seen.add((unit, title.lower()))
            out.setdefault(unit, {'papers': [], 'patents': []})['papers'].append((y, grade, title))
    if not pats.empty and 'application_id' in pats.columns:
        seen = set()
        for r in pats.fillna('').to_dict('records'):
            unit = unit_of.get(r.get('researcher_id'))
            app = str(r.get('application_id') or '').strip()
            y = pem._year_of(r.get('application_date'))
            if not unit or not app or not y or y < since or (unit, app) in seen:
                continue
            seen.add((unit, app))
            out.setdefault(unit, {'papers': [], 'patents': []})['patents'].append((y, _patent_grade(r)))
    return out


def summarize_level(records: dict, sizes: dict, this_year: int) -> dict:
    recent_from = this_year - TREND_RECENT_YEARS + 1
    rows = []
    for unit, size in sizes.items():
        rec = records.get(unit, {'papers': [], 'patents': []})
        pg = Counter(g for _, g, _ in rec['papers'])
        tg = Counter(g for _, g in rec['patents'])
        years = [y for y, _, _ in rec['papers']] + [y for y, _ in rec['patents']]
        recent = sum(1 for y in years if y >= recent_from)
        total = len(years)
        rows.append({
            'unit': unit, 'members': size,
            'papers': len(rec['papers']), 'patents': len(rec['patents']), 'total': total,
            'paper_grades': {g: pg.get(g, 0) for g in PAPER_GRADES},
            'patent_grades': {g: tg.get(g, 0) for g in PATENT_GRADES},
            'top': sum(pg.get(g, 0) for g in TOP_PAPER) + sum(tg.get(g, 0) for g in TOP_PATENT),
            'recent': recent, 'prior': total - recent,
            'per_capita': round(total / size, 2) if size else 0.0,
            'titles': [t for _, g, t in sorted(rec['papers'], key=lambda x: (PAPER_GRADES.index(x[1]), -x[0]))
                       if g in TOP_PAPER][:TITLES_PER_UNIT],
        })
    prior_years = RECENT_YEARS - TREND_RECENT_YEARS

    def _rates(r):
        return r['recent'] / TREND_RECENT_YEARS, r['prior'] / prior_years
    rising = [r for r in rows if r['recent'] >= 2 and _rates(r)[0] >= 1.5 * _rates(r)[1]]
    falling = [r for r in rows if r['prior'] >= 3 and _rates(r)[0] <= 0.5 * _rates(r)[1]]
    rising.sort(key=lambda r: -(_rates(r)[0] - _rates(r)[1]))
    falling.sort(key=lambda r: (_rates(r)[0] - _rates(r)[1]))
    top_units = sorted([r for r in rows if r['top']], key=lambda r: (-r['top'], -r['total'], r['unit']))[:TOP_N]
    capita = sorted([r for r in rows if r['members'] > 1 or r['total']], key=lambda r: (-r['per_capita'], r['unit']))
    slim = lambda r: {k: v for k, v in r.items() if k != 'titles'}  # noqa: E731
    pg_all = Counter()
    tg_all = Counter()
    for r in rows:
        pg_all.update(r['paper_grades'])
        tg_all.update(r['patent_grades'])
    return {
        'unit_count': len(rows),
        'papers': sum(r['papers'] for r in rows), 'patents': sum(r['patents'] for r in rows),
        'paper_grades': {g: pg_all.get(g, 0) for g in PAPER_GRADES},
        'patent_grades': {g: tg_all.get(g, 0) for g in PATENT_GRADES},
        'top_units': [dict(slim(r), titles=r['titles']) for r in top_units],
        'rising': [slim(r) for r in rising[:TOP_N]],
        'falling': [slim(r) for r in falling[:TOP_N]],
        'low': [r['unit'] for r in sorted(rows, key=lambda r: (r['total'], r['unit'])) if r['total'] <= 1],
        'per_capita_top': [slim(r) for r in capita[:TOP_N]],
        # 하위는 상위에 든 단위와 겹치지 않게(단위가 10개 미만이면 남은 것만)
        'per_capita_bottom': [slim(r) for r in capita[max(TOP_N, len(capita) - TOP_N):][::-1]],
    }


def _grades_text(d: dict) -> str:
    return '·'.join(f'{g} {n}' for g, n in d.items())


def _stats_text(s: dict, unit: str) -> str:
    """LLM 입력용 통계(이름 없음)."""
    fmt = lambda r: (f"{r['unit']}(구성원 {r['members']}명, 논문 {r['papers']}[{_grades_text(r['paper_grades'])}], "  # noqa: E731
                     f"특허 {r['patents']}[{_grades_text(r['patent_grades'])}], 최근2년 {r['recent']}·이전3년 {r['prior']}, "
                     f"인당 {r['per_capita']}건)")
    lines = [f'기준 단위: {unit} ({s["unit_count"]}개)',
             f"전체: 논문 {s['papers']}건[{_grades_text(s['paper_grades'])}], 특허 {s['patents']}건[{_grades_text(s['patent_grades'])}]",
             '최근 늘어난 단위: ' + ('; '.join(map(fmt, s['rising'])) or '없음'),
             '최근 줄어든 단위: ' + ('; '.join(map(fmt, s['falling'])) or '없음'),
             '실적이 적은 단위(1건 이하): ' + (', '.join(s['low']) or '없음'),
             '인당 생산성 상위: ' + ('; '.join(map(fmt, s['per_capita_top'])) or '없음'),
             '인당 생산성 하위: ' + ('; '.join(map(fmt, s['per_capita_bottom'])) or '없음'),
             '상위 등급(최우수·우수 논문 + 전략·A1 특허) 실적 상위 단위:']
    for i, r in enumerate(s['top_units']):
        lines.append(f"\n[{i}] {fmt(r)}, 상위 등급 {r['top']}건\n" + '\n'.join(f'  - {t}' for t in r['titles']))
    return '\n'.join(lines)


def fallback_overview(s: dict, unit: str) -> list:
    """LLM 실패 시 통계만으로 만든 개조식 문장."""
    out = [f"최근 5년 논문 {s['papers']}건(최우수·우수 {s['paper_grades']['최우수'] + s['paper_grades']['우수']}건), "
           f"특허 {s['patents']}건(전략·A1 {s['patent_grades']['전략'] + s['patent_grades']['A1']}건)"]
    if s['top_units']:
        r = s['top_units'][0]
        out.append(f"상위 등급 실적이 가장 많은 {unit}: {r['unit']} ({r['top']}건)")
    if s['rising']:
        out.append(f'최근 2년 늘어난 {unit}: ' + ', '.join(r['unit'] for r in s['rising'][:3]))
    if s['falling']:
        out.append(f'최근 2년 줄어든 {unit}: ' + ', '.join(r['unit'] for r in s['falling'][:3]))
    if s['per_capita_top']:
        r = s['per_capita_top'][0]
        out.append(f"인당 생산성 최고 {unit}: {r['unit']} (인당 {r['per_capita']}건)")
    if s['low']:
        out.append(f'실적이 적은 {unit}: ' + ', '.join(s['low'][:5]))
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


def build(levels: dict, pubs: pd.DataFrame, pats: pd.DataFrame, use_llm: bool = True,
          cache: dict | None = None, today: date | None = None) -> list:
    """levels: researcher_id → (1단계부서명, 3단계부서명) — pem.current_levels()(현재 재직·제외 조직 반영)."""
    today = today or date.today()
    since = today.year - RECENT_YEARS + 1
    cache = {} if cache is None else cache
    out = []
    for level, idx, unit in (('level1', 0, '부서'), ('level3', 1, '과제')):
        unit_of = {rid: lv[idx] for rid, lv in levels.items() if lv[idx]}
        sizes = Counter(unit_of.values())
        if level == 'level3':   # 구성원 1명 과제 제외(화면 그래프와 같은 기준)
            unit_of = {rid: u for rid, u in unit_of.items() if sizes[u] > 1}
            sizes = Counter(unit_of.values())
        s = summarize_level(unit_records(unit_of, pubs, pats, since), dict(sizes), today.year)
        res = _llm(s, unit, cache) if use_llm and (s['papers'] or s['patents']) else None
        topics = {}
        for u in (res or {}).get('units') or []:
            try:
                topics[int(u.get('idx'))] = [str(t).strip() for t in u.get('topics') or [] if str(t).strip()][:3]
            except (TypeError, ValueError):
                continue
        for i, r in enumerate(s['top_units']):
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
        print('  [WARN] publications/patents.csv 없음 — 자산화 AI 요약 생략')
        return False
    levels = pem.current_levels(researchers)
    if not levels:
        print('  [WARN] 팀/리더 참조 매칭 없음 — 자산화 AI 요약 생략')
        return False
    cache = pem._read_json(CACHE_FILE, {})
    result = build(levels, pubs, pats, cache=cache)
    pem._write_json(CACHE_FILE, cache)
    pem._write_json(OUTPUT_FILE, result)
    for r in result:
        print(f"[OK]   {OUTPUT_FILE} — {r['unit']} 기준 {r['unit_count']}개 단위, 논문 {r['papers']}·특허 {r['patents']}"
              f"{'' if r['llm'] else ' (LLM 응답 없음 — 통계 기반 요약으로 저장)'}")
    return True


if __name__ == '__main__':
    process()
