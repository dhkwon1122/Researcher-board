"""
핵심기술 처리 모듈

원천: source_reader.read_source('core_technology')
  → DB core_technology_stg 테이블 또는 data/raw_csv/core_technology.csv
  (1단계 xlsx_to_raw_csv.py가 data/raw/핵심기술.xlsx를 DRM 제거해 만든 사본)
출력 파일: data/processed/core_technology.csv, data/processed/core_technology_history.csv

읽는 컬럼:
  사원번호, 기술 분야, 핵심기술, 등급

출력 스키마:
  researcher_id, tech_field, tech_name, tech_grade, valid_year, valid_month
  (core_technology.csv는 valid_year/valid_month를 포함해 그대로 저장한다 —
  아래 시점 보호 참고. tech_grade 값이 없으면 '-'로 표기)

── 시점 보호(valid_year/valid_month) ──────────────────────────────────────
예전에는 매 실행마다 이 파일 전체를 통째로 덮어썼다(자연키 upsert가 아예
없었음) — 부분 인원만 담긴 파일을 올리면 나머지 사람의 기존 데이터가
사라지고, 옛날 파일을 나중에 다시 올리면 최신 데이터 전체가 옛날 것으로
되돌아가는 버그가 있었다(data/processed/CLAUDE.md 참고). 지금은 evaluations/
tech_ownership/job_profile/work_objective와 같은 방식으로, (researcher_id,
tech_field, tech_name) 조합 단위 업서트 + valid_year/valid_month 시점 보호로
바꿨다 — 그 조합에 이미 저장된 값보다 과거 시점이면 그 항목만 건너뛰고
경고하며, 건너뛴 것 포함 전체는 core_technology_history.csv에 항상 쌓인다.

컬럼명이 다를 경우 파일 상단의 COL_* 상수를 수정하세요.
"""

import os
import sys
from datetime import date

import pandas as pd

CORE_TECH_FILE = '핵심기술.xlsx'

# ── 컬럼명 설정 (파일 헤더와 다를 경우 여기서 수정) ──────────────────────────
COL_ID    = '사원번호'
COL_FIELD = '기술 분야'
COL_NAME  = '핵심기술'
COL_GRADE = '등급'
# ─────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR, OUT_DIR  # noqa: E402
from excel_reader import read_xlsx, norm_id
from merge_utils import TABLE_KEYS, write_merged_with_valid_period
from source_reader import read_source


def process(raw_dir: str = RAW_DIR, valid_date: date | None = None) -> bool:
    """valid_date: 이번 업로드분의 기준 연/월(기본값 오늘) — core_technology.csv에
    이미 저장된 (사람, 기술분야, 핵심기술) 조합보다 과거 시점이면 그 항목은
    갱신하지 않고 건너뛴다(core_technology_history.csv에는 건너뛴 것 포함
    전부 쌓인다)."""
    if raw_dir == RAW_DIR:
        df = read_source('core_technology')
        if df is None:
            print('[SKIP] core_technology 원천 데이터 없음 '
                  '(DB core_technology_stg 또는 data/raw_csv/core_technology.csv) — core_technology_raw 폴백 시도')
    else:
        raw_path = os.path.join(raw_dir, CORE_TECH_FILE)
        if os.path.exists(raw_path):
            df = read_xlsx(raw_path)
        else:
            df = None
            print(f'[SKIP] {CORE_TECH_FILE} 파일 없음({raw_dir})')

    if df is None:
        return False
    df.columns = [str(c).strip() for c in df.columns]

    if COL_ID not in df.columns:
        print(
            f'[ERROR] 필수 컬럼 없음: [{COL_ID}]\n'
            f'  process_core_technology.py 상단의 COL_ID를 실제 헤더에 맞게 수정하세요.\n'
            f'  현재 파일 헤더: {list(df.columns)}'
        )
        return False

    df['researcher_id'] = df[COL_ID].apply(norm_id)
    df = df[df['researcher_id'] != ''].copy()

    def _col(name):
        if name not in df.columns:
            return pd.Series('', index=df.index)
        s = df[name]
        return s.where(~s.isna(), '').astype(str).str.strip()

    result = pd.DataFrame({
        'researcher_id': df['researcher_id'],
        'tech_field':    _col(COL_FIELD),
        'tech_name':     _col(COL_NAME),
        'tech_grade':    _col(COL_GRADE),
    })
    result = result.replace({'nan': '', 'None': ''})
    result.loc[result['tech_grade'] == '', 'tech_grade'] = '-'
    result = result.sort_values(['researcher_id']).reset_index(drop=True)

    valid_date = valid_date or date.today()
    result['valid_year'] = f'{valid_date.year:04d}'
    result['valid_month'] = f'{valid_date.month:02d}'

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'core_technology.csv')
    hist_path = os.path.join(OUT_DIR, 'core_technology_history.csv')
    outcome = write_merged_with_valid_period(
        out_path, hist_path, result, TABLE_KEYS['core_technology'], TABLE_KEYS['core_technology_history'])

    n = result['researcher_id'].nunique()
    print(f'[OK]   core_technology.csv 저장 (이번 파일 {len(result)}행({n}명) 중 '
          f'{outcome["updated_rows"]}행 반영)')
    if outcome['skipped']:
        print(f'  [WARN] {len(outcome["skipped"])}건은 기존 저장된 값이 더 최신이라 건너뜀:')
        for s in outcome['skipped'][:10]:
            e = s['entity']
            print(f'    · {e.get("researcher_id", "")}/{e.get("tech_field", "")}/{e.get("tech_name", "")}: '
                  f'기존 {s["existing_period"]} > 이번 {s["new_period"]}')
        if len(outcome['skipped']) > 10:
            print(f'    · 외 {len(outcome["skipped"]) - 10}건')
    return True


if __name__ == '__main__':
    process()
