"""
표준 직무정보 처리 모듈

원천 파일: data/raw/직무정보_표준.xlsx
출력 파일: data/processed/job_profile_info_standard.json

읽는 컬럼:
  직무, 정의

처리:
  - xlsx를 JSON 배열로 변환합니다.

출력 스키마:
  [{"job_profile_standard": "...", "explain_job_profile_standard": "..."}, ...]

컬럼명이 다를 경우 파일 상단의 COL_* 상수를 수정하세요.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR, OUT_DIR  # noqa: E402
from excel_reader import clean_str as _clean, read_xlsx

SOURCE_FILE = '직무정보_표준.xlsx'

# ── 컬럼명 설정 (파일 헤더와 다를 경우 여기서 수정) ──────────────────────────
COL_JOB = '직무'
COL_EXPLAIN = '정의'
# ─────────────────────────────────────────────────────────────────────────────


def process() -> bool:
    raw_path = os.path.join(RAW_DIR, SOURCE_FILE)
    if not os.path.exists(raw_path):
        print(f'[SKIP] {SOURCE_FILE} 파일 없음')
        return False

    df = read_xlsx(raw_path)
    df.columns = [str(c).strip() for c in df.columns]

    for col in (COL_JOB, COL_EXPLAIN):
        if col not in df.columns:
            print(
                f'[ERROR] 필수 컬럼 없음: [{col}]\n'
                f'  process_job_profile_standard.py 상단의 COL_* 상수를 실제 헤더에 맞게 수정하세요.\n'
                f'  현재 파일 헤더: {list(df.columns)}'
            )
            return False

    items = []
    for _, row in df.iterrows():
        job = _clean(row.get(COL_JOB))
        if not job:
            continue
        items.append({
            'job_profile_standard': job,
            'explain_job_profile_standard': _clean(row.get(COL_EXPLAIN)),
        })

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'job_profile_info_standard.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

    print(f'[OK]   job_profile_info_standard.json 저장 ({len(items)}건)')
    return True


if __name__ == '__main__':
    process()
