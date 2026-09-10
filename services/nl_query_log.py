"""
AI 검색(자연어 질문) 쿼리 로깅 — 질문/intent/성공 여부/오류/건수를
data/processed/nl_query_log.csv에 한 줄씩 누적한다(services/feedback.py와
동일한 append-only CSV 패턴).

지금까지 이 앱의 자연어 질문 기능은 실행할 때마다 결과만 보여주고 끝 —
어떤 질문이 얼마나 자주 들어오는지, 어떤 질문에서 실패(error/unsupported/
빈 결과)가 나는지 기록이 전혀 없어 기능을 개선할 근거가 없었다(2026-08
중순 "AI 검색 강화 방법" 검토에서 지적된 가장 큰 공백). 이 모듈이 그
공백을 메운다 — services/nl_query.py의 단일 진입점 answer_question()
한 곳에서만 호출하면 구조화 3-intent/open_data_query 폴백 전부가
자동으로 기록된다.

민감정보를 남기지 않으려고 질문 원문과 intent/성공여부/오류/건수만
기록하고, 결과 행 데이터(연구원 이름 등)는 저장하지 않는다.
"""

import csv
import os
import threading
from datetime import datetime

from services import auth, data_store

LOG_DIR = data_store.DATA_DIR
LOG_PATH = os.path.join(LOG_DIR, 'nl_query_log.csv')

_FIELDNAMES = [
    '시각', '사용자', '질문', 'intent', '성공여부', '건수', '검색기준', '기간', '비고',
]

# app.py가 threaded=True라 여러 사용자가 동시에 질문을 보낼 수 있어, 파일에
# 줄을 추가하는 동안 프로세스 내 락으로 서로 다른 기록의 쓰기가 섞이지 않게
# 한다(services/feedback.py와 동일한 이유).
_write_lock = threading.Lock()

# 성공 판정: error/unsupported가 아니고 결과 행이 1건 이상이면 성공으로 본다.
# unsupported/error는 항상 실패, "정상 조회됐지만 0건"은 절반의 성공(질의
# 자체는 이해했지만 데이터가 없음)이라 별도 상태로 남긴다.
_FAIL_INTENTS = {'error', 'unsupported'}


def _status_for(result: dict) -> str:
    intent = result.get('intent')
    if intent in _FAIL_INTENTS:
        return '실패'
    total = result.get('total_rows')
    if total is None:
        total = len(result.get('rows') or [])
    return '성공' if total else '결과없음'


def log_query(question: str, result: dict, current_only: bool = True,
              period: tuple | None = None) -> None:
    """질문 1건의 처리 결과를 로그에 한 줄 추가한다. 로깅 자체가 실패해도
    (디스크 오류 등) 검색 기능에 영향을 주면 안 되므로 예외를 절대 밖으로
    던지지 않는다(best-effort)."""
    try:
        user = auth.get_current_user() or {}
        total = result.get('total_rows')
        if total is None:
            total = len(result.get('rows') or [])
        note = result.get('message') or result.get('note') or ''
        row = {
            '시각': datetime.now().isoformat(timespec='seconds'),
            '사용자': user.get('user_id', ''),
            '질문': (question or '').strip(),
            'intent': result.get('intent', ''),
            '성공여부': _status_for(result),
            '건수': total,
            '검색기준': '현재' if current_only else '과거포함',
            '기간': f'{period[0]}~{period[1]}' if period else '',
            '비고': str(note)[:300],
        }
        with _write_lock:
            os.makedirs(LOG_DIR, exist_ok=True)
            is_new = not os.path.isfile(LOG_PATH)
            with open(LOG_PATH, 'a', encoding='utf-8-sig', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=_FIELDNAMES)
                if is_new:
                    writer.writeheader()
                writer.writerow(row)
    except Exception:  # noqa: BLE001 — 로깅 실패가 검색 기능을 막으면 안 됨
        pass


def read_recent(limit: int = 200) -> list[dict]:
    """관리자 화면(pages/admin.py "AI 검색 로그" 탭)에서 최근 기록을 최신순으로
    보여줄 때 쓴다. 파일이 없으면 빈 리스트."""
    if not os.path.isfile(LOG_PATH):
        return []
    with open(LOG_PATH, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    return list(reversed(rows))[:limit]
