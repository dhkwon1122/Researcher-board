"""
평가표기 예외자 처리 모듈

원천: source_reader.read_source('evaluation_exception')
  → DB evaluation_exception_stg 테이블 또는 data/raw_csv/evaluation_exception.csv
  (1단계 xlsx_to_raw_csv.py가 data/raw/평가표기예외자.xlsx를 DRM 제거해
  만든 사본)
출력 파일: data/processed/evaluation_exception.csv

읽는 컬럼(헤더는 1번째 행):
  사원번호, 이름

처리:
  - 헤더를 researcher_id/name으로 변환해 그대로 저장한다.
  - researcher_id가 빈 행은 제외.
  - researcher_id가 중복된 행이 있으면 첫 번째 행만 남기고 나머지는 버린다
    (경고 출력) — 이후 조회가 항상 1:1(멤버십 판정)이 되도록 보장하기 위함.

출력 스키마:
  researcher_id, name

용도(2026-09-09, 사용자 확정): services/evaluations.py의 평가 셀 공통
서식 로직에서, 연봉등급이 없는 사람의 표기를 결정하는 데 쓰인다 — 이
파일에 researcher_id가 등록돼 있으면(예외자) 상/하반기업적 두 자리 대신
하반기업적 하나만 표시한다(등록 안 돼 있으면 기존대로 상/하반기업적
두 자리 모두 표시).

이 파일은 team_refer.csv와 달리 시점(연/월) 이력을 쌓지 않는다(2026-09-09,
사용자 확정 — "researcher_id 기준 현재값만 관리") — mapping_job_function.csv
와 동일하게 매 처리/저장마다 파일 전체를 새로 만든다.

관리 방식(2026-09-09, 사용자 확정): 관리자 "데이터 업데이트" 탭의 엑셀
업로드만 지원한다 — exception_job_function/team_refer와 달리 별도의
그리드 CRUD 관리 탭은 두지 않는다(services.web_pipeline_runner의
MANIFEST에 hidden_from_table 없이 일반 항목으로 등록).

컬럼명이 다를 경우 파일 상단의 _COL_MAP을 실제 헤더에 맞게 수정하세요.
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR, OUT_DIR  # noqa: E402
from excel_reader import clean_str as _clean, norm_id, read_xlsx  # noqa: E402
from source_reader import read_source  # noqa: E402

SOURCE_FILE = '평가표기예외자.xlsx'

# ── 컬럼명 매핑(엑셀 헤더명 → 출력 컬럼명) — 순서 무관, 이름으로 찾아 변환 ──────
_COL_MAP = {
    '사원번호': 'researcher_id',
    '이름': 'name',
}
# ─────────────────────────────────────────────────────────────────────────────


def build_rows_from_records(records: list) -> pd.DataFrame:
    """레코드 리스트(엑셀 헤더명을 키로 쓰는 dict)를 _COL_MAP 기준으로
    컬럼 매핑 + 정제해 표준 스키마(영문 컬럼명) DataFrame으로 변환한다.
    researcher_id가 없는 행은 매칭 키가 없어 아무 의미가 없으므로 제외한다."""
    df = pd.DataFrame(records)
    for col in _COL_MAP:
        if col not in df.columns:
            df[col] = ''

    result = pd.DataFrame({
        out_col: df[src_col].apply(_clean)
        for src_col, out_col in _COL_MAP.items()
    })
    result['researcher_id'] = result['researcher_id'].apply(norm_id)

    return result[result['researcher_id'] != ''].reset_index(drop=True)


def find_duplicate_researcher_ids(result: pd.DataFrame) -> list:
    """같은 업로드/저장 안에서 사원번호(researcher_id)가 중복된 행을 찾는다
    — 중복이 있으면 첫 번째 행만 채택되고 나머지는 조용히 사라지므로,
    저장 전에 미리 알려주기 위한 진단 함수.

    반환: [{'researcher_id': ..., 'count': N, 'rows': [{...}, ...]}, ...]"""
    if result.empty:
        return []
    dupes = result[result.duplicated('researcher_id', keep=False)]
    if dupes.empty:
        return []
    groups = []
    for rid, grp in dupes.groupby('researcher_id'):
        groups.append({
            'researcher_id': rid,
            'count': len(grp),
            'rows': grp.to_dict('records'),
        })
    return sorted(groups, key=lambda g: g['researcher_id'])


def _print_duplicate_warning(dupes: list) -> None:
    if not dupes:
        return
    print(f'[WARN] 사번(researcher_id) 중복 {len(dupes)}건은 첫 번째 행만 남기고 건너뜀:')
    for g in dupes:
        print(f"  · researcher_id={g['researcher_id']} ({g['count']}행)")


def process(raw_dir: str = RAW_DIR) -> bool:
    if raw_dir == RAW_DIR:
        df = read_source('evaluation_exception')
        if df is None:
            print('[SKIP] evaluation_exception 원천 데이터 없음 '
                  '(DB evaluation_exception_stg 또는 data/raw_csv/evaluation_exception.csv)')
            return False
    else:
        raw_path = os.path.join(raw_dir, SOURCE_FILE)
        if not os.path.exists(raw_path):
            print(f'[SKIP] {SOURCE_FILE} 파일 없음({raw_dir})')
            return False
        df = read_xlsx(raw_path)

    df.columns = [str(c).strip() for c in df.columns]

    missing = [col for col in _COL_MAP if col not in df.columns]
    if missing:
        print(
            f'[ERROR] 필수 컬럼 없음: {missing}\n'
            f'  process_evaluation_exception.py 상단의 _COL_MAP을 실제 헤더에 맞게 수정하세요.\n'
            f'  현재 파일 헤더: {list(df.columns)}'
        )
        return False

    result = build_rows_from_records(df.to_dict('records'))
    _print_duplicate_warning(find_duplicate_researcher_ids(result))
    result = result.drop_duplicates(subset=['researcher_id'], keep='first').reset_index(drop=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'evaluation_exception.csv')
    result.to_csv(out_path, index=False, encoding='utf-8-sig')

    print(f'[OK]   evaluation_exception.csv 저장 ({len(result)}건)')
    return True


if __name__ == '__main__':
    process()
