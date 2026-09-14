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
삭제됐다 — docs/CLAUDE.md 참고.)
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
    batch_concurrency, call_llm, extract_json, get_truncation_count, max_concurrency,
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
    """embedding_cache.json을 읽는다 — 손상돼 있어도 예외를 던지지 않고 빈
    캐시로 취급한다(2026-09-16 수정). gunicorn --workers 2(app.py 참고 —
    이 프로젝트에 이미 워커 간 경쟁 조건 사례가 있음) 환경에서 두 워커가
    거의 동시에 cached_embed()를 호출하면 예전에는 둘 다 open(path, 'w')로
    같은 파일을 truncate+write해, 한쪽이 다 쓰기 전에 다른 쪽이 truncate를
    걸치는 순간이 생겨 파일이 "완성된 JSON + 그 뒤에 다른 워커가 쓰다 만
    나머지 바이트"로 깨질 수 있었다(JOB Market에서 실제로 재현된 사용자
    리포트 — json.JSONDecodeError: "Extra data: line 1 column N" 형태로
    나타남, N이 첫 번째 완성된 JSON 문서의 끝 위치). 이 캐시는 순수 성능
    캐시(임베딩 재계산만 하면 복구됨 — pipeline/load_to_db.py 참고)라
    손상된 내용을 버리고 빈 캐시로 다시 시작해도 데이터 유실이 없다.
    _save_embed_cache()의 원자적 쓰기(임시 파일 + os.replace)로 새 손상은
    막았지만, 이미 손상된 채 남아있는 기존 파일도 있을 수 있어 읽기 쪽도
    함께 방어한다."""
    if not os.path.exists(_EMBED_CACHE_PATH):
        return {}
    try:
        with open(_EMBED_CACHE_PATH, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_embed_cache(cache: dict):
    """임시 파일에 다 쓴 뒤 os.replace()로 원자적으로 교체한다 — 여러
    워커가 거의 동시에 저장해도(멱등적이지 않은 read-modify-write라
    한쪽의 신규 항목이 유실될 순 있어도, 이건 순수 성능 캐시라 다음 호출
    때 다시 계산되면 그만) 읽는 쪽은 항상 "완성된 이전 파일" 또는
    "완성된 새 파일" 중 하나만 보게 되어 _load_embed_cache()가 겪던
    파일 손상(위 docstring 참고)이 재발하지 않는다."""
    os.makedirs(OUT_DIR, exist_ok=True)
    tmp_path = f'{_EMBED_CACHE_PATH}.{os.getpid()}.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(cache, f)
    os.replace(tmp_path, _EMBED_CACHE_PATH)


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


