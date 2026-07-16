"""
SAIT 부서 직무정보 처리 모듈

원천 파일: data/raw/직무정보_부서.xlsx
출력 파일: data/processed/job_profile_info_sait.json

읽는 컬럼:
  직무, 세부직무, 정의

처리:
  - xlsx를 JSON 배열로 변환합니다.

출력 스키마:
  [{"job_profile_sait": "...", "job_profile_detail_sait": "...",
    "explain_job_profile_sait": "..."}, ...]

컬럼명이 다를 경우 파일 상단의 COL_* 상수를 수정하세요.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from excel_reader import read_xlsx

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'raw')
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed')

SOURCE_FILE = '직무정보_부서.xlsx'

# ── 컬럼명 설정 (파일 헤더와 다를 경우 여기서 수정) ──────────────────────────
COL_JOB = '직무'
COL_DETAIL = '세부직무'
COL_EXPLAIN = '정의'
# ─────────────────────────────────────────────────────────────────────────────


def _clean(val) -> str:
    s = str(val).strip() if val is not None else ''
    return '' if s.lower() in ('nan', 'none', 'nat') else s


def process() -> bool:
    raw_path = os.path.join(RAW_DIR, SOURCE_FILE)
    if not os.path.exists(raw_path):
        print(f'[SKIP] {SOURCE_FILE} 파일 없음')
        return False

    df = read_xlsx(raw_path)
    df.columns = [str(c).strip() for c in df.columns]

    for col in (COL_JOB, COL_DETAIL, COL_EXPLAIN):
        if col not in df.columns:
            print(
                f'[ERROR] 필수 컬럼 없음: [{col}]\n'
                f'  process_job_profile_sait.py 상단의 COL_* 상수를 실제 헤더에 맞게 수정하세요.\n'
                f'  현재 파일 헤더: {list(df.columns)}'
            )
            return False

    items = []
    for _, row in df.iterrows():
        job = _clean(row.get(COL_JOB))
        if not job:
            continue
        items.append({
            'job_profile_sait': job,
            'job_profile_detail_sait': _clean(row.get(COL_DETAIL)),
            'explain_job_profile_sait': _clean(row.get(COL_EXPLAIN)),
        })

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'job_profile_info_sait.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

    print(f'[OK]   job_profile_info_sait.json 저장 ({len(items)}건)')
    return True


if __name__ == '__main__':
    process()
