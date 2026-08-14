"""
과제 정보 처리 모듈

원천: source_reader.read_source('tasks_information')
  → DB tasks_information_stg 테이블 또는 data/raw_csv/tasks_information.csv
  (1단계 xlsx_to_raw_csv.py가 data/raw/과제정보.xlsx를 DRM 제거해 만든 사본)
출력 파일: data/processed/tasks_information.csv

컬럼 매핑:
  과제명                        → task_name
  과제코드                      → task_code
  관계사                        → task_collabo
  개요_목표(수행목적)            → task_goal
  개요_가치                     → task_value
  개요_확보전략(목표)            → task_howtoget
  개요_예상문제                 → task_expectissue
  개요_주요 활용 Activity 계획   → task_Activityplan
  개요_향후활용계획(향후계획)     → task_futureusage
  작성일                        → write_date (YYYY-MM-DD)

중복 제거 (task_name 기준, tasks.csv와 1:1로 조인되도록 보장):
  동일한 task_name을 가진 행이 여러 개면 아래 우선순위로 1건만 남긴다.
    1순위: task_collabo~task_futureusage 중 값이 채워진 컬럼 수가 많은 행
    2순위: (1이 동률일 때) write_date가 가장 최근인 행
  ※ task_code가 같아도 task_name이 다르면(예: 과제 진행 중 개명) 서로 다른
    행으로 보존한다 — task_code 기준으로만 줄이면 tasks.csv가 참조하는
    과거 시점의 과제명이 유실되어 조인이 실패할 수 있기 때문.
  ※ task_name이 비어있는 행은 서로 다른 항목으로 간주해 중복 제거 대상에서 제외

컬럼 설정 (실제 파일 헤더에 맞게 상단 상수 수정):
  COL_NAME         : 과제명 컬럼명
  COL_CODE         : 과제코드 컬럼명
  COL_COLLABO      : 관계사 컬럼명
  COL_GOAL         : 개요_목표(수행목적) 컬럼명
  COL_VALUE        : 개요_가치 컬럼명
  COL_HOWTOGET     : 개요_확보전략(목표) 컬럼명
  COL_EXPECTISSUE  : 개요_예상문제 컬럼명
  COL_ACTIVITYPLAN : 개요_주요 활용 Activity 계획 컬럼명
  COL_FUTUREUSAGE  : 개요_향후활용계획(향후계획) 컬럼명
  COL_WRITE_DATE   : 작성일 컬럼명
"""

import os
import sys

import pandas as pd

TASK_INFO_FILE = '과제정보.xlsx'

# ── 컬럼명 설정 (파일 헤더와 다를 경우 여기서 수정) ──────────────────────────
COL_NAME         = '과제명'
COL_CODE         = '과제코드'
COL_COLLABO      = '관계사'
COL_GOAL         = '개요_목표(수행목적)'
COL_VALUE        = '개요_가치'
COL_HOWTOGET     = '개요_확보전략(목표)'
COL_EXPECTISSUE  = '개요_예상문제'
COL_ACTIVITYPLAN = '개요_주요 활용 Activity 계획'
COL_FUTUREUSAGE  = '개요_향후활용계획(향후계획)'
COL_WRITE_DATE   = '작성일'
# ─────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR, OUT_DIR  # noqa: E402
from excel_reader import excel_safe_text, is_blank, parse_yyyymmdd, read_xlsx
from merge_utils import TABLE_KEYS, write_merged
from source_reader import read_source

_CONTENT_COLS = [
    'task_collabo', 'task_goal', 'task_value', 'task_howtoget',
    'task_expectissue', 'task_Activityplan', 'task_futureusage',
]


def _filled_count(row) -> int:
    """task_collabo~task_futureusage 중 값이 채워진 컬럼 수."""
    return sum(1 for c in _CONTENT_COLS if not is_blank(row[c]))


def _dedupe_by_name(df: pd.DataFrame) -> pd.DataFrame:
    """task_name이 동일한 행 중, 채워진 항목이 가장 많은 행을 우선하고(신뢰도),
    그 수가 같으면 write_date가 가장 최근인 행을 남긴다.
    task_name이 빈 행은 서로 다른 항목으로 간주해 중복 제거 대상에서 제외한다."""
    has_name = df['task_name'].astype(str).str.strip() != ''
    with_name = df[has_name].copy()
    without_name = df[~has_name]

    with_name['_filled_count'] = with_name.apply(_filled_count, axis=1)
    with_name = (with_name
                 .sort_values(['_filled_count', 'write_date'])
                 .drop_duplicates('task_name', keep='last')
                 .drop(columns='_filled_count'))
    return pd.concat([with_name, without_name], ignore_index=True)


def process(raw_dir: str = RAW_DIR) -> bool:
    if raw_dir == RAW_DIR:
        df = read_source('tasks_information')
        if df is None:
            print('[SKIP] tasks_information 원천 데이터 없음 '
                  '(DB tasks_information_stg 또는 data/raw_csv/tasks_information.csv) — tasks_information_raw 폴백 시도')
    else:
        raw_path = os.path.join(raw_dir, TASK_INFO_FILE)
        if os.path.exists(raw_path):
            df = read_xlsx(raw_path)
        else:
            df = None
            print(f'[SKIP] {TASK_INFO_FILE} 파일 없음({raw_dir})')

    if df is None:
        return False
    df.columns = [str(c).strip() for c in df.columns]

    required = [COL_NAME, COL_CODE, COL_WRITE_DATE]
    missing = [c for c in required if c not in df.columns]
    if missing:
        print(
            f'[ERROR] 필수 컬럼 없음: {missing}\n'
            f'  process_task_information.py 상단의 컬럼명 상수를 실제 헤더에 맞게 수정하세요.\n'
            f'  현재 파일 헤더: {list(df.columns)}'
        )
        return False

    def _col(name):
        return df[name].astype(str).str.strip() if name in df.columns else pd.Series('', index=df.index)

    result = pd.DataFrame({
        'task_name':         _col(COL_NAME),
        'task_code':         _col(COL_CODE),
        'task_collabo':      _col(COL_COLLABO),
        'task_goal':         _col(COL_GOAL),
        'task_value':        _col(COL_VALUE),
        'task_howtoget':     _col(COL_HOWTOGET),
        'task_expectissue':  _col(COL_EXPECTISSUE),
        'task_Activityplan': _col(COL_ACTIVITYPLAN),
        'task_futureusage':  _col(COL_FUTUREUSAGE),
        'write_date':        df[COL_WRITE_DATE].apply(parse_yyyymmdd),
    })

    before = len(result)
    result = _dedupe_by_name(result)
    after = len(result)

    result = result.sort_values('task_name').reset_index(drop=True)

    # '- 대사공학 역량...' 처럼 '-'(또는 '=', '+', '@')로 시작하는 값을 Excel이
    # 수식으로 오인해 #NAME? 오류를 내는 문제 방지 (CSV에 저장하기 직전에만 적용)
    for col in _CONTENT_COLS:
        result[col] = result[col].apply(excel_safe_text)

    out_path = os.path.join(OUT_DIR, 'tasks_information.csv')
    merged = write_merged(out_path, result, TABLE_KEYS['tasks_information'])

    print(f'[OK]   tasks_information.csv 저장 (총 {len(merged)}행, 이번 파일 {after}행 반영, 파일 내 중복 제거로 {before - after}행 제외)')
    return True


if __name__ == '__main__':
    process()
