"""
직무_직군_맵핑 처리 모듈

원천: source_reader.read_source('mapping_job_function')
  → DB mapping_job_function_stg 테이블 또는 data/raw_csv/mapping_job_function.csv
  (1단계 xlsx_to_raw_csv.py가 data/raw/직무_직군_맵핑.xlsx를 DRM 제거해 만든 사본)
출력 파일: data/processed/mapping_job_function.csv

읽는 컬럼:
  직무, 직군(DS), 직군(SAIT)

처리:
  - 헤더를 job_function/job_category_DS/job_category_SAIT로 변환해 그대로 저장한다.
  - job_function(연구원의 job_function과 텍스트로 매칭할 키)이 빈 행은 제외.
  - job_function이 중복된 행이 있으면 첫 번째 행만 남기고 나머지는 버린다(경고 출력)
    — 이후 텍스트 매칭이 항상 1:1로 이뤄지도록 보장하기 위함.

출력 스키마:
  job_function, job_category_DS, job_category_SAIT

researcher_id 컬럼은 없다 — 매칭은 services/job_category.py가
researchers.csv의 job_function 값을 이 파일의 job_function과 텍스트로
비교해서 수행한다(연구원 개별 프로필 "보유기술" 배지, 전문성 MAP 호버
라벨 등 여러 화면이 공유). 이 파일은 researchers.csv와 달리 시점(연/월)
개념이 없는 순수 참조 테이블이라, 다른 이력형 테이블처럼 upsert하지
않고 매 실행마다 파일 전체를 새로 만든다(job_profile_info_sait.json 등
다른 참조 테이블과 동일한 방식).

컬럼명이 다를 경우 파일 상단의 COL_* 상수를 수정하세요.
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR, OUT_DIR  # noqa: E402
from excel_reader import clean_str as _clean, read_xlsx  # noqa: E402
from source_reader import read_source  # noqa: E402

SOURCE_FILE = '직무_직군_맵핑.xlsx'

# ── 컬럼명 설정 (파일 헤더와 다를 경우 여기서 수정) ──────────────────────────
COL_JOB_FUNCTION = '직무'
COL_CATEGORY_DS = '직군(DS)'
COL_CATEGORY_SAIT = '직군(SAIT)'
# ─────────────────────────────────────────────────────────────────────────────


def process(raw_dir: str = RAW_DIR) -> bool:
    if raw_dir == RAW_DIR:
        df = read_source('mapping_job_function')
        if df is None:
            print('[SKIP] mapping_job_function 원천 데이터 없음 '
                  '(DB mapping_job_function_stg 또는 data/raw_csv/mapping_job_function.csv)')
            return False
    else:
        raw_path = os.path.join(raw_dir, SOURCE_FILE)
        if not os.path.exists(raw_path):
            print(f'[SKIP] {SOURCE_FILE} 파일 없음({raw_dir})')
            return False
        df = read_xlsx(raw_path)

    df.columns = [str(c).strip() for c in df.columns]

    for col in (COL_JOB_FUNCTION, COL_CATEGORY_DS, COL_CATEGORY_SAIT):
        if col not in df.columns:
            print(
                f'[ERROR] 필수 컬럼 없음: [{col}]\n'
                f'  process_mapping_job_function.py 상단의 COL_* 상수를 실제 헤더에 맞게 수정하세요.\n'
                f'  현재 파일 헤더: {list(df.columns)}'
            )
            return False

    rows = []
    seen = set()
    dup_count = 0
    for _, row in df.iterrows():
        job_function = _clean(row.get(COL_JOB_FUNCTION))
        if not job_function:
            continue
        if job_function in seen:
            dup_count += 1
            continue
        seen.add(job_function)
        rows.append({
            'job_function': job_function,
            'job_category_DS': _clean(row.get(COL_CATEGORY_DS)),
            'job_category_SAIT': _clean(row.get(COL_CATEGORY_SAIT)),
        })

    if dup_count:
        print(f'  [WARN] 중복된 직무명 {dup_count}건은 첫 번째 행만 남기고 건너뜀')

    result = pd.DataFrame(rows, columns=['job_function', 'job_category_DS', 'job_category_SAIT'])

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'mapping_job_function.csv')
    result.to_csv(out_path, index=False, encoding='utf-8-sig')

    print(f'[OK]   mapping_job_function.csv 저장 ({len(result)}건)')
    return True


if __name__ == '__main__':
    process()
