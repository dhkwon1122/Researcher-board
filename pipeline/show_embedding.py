"""
BGE-M3 임베딩 방식 설명 모듈 (보고용)

연구원 전문성 프로필이 실제로 어떻게 벡터로 변환되고, 그 벡터가 어떻게
"유사한 연구원 찾기"에 쓰이는지를 특정 연구원 한 명을 예시로 콘솔형 HTML
리포트에 구체적으로 보여준다. process_researcher_similarity.py가 실제로
쓰는 것과 동일한 함수(researcher_fit.researcher_profile_text,
researcher_fit.cached_embed)를 그대로 재사용하므로, 실제 파이프라인과
완전히 같은 방식으로 변환된 결과를 보여준다.

이 리포트가 보여주는 3단계:
  1) 입력 텍스트 구성: 강점 분야/키워드/Hard Skills/Domain Knowledge를
     researcher_profile_text()가 어떤 텍스트로 이어붙이는지
  2) 임베딩 벡터: 그 텍스트를 BGE-M3가 1024차원 숫자 벡터로 바꾼 결과
     (전체를 다 보여주기엔 너무 기므로 앞부분 일부 + 통계만 표시)
  3) 활용 예시: 그 벡터로 코사인 유사도를 계산해 가장 가까운 연구원
     top-5를 찾는 것(순수 임베딩 단계만 — LLM 정성 판정은 포함하지 않음,
     그건 process_researcher_similarity.py의 2단계에서 별도로 함)

사용법:
  python pipeline/show_embedding.py <researcher_id>

Source:
  data/processed/연구원 보유 전문성 분석.json (process_researcher_expertise.py)
  data/processed/researchers.csv               (이름 표시용)
  data/processed/embedding_cache.json           (있으면 재사용, 없으면 새로 계산)

Output:
  data/processed/embedding_explainer_{researcher_id}.html
"""

import html
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import BASE_DIR, OUT_DIR  # noqa: E402
sys.path.insert(0, BASE_DIR)
import rd_specialist_markdown as mmd  # noqa: E402
import researcher_fit as fit  # noqa: E402
from services.llm import LLMError  # noqa: E402


def _read_expertise() -> list:
    path = os.path.join(OUT_DIR, '연구원 보유 전문성 분석.json')
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _profile_fields_html(profile: dict) -> str:
    """프로필 원본 필드(강점 분야/키워드/주요 역할·책임/전문지식 및 역량)를
    researcher_profile_text()로 이어붙이기 전, 사람이 보기 좋은 형태로 나열
    (원본 JSON 키를 그대로 보여준다 — researcher_fit 내부 로직에 의존하지 않음)."""
    parts = []
    fields = profile.get('strength_fields') or []
    keywords = profile.get('strength_keywords') or []
    if fields:
        chips = ''.join(f'<span class="chip">{html.escape(f)}</span>' for f in fields)
        parts.append(f'<div class="chip-row">{chips}</div>')
    if keywords:
        chips = ''.join(f'<span class="chip kw">{html.escape(k)}</span>' for k in keywords)
        parts.append(f'<div class="chip-row">{chips}</div>')
    list_items = [
        f'<li>{html.escape(v)}</li>'
        for section in (profile.get('key_responsibilities') or [], profile.get('domain_knowledge_skill') or [])
        for v in section
    ]
    if list_items:
        parts.append(f'<ul class="kv-list">{"".join(list_items)}</ul>')
    return ''.join(parts) or '<p class="empty">원본 프로필 필드 없음</p>'


def _vector_preview_html(vector: np.ndarray, preview_n: int = 24) -> str:
    norm = float(np.linalg.norm(vector))
    preview = ', '.join(f'{v:.4f}' for v in vector[:preview_n])
    return f'''<pre class="raw-md">[{preview}, ... ] (총 {vector.shape[0]}차원 중 앞 {preview_n}개만 표시)</pre>
<p class="card-sub">L2 노름(벡터 길이): {norm:.4f} · 최솟값 {float(vector.min()):.4f} · 최댓값 {float(vector.max()):.4f}</p>'''


def _neighbor_table_html(neighbors: list, name_map: dict, dept_map: dict, org_map: dict) -> str:
    if not neighbors:
        return '<p class="empty">비교할 다른 연구원 데이터 없음</p>'
    rows = ''.join(f'''<tr>
  <td>
    <div class="m-name">{html.escape(name_map.get(rid, rid))}</div>
    <div class="m-dept">{html.escape(dept_map.get(rid, ''))} · {html.escape(org_map.get(rid, ''))}</div>
  </td>
  <td class="m-score">{round(score * 100)}%</td>
</tr>''' for rid, score in neighbors)
    return (
        '<div class="table-wrap"><table class="match-table">'
        '<thead><tr><th>연구원</th><th>코사인 유사도</th></tr></thead>'
        f'<tbody>{rows}</tbody></table></div>'
    )


def _build_html(researcher_id: str, profile: dict, text: str, vector: np.ndarray,
                 neighbors: list, name_map: dict, dept_map: dict, org_map: dict) -> str:
    name = name_map.get(researcher_id, researcher_id)
    sidebar = (
        '<h1>임베딩 설명 콘솔</h1>'
        '<p class="tagline">BGE-M3가 연구원 전문성 프로필을 어떻게 벡터로 바꾸고, '
        '그 벡터를 어떻게 유사 연구원 탐색에 쓰는지 보여주는 보고용 리포트</p>'
        '<div class="nav-group"><div class="nav-group-label">대상 연구원</div>'
        f'<div class="nav-item"><span>{html.escape(researcher_id)} {html.escape(name)}</span></div></div>'
    )
    stats = mmd.stat_row_html([
        (len(text), '입력 텍스트 길이(자)'),
        (vector.shape[0], '임베딩 차원수'),
        (len(neighbors), '유사도 계산 예시 (top-K)'),
    ])
    body = f'''
<div class="card">
  <div class="card-top"><h3>{html.escape(researcher_id)} {html.escape(name)}</h3></div>
  <p class="card-sub">{html.escape(dept_map.get(researcher_id, ''))} · {html.escape(org_map.get(researcher_id, ''))}</p>
</div>
<div class="card">
  <div class="card-top"><h3>1단계 — 입력 텍스트 구성</h3></div>
  <p class="card-sub">강점 분야/강점 키워드/Hard Skills/Domain Knowledge를 아래처럼 정리한 원본 필드에서,</p>
  {_profile_fields_html(profile)}
  <p class="card-sub" style="margin-top:12px">researcher_profile_text()가 이를 한 덩어리 텍스트로 이어붙입니다(실제로 BGE-M3에 들어가는 입력):</p>
  <pre class="raw-md">{html.escape(text)}</pre>
</div>
<div class="card">
  <div class="card-top"><h3>2단계 — 임베딩 벡터</h3></div>
  <p class="card-sub">위 텍스트를 사내 BGE-M3 서버(services/llm.py의 embed())가 {vector.shape[0]}차원
  숫자 벡터로 변환합니다. 벡터 자체는 사람이 읽을 수 있는 값이 아니라, "의미가 비슷하면 벡터도
  가까운 방향을 향한다"는 성질만 이용합니다.</p>
  {_vector_preview_html(vector)}
</div>
<div class="card">
  <div class="card-top"><h3>3단계 — 활용 예시: 코사인 유사도로 가장 가까운 연구원 찾기</h3></div>
  <p class="card-sub">이 연구원의 벡터와 다른 모든 연구원 벡터 사이의 코사인 유사도를 계산해
  정렬한 순수 임베딩 기준 top-{len(neighbors)}입니다(LLM 정성 판정 전 단계 — 실제
  연구원 ↔ 연구원 리포트는 여기서 추린 후보에 LLM 근거 판정을 한 번 더 거칩니다).</p>
  {_neighbor_table_html(neighbors, name_map, dept_map, org_map)}
</div>
'''
    return mmd.console_page(f'임베딩 설명 — {researcher_id} {name}', sidebar, stats + body)


def process(researcher_id: str) -> bool:
    profiles = _read_expertise()
    if not profiles:
        print('[show_embedding] 연구원 보유 전문성 분석.json 없음 — 종료 '
              '(process_researcher_expertise.py 먼저 실행)')
        return False

    profile_by_id = {p['researcher_id']: p for p in profiles}
    if researcher_id not in profile_by_id:
        print(f'[show_embedding] researcher_id={researcher_id} 없음 — 종료 '
              '(연구원 보유 전문성 분석.json에 해당 연구원이 없음)')
        return False

    researcher_ids = [p['researcher_id'] for p in profiles]
    texts = [fit.researcher_profile_text(p) for p in profiles]
    print(f'[show_embedding] 연구원 {len(profiles)}명 임베딩 계산 중(캐시 있으면 재사용)...')
    try:
        embeddings = fit.cached_embed(texts)
    except LLMError as exc:
        print(f'[show_embedding] 임베딩 실패 — 종료: {exc}')
        return False

    idx = researcher_ids.index(researcher_id)
    sims = fit.cosine_sim_matrix(embeddings, embeddings)[idx].copy()
    sims[idx] = -1.0
    k = min(5, len(researcher_ids) - 1)
    top_idx = fit.top_k_idx(sims, k) if k > 0 else []
    neighbors = [(researcher_ids[j], float(sims[j])) for j in top_idx]

    researchers_df = fit.read_researchers(OUT_DIR)
    name_map, dept_map, org_map = {}, {}, {}
    if not researchers_df.empty:
        indexed = researchers_df.set_index('researcher_id')
        name_map = indexed['name'].to_dict()
        dept_map = indexed['department'].to_dict()
        org_map = indexed['org_code'].to_dict()

    html_out = _build_html(
        researcher_id, profile_by_id[researcher_id], texts[idx], embeddings[idx],
        neighbors, name_map, dept_map, org_map,
    )
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f'embedding_explainer_{researcher_id}.html')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html_out)
    print(f'[OK]   {out_path} 저장')
    return True


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('사용법: python pipeline/show_embedding.py <researcher_id>')
        sys.exit(1)
    process(sys.argv[1].strip().zfill(8))
