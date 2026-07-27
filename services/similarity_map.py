"""
연구원 전문성 임베딩(BGE-M3) 기반 2D 유사도 지도 계산.

pipeline/process_researcher_expertise.py(연구원 보유 전문성 분석.json)와
pipeline/process_researcher_similarity.py·process_project_researcher_fit.py가
채워둔 embedding_cache.json(텍스트 해시 → 1024차원 BGE-M3 벡터)을 읽어, UMAP으로
2D 좌표로 투영한다.

이 서비스는 새로 임베딩을 계산하지 않는다(대시보드 페이지 로드 시 BGE-M3 서버를
호출하지 않음 — 캐시에 없는 연구원은 그냥 지도에서 제외된다). 지도에 모든
연구원이 나오게 하려면 먼저 pipeline/process_researcher_similarity.py(또는
process_project_researcher_fit.py)를 실행해 embedding_cache.json을 채워야 한다.
"""

import json
import os
from collections import Counter

import numpy as np
import pandas as pd

from pipeline.researcher_fit import _text_hash, researcher_profile_text
from services.data_store import DATA_DIR, read_processed


def _profile_suffix(profile: str) -> str:
    return '' if profile == 'default' else f'.{profile}'


def _cluster_label(rows: list) -> str:
    """클러스터 구성원들의 strength_fields 중 가장 흔한 상위 2개를 조합해
    자동으로 영역 이름을 만든다. 강점 분야 데이터가 전혀 없으면 '미분류 영역'."""
    counter = Counter()
    for r in rows:
        counter.update(r.get('strength_fields') or [])
    if not counter:
        return '미분류 영역'
    return ' · '.join(name for name, _ in counter.most_common(2))


def compute_clusters(df: pd.DataFrame, min_cluster_size: int = 3) -> pd.DataFrame:
    """2D UMAP 좌표(x, y) 위에서 HDBSCAN으로 밀도 기반 클러스터를 찾고, 각
    클러스터에 구성원의 강점 분야 기반 자동 이름(cluster_label)을 붙인다.
    노이즈(어느 클러스터에도 속하지 않는 점, HDBSCAN 라벨 -1)는 cluster=-1,
    cluster_label=''로 남는다 — 화면에서 경계/이름 없이 점만 표시된다.

    좌표 축척(UMAP 출력 범위)이 데이터마다 달라 거리 기반 eps 튜닝이 번거로운
    DBSCAN 대신, 최소 군집 크기만 정하면 되는 HDBSCAN을 쓴다."""
    from sklearn.cluster import HDBSCAN

    if df.empty or len(df) < min_cluster_size:
        df = df.copy()
        df['cluster'] = -1
        df['cluster_label'] = ''
        return df

    clusterer = HDBSCAN(min_cluster_size=min_cluster_size, copy=False)
    labels = clusterer.fit_predict(df[['x', 'y']].to_numpy())

    df = df.copy()
    df['cluster'] = labels

    cluster_labels = {}
    for cid in set(labels):
        if cid == -1:
            continue
        members = df[df['cluster'] == cid].to_dict('records')
        cluster_labels[cid] = _cluster_label(members)
    df['cluster_label'] = df['cluster'].map(cluster_labels).fillna('')
    return df


def load_similarity_map(profile: str = 'default', n_neighbors: int = 15,
                         random_state: int = 42, min_cluster_size: int = 3) -> tuple:
    """연구원 전문성 임베딩을 UMAP으로 2D에 투영하고, HDBSCAN으로 유사 전문성
    영역을 클러스터링해 자동 이름을 붙인 DataFrame과, 임베딩 캐시가 없어
    지도에서 빠진 연구원 수를 반환한다.

    반환: (df, missing_count)
      df 컬럼: researcher_id, name, department, org_code, strength_fields(list),
               strength_keywords(list), x, y, cluster, cluster_label
      필요 입력 파일이 없거나(연구원 보유 전문성 분석.json/embedding_cache.json)
      좌표를 계산할 만큼 표본이 충분치 않으면(3명 미만) x/y 없는 빈 DataFrame을
      반환한다 — 호출부가 이를 보고 안내 메시지를 보여줄 수 있다."""
    suffix = _profile_suffix(profile)
    expertise_path = os.path.join(DATA_DIR, f'연구원 보유 전문성 분석{suffix}.json')
    cache_path = os.path.join(DATA_DIR, 'embedding_cache.json')

    if not os.path.exists(expertise_path) or not os.path.exists(cache_path):
        return pd.DataFrame(), 0

    with open(expertise_path, encoding='utf-8') as f:
        profiles = json.load(f)
    with open(cache_path, encoding='utf-8') as f:
        embed_cache = json.load(f)

    researchers_df = read_processed('researchers')
    name_map, dept_map, org_map = {}, {}, {}
    if not researchers_df.empty:
        indexed = researchers_df.set_index('researcher_id')
        name_map = indexed['name'].to_dict()
        dept_map = indexed['department'].to_dict()
        org_map = indexed['org_code'].to_dict()

    rows, vectors = [], []
    missing = 0
    for item in profiles:
        rid = item.get('researcher_id', '')
        vec = embed_cache.get(_text_hash(researcher_profile_text(item)))
        if vec is None:
            missing += 1
            continue
        vectors.append(vec)
        rows.append({
            'researcher_id': rid,
            'name': name_map.get(rid, ''),
            'department': dept_map.get(rid, '') or '미분류',
            'org_code': org_map.get(rid, '') or '미분류',
            'strength_fields': item.get('strength_fields') or [],
            'strength_keywords': item.get('strength_keywords') or [],
        })

    if len(rows) < 3:
        return pd.DataFrame(rows), missing

    import umap  # 무거운 의존성(numba JIT)이라 실제로 지도를 계산할 때만 임포트

    x = np.array(vectors, dtype=np.float32)
    safe_n_neighbors = max(2, min(n_neighbors, len(rows) - 1))
    reducer = umap.UMAP(n_neighbors=safe_n_neighbors, random_state=random_state)
    coords = reducer.fit_transform(x)

    df = pd.DataFrame(rows)
    df['x'] = coords[:, 0]
    df['y'] = coords[:, 1]
    df = compute_clusters(df, min_cluster_size=min_cluster_size)
    return df, missing
