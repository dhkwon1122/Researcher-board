"""
AI 검색(자연어 질문) 결과에 대한 사용자 피드백 — 좋아요/나빠요 즉시 평가와
서술형 개선 의견을 둘 다 받아 data/processed/nl_query_feedback.csv에
누적하고(services/feedback.py와 동일한 append-only 패턴), 다음 검색부터
"비슷한 과거 질문에 이런 피드백이 있었다"는 힌트로 프롬프트에 자동
주입한다 — 관리자가 수동으로 커스텀 규칙(services/query_settings.py)에
옮겨 적어야만 반영되던 것과 달리, 사용자가 남긴 서술형 의견이 별도 조치
없이도 다음 비슷한 질문부터 자동 반영된다.

매칭은 이 프로젝트가 이미 곳곳에서 쓰는 패턴(services/nl_query.expand_term(),
services/open_data_query._embedding_match())과 동일하게 BGE-M3 임베딩
코사인 유사도로 "비슷한 과거 질문"을 찾는다 — 정확히 같은 질문만 찾는 게
아니라 표현이 달라도 의미가 비슷하면 찾아지도록. 임베딩 서버가 없거나
실패해도(LLMError) 검색 기능 자체에는 영향이 없도록 항상 빈 결과로
안전하게 폴백한다.

찾아낸 과거 피드백은 그대로 "이 사람이 정답이다"로 신뢰하지 않고, LLM에게
"참고하되 실제 질문과 다르면 무시하라"는 조건을 달아 전달한다 — 이 프로젝트
전체의 "구조화 출력 강제, 환각 방지" 원칙과 같은 이유로, 잘못된 과거 피드백
하나가 관련 없는 질문에까지 영향을 주지 않게 하기 위함.
"""

import csv
import os
import sys
import threading
from datetime import datetime

from services import data_store

_PIPELINE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'pipeline')
sys.path.insert(0, os.path.abspath(_PIPELINE_DIR))

import researcher_fit as fit  # noqa: E402
from services.llm import LLMError  # noqa: E402

LOG_DIR = data_store.DATA_DIR
LOG_PATH = os.path.join(LOG_DIR, 'nl_query_feedback.csv')

_FIELDNAMES = ['시각', '사용자', '질문', 'intent', 'rating', '의견']
_MAX_COMMENT_LEN = 500

RATINGS = ('좋아요', '나빠요')

_SIMILARITY_THRESHOLD = 0.75
_TOP_N = 3

_write_lock = threading.Lock()


def submit_feedback(question: str, result: dict, rating: str = '', comment: str = '') -> None:
    """질문 1건에 대한 피드백을 한 줄 추가한다. rating/comment 중 최소 하나는
    있어야 한다(둘 다 비면 ValueError — 호출부가 화면에 안내). rating이
    RATINGS 밖의 값이면 빈 문자열로 무시한다."""
    question = (question or '').strip()
    rating = rating if rating in RATINGS else ''
    comment = (comment or '').strip()[:_MAX_COMMENT_LEN]
    if not question:
        raise ValueError('질문이 없습니다.')
    if not rating and not comment:
        raise ValueError('평가나 의견 중 하나는 입력해주세요.')

    from services import auth
    try:
        user = auth.get_current_user() or {}
    except RuntimeError:  # Flask 요청 컨텍스트 밖(테스트 등) — 사용자 없음으로 처리
        user = {}

    row = {
        '시각': datetime.now().isoformat(timespec='seconds'),
        '사용자': user.get('user_id', ''),
        '질문': question,
        'intent': (result or {}).get('intent', ''),
        'rating': rating,
        '의견': comment,
    }
    with _write_lock:
        os.makedirs(LOG_DIR, exist_ok=True)
        is_new = not os.path.isfile(LOG_PATH)
        with open(LOG_PATH, 'a', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=_FIELDNAMES)
            if is_new:
                writer.writeheader()
            writer.writerow(row)


def read_recent(limit: int = 200) -> list[dict]:
    """관리자 화면("AI 검색 로그" 탭)에서 최근 피드백을 최신순으로 보여줄 때
    쓴다. 파일이 없으면 빈 리스트."""
    if not os.path.isfile(LOG_PATH):
        return []
    with open(LOG_PATH, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    return list(reversed(rows))[:limit]


def find_similar_feedback(question: str, top_n: int = _TOP_N,
                           threshold: float = _SIMILARITY_THRESHOLD) -> list[dict]:
    """서술형 의견(comment)이 있는 과거 피드백 중, 지금 질문과 의미가 비슷한
    것을 최대 top_n건 찾는다. 평가(rating)만 있고 의견이 없는 피드백은 LLM에
    줄 만한 구체적 지시가 없어 제외한다(관리자 화면 통계용으로만 쓰임).
    임베딩 서버 미설정/실패 시 빈 리스트로 안전하게 폴백한다."""
    question = (question or '').strip()
    if not question:
        return []
    rows = [r for r in read_recent(500) if (r.get('의견') or '').strip()]
    if not rows:
        return []
    candidates = [r['질문'] for r in rows]
    try:
        vectors = fit.cached_embed([question] + candidates)
    except LLMError:
        return []
    except Exception:  # noqa: BLE001 — 이 힌트 하나가 실패해도 검색 자체는 계속돼야 함
        return []
    q_vec, pool_vecs = vectors[:1], vectors[1:]
    sims = fit.cosine_sim_matrix(q_vec, pool_vecs)[0]
    ranked = sorted(range(len(rows)), key=lambda i: -sims[i])[:top_n]
    return [
        {'question': rows[i]['질문'], 'comment': rows[i]['의견'], 'rating': rows[i].get('rating', '')}
        for i in ranked if sims[i] >= threshold
    ]


def feedback_hint_for(question: str) -> str:
    """SQL 생성/intent 분류 시스템 프롬프트 뒤에 그대로 덧붙일 수 있는 텍스트
    조각. 비슷한 과거 피드백이 없으면 빈 문자열(프롬프트에 아무 영향 없음)."""
    matches = find_similar_feedback(question)
    if not matches:
        return ''
    lines = '\n'.join(
        f'- 과거 질문 "{m["question"]}"에 대해 사용자가 남긴 의견: {m["comment"]}'
        for m in matches
    )
    return (
        '\n\n# 사용자 피드백 (비슷한 과거 질문에 남겨진 개선 의견 — 참고하되, '
        '지금 질문과 실제로 관련 없으면 무시할 것)\n' + lines
    )
