"""
팀참조시트(조직 계층 구조 + 각 조직 단위 책임자 정보) 처리 모듈

원천 파일: data/raw/팀참조시트.xlsx (헤더: 절대 2행, header_row=1)
출력 파일: data/processed/team_refer.csv

한 행 = 하나의 조직 단위(조직도의 노드 하나)이며, 그 조직 단위 책임자(부서장)의
사번/성명/직책이 함께 표기되어 있다 — 연구원별 1행이 아니라 조직 단위별 1행이다.

컬럼명 매핑(엑셀 헤더명 → 위치와 무관하게 이름으로 찾아 변환):
  과제파트명 → project_name    researchers.csv의 org_code와 매핑되는 조직 단위 키
  과제명통일 → end_name        조직도에 표시할 통일된 명칭
  조직 레벨  → team_layer      조직도 깊이(1~4). 비어 있으면 조직도에 표시되지 않는 행이므로 제외한다.
  사번      → researcher_id   해당 조직 단위 책임자(부서장) 사번
  성명      → name            해당 조직 단위 책임자 성명
  직책      → assignment_name 해당 조직 단위 책임자 직책 (예: PL/본부장/파트장)
  코드3     → code3           조직도 상 위계·표시 순서를 나타내는 코드 (예: A0000, B0100, B0101~B0116)

컬럼명이 다를 경우 파일 상단의 _COL_MAP을 실제 헤더에 맞게 수정하세요.
"""

import csv
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR, OUT_DIR  # noqa: E402
from excel_reader import clean_str as _clean, is_blank, norm_id, read_xlsx

SOURCE_FILE = '팀참조시트.xlsx'


def _clean_int(val) -> str:
    """조직 레벨(team_layer) 값을 정수 문자열로 정규화. 엑셀이 숫자로 읽어
    1.0 처럼 실수형으로 들어와도 '1'로 맞춘다. 비어 있으면 빈 문자열."""
    if is_blank(val):
        return ''
    s = str(val).strip()
    try:
        return str(int(float(s)))
    except (ValueError, OverflowError):
        return s

# ── 컬럼명 매핑(엑셀 헤더명 → 출력 컬럼명) — 순서 무관, 이름으로 찾아 변환 ──────
_COL_MAP = {
    '과제파트명': 'project_name',
    '과제명통일': 'end_name',
    '조직 레벨': 'team_layer',
    '사번': 'researcher_id',
    '성명': 'name',
    '직책': 'assignment_name',
    '코드3': 'code3',
}
# ─────────────────────────────────────────────────────────────────────────────


def process() -> bool:
    raw_path = os.path.join(RAW_DIR, SOURCE_FILE)
    if not os.path.exists(raw_path):
        print(f'[SKIP] {SOURCE_FILE} 파일 없음')
        return False

    df = read_xlsx(raw_path, header_row=1)
    df.columns = [str(c).strip() for c in df.columns]

    missing = [col for col in _COL_MAP if col not in df.columns]
    if missing:
        print(
            f'[ERROR] 필수 컬럼 없음: {missing}\n'
            f'  process_team_refer.py 상단의 _COL_MAP을 실제 헤더에 맞게 수정하세요.\n'
            f'  현재 파일 헤더: {list(df.columns)}'
        )
        return False

    result = pd.DataFrame({
        out_col: df[src_col].apply(_clean)
        for src_col, out_col in _COL_MAP.items()
    })
    result['researcher_id'] = result['researcher_id'].apply(norm_id)
    result['team_layer'] = df['조직 레벨'].apply(_clean_int)  # '1.0' 같은 실수형 표기 정리

    # 조직 레벨(team_layer)이 없는 행은 조직도에 나타나지 않으므로 제외한다.
    result = result[result['team_layer'] != ''].reset_index(drop=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'team_refer.csv')
    result.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)

    print(f'[OK]   team_refer.csv 저장 ({len(result)}행)')
    return True


if __name__ == '__main__':
    process()
