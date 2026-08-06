"""
좌측 상단 "기능 관련 수정/추가/보완/기타 의견 제출하기" 버튼 — 베타테스터
의견을 누적 CSV 한 파일(request_fucntion.csv, 파일명은 사용자 확정 표기
그대로)에 한 줄씩 추가한다. 로그인 체계가 없어 작성자는 선택 입력이다.

Source: data/processed/feedback/request_fucntion.csv
"""

import csv
import os
import threading
from datetime import datetime

from services import data_store

FEEDBACK_DIR = os.path.join(data_store.DATA_DIR, 'feedback')
FEEDBACK_PATH = os.path.join(FEEDBACK_DIR, 'request_fucntion.csv')

CATEGORIES = ['수정', '추가', '보완', '기타']

_FIELDNAMES = ['제출일시', '구분', '작성자', '내용']

# threaded=True(app.py)로 여러 사용자가 동시에 제출할 수 있어, 파일에 줄을
# 추가하는 동안 프로세스 내 락으로 서로 다른 제출의 쓰기가 섞이지 않게 한다.
_write_lock = threading.Lock()


def submit_feedback(category: str, message: str, author: str = '') -> None:
    """의견 한 건을 request_fucntion.csv에 한 줄 추가한다. 내용이 비어 있으면
    ValueError(호출부가 화면에 그대로 안내 문구로 보여줄 수 있음)."""
    category = (category or '').strip()
    if category not in CATEGORIES:
        category = '기타'
    message = (message or '').strip()
    if not message:
        raise ValueError('내용을 입력해주세요.')

    row = {
        '제출일시': datetime.now().isoformat(timespec='seconds'),
        '구분': category,
        '작성자': (author or '').strip(),
        '내용': message,
    }
    with _write_lock:
        os.makedirs(FEEDBACK_DIR, exist_ok=True)
        is_new = not os.path.isfile(FEEDBACK_PATH)
        with open(FEEDBACK_PATH, 'a', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=_FIELDNAMES)
            if is_new:
                writer.writeheader()
            writer.writerow(row)
