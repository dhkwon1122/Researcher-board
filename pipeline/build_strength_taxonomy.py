"""
strength_fields / strength_keywords 표준화 1~2단계: 현황 집계 + 유사 표기 클러스터링
+ 표준 목록 초안 생성

process_researcher_expertise.py가 자유 생성한 연구원 보유 전문성 분석.json의
strength_fields/strength_keywords는 통제 어휘집 없이 LLM이 매번 새로 표현을
만들어내므로("로봇 제어"/"로봇제어"/"로봇공학"처럼) 같은 의미가 표기만 다르게
쌓인다. 표준화 작업은 3단계(1.전체 현황 검토 → 2.표준 목록 정의 → 3.표준
목록으로 재할당)로 진행하며, 이 스크립트는 1~2단계를 수행한다.

  1단계(현황 검토, strength_taxonomy_review.json/html): 사람이 눈으로 확인하는
  용도 — 표준 목록을 자동 확정하지 않는다.
    1) 원문 표기별 빈도 — 어떤 값이 몇 명에게 쓰였는지(정규화 없이 있는 그대로)
    2) 유사 표기 클러스터링 — BGE-M3 임베딩 코사인 유사도가 임계값(기본 0.85)
       이상인 원문들을 하나의 통합 후보 그룹으로 묶어 보여준다.

  2단계(표준 목록 정의, strength_taxonomy.json): 각 클러스터에서 가장 많은
  연구원에게 쓰인 원문을 표준명으로, 그룹 내 나머지 원문들을 동의어로 삼아
  초안을 자동 생성한다. 이 초안은 strength_taxonomy_draft.json으로 항상
  최신 상태로 재생성되고, strength_taxonomy.json(실제로 3단계 재할당/자연어
  질문 기능이 참조하는 "확정" 표준 목록)에는 파일이 아직 없을 때만
  부트스트랩으로 한 번 복사한다 — 이미 있으면 사람이 검토·수정한 내용을
  덮어쓰지 않도록 자동으로 다시 쓰지 않는다(수정은 그 파일을 직접 편집).

strength_fields/strength_keywords는 서로 다른 어휘집이라 따로 집계·클러스터링한다.

Source:
  data/processed/연구원 보유 전문성 분석.json (process_researcher_expertise.py)

Output:
  data/processed/strength_taxonomy_review.json/html (1단계, 사람이 보는 현황 검토)
  data/processed/strength_taxonomy_draft.json        (2단계 초안, 매 실행마다 갱신)
  data/processed/strength_taxonomy.json              (2단계 확정본, 최초 1회만 자동 생성)

사용법:
  python pipeline/build_strength_taxonomy.py [--similarity-threshold 0.85]
"""

import html
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT_DIR  # noqa: E402
import researcher_fit as fit  # noqa: E402
import rd_specialist_markdown as mmd  # noqa: E402
from services.llm import LLMError  # noqa: E402

DEFAULT_SIMILARITY_THRESHOLD = 0.85


def _read_profiles() -> list:
    path = os.path.join(OUT_DIR, '연구원 보유 전문성 분석.json')
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _value_researcher_sets(profiles: list, key: str) -> dict:
    """{원문 값: {그 값을 가진 researcher_id 집합}}. 앞뒤 공백만 정리하고
    대소문자/형태 정규화는 하지 않는다 — 표기 그대로 집계하는 것이 이 단계의
    목적이다(정규화는 2단계 표준 목록 정의에서 사람이 판단할 몫)."""
    out: dict = {}
    for p in profiles:
        rid = p.get('researcher_id', '')
        for v in (p.get(key) or []):
            v = str(v).strip()
            if not v:
                continue
            out.setdefault(v, set()).add(rid)
    return out


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _cluster_values(value_researchers: dict, threshold: float) -> list:
    """유사 표기(BGE-M3 임베딩 코사인 유사도 >= threshold)를 하나의 통합 후보
    그룹으로 묶는다(단순 문자열 매칭이 아니라 의미 기반이라 "로봇 제어"/
    "로봇제어"/"로봇공학"처럼 띄어쓰기·형태가 달라도 묶인다). 반환:
    [{'candidate_name', 'raw_values': [(값, 인원수), ...], 'researcher_count'}, ...]
    (researcher_count는 그룹 내 값들의 researcher_id 합집합 크기 — 한 연구원이
    같은 그룹의 값 여러 개를 동시에 가져도 중복으로 세지 않는다), 인원수
    내림차순 정렬."""
    values = list(value_researchers.keys())
    if not values:
        return []
    if len(values) == 1:
        v = values[0]
        return [{
            'candidate_name': v,
            'raw_values': [(v, len(value_researchers[v]))],
            'researcher_count': len(value_researchers[v]),
        }]

    vectors = fit.cached_embed(values)
    sims = fit.cosine_sim_matrix(vectors, vectors)

    uf = _UnionFind(len(values))
    for i in range(len(values)):
        for j in range(i + 1, len(values)):
            if sims[i][j] >= threshold:
                uf.union(i, j)

    groups: dict = {}
    for i, v in enumerate(values):
        groups.setdefault(uf.find(i), []).append(v)

    clusters = []
    for members in groups.values():
        members_sorted = sorted(members, key=lambda v: len(value_researchers[v]), reverse=True)
        researcher_union: set = set()
        for v in members_sorted:
            researcher_union |= value_researchers[v]
        clusters.append({
            'candidate_name': members_sorted[0],
            'raw_values': [(v, len(value_researchers[v])) for v in members_sorted],
            'researcher_count': len(researcher_union),
        })
    clusters.sort(key=lambda c: c['researcher_count'], reverse=True)
    return clusters


def _clusters_to_taxonomy_entries(clusters: list, prefix: str) -> list:
    """클러스터 목록 → 표준 목록 항목([{id, standard_name, synonyms}, ...]) 초안.
    각 그룹에서 가장 많은 연구원에게 쓰인 원문을 표준명으로 임시 채택한다 —
    최종 이름 확정/그룹 병합·분리 판단은 사람이 strength_taxonomy.json을 직접
    열어 검토·수정해야 한다(이 함수는 그 초안만 만든다)."""
    entries = []
    for i, c in enumerate(clusters, start=1):
        entries.append({
            'id': f'{prefix}_{i:03d}',
            'standard_name': c['candidate_name'],
            'synonyms': sorted({v for v, _ in c['raw_values']}),
        })
    return entries


def _cluster_table_html(clusters: list, total_researchers: int) -> str:
    rows = []
    for c in clusters:
        variants = ', '.join(f'{html.escape(v)}({n}명)' for v, n in c['raw_values'])
        merge_note = (
            f' <span class="chip kw">표기 {len(c["raw_values"])}종 통합 후보</span>'
            if len(c['raw_values']) > 1 else ''
        )
        pct = f'{c["researcher_count"] / total_researchers * 100:.0f}%' if total_researchers else '-'
        rows.append(
            f'<tr><td><strong>{html.escape(c["candidate_name"])}</strong>{merge_note}</td>'
            f'<td>{variants}</td>'
            f'<td>{c["researcher_count"]}명 ({pct})</td></tr>'
        )
    return (
        '<div class="table-wrap"><table class="match-table">'
        '<thead><tr><th>후보 표준명(임시)</th><th>원문 표기(인원수)</th><th>인원수(비중)</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
    )


def build(similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD) -> bool:
    profiles = _read_profiles()
    if not profiles:
        print('[build_strength_taxonomy] 연구원 보유 전문성 분석.json 없음 — 종료 '
              '(process_researcher_expertise.py 먼저 실행)')
        return False

    total_researchers = len(profiles)
    field_values = _value_researcher_sets(profiles, 'strength_fields')
    keyword_values = _value_researcher_sets(profiles, 'strength_keywords')

    print(f'[build_strength_taxonomy] strength_fields 원문 {len(field_values)}종 클러스터링 중...')
    try:
        field_clusters = _cluster_values(field_values, similarity_threshold)
        print(f'[build_strength_taxonomy] strength_keywords 원문 {len(keyword_values)}종 클러스터링 중...')
        keyword_clusters = _cluster_values(keyword_values, similarity_threshold)
    except LLMError as exc:
        print(f'[build_strength_taxonomy] 임베딩 실패 — 종료: {exc}')
        return False

    result = {
        'generated_at': datetime.now().isoformat(),
        'total_researchers': total_researchers,
        'similarity_threshold': similarity_threshold,
        'fields': {
            'total_distinct_raw_values': len(field_values),
            'total_candidate_clusters': len(field_clusters),
            'clusters': [
                {
                    'candidate_name': c['candidate_name'],
                    'raw_values': [{'value': v, 'researcher_count': n} for v, n in c['raw_values']],
                    'researcher_count': c['researcher_count'],
                }
                for c in field_clusters
            ],
        },
        'keywords': {
            'total_distinct_raw_values': len(keyword_values),
            'total_candidate_clusters': len(keyword_clusters),
            'clusters': [
                {
                    'candidate_name': c['candidate_name'],
                    'raw_values': [{'value': v, 'researcher_count': n} for v, n in c['raw_values']],
                    'researcher_count': c['researcher_count'],
                }
                for c in keyword_clusters
            ],
        },
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    json_path = os.path.join(OUT_DIR, 'strength_taxonomy_review.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print('[OK]   strength_taxonomy_review.json 저장')

    # 2단계(표준 목록 정의) 초안 — 실행할 때마다 최신 클러스터링 기준으로 항상
    # 다시 생성한다(review 산출물의 일부이므로 사람이 아직 확정하지 않은 후보).
    taxonomy_draft = {
        'generated_at': datetime.now().isoformat(),
        'similarity_threshold': similarity_threshold,
        'fields': _clusters_to_taxonomy_entries(field_clusters, 'field'),
        'keywords': _clusters_to_taxonomy_entries(keyword_clusters, 'kw'),
    }
    draft_path = os.path.join(OUT_DIR, 'strength_taxonomy_draft.json')
    with open(draft_path, 'w', encoding='utf-8') as f:
        json.dump(taxonomy_draft, f, ensure_ascii=False, indent=2)
    print('[OK]   strength_taxonomy_draft.json 저장(항상 최신 클러스터링 기준으로 재생성)')

    # strength_taxonomy.json은 사람이 검토·수정할 "확정" 표준 목록이므로, 이미
    # 있으면 자동으로 덮어쓰지 않는다(수작업 수정이 사라지는 것을 방지) — 최초
    # 실행일 때만 초안을 그대로 채택해 부트스트랩한다.
    taxonomy_path = os.path.join(OUT_DIR, 'strength_taxonomy.json')
    if not os.path.exists(taxonomy_path):
        with open(taxonomy_path, 'w', encoding='utf-8') as f:
            json.dump(taxonomy_draft, f, ensure_ascii=False, indent=2)
        print('[OK]   strength_taxonomy.json 최초 생성 — 초안을 그대로 표준 목록으로 채택했습니다. '
              '검토 후 이 파일을 직접 수정하세요(다음 실행부터는 자동으로 덮어쓰지 않습니다).')
    else:
        print('[SKIP] strength_taxonomy.json 이미 존재 — 자동으로 덮어쓰지 않습니다 '
              '(최신 통합 후보는 strength_taxonomy_draft.json에서 확인 후 직접 반영하세요).')

    stats = mmd.stat_row_html([
        (total_researchers, '분석된 연구원 수'),
        (len(field_values), 'strength_fields 원문 표기 수'),
        (len(field_clusters), 'strength_fields 통합 후보 그룹 수'),
        (len(keyword_values), 'strength_keywords 원문 표기 수'),
        (len(keyword_clusters), 'strength_keywords 통합 후보 그룹 수'),
        mmd.generated_at_stat(datetime.now().strftime('%Y-%m-%d %H:%M')),
    ])

    sidebar = (
        '<h1>strength 표준화 1단계 검토</h1>'
        '<p class="tagline">strength_fields/strength_keywords 원문 표기 현황 + BGE-M3 임베딩'
        f' 유사도 기반 통합 후보(임계값 {similarity_threshold})</p>'
        '<a class="nav-item" href="#fields"><span>Strength Fields</span></a>'
        '<a class="nav-item" href="#keywords"><span>Strength Keywords</span></a>'
    )
    body = (
        stats
        + f'<h2 id="fields">Strength Fields ({len(field_values)}종 원문 → {len(field_clusters)}개 통합 후보 그룹)</h2>'
        + _cluster_table_html(field_clusters, total_researchers)
        + f'<h2 id="keywords">Strength Keywords ({len(keyword_values)}종 원문 → {len(keyword_clusters)}개 통합 후보 그룹)</h2>'
        + _cluster_table_html(keyword_clusters, total_researchers)
    )
    html_out = mmd.console_page('strength 표준화 - 1단계 검토', sidebar, body)
    html_path = os.path.join(OUT_DIR, 'strength_taxonomy_review.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_out)
    print('[OK]   strength_taxonomy_review.html 저장')
    return True


def _parse_threshold_arg(argv: list) -> float:
    if '--similarity-threshold' in argv:
        idx = argv.index('--similarity-threshold')
        if idx + 1 < len(argv):
            try:
                return float(argv[idx + 1])
            except ValueError:
                pass
    return DEFAULT_SIMILARITY_THRESHOLD


if __name__ == '__main__':
    build(_parse_threshold_arg(sys.argv))
