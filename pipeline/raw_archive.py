"""
원본 파일 아카이브 — 업로드/처리되는 원본을 덮어쓰기 전에 타임스탬프를 붙여
별도 폴더(data/raw_archive/)에 무제한 보관한다(사용자 확정 — 정리 정책은
추후 판단).

지금까지는 웹 업로드(services/web_pipeline_runner.py)든 CLI 경로(data/raw/)든
새 원본이 오면 이전 원본이 그 자리에서 사라졌다 — 나중에 처리 로직 버그를
발견해도 그 시점 원본으로 재처리할 수 없고, "그때 정확히 뭘 올렸었나"
감사 추적도 안 됐다(data/processed/CLAUDE.md 2026-08-27 참고).

사용법:
    from raw_archive import archive_raw_file
    archive_raw_file(path_to_source_file, category='researchers')
    # → data/raw_archive/researchers/20260827_143012_인력현황.xlsx 로 복사
"""

import os
import shutil
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import BASE_DIR  # noqa: E402

RAW_ARCHIVE_DIR = os.path.join(BASE_DIR, 'data', 'raw_archive')


def archive_raw_file(source_path: str, category: str) -> str | None:
    """source_path의 현재 내용을 data/raw_archive/<category>/<YYYYMMDD_HHMMSS>_
    <원본파일명>으로 복사한다. source_path가 없으면 아무것도 하지 않고 None을
    반환(호출부가 실패로 취급하지 않도록 예외를 던지지 않음 — 아카이브 실패가
    실제 업로드/처리 흐름을 막아서는 안 되므로 존재 여부만 조용히 확인한다)."""
    if not source_path or not os.path.exists(source_path):
        return None

    dest_dir = os.path.join(RAW_ARCHIVE_DIR, category)
    os.makedirs(dest_dir, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = os.path.basename(source_path)
    dest_path = os.path.join(dest_dir, f'{timestamp}_{filename}')

    # 같은 초에 두 번 이상 호출되는 경우(거의 없지만) 덮어쓰지 않도록 번호를 붙인다.
    n = 1
    while os.path.exists(dest_path):
        dest_path = os.path.join(dest_dir, f'{timestamp}_{n}_{filename}')
        n += 1

    shutil.copy2(source_path, dest_path)
    return dest_path


def archive_raw_bytes(content_bytes: bytes, filename: str, category: str) -> str:
    """웹 업로드처럼 파일이 디스크에 먼저 존재하지 않고 바이트로 들어오는
    경우용 — 그대로 아카이브에 저장한다."""
    dest_dir = os.path.join(RAW_ARCHIVE_DIR, category)
    os.makedirs(dest_dir, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    dest_path = os.path.join(dest_dir, f'{timestamp}_{filename}')

    n = 1
    while os.path.exists(dest_path):
        dest_path = os.path.join(dest_dir, f'{timestamp}_{n}_{filename}')
        n += 1

    with open(dest_path, 'wb') as f:
        f.write(content_bytes)
    return dest_path
