"""
임직원 직무이력 처리 모듈

원천: source_reader.read_source('job_profile')
  → DB job_profile_stg 테이블 또는 data/raw_csv/job_profile.csv
  (1단계 xlsx_to_raw_csv.py가 data/raw/임직원_직무이력.xlsx를 DRM 제거해 만든 사본)
출력 파일: data/processed/job_profile.csv

읽는 컬럼:
  사번, 성명, 직무, 시작일, 종료일

처리:
  - 동일 인물의 동일 직무(job_profile_name)가 연속되는 경우(이전 종료일 + 1일 =
    다음 시작일) 하나의 기간으로 통합합니다.
  - 종료일이 비어있으면 진행중(현재 직무)으로 보고, 출력 컬럼도 빈 값으로 둡니다
    (타임라인에서는 이를 "진행중"으로 표기). 시작일 값으로 임의 대체하지 않습니다.
  - researcher_id별로 여러 직무 기간을 옆으로 펼쳐(wide) 한 행으로 만듭니다.
    슬롯 수(N)는 고정값이 아니라, 실제 데이터에서 한 사람이 가진 최대 직무
    기간 수로 정해집니다.

출력 스키마:
  researcher_id, name,
  job_profile_name_1, job_start_date_1, job_end_date_1, ...,
  job_profile_name_N, job_start_date_N, job_end_date_N

컬럼명이 다를 경우 파일 상단의 COL_* 상수를 수정하세요.
"""

import os
import sys

import pandas as pd

JOB_PROFILE_FILE = '임직원_직무이력.xlsx'

# ── 컬럼명 설정 (파일 헤더와 다를 경우 여기서 수정) ──────────────────────────
COL_ID    = '사번'
COL_NAME  = '성명'
COL_JOB   = '직무'
COL_START = '시작일'
COL_END   = '종료일'
# ─────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR, OUT_DIR  # noqa: E402
from excel_reader import clean_str as _clean, read_xlsx, norm_id
from merge_utils import TABLE_KEYS, write_merged
from source_reader import read_source


def _parse_date(val):
    s = str(val).strip() if val is not None else ''
    if not s or s.lower() in ('nan', 'none', 'nat'):
        return None
    try:
        return pd.Timestamp(s)
    except (ValueError, TypeError):
        return None


def _merge_consecutive(records):
    """records: 한 사람의 직무 기록 리스트({'job','start','end'}), start 오름차순
    정렬된 상태. 같은 job이 '종료일 + 1일 = 다음 시작일'로 이어지면 하나로 합친다.
    end=None은 종료일 없음(진행중)을 뜻하며, 그 뒤로는 추가 병합을 시도하지 않는다."""
    if not records:
        return []
    merged = [dict(records[0])]
    for rec in records[1:]:
        prev = merged[-1]
        if (rec['job'] == prev['job'] and prev['end'] is not None
                and rec['start'] == prev['end'] + pd.Timedelta(days=1)):
            prev['end'] = rec['end']
        else:
            merged.append(dict(rec))
    return merged


def process(raw_dir: str = RAW_DIR) -> bool:
    if raw_dir == RAW_DIR:
        df = read_source('job_profile')
        if df is None:
            print('[SKIP] job_profile 원천 데이터 없음 '
                  '(DB job_profile_stg 또는 data/raw_csv/job_profile.csv) — job_profile_raw 폴백 시도')
    else:
        raw_path = os.path.join(raw_dir, JOB_PROFILE_FILE)
        if os.path.exists(raw_path):
            df = read_xlsx(raw_path)
        else:
            df = None
            print(f'[SKIP] {JOB_PROFILE_FILE} 파일 없음({raw_dir})')

    if df is None:
        return False
    df.columns = [str(c).strip() for c in df.columns]

    for col in (COL_ID, COL_JOB, COL_START, COL_END):
        if col not in df.columns:
            print(
                f'[ERROR] 필수 컬럼 없음: [{col}]\n'
                f'  process_job_profile.py 상단의 COL_* 상수를 실제 헤더에 맞게 수정하세요.\n'
                f'  현재 파일 헤더: {list(df.columns)}'
            )
            return False

    df['researcher_id'] = df[COL_ID].apply(norm_id)
    df = df[df['researcher_id'] != ''].copy()

    by_researcher = {}
    names = {}
    for _, row in df.iterrows():
        rid = row['researcher_id']
        start = _parse_date(row.get(COL_START))
        if start is None:
            continue
        end = _parse_date(row.get(COL_END))
        if end is not None and end < start:
            end = start
        job = _clean(row.get(COL_JOB))
        by_researcher.setdefault(rid, []).append({'job': job, 'start': start, 'end': end})
        if rid not in names:
            names[rid] = _clean(row.get(COL_NAME))

    merged_by_researcher = {}
    max_n = 0
    for rid, records in by_researcher.items():
        records.sort(key=lambda r: r['start'])
        merged = _merge_consecutive(records)
        merged_by_researcher[rid] = merged
        max_n = max(max_n, len(merged))

    out_cols = ['researcher_id', 'name']
    for i in range(1, max_n + 1):
        out_cols += [f'job_profile_name_{i}', f'job_start_date_{i}', f'job_end_date_{i}']

    rows = []
    for rid in sorted(merged_by_researcher):
        merged = merged_by_researcher[rid]
        row = {'researcher_id': rid, 'name': names.get(rid, '')}
        for i in range(1, max_n + 1):
            if i <= len(merged):
                rec = merged[i - 1]
                row[f'job_profile_name_{i}'] = rec['job']
                row[f'job_start_date_{i}'] = rec['start'].strftime('%Y-%m-%d')
                row[f'job_end_date_{i}'] = rec['end'].strftime('%Y-%m-%d') if rec['end'] is not None else ''
            else:
                row[f'job_profile_name_{i}'] = ''
                row[f'job_start_date_{i}'] = ''
                row[f'job_end_date_{i}'] = ''
        rows.append(row)

    result = pd.DataFrame(rows, columns=out_cols)

    out_path = os.path.join(OUT_DIR, 'job_profile.csv')
    merged = write_merged(out_path, result, TABLE_KEYS['job_profile'])

    print(f'[OK]   job_profile.csv 저장 (총 {len(merged)}행, 이번 파일 {len(result)}행 반영, 이번 파일 최대 {max_n}개 직무 슬롯)')
    return True


if __name__ == '__main__':
    process()
