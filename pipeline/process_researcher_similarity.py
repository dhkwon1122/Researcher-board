"""
연구원 ↔ 연구원 유사도 분석 모듈

과제(프로젝트)는 서로 완전히 달라도(예: CPO ↔ CPU) 그 안의 개별 스킬(AI,
회로설계 등)은 겹칠 수 있다. 과제 라벨이 아니라 "실제로 어떤 전문성을
갖고 있는가"로 연구원을 직접 비교하기 위해, process_researcher_expertise.py가
만든 연구원별 전문성 프로필(강점 분야/강점 키워드/Hard Skills/Domain
Knowledge)을 BGE-M3로 임베딩하고 코사인 유사도를 계산한다.

사내 chat LLM은 호출하지 않는다(순수 임베딩 유사도) — 판단·설명이 아니라
"의미적으로 얼마나 가까운가"만 필요하므로 비용이 거의 들지 않는다. 임베딩은
표현이 달라도("AI" vs "인공지능") 의미가 비슷하면 가깝게 나오므로, 과제명이
전혀 달라도 실제로 비슷한 일을 하는 연구원을 찾아낼 수 있다.

매칭 로직(코사인 유사도, top-K 추출)은 pipeline/researcher_fit.py 공용 모듈을
그대로 재사용한다(process_project_researcher_fit.py가 과제↔연구원 매칭에
쓰는 것과 동일한 함수들이며, 임베딩 자체는 두 스크립트가 다시 계산한다 —
비교 대상 텍스트 집합이 다르기 때문).

Source:
  data/processed/연구원 보유 전문성 분석[.<profile>].json (process_researcher_expertise.py)
  data/processed/researchers.csv                          (HTML에 이름 표시용)

Output:
  data/processed/researcher_similarity[.<profile>].json
  data/processed/researcher_similarity[.<profile>].html

profile 인자는 "어떤 LLM이 만든 연구원 전문성 분석 결과를 비교할지"를 고른다
(임베딩 모델 자체는 항상 BGE-M3로 고정이며 profile과 무관하다):
  python pipeline/process_researcher_similarity.py                    # 기존 LLM(profile='default') 분석 기준
  python pipeline/process_researcher_similarity.py --profile thinkingcap  # 2번째 LLM 분석 기준

사용법:
  python pipeline/process_researcher_similarity.py [--profile thinkingcap] [--top-k 5]
"""

import html
import json
import os
import sys

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE_DIR, 'data', 'processed')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
import rd_specialist_markdown as mmd  # noqa: E402
import researcher_fit as fit  # noqa: E402
from services.llm import LLMError  # noqa: E402

DEFAULT_TOP_K = fit.TOP_K


def _read_expertise(profile: str) -> list:
    suffix = mmd.profile_suffix(profile)
    path = os.path.join(OUT_DIR, f'연구원 보유 전문성 분석{suffix}.json')
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def compute_similarity(profiles: list, top_k: int = DEFAULT_TOP_K) -> list:
    """profiles: 연구원 보유 전문성 분석.json의 원소 리스트(researcher_id 포함).
    반환: [{'researcher_id', 'similar': [{'researcher_id', 'score'}, ...]}, ...]
    similar은 자기 자신을 제외하고 유사도 내림차순 상위 top_k. score는 코사인
    유사도(-1~1, 실제로는 임베딩 특성상 대부분 0~1 범위)를 소수 4자리로 반올림."""
    researcher_ids = [p['researcher_id'] for p in profiles]
    texts = [fit.researcher_profile_text(p) for p in profiles]

    embeddings = np.array(fit.embed(texts), dtype=np.float32)
    sims = fit.cosine_sim_matrix(embeddings, embeddings)

    n = len(researcher_ids)
    k = min(top_k, n - 1) if n > 1 else 0

    results = []
    for i in range(n):
        row = sims[i].copy()
        row[i] = -1.0  # 자기 자신은 후보에서 제외
        top_idx = fit.top_k_idx(row, k) if k > 0 else []
        similar = [
            {'researcher_id': researcher_ids[j], 'score': round(float(sims[i, j]), 4)}
            for j in top_idx
        ]
        results.append({'researcher_id': researcher_ids[i], 'similar': similar})
    return results


def _build_html(results: list, profile: str, researchers_df: pd.DataFrame, top_k: int) -> str:
    name_map = {}
    if not researchers_df.empty:
        name_map = researchers_df.set_index('researcher_id')['name'].to_dict()

    toc_links = []
    cards = []
    for i, item in enumerate(results, start=1):
        rid = item['researcher_id']
        anchor = f'researcher-{i}'
        label = f'{rid} {name_map.get(rid, "")}'.strip()
        toc_links.append(
            f'<a class="btn btn-sm btn-outline-primary rounded-pill" href="#{anchor}">{html.escape(label)}</a>'
        )

        rows = ''.join(
            f'''<div class="rank-row d-flex justify-content-between align-items-start gap-2">
  <div class="name">{html.escape(s['researcher_id'])} {html.escape(name_map.get(s['researcher_id'], ''))}</div>
  <span class="badge rounded-pill text-bg-primary">유사도 {round(s['score'] * 100)}%</span>
</div>'''
            for s in item['similar']
        ) or '<p class="empty">비교할 다른 연구원 데이터 없음</p>'

        cards.append(f'''<div class="fit-card card" id="{anchor}">
  <div class="card-body">
    <h3>{html.escape(label)}</h3>
    <p class="subtitle">과제와 무관하게, 전문성이 가장 유사한 연구원 Top {top_k}</p>
    {rows}
  </div>
</div>''')

    profile_note = f' ({profile})' if profile != 'default' else ''
    body_html = f'<nav class="toc">{"".join(toc_links)}</nav>\n{"".join(cards)}'
    return mmd.html_page(
        title=f'연구원 ↔ 연구원 유사도{profile_note}',
        heading=f'연구원 ↔ 연구원 유사도{profile_note}',
        subtitle='과제 단위가 아닌 전문성(강점 분야·키워드·Hard Skills·Domain Knowledge) 임베딩 기반 유사도',
        body_html=body_html,
        extra_style=fit.EXTRA_STYLE,
    )


def process(profile: str = 'default', top_k: int = DEFAULT_TOP_K) -> bool:
    profiles = _read_expertise(profile)
    if not profiles:
        suffix = mmd.profile_suffix(profile)
        print(f'[process_researcher_similarity] 연구원 보유 전문성 분석{suffix}.json 없음 — 종료 '
              f'(process_researcher_expertise.py'
              f'{" --profile " + profile if profile != "default" else ""} 먼저 실행)')
        return False
    if len(profiles) < 2:
        print('[process_researcher_similarity] 비교할 연구원이 2명 미만 — 종료')
        return False

    print(f'[process_researcher_similarity] 연구원 {len(profiles)}명 임베딩 계산 중 (profile={profile})...')
    try:
        results = compute_similarity(profiles, top_k=top_k)
    except LLMError as exc:
        print(f'[process_researcher_similarity] 임베딩 실패 — 종료: {exc}')
        return False

    suffix = mmd.profile_suffix(profile)
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f'researcher_similarity{suffix}.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f'[OK]   researcher_similarity{suffix}.json 저장 ({len(results)}명)')

    researchers_df = fit.read_researchers(OUT_DIR)
    html_out = _build_html(results, profile, researchers_df, top_k)
    html_path = os.path.join(OUT_DIR, f'researcher_similarity{suffix}.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_out)
    print(f'[OK]   researcher_similarity{suffix}.html 저장')

    return True


def _parse_top_k_arg(argv: list, default: int) -> int:
    if '--top-k' in argv:
        idx = argv.index('--top-k')
        if idx + 1 < len(argv):
            try:
                return int(argv[idx + 1])
            except ValueError:
                pass
    return default


if __name__ == '__main__':
    process(profile=mmd.parse_profile_arg(sys.argv), top_k=_parse_top_k_arg(sys.argv, DEFAULT_TOP_K))
