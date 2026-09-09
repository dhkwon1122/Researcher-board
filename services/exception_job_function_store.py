"""
"직군 예외자" 관리자 화면(pages/admin.py)의 웹 CRUD 저장소.

services/team_refer_store.py와 같은 목적(그리드 CRUD가 CSV/DB 양쪽에
직접 반영)이지만, exception_job_function.csv는 team_refer.csv와 달리
시점(연/월) 이력을 쌓지 않는 "현재값만" 참조 테이블이다(2026-09-09,
사용자 확정 — "researcher_id 기준 현재값만 관리"). 그래서 구조가 훨씬
단순하다:
  - 자연키 upsert/톰스톤이 없다 — 저장할 때마다 그리드의 현재 내용
    전체로 CSV/DB를 통째로 교체한다(그리드에서 지운 행은 다음 저장
    결과에 그냥 없으면 그만).
  - "입력 날짜"(valid_date) 개념이 없다.

DB 쓰기는 services/team_refer_store.py와 같은 패턴(DATABASE_URL
미설정/실패 시 모든 함수가 조용히 실패를 나타내는 값을 반환)을 따른다 —
DB가 없어도 CSV 쓰기만으로 정상 동작해야 한다(save_snapshot()의 반환값
db_ok로 호출부가 구분해서 안내).
"""
from __future__ import annotations

import os
import sys

import pandas as pd
from sqlalchemy import Column, MetaData, String, Table

from services.db import get_engine

_PIPELINE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'pipeline')
sys.path.insert(0, os.path.abspath(_PIPELINE_DIR))

import process_exception_job_function as pejf  # noqa: E402
from paths import OUT_DIR  # noqa: E402

# 엑셀 헤더명(관리자 화면 그리드가 쓰는 컬럼 키) ↔ 표준 영문 컬럼명(CSV/DB가
# 쓰는 컬럼 키) 매핑 — process_exception_job_function._COL_MAP을 그대로
# 재사용해 두 경로가 어긋나지 않게 한다.
KOREAN_COLUMNS = list(pejf._COL_MAP.keys())
_REVERSE_COL_MAP = {v: k for k, v in pejf._COL_MAP.items()}
_ALL_VALUE_COLUMNS = list(pejf._COL_MAP.values())  # researcher_id 포함

metadata = MetaData()

# 시점 이력이 없어 자연키 upsert가 필요 없다 — 저장 시 전체를 delete+insert로
# 교체하므로 PK 제약도 두지 않는다(load_to_db.py의 배치 적재가 매번 테이블을
# 그대로 재생성하기도 해, PK를 걸어도 그 배치 경로에서는 유지되지 않는다 —
# team_refer와 동일한 기존 제약, 여기서는 전체 교체 방식이라 애초에 문제되지
# 않는다).
exception_job_function = Table(
    'exception_job_function',
    metadata,
    *[Column(c, String) for c in _ALL_VALUE_COLUMNS],
)

_table_ready = False


def available() -> bool:
    """DB 엔진이 있고 exception_job_function 테이블이 준비돼 있으면 True."""
    global _table_ready
    engine = get_engine()
    if engine is None:
        return False
    if not _table_ready:
        try:
            metadata.create_all(engine, tables=[exception_job_function])
            _table_ready = True
        except Exception as exc:
            print(f'[exception_job_function_store] 테이블 준비 실패: {exc}')
            return False
    return True


def _replace_db(result: pd.DataFrame) -> bool:
    """DB 테이블 전체를 이번 저장 내용으로 교체한다 — 자연키 upsert가 아니라
    "현재값만" 성격이라(삭제된 행이 DB에만 남아있는 걸 막으려면) 매번 전체를
    비우고 다시 채운다."""
    if not available():
        return False
    try:
        with get_engine().begin() as conn:
            conn.execute(exception_job_function.delete())
            if not result.empty:
                rows = result[_ALL_VALUE_COLUMNS].to_dict('records')
                conn.execute(exception_job_function.insert(), rows)
        return True
    except Exception as exc:
        print(f'[exception_job_function_store] DB 반영 실패(CSV에는 반영됨): {exc}')
        return False


def list_editable_rows() -> list[dict]:
    """관리자 화면 그리드에 로드할 "현재" 예외자 목록 — 엑셀 원본 헤더명을
    키로 쓴다. services.data_store.read_processed()로 읽어(DB 우선, 없으면
    CSV) 사번(researcher_id) 오름차순으로 정렬한다."""
    from services.data_store import read_processed

    df = read_processed('exception_job_function')
    if df.empty:
        return []
    df = df.sort_values('researcher_id')
    return [
        {kor: str(row.get(eng, '') or '') for eng, kor in _REVERSE_COL_MAP.items()}
        for _, row in df.iterrows()
    ]


def save_snapshot(records: list[dict]) -> dict:
    """저장 버튼 콜백 진입점 — 그리드의 현재 행 전체를 그대로
    exception_job_function.csv/DB로 교체한다. records: 엑셀 헤더명을 키로
    쓰는 행 목록(사번 없는 행은 이미 걸러진 상태로 넘어온다고 가정 —
    pages/admin.py가 저장 전에 걸러 안내)."""
    result = pejf.build_rows_from_records(records)
    duplicate_ids = pejf.find_duplicate_researcher_ids(result)
    result = result.drop_duplicates(subset=['researcher_id'], keep='first').reset_index(drop=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'exception_job_function.csv')
    result.to_csv(out_path, index=False, encoding='utf-8-sig')

    db_ok = _replace_db(result)
    return {
        'saved_rows': len(result), 'db_ok': db_ok,
        'duplicate_researcher_ids': duplicate_ids,
    }


def _build_workbook(records: list[dict]):
    """records(엑셀 원본 헤더명 키의 행 목록)를 KOREAN_COLUMNS 순서의
    openpyxl 워크북으로 조립한다 — current_snapshot_workbook_bytes()가
    사용."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '직군_예외자'
    ws.append(KOREAN_COLUMNS)
    for r in records:
        ws.append([r.get(c, '') for c in KOREAN_COLUMNS])
    return wb


def current_snapshot_workbook_bytes() -> bytes:
    """관리자 화면 "엑셀 다운로드" 버튼용 — 그리드에서 편집 중인(아직
    저장하지 않은) 내용이 아니라, 저장소에 이미 반영된 최신 값
    (list_editable_rows())을 그대로 내려받는다(team_refer_store.py와
    동일한 원칙)."""
    import io

    buf = io.BytesIO()
    _build_workbook(list_editable_rows()).save(buf)
    return buf.getvalue()
