"""
과제 기반 전문성 분류 (임베딩 유사도 + 사내 LLM 근거 생성)

Source:
  data/processed/tasks.csv               — 연구원별 과제 참여 이력 (task_name)
  data/processed/tasks_information.csv   — 과제 상세 정보 (task_name 기준 조인)
  data/reference/tech_classification.csv — 국가과학기술표준분류 (대/중/소분류)

Output:
  data/processed/tasks_classification.csv — 과제별 CLOSE 3 분류 (임베딩 유사도 상위 3개)
  data/processed/researcher_expertise.csv — 연구원별 최종 CLOSE 3 / FAR 3

분류 로직:
  1. 과제 텍스트(task_name~task_futureusage)와 소분류 카테고리(대+중+소 라벨)를
     로컬 Ollama(BGE-M3, services.llm.embed())로 임베딩하고 코사인 유사도로
     과제별 CLOSE 3(가장 가까운 분류 3개)를 선정한다.
  2. 연구원이 참여한 모든 과제의 임베딩을 평균 낸 "프로필 임베딩"으로 전체
     분류체계를 다시 검색해 연구원의 최종 CLOSE 3을 선정한다.
  3. 과제별 CLOSE 3 후보 풀 중, 최종 프로필 임베딩과 가장 유사도가 낮은 3개를
     FAR 3으로 선정한다 (최종 CLOSE 3과 겹치는 카테고리는 제외).
  4. 순위(CLOSE/FAR)는 임베딩만으로 계산되며 로컬 Ollama만 있으면 동작한다.
     사유(근거) 텍스트는 --llm 옵션으로 사내 LLM을 호출해야 채워진다.

사용법:
  python pipeline/process_task_classification.py           # 임베딩 기반 순위만 계산
  python pipeline/process_task_classification.py --llm     # 사내 LLM으로 사유까지 생성
"""

import csv
import json
import os
import sys

import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR  = os.path.join(BASE_DIR, 'data', 'processed')
REF_DIR  = os.path.join(BASE_DIR, 'data', 'reference')

sys.path.insert(0, BASE_DIR)
from services.llm import LLMError, embed  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_client import call_llm, extract_json  # noqa: E402

TAXONOMY_FILE = os.path.join(REF_DIR, 'tech_classification.csv')
EMB_CACHE_FILE = os.path.join(OUT_DIR, '_tech_classification_embeddings.npy')

N_CLOSE = 3
N_FAR = 3

_TASK_TEXT_COLS = [
    'task_name', 'task_collabo', 'task_goal', 'task_value',
    'task_howtoget', 'task_expectissue', 'task_Activityplan', 'task_futureusage',
]

SYSTEM_PROMPT_TASK = (
    '당신은 R&D 기술 분류 전문가입니다. 요청한 JSON 형식만 출력하고, '
    '그 외 텍스트는 출력하지 마세요.'
)
SYSTEM_PROMPT_RESEARCHER = (
    '당신은 구루 교수급의 전문성을 지닌 R&D 연구소 CTO입니다. 요청한 JSON 형식만 '
    '출력하고, 그 외 텍스트는 출력하지 마세요.'
)

_RESULT_COLS = [
    'researcher_id', 'kind', 'rank', 'category_top', 'category_mid',
    'category_name', 'category_code', 'similarity', 'evidence_tasks', 'reason',
]


def _cosine_sim_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """a: (n, d), b: (m, d) → (n, m) 코사인 유사도 행렬."""
    a_norm = a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-9)
    b_norm = b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-9)
    return a_norm @ b_norm.T


def _load_taxonomy() -> pd.DataFrame:
    df = pd.read_csv(TAXONOMY_FILE, encoding='utf-8-sig', dtype=str).fillna('')
    df['category_doc'] = (df['대분류코드명'] + ' ' + df['중분류코드명'] + ' ' + df['소분류코드명']).str.strip()
    return df.reset_index(drop=True)


def _get_taxonomy_embeddings(taxonomy: pd.DataFrame) -> np.ndarray:
    """소분류 카테고리 임베딩을 캐시에서 읽거나 새로 계산해 캐시에 저장."""
    if os.path.exists(EMB_CACHE_FILE):
        cached = np.load(EMB_CACHE_FILE)
        if cached.shape[0] == len(taxonomy):
            return cached
        print('[process_task_classification] 분류체계 행 수 변경 감지 — 임베딩 캐시 재계산')

    print(f'[process_task_classification] 분류체계 {len(taxonomy)}건 임베딩 계산 중 '
          f'(최초 1회, 다소 시간이 걸릴 수 있습니다)...')
    vectors = embed(taxonomy['category_doc'].tolist())
    arr = np.array(vectors, dtype=np.float32)
    os.makedirs(OUT_DIR, exist_ok=True)
    np.save(EMB_CACHE_FILE, arr)
    return arr


def _task_document(row) -> str:
    parts = [str(row.get(c, '')).strip() for c in _TASK_TEXT_COLS]
    return ' '.join(p for p in parts if p and p not in ('nan', 'None'))


def _embed_tasks(info_df: pd.DataFrame) -> dict:
    docs = info_df.apply(_task_document, axis=1).tolist()
    vectors = embed(docs)
    return dict(zip(info_df['task_name'], vectors))


def _classify_tasks(info_df: pd.DataFrame, task_emb_by_name: dict,
                     taxonomy: pd.DataFrame, taxo_emb: np.ndarray) -> pd.DataFrame:
    task_names = info_df['task_name'].tolist()
    task_emb = np.array([task_emb_by_name[n] for n in task_names], dtype=np.float32)
    sims = _cosine_sim_matrix(task_emb, taxo_emb)  # (n_tasks, n_categories)

    rows = []
    for i, task_name in enumerate(task_names):
        order = np.argsort(-sims[i])[:N_CLOSE]
        for rank, idx in enumerate(order, start=1):
            cat = taxonomy.iloc[idx]
            rows.append({
                'task_name': task_name,
                'rank': rank,
                'category_top': cat['대분류코드명'],
                'category_mid': cat['중분류코드명'],
                'category_name': cat['소분류코드명'],
                'category_code': cat['소분류코드'],
                'similarity': round(float(sims[i, idx]), 4),
                'reason': '',
            })
    return pd.DataFrame(rows)


def _generate_task_reasons(task_cls: pd.DataFrame, info_df: pd.DataFrame) -> pd.DataFrame:
    task_cls = task_cls.copy()
    info_by_name = info_df.drop_duplicates('task_name').set_index('task_name')

    for task_name, grp in task_cls.groupby('task_name', sort=False):
        if task_name not in info_by_name.index:
            continue
        info_row = info_by_name.loc[task_name]
        candidates = '\n'.join(
            f"{r['rank']}순위: {r['category_top']} > {r['category_mid']} > {r['category_name']} "
            f"(유사도 {r['similarity']:.2f})"
            for _, r in grp.iterrows()
        )
        prompt = f"""아래는 과제 정보와, 이 과제와 임베딩 유사도가 높은 기술분류 후보 3개입니다.

과제명: {task_name}
수행목적: {info_row.get('task_goal', '')}
가치: {info_row.get('task_value', '')}
확보전략: {info_row.get('task_howtoget', '')}
향후활용계획: {info_row.get('task_futureusage', '')}

유사 분류 후보:
{candidates}

각 순위별로 왜 이 분류가 이 과제와 관련 있는지 근거를 한 문장으로 압축적으로 작성하세요.
다음 JSON 형식으로만 출력하세요:
{{"reasons": ["1순위 근거", "2순위 근거", "3순위 근거"]}}
"""
        raw = call_llm(prompt, SYSTEM_PROMPT_TASK)
        if not raw:
            continue
        try:
            reasons = json.loads(extract_json(raw)).get('reasons', [])
        except json.JSONDecodeError:
            continue
        for j, idx in enumerate(grp.index.tolist()):
            if j < len(reasons):
                task_cls.at[idx, 'reason'] = reasons[j]

    return task_cls


def _researcher_final(rid: str, name: str, pool: pd.DataFrame,
                       taxonomy: pd.DataFrame, taxo_emb: np.ndarray,
                       task_emb_by_name: dict) -> list[dict]:
    if pool.empty:
        return []

    names_in_pool = pool['task_name'].unique().tolist()
    vecs = [task_emb_by_name[n] for n in names_in_pool if n in task_emb_by_name]
    if not vecs:
        return []
    profile_vec = np.mean(np.array(vecs), axis=0, keepdims=True)

    # 최종 CLOSE 3: 프로필 임베딩으로 분류체계 전체를 다시 검색
    sims_all = _cosine_sim_matrix(profile_vec, taxo_emb)[0]
    close_order = np.argsort(-sims_all)[:N_CLOSE]
    close_rows = []
    close_codes = set()
    for rank, idx in enumerate(close_order, start=1):
        cat = taxonomy.iloc[idx]
        close_codes.add(cat['소분류코드'])
        close_rows.append({
            'researcher_id': rid, 'kind': 'CLOSE', 'rank': rank,
            'category_top': cat['대분류코드명'], 'category_mid': cat['중분류코드명'],
            'category_name': cat['소분류코드명'], 'category_code': cat['소분류코드'],
            'similarity': round(float(sims_all[idx]), 4),
            'evidence_tasks': ', '.join(names_in_pool[:5]), 'reason': '',
        })

    # FAR 3: 과제별 CLOSE 3 후보 풀 중, 프로필과 가장 유사도가 낮은 항목
    # (최종 CLOSE 3과 겹치는 카테고리는 제외)
    cat_row_by_code = {row['소분류코드']: (i, row) for i, row in taxonomy.iterrows()}
    seen_codes = set()
    far_candidates = []
    for _, r in pool.iterrows():
        code = r['category_code']
        if code in close_codes or code in seen_codes or code not in cat_row_by_code:
            continue
        seen_codes.add(code)
        idx, _ = cat_row_by_code[code]
        far_candidates.append((float(sims_all[idx]), r))
    far_candidates.sort(key=lambda t: t[0])

    far_rows = []
    for rank, (sim, r) in enumerate(far_candidates[:N_FAR], start=1):
        src_tasks = pool[pool['category_code'] == r['category_code']]['task_name'].unique()
        far_rows.append({
            'researcher_id': rid, 'kind': 'FAR', 'rank': rank,
            'category_top': r['category_top'], 'category_mid': r['category_mid'],
            'category_name': r['category_name'], 'category_code': r['category_code'],
            'similarity': round(sim, 4),
            'evidence_tasks': ', '.join(src_tasks[:5]), 'reason': '',
        })

    return close_rows + far_rows


def _generate_researcher_reasons(name: str, rows: list[dict]) -> list[dict]:
    close = [r for r in rows if r['kind'] == 'CLOSE']
    far = [r for r in rows if r['kind'] == 'FAR']
    if not close and not far:
        return rows

    def _fmt(items):
        return '\n'.join(
            f"{r['rank']}순위: {r['category_top']} > {r['category_mid']} > {r['category_name']} "
            f"(관련 과제: {r['evidence_tasks']})"
            for r in items
        )

    prompt = f"""연구원 {name}의 전체 과제 이력을 종합했을 때 아래와 같이 계산되었습니다.

[최종 전문성에 가장 가까운 분류 CLOSE 3]
{_fmt(close)}

[과제별로는 후보에 올랐지만 최종 전문성과 가장 거리가 먼 분류 FAR 3]
{_fmt(far)}

각 항목마다 왜 그렇게 판단되는지 근거를 한 문장으로 압축적으로 작성하세요.
다음 JSON 형식으로만 출력하세요:
{{
  "close_reasons": ["1순위 근거", "2순위 근거", "3순위 근거"],
  "far_reasons": ["1순위 근거", "2순위 근거", "3순위 근거"]
}}
"""
    raw = call_llm(prompt, SYSTEM_PROMPT_RESEARCHER)
    if not raw:
        return rows
    try:
        parsed = json.loads(extract_json(raw))
    except json.JSONDecodeError:
        return rows

    close_reasons = parsed.get('close_reasons', [])
    far_reasons = parsed.get('far_reasons', [])
    for i, r in enumerate(close):
        if i < len(close_reasons):
            r['reason'] = close_reasons[i]
    for i, r in enumerate(far):
        if i < len(far_reasons):
            r['reason'] = far_reasons[i]
    return close + far


def process(use_llm: bool = False):
    tasks_path = os.path.join(OUT_DIR, 'tasks.csv')
    info_path = os.path.join(OUT_DIR, 'tasks_information.csv')
    if not os.path.exists(tasks_path):
        print('[process_task_classification] tasks.csv 없음 — 건너뜀')
        return
    if not os.path.exists(info_path):
        print('[process_task_classification] tasks_information.csv 없음 — 건너뜀')
        return
    if not os.path.exists(TAXONOMY_FILE):
        print('[process_task_classification] data/reference/tech_classification.csv 없음 — 건너뜀')
        return

    tasks_df = pd.read_csv(tasks_path, encoding='utf-8-sig', dtype=str)
    tasks_df['researcher_id'] = tasks_df['researcher_id'].astype(str).str.zfill(8)
    info_df = pd.read_csv(info_path, encoding='utf-8-sig', dtype=str).fillna('')

    total = len(tasks_df)
    matched = tasks_df.merge(info_df[['task_name']], on='task_name', how='inner')
    rate = (len(matched) / total * 100) if total else 0.0
    print(f'[process_task_classification] task_name 매칭: {len(matched)}/{total}행 ({rate:.1f}%)')

    matched_names = tasks_df['task_name'].unique().tolist()
    info_matched = info_df[info_df['task_name'].isin(matched_names)].drop_duplicates('task_name').reset_index(drop=True)
    if info_matched.empty:
        print('[process_task_classification] 매칭되는 과제 없음 — 종료')
        return

    taxonomy = _load_taxonomy()
    try:
        taxo_emb = _get_taxonomy_embeddings(taxonomy)
        print(f'[process_task_classification] 과제 {len(info_matched)}건 임베딩 계산 중...')
        task_emb_by_name = _embed_tasks(info_matched)
    except LLMError as exc:
        print(f'[process_task_classification] 임베딩 실패 — 건너뜀: {exc}')
        return

    task_cls = _classify_tasks(info_matched, task_emb_by_name, taxonomy, taxo_emb)

    if use_llm:
        print('[process_task_classification] 과제별 분류 근거 생성 중 (사내 LLM)...')
        task_cls = _generate_task_reasons(task_cls, info_matched)

    os.makedirs(OUT_DIR, exist_ok=True)
    task_cls_path = os.path.join(OUT_DIR, 'tasks_classification.csv')
    task_cls.to_csv(task_cls_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
    print(f'[process_task_classification] tasks_classification.csv 저장 ({len(task_cls)}행)')

    res_path = os.path.join(OUT_DIR, 'researchers.csv')
    name_map = {}
    if os.path.exists(res_path):
        res_df = pd.read_csv(res_path, dtype=str)
        name_map = res_df.set_index('researcher_id')['name'].to_dict()

    rids = tasks_df['researcher_id'].unique()
    result_rows = []
    print(f'[process_task_classification] 연구원별 최종 분류 계산 중 ({len(rids)}명)...')
    for rid in rids:
        name = name_map.get(rid, rid)
        task_names = tasks_df[tasks_df['researcher_id'] == rid]['task_name'].unique().tolist()
        pool = task_cls[task_cls['task_name'].isin(task_names)].copy()
        if pool.empty:
            continue

        rows = _researcher_final(rid, name, pool, taxonomy, taxo_emb, task_emb_by_name)
        if not rows:
            continue
        if use_llm:
            rows = _generate_researcher_reasons(name, rows)

        result_rows.extend(rows)
        print(f'    [{rid}] {name} 분류 완료 (참여 과제 {pool["task_name"].nunique()}건)')

    out_df = pd.DataFrame(result_rows, columns=_RESULT_COLS)
    out_path = os.path.join(OUT_DIR, 'researcher_expertise.csv')
    out_df.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
    print(f'[process_task_classification] researcher_expertise.csv 저장 ({len(out_df)}행)')


if __name__ == '__main__':
    process(use_llm='--llm' in sys.argv)
