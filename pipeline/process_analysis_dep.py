"""
전문성 분석 대상 부서 전처리 모듈

원천 파일: data/raw/전문성 분석 부서.xlsx
출력 파일: data/processed/analysis_dep.csv (컬럼: department)

process_researcher_expertise.py가 연구원 전문성 분석 대상을 정할 때, 연구원의
department(researchers.csv, 현소속부서명)가 이 목록에 있는 경우에만 분석
대상에 포함한다. 이 파일이 없으면(아직 준비 전이면) 부서 필터 없이 전체
연구원을 분석한다(process_researcher_expertise.py 쪽에서 처리).

과제 자체 분석(process_project_expertise.py)은 개인 department가 없는 과제
단위 데이터라 이 필터의 영향을 받지 않는다.

컬럼명이 다를 경우 파일 상단의 COL_DEPT 상수를 수정하세요.
"""

import csv
import os
import sys

RAW_FILE = '전문성 분석 부서.xlsx'
COL_DEPT = '현소속부서명'

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR, OUT_DIR  # noqa: E402
from excel_reader import is_blank, read_xlsx  # noqa: E402


def process() -> bool:
    raw_path = os.path.join(RAW_DIR, RAW_FILE)
    if not os.path.exists(raw_path):
        print(f'[SKIP] {RAW_FILE} 파일 없음')
        return False

    df = read_xlsx(raw_path)
    df.columns = [str(c).strip() for c in df.columns]

    if COL_DEPT not in df.columns:
        print(
            f'[ERROR] 필수 컬럼 없음: [{COL_DEPT}]\n'
            f'  process_analysis_dep.py 상단의 COL_DEPT 상수를 실제 헤더에 맞게 수정하세요.\n'
            f'  현재 파일 헤더: {list(df.columns)}'
        )
        return False

    depts = sorted({str(v).strip() for v in df[COL_DEPT] if not is_blank(v)})
    if not depts:
        print(f'[process_analysis_dep] {RAW_FILE}에서 유효한 {COL_DEPT} 값을 찾지 못함 — 종료')
        return False

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'analysis_dep.csv')
    with open(out_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        writer.writerow(['department'])
        for dept in depts:
            writer.writerow([dept])

    print(f'[OK]   analysis_dep.csv 저장 ({len(depts)}개 부서)')
    return True


if __name__ == '__main__':
    process()
