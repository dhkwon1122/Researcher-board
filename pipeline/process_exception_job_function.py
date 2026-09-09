"""
직무_직군_맵핑_예외자 처리 모듈

원천: source_reader.read_source('exception_job_function')
  → DB exception_job_function_stg 테이블 또는 data/raw_csv/exception_job_function.csv
  (1단계 xlsx_to_raw_csv.py가 data/raw/직무_직군_맵핑_예외자.xlsx를 DRM 제거해
  만든 사본)
출력 파일: data/processed/exception_job_function.csv

읽는 컬럼:
  사원번호, 성명, 직군예외

처리:
  - 헤더를 researcher_id/name/exception_job_category로 변환해 그대로 저장한다.
  - researcher_id가 빈 행은 제외.
  - researcher_id가 중복된 행이 있으면 첫 번째 행만 남기고 나머지는 버린다
    (경고 출력) — 이후 조회가 항상 1:1이 되도록 보장하기 위함.

출력 스키마:
  researcher_id, name, exception_job_category

용도(2026-09-09, 사용자 확정): 연구원 개별 프로필/전문성 MAP이 보여주는
"SAIT 직군" 표시를 mapping_job_function.csv 기반 매칭 결과와 무관하게
강제로 덮어쓴다 — DS 직군은 그대로 매칭 결과를 유지하고, SAIT 직군만 이
파일의 exception_job_category 값으로 교체한다(services/job_category.py가
이 override를 적용하는 유일한 창구). 매칭 성공/실패와 무관하게 항상
적용된다 — 원래 job_function이 mapping_job_function.csv에 없어 DS가
"-"인 사람도, 이 파일에 등록돼 있으면 SAIT는 예외값으로 표시된다.

이 파일은 team_refer.csv와 달리 시점(연/월) 이력을 쌓지 않는다(2026-09-09,
사용자 확정 — "researcher_id 기준 현재값만 관리") — mapping_job_function.csv
와 동일하게 매 처리/저장마다 파일 전체를 새로 만든다.

── 웹 업로드/그리드 CRUD(관리자 "직군 예외자" 탭) ─────────────────────────────
process()는 다른 process_*.py처럼 raw_dir 매개변수를 받는다 —
services.web_pipeline_runner가 data/web_updates/exception_job_function/로
넘겨 업로드된 파일을 읽게 한다(기본값은 기존과 동일한 data/raw). 관리자
화면 그리드 CRUD(services/exception_job_function_store.py)는 이 파일의
build_rows_from_records()/find_duplicate_researcher_ids()를 그대로
재사용해 두 경로(엑셀 업로드 vs 그리드 직접 편집)가 같은 컬럼 매핑/정제
기준을 공유하게 한다(pipeline/process_team_refer.py와 동일한 설계).

컬럼명이 다를 경우 파일 상단의 _COL_MAP을 실제 헤더에 맞게 수정하세요.
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR, OUT_DIR  # noqa: E402
from excel_reader import clean_str as _clean, norm_id, read_xlsx  # noqa: E402
from source_reader import read_source  # noqa: E402

SOURCE_FILE = '직무_직군_맵핑_예외자.xlsx'

# ── 컬럼명 매핑(엑셀 헤더명 → 출력 컬럼명) — 순서 무관, 이름으로 찾아 변환 ──────
_COL_MAP = {
    '사원번호': 'researcher_id',
    '성명': 'name',
    '직군예외': 'exception_job_category',
}
# ─────────────────────────────────────────────────────────────────────────────


def build_rows_from_records(records: list) -> pd.DataFrame:
    """레코드 리스트(엑셀 헤더명을 키로 쓰는 dict — xlsx 업로드의
    df.to_dict('records')든, 관리자 화면 그리드의 행이든 동일한 형태)를
    _COL_MAP 기준으로 컬럼 매핑 + 정제해 표준 스키마(영문 컬럼명)
    DataFrame으로 변환한다. researcher_id가 없는 행은 매칭 키가 없어
    아무 의미가 없으므로 제외한다."""
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
    (process_team_refer.find_duplicate_dep_ids()와 동일한 발상 — 중복이
    있으면 첫 번째 행만 채택되고 나머지는 조용히 사라지므로, 저장 전에
    미리 알려주기 위한 진단 함수). process()(CLI/웹 업로드)와
    services.exception_job_function_store.save_snapshot()(웹 저장) 양쪽이
    공유한다.

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
        df = read_source('exception_job_function')
        if df is None:
            print('[SKIP] exception_job_function 원천 데이터 없음 '
                  '(DB exception_job_function_stg 또는 data/raw_csv/exception_job_function.csv)')
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
            f'  process_exception_job_function.py 상단의 _COL_MAP을 실제 헤더에 맞게 수정하세요.\n'
            f'  현재 파일 헤더: {list(df.columns)}'
        )
        return False

    result = build_rows_from_records(df.to_dict('records'))
    _print_duplicate_warning(find_duplicate_researcher_ids(result))
    result = result.drop_duplicates(subset=['researcher_id'], keep='first').reset_index(drop=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'exception_job_function.csv')
    result.to_csv(out_path, index=False, encoding='utf-8-sig')

    print(f'[OK]   exception_job_function.csv 저장 ({len(result)}건)')
    return True


if __name__ == '__main__':
    process()
