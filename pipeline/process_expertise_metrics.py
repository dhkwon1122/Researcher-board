"""
연구원 전문성 심화 지표 — LLM 호출 없는 결정적 계산 모음(2026-10, 사용자 확정)

process_researcher_expertise.py(LLM 전문성 분석)가 끝난 뒤 run_analysis.py가
이어서 실행한다. 여기 있는 지표는 전부 이미 있는 원천/분석 데이터를 집계만
하므로 비용이 들지 않는다.

  0) 강점 분야/키워드 표기 표준화 재할당 → researcher_strength_std.json
     strength_taxonomy.json(build_strength_taxonomy.py의 확정 표준 목록)으로
     연구원별 strength_fields/strength_keywords를 표준명에 다시 매핑한다.
     원본 LLM 결과(연구원 보유 전문성 분석.json)는 건드리지 않는다.
       - 표준명/동의어와 정확히 일치(공백·대소문자 무시) → 그 표준명
       - 없으면 표준명 중 임베딩 코사인 유사도가 가장 높은 것(>= 0.85)
       - 그래도 없으면 원문 그대로 두고 "미분류"로 표시
         (strength_unmapped.json에 모아 사람이 strength_taxonomy.json에
         동의어/표준명으로 추가하도록 안내)
     표준 목록 파일이 아직 없으면 build_strength_taxonomy.build()로 먼저
     부트스트랩한다(그 함수가 최초 1회만 확정본을 만들고 이후로는 사람이
     수정한 내용을 덮어쓰지 않는다).

  2) 주도형/참여형 지표 → researcher_contribution_metrics.csv
     publications.csv/patents.csv에서 연구원별 논문 주저자·교신 비율, 평균
     기여도, 특허 대표발명자 비율, 평균 지분율과 최근 5년치 같은 지표를
     집계한다.
       - 주도 논문: author_rank==1 또는 author_type에 제1/주저자/단독/1저자
         포함, 또는 교신저자(is_corresponding 참)
       - 주도 특허: is_lead_inventor == 'Y' (application_id 기준 중복 제거)
       - 판정(contribution_type): 논문·특허 중 건수 3건 이상인 원천이 하나라도
         있고 그 원천의 주도 비율이 50% 이상이면 '주도형', 3건 이상인 원천이
         있는데 모두 50% 미만이면 '참여형', 3건 이상인 원천이 없으면
         '판정보류'(건수가 적어 비율이 의미 없음)

  3) 협업 네트워크 → collaboration_edges.csv / collaboration_metrics.csv
     같은 논문(제목 공백·대소문자 무시 + 게재일)에 함께 이름을 올린 사내
     연구원, 같은 특허(application_id)의 공동발명자를 협업 관계로 본다.
     edges: 연구원 쌍별 공동 논문/특허 수·최근 연도·같은 부서 여부.
     metrics: 연구원별 협업자 수, 타부서 협업자 수/비율, 상위 5명.
     사내 저자가 COLLAB_MAX_GROUP명을 넘는 대형 공저 1건은 관계 폭증을
     막기 위해 제외한다.

  4) 기술별 보유자 수(핵심인력 리스크) → technology_holder_summary.csv
     현재 재직자 기준으로 기술(핵심기술 tech_name / 보유기술 tech_1~5 / 표준화된
     강점 분야)별 보유자 수와 고수준 보유자 수(핵심기술 등급 A 이상, 보유기술
     Lv 3 이상)를 센다. risk_level: 보유자 2명 이하 '위험', 고수준 보유자
     1명 이하 '주의', 그 외 '정상'. 개인 명단(holder_ids)이 들어 있어 화면/AI
     검색 모두 관리자(manage_users)에게만 보인다.

사용법:
  python pipeline/process_expertise_metrics.py
"""

import json
import os
import sys
from datetime import date

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT_DIR  # noqa: E402
import researcher_fit as fit  # noqa: E402
from services.llm import LLMError  # noqa: E402

PROFILES_FILE = '연구원 보유 전문성 분석.json'
TAXONOMY_FILE = 'strength_taxonomy.json'
STRENGTH_STD_FILE = 'researcher_strength_std.json'
UNMAPPED_FILE = 'strength_unmapped.json'

CONTRIBUTION_FILE = 'researcher_contribution_metrics.csv'
TECH_HOLDER_FILE = 'technology_holder_summary.csv'
COLLAB_EDGES_FILE = 'collaboration_edges.csv'
COLLAB_METRICS_FILE = 'collaboration_metrics.csv'
COLLAB_MAX_GROUP = 20
COLLAB_TOP_N = 5

STD_EMBED_THRESHOLD = 0.85
CONTRIB_MIN_ITEMS = 3
CONTRIB_LEAD_RATIO = 0.5
RECENT_YEARS = 5
RISK_HOLDER_MAX = 2
CAUTION_HIGH_LEVEL_MAX = 1
_HIGH_CORE_GRADES = {'S', 'A'}
HIGH_LV_MIN = 3
_LEAD_AUTHOR_MARKERS = ('제1', '주저자', '단독', '1저자', '교신')
_TRUE_VALUES = {'true', 'y', 'yes', 'o', '1', '참'}


def _read_json(name: str, default):
    path = os.path.join(OUT_DIR, name)
    if not os.path.exists(path):
        return default
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _write_json(name: str, data) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, name), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _norm(text: str) -> str:
    return ''.join(str(text).split()).lower()


# ── 0) 강점 분야/키워드 표준화 재할당 ─────────────────────────────────────────

def _load_taxonomy() -> dict:
    taxonomy = _read_json(TAXONOMY_FILE, {})
    if taxonomy:
        return taxonomy
    print('[process_expertise_metrics] strength_taxonomy.json 없음 — build_strength_taxonomy로 부트스트랩')
    try:
        import build_strength_taxonomy
        build_strength_taxonomy.build()
    except Exception as exc:  # noqa: BLE001 — 표준화는 보조 단계라 실패해도 원문으로 진행
        print(f'  [WARN] 표준 목록 생성 실패: {type(exc).__name__}: {exc}')
    return _read_json(TAXONOMY_FILE, {})


def _build_mapper(entries: list, raw_values: set) -> dict:
    """원문 값 → 표준명(또는 None=미분류) 매핑을 한 번에 만든다."""
    exact: dict = {}
    standard_names: list = []
    for e in entries or []:
        std = str(e.get('standard_name', '')).strip()
        if not std:
            continue
        standard_names.append(std)
        exact[_norm(std)] = std
        for syn in e.get('synonyms') or []:
            exact.setdefault(_norm(syn), std)

    mapping: dict = {}
    leftovers: list = []
    for v in raw_values:
        std = exact.get(_norm(v))
        if std:
            mapping[v] = std
        else:
            leftovers.append(v)

    if leftovers and standard_names:
        try:
            left_vec = fit.cached_embed(leftovers)
            std_vec = fit.cached_embed(standard_names)
            sims = fit.cosine_sim_matrix(left_vec, std_vec)
            for i, v in enumerate(leftovers):
                j = int(sims[i].argmax())
                mapping[v] = standard_names[j] if float(sims[i][j]) >= STD_EMBED_THRESHOLD else None
        except LLMError as exc:
            print(f'  [WARN] 임베딩 매칭 생략(정확 일치만 적용): {exc}')
    for v in leftovers:
        mapping.setdefault(v, None)
    return mapping


def standardize_strengths(profiles: list, taxonomy: dict) -> tuple[list, dict]:
    """반환: (연구원별 표준화 결과 리스트, 미분류 요약)."""
    keys = (('strength_fields', 'fields'), ('strength_keywords', 'keywords'))
    mappers = {}
    for key, tax_key in keys:
        raw = {str(v).strip() for p in profiles for v in (p.get(key) or []) if str(v).strip()}
        mappers[key] = _build_mapper(taxonomy.get(tax_key, []), raw)

    results = []
    unmapped: dict = {'fields': {}, 'keywords': {}}
    for p in profiles:
        rid = p.get('researcher_id', '')
        row = {'researcher_id': rid}
        for key, tax_key in keys:
            std_list, miss = [], []
            for v in p.get(key) or []:
                v = str(v).strip()
                if not v:
                    continue
                std = mappers[key].get(v)
                if std is None:
                    miss.append(v)
                    unmapped[tax_key].setdefault(v, set()).add(rid)
                    std = v
                if std not in std_list:
                    std_list.append(std)
            row[f'{key}_std'] = std_list
            row[f'{key}_unmapped'] = miss
        results.append(row)

    summary = {
        tax_key: sorted(
            ({'value': v, 'researcher_count': len(rids)} for v, rids in vals.items()),
            key=lambda x: -x['researcher_count'],
        )
        for tax_key, vals in unmapped.items()
    }
    return results, summary


def run_strength_standardization(profiles: list) -> list:
    taxonomy = _load_taxonomy()
    if not taxonomy:
        print('  [WARN] 표준 목록 없이 진행 — 모든 값을 원문 그대로(미분류) 둡니다.')
    results, summary = standardize_strengths(profiles, taxonomy)
    _write_json(STRENGTH_STD_FILE, results)
    _write_json(UNMAPPED_FILE, summary)
    n_f, n_k = len(summary['fields']), len(summary['keywords'])
    print(f'[OK]   {STRENGTH_STD_FILE} 저장 ({len(results)}명, 미분류 분야 {n_f}종·키워드 {n_k}종 '
          f'→ {UNMAPPED_FILE} 확인 후 {TAXONOMY_FILE}에 추가하세요)')
    return results


# ── 2) 주도형/참여형 지표 ─────────────────────────────────────────────────────

def _read_csv(name: str) -> pd.DataFrame:
    path = os.path.join(OUT_DIR, f'{name}.csv')
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')
    if 'researcher_id' in df.columns:
        df['researcher_id'] = df['researcher_id'].astype(str).str.zfill(8)
    return df


def _year_of(value) -> int | None:
    text = str(value or '').strip()
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    return None


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    return df[name] if name in df.columns else pd.Series([''] * len(df), index=df.index)


def _is_lead_paper(row) -> bool:
    if str(row.get('author_rank', '')).strip() in ('1', '1.0'):
        return True
    author_type = str(row.get('author_type', ''))
    if any(m in author_type for m in _LEAD_AUTHOR_MARKERS):
        return True
    return str(row.get('is_corresponding', '')).strip().lower() in _TRUE_VALUES


def _mean_numeric(series: pd.Series) -> float | None:
    vals = pd.to_numeric(series.astype(str).str.replace('%', '', regex=False), errors='coerce').dropna()
    return round(float(vals.mean()), 1) if len(vals) else None


def _pct(part: int, total: int) -> float | None:
    return round(part * 100.0 / total, 1) if total else None


def _classify(pub_n: int, pub_lead: int, pat_n: int, pat_lead: int) -> tuple[str, str]:
    judged = []
    for label, n, lead in (('논문', pub_n, pub_lead), ('특허', pat_n, pat_lead)):
        if n >= CONTRIB_MIN_ITEMS:
            judged.append((label, n, lead, lead / n))
    if not judged:
        return '판정보류', f'논문 {pub_n}건·특허 {pat_n}건(각 {CONTRIB_MIN_ITEMS}건 미만)'
    basis = ', '.join(f'{label} 주도 {lead}/{n}건({ratio * 100:.0f}%)' for label, n, lead, ratio in judged)
    if any(ratio >= CONTRIB_LEAD_RATIO for *_, ratio in judged):
        return '주도형', basis
    return '참여형', basis


def compute_contribution_metrics(researchers: pd.DataFrame, pubs: pd.DataFrame,
                                 pats: pd.DataFrame, today: date | None = None) -> pd.DataFrame:
    recent_from = (today or date.today()).year - RECENT_YEARS + 1

    if not pubs.empty:
        pubs = pubs.copy()
        pubs['_lead'] = pubs.apply(_is_lead_paper, axis=1)
        pubs['_corr'] = _col(pubs, 'is_corresponding').astype(str).str.strip().str.lower().isin(_TRUE_VALUES)
        year_src = _col(pubs, 'pub_year').where(_col(pubs, 'pub_year').astype(str).str.strip() != '',
                                                _col(pubs, 'pub_date'))
        pubs['_year'] = year_src.map(_year_of)
    if not pats.empty:
        pats = pats.copy()
        if 'application_id' in pats.columns:
            pats = pats.drop_duplicates(['application_id', 'researcher_id'])
        pats['_lead'] = _col(pats, 'is_lead_inventor').astype(str).str.strip().str.upper() == 'Y'
        pats['_year'] = _col(pats, 'application_date').map(_year_of)

    rids = set()
    for df in (researchers, pubs, pats):
        if not df.empty and 'researcher_id' in df.columns:
            rids.update(df['researcher_id'].astype(str))
    rids.discard('')

    pub_groups = dict(tuple(pubs.groupby('researcher_id'))) if not pubs.empty else {}
    pat_groups = dict(tuple(pats.groupby('researcher_id'))) if not pats.empty else {}

    rows = []
    for rid in sorted(rids):
        p = pub_groups.get(rid, pd.DataFrame())
        t = pat_groups.get(rid, pd.DataFrame())
        pub_n, pat_n = len(p), len(t)
        pub_lead = int(p['_lead'].sum()) if pub_n else 0
        pat_lead = int(t['_lead'].sum()) if pat_n else 0
        p_recent = p[p['_year'].fillna(0) >= recent_from] if pub_n else p
        t_recent = t[t['_year'].fillna(0) >= recent_from] if pat_n else t
        ctype, basis = _classify(pub_n, pub_lead, pat_n, pat_lead)
        rows.append({
            'researcher_id': rid,
            'pub_count': pub_n,
            'pub_lead_count': pub_lead,
            'pub_lead_pct': _pct(pub_lead, pub_n),
            'pub_corr_pct': _pct(int(p['_corr'].sum()), pub_n) if pub_n else None,
            'pub_avg_contribution': _mean_numeric(_col(p, 'contribution')) if pub_n else None,
            'pat_count': pat_n,
            'pat_lead_count': pat_lead,
            'pat_lead_pct': _pct(pat_lead, pat_n),
            'pat_avg_share': _mean_numeric(_col(t, 'share_ratio')) if pat_n else None,
            'recent_pub_count': len(p_recent),
            'recent_pub_lead_pct': _pct(int(p_recent['_lead'].sum()), len(p_recent)) if len(p_recent) else None,
            'recent_pat_count': len(t_recent),
            'recent_pat_lead_pct': _pct(int(t_recent['_lead'].sum()), len(t_recent)) if len(t_recent) else None,
            'contribution_type': ctype,
            'contribution_basis': basis,
        })
    return pd.DataFrame(rows)


def run_contribution_metrics() -> bool:
    researchers = _read_csv('researchers')
    pubs, pats = _read_csv('publications'), _read_csv('patents')
    if researchers.empty and pubs.empty and pats.empty:
        print('  [WARN] researchers/publications/patents.csv 없음 — 주도형/참여형 지표 생략')
        return False
    df = compute_contribution_metrics(researchers, pubs, pats)
    os.makedirs(OUT_DIR, exist_ok=True)
    df.to_csv(os.path.join(OUT_DIR, CONTRIBUTION_FILE), index=False, encoding='utf-8-sig')
    counts = df['contribution_type'].value_counts().to_dict() if not df.empty else {}
    print(f'[OK]   {CONTRIBUTION_FILE} 저장 ({len(df)}명, '
          + ', '.join(f'{k} {v}명' for k, v in counts.items()) + ')')
    return True


# ── 3) 협업 네트워크 ─────────────────────────────────────────────────────────

def _collab_groups(pubs: pd.DataFrame, pats: pd.DataFrame) -> list:
    """[(kind, members(sorted list), year), ...] — 사내 연구원 2명 이상인 건만."""
    groups = []
    if not pubs.empty and 'title' in pubs.columns:
        p = pubs.assign(_key=pubs['title'].map(_norm) + '|' + _col(pubs, 'pub_date').astype(str).str[:10])
        p = p[p['title'].astype(str).str.strip() != '']
        for _, g in p.groupby('_key'):
            members = sorted(set(g['researcher_id']))
            year = max((y for y in (_year_of(v) for v in list(_col(g, 'pub_year')) + list(_col(g, 'pub_date'))) if y),
                       default=None)
            groups.append(('paper', members, year))
    if not pats.empty and 'application_id' in pats.columns:
        t = pats[pats['application_id'].astype(str).str.strip() != '']
        for _, g in t.groupby('application_id'):
            members = sorted(set(g['researcher_id']))
            year = max((y for y in map(_year_of, _col(g, 'application_date')) if y), default=None)
            groups.append(('patent', members, year))
    return [(k, m, y) for k, m, y in groups if 2 <= len(m) <= COLLAB_MAX_GROUP]


def compute_collaboration(researchers: pd.DataFrame, pubs: pd.DataFrame,
                          pats: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    dept = {}
    if not researchers.empty and 'department' in researchers.columns:
        dept = dict(zip(researchers['researcher_id'], researchers['department'].astype(str).str.strip()))

    edges: dict = {}
    for kind, members, year in _collab_groups(pubs, pats):
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                e = edges.setdefault((a, b), {'paper_count': 0, 'patent_count': 0, 'last_year': None})
                e[f'{kind}_count'] += 1
                if year and (e['last_year'] is None or year > e['last_year']):
                    e['last_year'] = year

    edge_rows = []
    for (a, b), e in edges.items():
        da, db = dept.get(a, ''), dept.get(b, '')
        edge_rows.append({
            'researcher_a': a, 'researcher_b': b,
            'paper_count': e['paper_count'], 'patent_count': e['patent_count'],
            'total_count': e['paper_count'] + e['patent_count'],
            'last_year': e['last_year'] or '',
            'department_a': da, 'department_b': db,
            'same_department': 'Y' if da and da == db else 'N',
        })
    edges_df = pd.DataFrame(edge_rows, columns=[
        'researcher_a', 'researcher_b', 'paper_count', 'patent_count', 'total_count',
        'last_year', 'department_a', 'department_b', 'same_department'])
    if not edges_df.empty:
        edges_df = edges_df.sort_values('total_count', ascending=False).reset_index(drop=True)

    partners: dict = {}
    for r in edge_rows:
        for me, other in ((r['researcher_a'], r['researcher_b']), (r['researcher_b'], r['researcher_a'])):
            partners.setdefault(me, []).append((other, r['total_count'], r['same_department'] == 'N'))
    metric_rows = []
    for rid, lst in sorted(partners.items()):
        lst.sort(key=lambda x: -x[1])
        cross = sum(1 for _, _, c in lst if c)
        top = lst[:COLLAB_TOP_N]
        metric_rows.append({
            'researcher_id': rid,
            'collaborator_count': len(lst),
            'cross_dept_collaborator_count': cross,
            'cross_dept_ratio': round(cross * 100.0 / len(lst), 1),
            'top_collaborators': ';'.join(o for o, _, _ in top),
            'top_collaborator_counts': ';'.join(str(n) for _, n, _ in top),
        })
    return edges_df, pd.DataFrame(metric_rows, columns=[
        'researcher_id', 'collaborator_count', 'cross_dept_collaborator_count', 'cross_dept_ratio',
        'top_collaborators', 'top_collaborator_counts'])


def run_collaboration() -> bool:
    researchers = _read_csv('researchers')
    pubs, pats = _read_csv('publications'), _read_csv('patents')
    if pubs.empty and pats.empty:
        print('  [WARN] publications/patents.csv 없음 — 협업 네트워크 생략')
        return False
    edges_df, metrics_df = compute_collaboration(researchers, pubs, pats)
    os.makedirs(OUT_DIR, exist_ok=True)
    edges_df.to_csv(os.path.join(OUT_DIR, COLLAB_EDGES_FILE), index=False, encoding='utf-8-sig')
    metrics_df.to_csv(os.path.join(OUT_DIR, COLLAB_METRICS_FILE), index=False, encoding='utf-8-sig')
    print(f'[OK]   {COLLAB_EDGES_FILE}/{COLLAB_METRICS_FILE} 저장 '
          f'(협업 관계 {len(edges_df)}건, 협업자 있는 연구원 {len(metrics_df)}명)')
    return True


# ── 4) 기술별 보유자 수 ───────────────────────────────────────────────────────

def _risk_level(holders: int, high: int | None) -> str:
    if holders <= RISK_HOLDER_MAX:
        return '위험'
    if high is not None and high <= CAUTION_HIGH_LEVEL_MAX:
        return '주의'
    return '정상'


def compute_technology_holders(researchers: pd.DataFrame, core: pd.DataFrame, own: pd.DataFrame,
                               strength_std: list) -> pd.DataFrame:
    """(출처, 기술) → 보유자/고수준 보유자. 이름 비교는 공백·대소문자 무시."""
    current = set()
    dept_by_id = {}
    if not researchers.empty:
        cur = researchers
        if 'is_current' in cur.columns:
            cur = cur[cur['is_current'].astype(str).str.upper() != 'N']
        current = set(cur['researcher_id'])
        if 'department' in cur.columns:
            dept_by_id = dict(zip(cur['researcher_id'], cur['department'].astype(str)))

    groups: dict = {}  # (source, norm) -> {'technology', 'tech_field', 'holders': set, 'high': set|None}

    def _add(source, name, rid, high: bool | None, field=''):
        name = str(name or '').strip()
        if not name or name == '-' or (current and rid not in current):
            return
        g = groups.setdefault((source, _norm(name)), {
            'technology': name, 'tech_field': field, 'holders': set(),
            'high': set() if high is not None else None})
        g['holders'].add(rid)
        if high and g['high'] is not None:
            g['high'].add(rid)
        if field and not g['tech_field']:
            g['tech_field'] = field

    for _, r in core.iterrows():
        grade = str(r.get('tech_grade', '')).strip().upper()
        _add('핵심기술', r.get('tech_name'), r['researcher_id'], grade in _HIGH_CORE_GRADES,
             str(r.get('tech_field', '')).strip())
    if not own.empty:
        slots = sorted({int(c.split('_')[1]) for c in own.columns
                        if c.startswith('tech_') and c.split('_')[1].isdigit()})
        for _, r in own.iterrows():
            for i in slots:
                try:
                    lv = float(str(r.get(f'lv_{i}', '')).strip())
                except ValueError:
                    lv = 0
                _add('보유기술', r.get(f'tech_{i}'), r['researcher_id'], lv >= HIGH_LV_MIN)
    for item in strength_std or []:
        rid = str(item.get('researcher_id', '')).zfill(8)
        for f in item.get('strength_fields_std') or []:
            _add('강점분야', f, rid, None)

    rows = []
    for (source, _), g in groups.items():
        holders = sorted(g['holders'])
        high = sorted(g['high']) if g['high'] is not None else None
        rows.append({
            'source': source,
            'technology': g['technology'],
            'tech_field': g['tech_field'],
            'holder_count': len(holders),
            'high_level_count': len(high) if high is not None else '',
            'department_count': len({dept_by_id.get(x, '') for x in holders} - {''}),
            'risk_level': _risk_level(len(holders), len(high) if high is not None else None),
            'holder_ids': ';'.join(holders),
            'high_level_ids': ';'.join(high) if high is not None else '',
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        order = {'위험': 0, '주의': 1, '정상': 2}
        df = df.sort_values(['risk_level', 'holder_count', 'source'],
                            key=lambda c: c.map(order) if c.name == 'risk_level' else c).reset_index(drop=True)
    return df


def run_technology_holders(strength_std: list) -> bool:
    researchers = _read_csv('researchers')
    core, own = _read_csv('core_technology'), _read_csv('tech_ownership')
    if core.empty and own.empty and not strength_std:
        print('  [WARN] core_technology/tech_ownership/강점 표준화 결과 없음 — 기술별 보유자 수 생략')
        return False
    df = compute_technology_holders(researchers, core, own, strength_std)
    os.makedirs(OUT_DIR, exist_ok=True)
    df.to_csv(os.path.join(OUT_DIR, TECH_HOLDER_FILE), index=False, encoding='utf-8-sig')
    risk = int((df['risk_level'] == '위험').sum()) if not df.empty else 0
    print(f'[OK]   {TECH_HOLDER_FILE} 저장 ({len(df)}개 기술, 위험 {risk}개)')
    return True


def process() -> bool:
    ok = True
    profiles = _read_json(PROFILES_FILE, [])
    strength_std = []
    if profiles:
        strength_std = run_strength_standardization(profiles)
    else:
        print(f'[process_expertise_metrics] {PROFILES_FILE} 없음 — 강점 표준화 생략 '
              '(process_researcher_expertise.py 먼저 실행)')
        ok = False
    ok = run_contribution_metrics() and ok
    ok = run_collaboration() and ok
    ok = run_technology_holders(strength_std) and ok
    return ok


if __name__ == '__main__':
    process()
