"""
연구원 전문성 프로필 텍스트 구성 + BGE-M3 임베딩 공용 유틸리티.

process_researcher_similarity.py(연구원↔연구원 유사도)가 researcher_profile_text()/
cached_embed()/cosine_sim_matrix() 전체를 쓰고, services/jd_reconciliation.py
(과제 직무/대상자 검증)는 researcher_profile_text()만 재사용한다.

※ LLM 프롬프트에는 researcher_id/이름을 절대 포함하지 않는다 — 이 원칙은
  이 모듈을 쓰는 모든 호출부가 지킨다.

임베딩은 텍스트 내용 해시 기준으로 캐시(cached_embed, embedding_cache.json)해
재사용한다. 캐시 키가 텍스트 내용 자체의 해시라, 연구원 전문성 분석이 갱신돼
텍스트가 바뀌면 자동으로 새 항목으로 취급돼 별도 새로고침 옵션 없이도 항상
최신 텍스트에 맞는 임베딩을 쓴다.

(예전에는 이 모듈이 process_project_researcher_fit.py의 과제↔연구원 매칭
로직도 함께 담고 있었지만, 그 기능 자체가 제거되면서 관련 함수도 함께
삭제됐다 — data/processed/CLAUDE.md 참고.)
"""

import hashlib
import json
import os
import re
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import BASE_DIR, OUT_DIR  # noqa: E402
sys.path.insert(0, BASE_DIR)
from llm_client import (  # noqa: E402
    call_llm, extract_json, get_truncation_count, max_concurrency,
    reset_truncation_count, run_concurrent,
)
from services.llm import LLMError, embed  # noqa: E402,F401 (embed/LLMError는 호출부에서도 사용)

TOP_K = 5

_EMBED_CACHE_PATH = os.path.join(OUT_DIR, 'embedding_cache.json')


def normalize_org_code(text: str) -> str:
    """researchers.csv의 org_code와 project_confl_address.csv의 project_name을
    서로 비교 가능한 형태로 정규화한다.

    project_name은 "[탐색] 가나다라마바사"처럼 앞에 대괄호 분류 태그가 붙고
    띄어쓰기도 있을 수도/없을 수도 있는 반면, org_code는 "가나다라마바사"처럼
    태그도 공백도 없는 형태다 — 앞쪽 대괄호 태그(있으면)를 떼고 모든 공백을
    제거해야 두 값이 정확히 같아진다.

    process_project_expertise.py(_resolve_personnel)와
    services/jd_reconciliation.py(get_project_members)가 이 함수를 공유해서
    "이 과제 사람" 판별 기준이 항상 일치하도록 한다."""
    s = re.sub(r'^\[[^\]]*\]\s*', '', str(text or '').strip())
    return re.sub(r'\s+', '', s)


def read_researchers(out_dir: str) -> pd.DataFrame:
    path = os.path.join(out_dir, 'researchers.csv')
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')
    df['researcher_id'] = df['researcher_id'].astype(str).str.zfill(8)
    return df


def read_education(out_dir: str) -> pd.DataFrame:
    """read_researchers()와 동일한 패턴 — process_researcher_similarity.py의
    학력 기반 하드 파티션(build_degree_map())이 사용."""
    path = os.path.join(out_dir, 'education.csv')
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')
    df['researcher_id'] = df['researcher_id'].astype(str).str.zfill(8)
    return df


def researcher_profile_text(profile: dict) -> str:
    parts = []
    if profile.get('strength_fields'):
        parts.append('강점 분야: ' + ', '.join(profile['strength_fields']))
    if profile.get('strength_keywords'):
        parts.append('강점 키워드: ' + ', '.join(profile['strength_keywords']))
    if profile.get('key_responsibilities'):
        parts.append('주요 역할·책임: ' + '; '.join(profile['key_responsibilities']))
    if profile.get('domain_knowledge_skill'):
        parts.append('전문지식 및 역량: ' + '; '.join(profile['domain_knowledge_skill']))
    return '\n'.join(parts) if parts else '(전문성 데이터 없음)'


def cosine_sim_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a_norm = a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-9)
    b_norm = b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-9)
    return a_norm @ b_norm.T


def top_k_idx(sims_row: np.ndarray, k: int) -> list:
    order = np.argsort(-sims_row)
    return order[:k].tolist()


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _load_embed_cache() -> dict:
    if not os.path.exists(_EMBED_CACHE_PATH):
        return {}
    with open(_EMBED_CACHE_PATH, encoding='utf-8') as f:
        return json.load(f)


def _save_embed_cache(cache: dict):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(_EMBED_CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache, f)


def cached_embed(texts: list) -> np.ndarray:
    """embed()를 텍스트 내용 해시 기준으로 캐시해 재사용한다. 캐시에 없는
    텍스트만 모아 한 번에 embed() 호출하고(실패 시 LLMError 그대로 전파),
    결과를 캐시에 채운 뒤 저장한다(embedding_cache.json,
    process_researcher_similarity.py가 사용)."""
    cache = _load_embed_cache()
    hashes = [_text_hash(t) for t in texts]
    missing_idx = [i for i, h in enumerate(hashes) if h not in cache]
    if missing_idx:
        new_vectors = embed([texts[i] for i in missing_idx])
        for i, vec in zip(missing_idx, new_vectors):
            cache[hashes[i]] = vec
        _save_embed_cache(cache)
    return np.array([cache[h] for h in hashes], dtype=np.float32)


