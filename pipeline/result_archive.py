"""
분석 결과(json/html) 실행 이력 아카이브 저장 유틸리티.

data/processed의 '현재본'(파이프라인 체인용 — 예: process_researcher_similarity.py가
그대로 읽는 고정 파일명, 매 실행마다 덮어씀)은 전혀 건드리지 않는다. 그와는
별개로, 실행 시각을 파일명에 붙인 사본을 data/processed/result/<subfolder>/
아래에 추가로 남겨 이력이 누적되도록 한다(덮어쓰기 없음).
process_project_expertise.py, process_researcher_expertise.py,
process_researcher_similarity.py가 공용으로 사용한다.
"""

import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import BASE_DIR, RESULT_DIR  # noqa: E402


def archive_copy(subfolder: str, filename_base: str, ext: str, content: str) -> str:
    """data/processed/result/<subfolder>/에 '<filename_base>_<YYYYmmdd_HHMMSS>.<ext>'로 저장.
    폴더가 없으면 만들고, 같은 이름으로 덮어쓰지 않도록 매 호출마다 새 타임스탬프를 붙인다."""
    folder = os.path.join(RESULT_DIR, subfolder)
    os.makedirs(folder, exist_ok=True)
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    path = os.path.join(folder, f'{filename_base}_{ts}.{ext}')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f'[archive] {os.path.relpath(path, BASE_DIR)} 저장')
    return path
