"""
두 사내 LLM(profile) 비교 리포트 생성 모듈

process_project_expertise.py / process_researcher_expertise.py /
process_project_researcher_fit.py를 서로 다른 두 profile(예: 'default'와
'thinkingcap')로 각각 실행한 뒤, 그 결과물(JSON)만 읽어 하나의 비교 HTML로
만든다. 이 스크립트 자체는 LLM을 호출하지 않는다.

비교 대상 3가지:
  1) 컨플 요약 + 과제 전문성 분석 (project_expertise_analysis[.<profile>].json)
     — 과제명(project_name) 기준으로 나란히 표시. 직무명은 모델마다 표현이
       달라 자유 텍스트 일치를 강제하지 않고(강제 배지 없음), 직무 개수/
       난이도 분포 정도만 가벼운 지표로 함께 보여준다.
  2) 연구원 전문성 분석 (연구원 보유 전문성 분석[.<profile>].json)
     — researcher_id(안정적 식별자) 기준. strength_fields/strength_keywords를
       대소문자 무시 문자열 집합으로 비교해 공통/A만/B만을 배지로 표시한다.
  3) 연구원 매칭 (project_fit_by_project / project_fit_by_researcher
     [.<profile>].json)
     — researcher_id·project_name 모두 안정적 식별자이므로, 과제 기준은
       과제별 추천 연구원 집합을, 인별 기준은 연구원별 추천 과제 집합을
       비교해 공통/A만/B만을 배지로 표시한다(직무명 자체는 비교 키로 쓰지
       않고 참고 텍스트로만 노출).

Source:
  data/processed/project_expertise_analysis[.<profile>].json
  data/processed/연구원 보유 전문성 분석[.<profile>].json
  data/processed/project_fit_by_project[.<profile>].json
  data/processed/project_fit_by_researcher[.<profile>].json
  data/processed/researchers.csv (이름 표시용)

Output:
  data/processed/llm_comparison.html

사용법:
  python pipeline/process_llm_compare.py [--profile-a default] [--profile-b thinkingcap]
"""

import html
import json
import os
import sys

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE_DIR, 'data', 'processed')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rd_specialist_markdown as mmd  # noqa: E402

PROFILE_LABEL = {'default': '① 기존 LLM', 'thinkingcap': '② thinkingcap'}


def _profile_label(profile: str) -> str:
    return PROFILE_LABEL.get(profile, profile)


def _parse_args(argv: list) -> tuple:
    def _opt(flag, default):
        if flag in argv:
            idx = argv.index(flag)
            if idx + 1 < len(argv):
                return argv[idx + 1]
        return default
    return _opt('--profile-a', 'default'), _opt('--profile-b', 'thinkingcap')


def _read_json(name: str, profile: str):
    suffix = mmd.profile_suffix(profile)
    path = os.path.join(OUT_DIR, f'{name}{suffix}.json')
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _read_researcher_names() -> dict:
    path = os.path.join(OUT_DIR, 'researchers.csv')
    if not os.path.exists(path):
        return {}
    df = pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')
    df['researcher_id'] = df['researcher_id'].astype(str).str.zfill(8)
    return df.set_index('researcher_id')['name'].to_dict()


def _compare_sets(items_a: list, items_b: list) -> tuple:
    """대소문자 무시 문자열 집합 비교 → (공통, A만, B만). 표시 문자열은 원본
    그대로(공통은 A측 표기 사용)."""
    norm_a = {str(s).strip().lower(): str(s).strip() for s in items_a if str(s).strip()}
    norm_b = {str(s).strip().lower(): str(s).strip() for s in items_b if str(s).strip()}
    common_keys = set(norm_a) & set(norm_b)
    common = sorted(norm_a[k] for k in common_keys)
    only_a = sorted(norm_a[k] for k in set(norm_a) - common_keys)
    only_b = sorted(norm_b[k] for k in set(norm_b) - common_keys)
    return common, only_a, only_b


def _badge_group(label: str, items: list, css_class: str) -> str:
    if not items:
        return ''
    badges = ''.join(f'<span class="badge rounded-pill {css_class}">{html.escape(s)}</span>' for s in items)
    return f'<div class="cmp-group"><div class="cmp-group-label">{label}</div><div class="cmp-badges">{badges}</div></div>'


def _overlap_block(common: list, only_a: list, only_b: list, label_a: str, label_b: str) -> str:
    parts = [
        _badge_group(f'공통 (양쪽 모두)', common, 'text-bg-success'),
        _badge_group(f'{label_a}만', only_a, 'text-bg-primary'),
        _badge_group(f'{label_b}만', only_b, 'text-bg-warning'),
    ]
    parts = [p for p in parts if p]
    return ''.join(parts) if parts else '<p class="empty">비교할 데이터 없음</p>'


# ── 1) 과제 전문성 분석 비교 ─────────────────────────────────────────────────


def _job_stat_line(analysis_text: str) -> str:
    jobs = mmd.deepdive_jobs(analysis_text)
    if not jobs:
        return '직무 딥다이브 데이터 없음'
    dist = {'상': 0, '중': 0, '하': 0}
    for j in jobs:
        if j.get('difficulty') in dist:
            dist[j['difficulty']] += 1
    return f"직무 {len(jobs)}개 (난이도 상 {dist['상']} · 중 {dist['중']} · 하 {dist['하']})"


def _project_desc_line(item: dict) -> str:
    keywords = ', '.join((item.get('keywords_kr') or []) + (item.get('keywords_en') or []))
    parts = [
        f"핵심 기술: {item.get('core_tech') or '확인 불가'}",
        f"최종 산출물: {item.get('deliverable') or '확인 불가'}",
        f"기술적 난제: {item.get('challenge') or '확인 불가'}",
    ]
    if keywords:
        parts.append(f'키워드: {keywords}')
    return ' · '.join(parts)


def _build_project_expertise_section(profile_a: str, profile_b: str) -> str:
    items_a = {p['project_name']: p for p in _read_json('project_expertise_analysis', profile_a)}
    items_b = {p['project_name']: p for p in _read_json('project_expertise_analysis', profile_b)}
    if not items_a and not items_b:
        return '<p class="empty">비교할 과제 전문성 분석 데이터가 없습니다. ' \
               'process_project_expertise.py를 두 profile로 각각 실행해 주세요.</p>'

    ordered_names = list(items_a.keys()) + [n for n in items_b if n not in items_a]
    label_a, label_b = _profile_label(profile_a), _profile_label(profile_b)

    cards = []
    for i, name in enumerate(ordered_names, start=1):
        it_a, it_b = items_a.get(name), items_b.get(name)
        dep_name = (it_a or it_b or {}).get('dep_name', '')

        def _col(it, side):
            if it is None:
                return f'<p class="empty">{label_a if side == "a" else label_b} 결과 없음</p>'
            anchor = f'proj-{i}-{side}'
            deepdive_html, other_html = mmd.render_expertise_html(
                it.get('expertise_analysis', ''), anchor, empty_message='전문성 분석 데이터 없음',
            )
            return f'''<p class="cmp-desc">{html.escape(_project_desc_line(it))}</p>
<p class="cmp-stat"><i class="bi bi-bar-chart-fill"></i> {html.escape(_job_stat_line(it.get('expertise_analysis', '')))}</p>
{deepdive_html}
{other_html}'''

        cards.append(f'''<section class="cmp-card card" id="proj-{i}">
  <div class="card-body">
    <div class="d-flex align-items-center gap-2 mb-3">
      {f'<span class="badge text-bg-dark rounded-pill">{html.escape(dep_name)}</span>' if dep_name else ''}
      <h2 class="cmp-title">{html.escape(name)}</h2>
    </div>
    <div class="row row-cols-1 row-cols-lg-2 g-4">
      <div class="col"><div class="cmp-col-label cmp-col-a">{label_a}</div>{_col(it_a, 'a')}</div>
      <div class="col"><div class="cmp-col-label cmp-col-b">{label_b}</div>{_col(it_b, 'b')}</div>
    </div>
  </div>
</section>''')

    toc = ''.join(
        f'<a class="btn btn-sm btn-outline-primary rounded-pill" href="#proj-{i}">{html.escape(n)}</a>'
        for i, n in enumerate(ordered_names, start=1)
    )
    return f'<nav class="toc">{toc}</nav>\n{"".join(cards)}'


# ── 2) 연구원 전문성 분석 비교 ───────────────────────────────────────────────


def _build_researcher_expertise_section(profile_a: str, profile_b: str, name_map: dict) -> str:
    profiles_a = {p['researcher_id']: p for p in _read_json('연구원 보유 전문성 분석', profile_a)}
    profiles_b = {p['researcher_id']: p for p in _read_json('연구원 보유 전문성 분석', profile_b)}
    if not profiles_a and not profiles_b:
        return '<p class="empty">비교할 연구원 전문성 분석 데이터가 없습니다. ' \
               'process_researcher_expertise.py를 두 profile로 각각 실행해 주세요.</p>'

    label_a, label_b = _profile_label(profile_a), _profile_label(profile_b)
    rids = sorted(set(profiles_a) | set(profiles_b))

    cards = []
    for rid in rids:
        pa, pb = profiles_a.get(rid, {}), profiles_b.get(rid, {})
        fields_common, fields_a, fields_b = _compare_sets(
            pa.get('strength_fields', []), pb.get('strength_fields', []))
        kw_common, kw_a, kw_b = _compare_sets(
            pa.get('strength_keywords', []), pb.get('strength_keywords', []))

        cards.append(f'''<div class="cmp-card card" id="researcher-{rid}">
  <div class="card-body">
    <h2 class="cmp-title">{rid} {html.escape(name_map.get(rid, ''))}</h2>
    <p class="cmp-section-label">강점 분야</p>
    {_overlap_block(fields_common, fields_a, fields_b, label_a, label_b)}
    <p class="cmp-section-label mt-3">강점 키워드</p>
    {_overlap_block(kw_common, kw_a, kw_b, label_a, label_b)}
  </div>
</div>''')

    toc = ''.join(
        f'<a class="btn btn-sm btn-outline-primary rounded-pill" href="#researcher-{rid}">{rid} {html.escape(name_map.get(rid, ""))}</a>'
        for rid in rids
    )
    return f'<nav class="toc">{toc}</nav>\n{"".join(cards)}'


# ── 3) 연구원 매칭 비교 ──────────────────────────────────────────────────────


def _build_matching_section(profile_a: str, profile_b: str, name_map: dict) -> str:
    by_project_a = _read_json('project_fit_by_project', profile_a)
    by_project_b = _read_json('project_fit_by_project', profile_b)
    by_researcher_a = _read_json('project_fit_by_researcher', profile_a)
    by_researcher_b = _read_json('project_fit_by_researcher', profile_b)

    if not (by_project_a or by_project_b or by_researcher_a or by_researcher_b):
        return '<p class="empty">비교할 연구원 매칭 데이터가 없습니다. ' \
               'process_project_researcher_fit.py를 두 profile로 각각 실행해 주세요.</p>'

    label_a, label_b = _profile_label(profile_a), _profile_label(profile_b)

    def _rid_label(rid):
        return f'{rid} {name_map.get(rid, "")}'.strip()

    # 과제 기준: 과제명(project_name)별로, 모든 직무 랭킹을 합쳐 추천된 연구원 집합을 비교.
    def _project_researcher_sets(rows):
        agg = {}
        for r in rows:
            agg.setdefault(r['project_name'], set()).update(rk['researcher_id'] for rk in r.get('rankings', []))
        return agg

    proj_a = _project_researcher_sets(by_project_a)
    proj_b = _project_researcher_sets(by_project_b)
    project_names = list(proj_a.keys()) + [n for n in proj_b if n not in proj_a]

    by_project_cards = []
    for name in project_names:
        common, only_a, only_b = _compare_sets(
            [_rid_label(r) for r in proj_a.get(name, set())],
            [_rid_label(r) for r in proj_b.get(name, set())],
        )
        by_project_cards.append(f'''<div class="cmp-card card">
  <div class="card-body">
    <h2 class="cmp-title">{html.escape(name)}</h2>
    <p class="cmp-desc">추천 연구원 비교 (직무 무관, 과제 단위 합산)</p>
    {_overlap_block(common, only_a, only_b, label_a, label_b)}
  </div>
</div>''')
    by_project_html = ''.join(by_project_cards) or '<p class="empty">데이터 없음</p>'

    # 인별 기준: researcher_id별로, 추천된 과제명(project_name) 집합을 비교.
    def _researcher_project_sets(rows):
        agg = {}
        for r in rows:
            agg.setdefault(r['researcher_id'], set()).update(m['project_name'] for m in r.get('matches', []))
        return agg

    res_a = _researcher_project_sets(by_researcher_a)
    res_b = _researcher_project_sets(by_researcher_b)
    rids = list(res_a.keys()) + [r for r in res_b if r not in res_a]

    by_researcher_cards = []
    for rid in rids:
        common, only_a, only_b = _compare_sets(list(res_a.get(rid, set())), list(res_b.get(rid, set())))
        by_researcher_cards.append(f'''<div class="cmp-card card">
  <div class="card-body">
    <h2 class="cmp-title">{_rid_label(rid)}</h2>
    <p class="cmp-desc">추천 과제 비교</p>
    {_overlap_block(common, only_a, only_b, label_a, label_b)}
  </div>
</div>''')
    by_researcher_html = ''.join(by_researcher_cards) or '<p class="empty">데이터 없음</p>'

    return f'''<ul class="nav nav-tabs justify-content-center mb-4" role="tablist">
  <li class="nav-item" role="presentation">
    <button class="nav-link active" data-bs-toggle="tab" data-bs-target="#match-by-project" type="button">과제 기준</button>
  </li>
  <li class="nav-item" role="presentation">
    <button class="nav-link" data-bs-toggle="tab" data-bs-target="#match-by-researcher" type="button">인별 기준</button>
  </li>
</ul>
<div class="tab-content">
  <div class="tab-pane fade show active" id="match-by-project">{by_project_html}</div>
  <div class="tab-pane fade" id="match-by-researcher">{by_researcher_html}</div>
</div>'''


EXTRA_STYLE = mmd.EXPERTISE_CARD_STYLE + """
  .cmp-card {
    max-width: 1100px; margin: 0 auto 28px; border: 1px solid var(--gs-border);
    border-radius: 18px; background: var(--gs-surface); box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  }
  .cmp-card .card-body { padding: 26px 30px; }
  .cmp-title { font-size: 1.1rem; font-weight: 700; margin: 0; }
  .cmp-desc { color: #444; font-size: 0.84rem; margin: 4px 0 4px; }
  .cmp-stat { color: var(--gs-muted); font-size: 0.78rem; margin: 0 0 14px; }
  .cmp-section-label { font-size: 0.8rem; font-weight: 700; color: var(--gs-muted); margin: 0 0 6px; }
  .cmp-col-label {
    display: inline-block; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.03em;
    text-transform: uppercase; padding: 3px 10px; border-radius: 999px; margin-bottom: 10px;
  }
  .cmp-col-a { background: #e8f2ff; color: #0071e3; }
  .cmp-col-b { background: #fff3e0; color: #b06a00; }
  .cmp-group { margin-bottom: 10px; }
  .cmp-group:last-child { margin-bottom: 0; }
  .cmp-group-label { font-size: 0.74rem; color: var(--gs-muted); margin-bottom: 4px; }
  .cmp-badges { display: flex; flex-wrap: wrap; gap: 6px; }
  .cmp-badges .badge { font-weight: 500; }
  #top-tabs .nav-link { font-weight: 600; color: var(--gs-muted); }
  #top-tabs .nav-link.active { color: var(--gs-text); }
"""


def build_html(profile_a: str, profile_b: str) -> str:
    name_map = _read_researcher_names()
    project_section = _build_project_expertise_section(profile_a, profile_b)
    researcher_section = _build_researcher_expertise_section(profile_a, profile_b, name_map)
    matching_section = _build_matching_section(profile_a, profile_b, name_map)

    body_html = f'''<ul class="nav nav-tabs justify-content-center mb-4" id="top-tabs" role="tablist">
  <li class="nav-item" role="presentation">
    <button class="nav-link active" data-bs-toggle="tab" data-bs-target="#tab-project" type="button">컨플 요약 · 과제 전문성 분석</button>
  </li>
  <li class="nav-item" role="presentation">
    <button class="nav-link" data-bs-toggle="tab" data-bs-target="#tab-researcher" type="button">연구원 전문성 분석</button>
  </li>
  <li class="nav-item" role="presentation">
    <button class="nav-link" data-bs-toggle="tab" data-bs-target="#tab-matching" type="button">연구원 매칭</button>
  </li>
</ul>
<div class="tab-content">
  <div class="tab-pane fade show active" id="tab-project">{project_section}</div>
  <div class="tab-pane fade" id="tab-researcher">{researcher_section}</div>
  <div class="tab-pane fade" id="tab-matching">{matching_section}</div>
</div>'''

    return mmd.html_page(
        title='사내 LLM 비교 리포트',
        heading='사내 LLM 비교 리포트',
        subtitle=f'{_profile_label(profile_a)} vs {_profile_label(profile_b)} — '
                 f'컨플요약+과제 전문성 분석 / 연구원 전문성 분석 / 연구원 매칭',
        body_html=body_html,
        extra_style=EXTRA_STYLE,
    )


def process(profile_a: str = 'default', profile_b: str = 'thinkingcap') -> bool:
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'llm_comparison.html')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(build_html(profile_a, profile_b))
    print(f'[OK]   llm_comparison.html 저장 ({profile_a} vs {profile_b})')
    return True


if __name__ == '__main__':
    a, b = _parse_args(sys.argv)
    process(profile_a=a, profile_b=b)
