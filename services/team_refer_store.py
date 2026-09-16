"""
"팀/리더 참조" 관리자 화면(pages/admin.py)의 웹 CRUD 저장소.

team_refer는 이미 두 갈래로 존재한다 — data/processed/team_refer.csv(CSV,
pipeline.merge_utils가 (dep_id, valid_year, valid_month, valid_day) 자연키로
날짜 기반 누적)와, DATABASE_URL이 설정된 환경에서는 DB의 team_refer 테이블
(services.data_store.read_processed()가 DB를 우선 읽는다). 지금까지 이
테이블은 배치 파이프라인(pipeline/load_to_db.py)만 채웠는데, 이 모듈부터는
실행 중인 웹 앱이 저장 시점에 CSV와 DB 양쪽에 직접 반영한다 — DB에도 쓰는
이유: pipeline.rd_specialist_markdown.read_team_refer()가 DB를 우선 읽으므로,
CSV에만 쓰면 DATABASE_URL이 설정된 운영 환경에서는 화면이 계속 예전 DB
값을 보여준다.

DB 쓰기는 services/user_store.py와 같은 패턴(SQLAlchemy Core, DATABASE_URL
미설정/실패 시 모든 함수가 조용히 실패를 나타내는 값을 반환)을 따른다 —
DB가 없어도 CSV 쓰기만으로 정상 동작해야 한다(save_snapshot()의 반환값
db_ok로 호출부가 구분해서 안내).

── 3단계 부서 체계 + 그리드 UX 변경(2026-09-11) ────────────────────────────────
team_refer.csv가 부서/과제·파트 2단 구분에서 1/2/3단계 부서명 3단 구조로
바뀌면서(pipeline/process_team_refer.py, pipeline/team_hierarchy.py 참고),
dep_id/upper_dep_id/team_layer가 더 이상 사람이 직접 입력하는 엑셀 컬럼이
아니라 1/2/3단계 부서명 "전체 경로" 텍스트에서 매번 결정적으로 자동 계산된다.
그 결과 이 그리드의 UX도 함께 단순해졌다:
  - 그리드에 더 이상 부서ID/상위부서ID/조직 레벨 컬럼이 없다(KOREAN_COLUMNS는
    이제 process_team_refer._COL_MAP의 9개 인텔이크 컬럼 그대로 — 1/2/3단계
    부서명을 각 행에 "전체 경로"로 채우면 저장 시점에 자동으로 조직 단위별
    1행(own-level-only)으로 재구성된다).
  - team_refer.csv 자체는 own-level-only 저장 스키마이므로(그 조직 자신의
    레벨 이름만 채움), 그리드에 불러올 때는 pipeline.team_hierarchy.
    backfill_full_path()로 상위부서 이름까지 전체 경로로 채워서 보여준다
    (derive_hierarchy()의 역방향 — 왕복해도 멱등적).
  - 예전엔 admin.py가 "그리드에서 사라진 부서ID"를 직접 비교해 삭제(톰스톤)
    대상을 판정했는데(부서ID가 사람이 타이핑하는 값이라 diff가 안정적이었음),
    이제 dep_id는 텍스트에서 매번 새로 계산되는 값이라 그 방식이 성립하지
    않는다 — 대신 process_team_refer.tombstone_missing_dep_ids()를 그대로
    재사용해, "이번 저장 내용에 없는, 현재 살아있는 dep_id"를 저장 시점마다
    자동으로 찾아 마감 처리한다(그리드가 매번 "현재 조직 전체"를 불러와 그
    전체를 다시 저장하는 구조이므로, process()의 xlsx 일괄 업로드와 동일한
    원리가 그대로 적용됨). save_snapshot()의 deleted_dep_ids 인자가 이래서
    사라졌다 — 호출부(pages/admin.py)가 더 이상 삭제 대상을 직접 계산해
    넘길 필요가 없다.
"""
from __future__ import annotations

import os
import sys
from datetime import date

import pandas as pd
from sqlalchemy import Column, MetaData, String, Table

from services.db import get_engine

_PIPELINE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'pipeline')
sys.path.insert(0, os.path.abspath(_PIPELINE_DIR))

import merge_utils  # noqa: E402
import process_team_refer as ptr  # noqa: E402
import rd_specialist_markdown as mmd  # noqa: E402
import team_hierarchy as th  # noqa: E402
from paths import OUT_DIR  # noqa: E402

# 엑셀 헤더명(관리자 화면 그리드가 쓰는 컬럼 키) ↔ 표준 영문 컬럼명(CSV/DB가
# 쓰는 컬럼 키) 매핑 — process_team_refer._COL_MAP을 그대로 재사용해 두
# 경로가 어긋나지 않게 한다(9개 인텔이크 컬럼 — dep_id/upper_dep_id/
# team_layer는 자동 계산이라 여기 없음).
KOREAN_COLUMNS = list(ptr._COL_MAP.keys())
_REVERSE_COL_MAP = {v: k for k, v in ptr._COL_MAP.items()}
# team_refer.csv/DB 저장 스키마 전체(team_hierarchy.FIELDS — dep_id/
# upper_dep_id/team_layer 등 자동 계산 필드 포함) + deleted.
_ALL_VALUE_COLUMNS = list(th.FIELDS) + ['deleted']  # dep_id 포함

metadata = MetaData()

# (dep_id, valid_year, valid_month, valid_day) 복합 기본키 — CSV의 자연키와
# 동일(pipeline/merge_utils.py의 TABLE_KEYS['team_refer'] 참고). 그 외
# 컬럼은 전부 문자열로 저장해 services.data_store._read_from_db()의
# dtype=str 읽기(=CSV 폴백 경로)와 형식을 맞춘다.
team_refer = Table(
    'team_refer',
    metadata,
    Column('dep_id', String, primary_key=True),
    Column('valid_year', String, primary_key=True),
    Column('valid_month', String, primary_key=True),
    Column('valid_day', String, primary_key=True),
    *[Column(c, String) for c in _ALL_VALUE_COLUMNS if c != 'dep_id'],
)

_table_ready = False


def available() -> bool:
    """DB 엔진이 있고 team_refer 테이블이 준비돼 있으면 True."""
    global _table_ready
    engine = get_engine()
    if engine is None:
        return False
    if not _table_ready:
        try:
            metadata.create_all(engine, tables=[team_refer])
            _table_ready = True
        except Exception as exc:
            print(f'[team_refer_store] team_refer 테이블 준비 실패: {exc}')
            return False
    return True


def _upsert_rows_to_db(rows_df: pd.DataFrame) -> bool:
    """rows_df(자연키 + 값 컬럼 전체)를 DB team_refer 테이블에 upsert.
    PostgreSQL 전용 ON CONFLICT 구문 사용(services/db.py가 PostgreSQL만
    지원 — .env.example 참고)."""
    if rows_df.empty:
        return True
    if not available():
        return False
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    key_cols = ['dep_id', 'valid_year', 'valid_month', 'valid_day']
    try:
        with get_engine().begin() as conn:
            for _, row in rows_df.iterrows():
                values = {c: str(row.get(c) or '') for c in key_cols + _ALL_VALUE_COLUMNS if c != 'dep_id'}
                values['dep_id'] = str(row.get('dep_id') or '')
                stmt = pg_insert(team_refer).values(**values)
                stmt = stmt.on_conflict_do_update(
                    index_elements=key_cols,
                    set_={c: stmt.excluded[c] for c in _ALL_VALUE_COLUMNS if c != 'dep_id'},
                )
                conn.execute(stmt)
        return True
    except Exception as exc:
        print(f'[team_refer_store] DB 반영 실패(CSV에는 반영됨): {exc}')
        return False


def _flatten_org_tree(tree: list) -> list:
    """build_org_tree()가 만든 계층 트리(각 노드는 원본 행 dict +
    'children' 리스트)를 부모→자식 순서로 평탄화한다(깊이 우선 순회) —
    형제는 build_org_tree() 안에서 이미 조직코드(dep_code) 오름차순으로
    정렬돼 있으므로, 이 평탄화 결과는 "같은 부모 밑 조직끼리는 항상 화면에
    붙어서 보이는" 계층적 그룹 순서가 된다(2026-09-14 도입 — 기존 "전체
    조직코드 오름차순" 한 가지 기준으로만 정렬하면 서로 다른 부모의
    자식들이 전역 조직코드 값에 따라 뒤섞여 보일 수 있었다). 원래는 이
    그룹 순서가 그리드의 행 드래그 재정렬 기능이 성립하기 위한 선행
    조건이었는데, 그 드래그 기능 자체는 2026-09-17에 성능 문제로
    제거됐다 — 이 계층적 정렬은 순수하게 가독성을 위해 그대로 유지한다."""
    flat = []
    for node in tree:
        children = node.get('children') or []
        flat.append({k: v for k, v in node.items() if k != 'children'})
        flat.extend(_flatten_org_tree(children))
    return flat


def list_editable_rows() -> list[dict]:
    """관리자 화면 그리드에 로드할 "현재" 팀참조 행 목록 — 엑셀 원본
    헤더명(KOREAN_COLUMNS)을 키로 쓴다(사용자 요청: 컬럼명은 xlsx 그대로).
    계층적으로 정렬한다(2026-09-14, 사용자 확정 — 기존 "전체 조직코드
    오름차순" 단일 기준에서 변경): build_org_tree()로 부모-자식 트리를
    만든 뒤 깊이 우선으로 평탄화 — 최상위 조직부터, 그 바로 아래 자식들이
    바로 이어지고(조직코드 오름차순), 그 다음 형제 조직으로 넘어가는
    순서 — 같은 부모 밑 조직끼리 항상 화면에서 붙어 보여 가독성이 좋다.
    pipeline.rd_specialist_markdown.read_team_refer()로 dep_id별 최신·
    비삭제 행(own-level-only 저장 스키마)만 가져온 뒤,
    team_hierarchy.backfill_full_path()로 1/2/3단계 부서명을 전체 경로로
    채워 그리드에 보여준다 — 그래야 그대로 다시 저장해도(수정 없이
    저장만 해도) build_rows_from_records()가 같은 dep_id를 재계산해
    내용이 유지된다."""
    rows = mmd.read_team_refer(OUT_DIR)
    rows = th.backfill_full_path(rows)
    tree = mmd.build_org_tree(rows)
    rows = _flatten_org_tree(tree)
    return [
        {kor: r.get(eng, '') for eng, kor in _REVERSE_COL_MAP.items()}
        for r in rows
    ]


def _renumber_dep_codes(records: list[dict]) -> list[dict]:
    """조직코드(『조직코드』, dep_code)를 저장 직전에 매번 새로 매긴다.

    build_org_tree()(pipeline/rd_specialist_markdown.py)의 형제 정렬이
    문자열 비교라, 패딩 없는 '2'/'10'을 그대로 두면 '10'이 '2'보다 문자상
    앞서 실제 원하는 숫자 순서와 어긋난다(2026-09-16, 사용자 보고로 확인
    — 화면에서 행을 옮겨 저장해도 다시 열면 순서가 어긋나 보이는 원인).
    4자리로 0-패딩하면 문자열 비교와 숫자 비교 결과가 항상 같아진다
    (team_hierarchy.py가 새 조직에 기본값을 채울 때 쓰는 `f'{i:04d}'`와
    동일한 규칙으로 통일).

    비공식소속부서명이 빈 행(관리자 화면 그리드에는 안 보이는, 리프에
    실제 배정이 없는 조직 — pages/admin.py의 _split_hidden_rows() 참고)은
    화면에서 순서를 확인/조정할 방법이 없으므로, 보이는 조직(0001부터
    화면 순서 그대로)과 절대 겹치지 않도록 9999부터 거꾸로 매겨 항상
    형제들 중 맨 뒤로 밀려나게 한다(2026-09-16, 사용자 확정).

    호출부(save_snapshot())가 저장할 때마다 무조건 이 함수를 거치므로,
    예전에 패딩 없이 저장된 조직코드도 다음 저장 한 번으로 자동 정리된다
    — 별도 마이그레이션이 필요 없다."""
    visible_i, hidden_i = 0, 9999
    out = []
    for r in records:
        r = dict(r)
        if str(r.get('비공식소속부서명') or '').strip():
            visible_i += 1
            r['조직코드'] = f'{visible_i:04d}'
        else:
            r['조직코드'] = f'{hidden_i:04d}'
            hidden_i -= 1
        out.append(r)
    return out


def save_snapshot(records: list[dict], valid_date: date) -> dict:
    """저장 버튼 콜백 진입점.

    records: 그리드의 현재 행(엑셀 헤더명 키, "전체 경로 포함" 인텔이크
    형태 — list_editable_rows()가 채워준 상위 부서명을 그대로 유지한 채
    일부만 고쳐도 되고, 새 행을 추가할 때도 1/2/3단계 이름을 자기 레벨까지
    채우면 된다). _renumber_dep_codes()로 조직코드를 먼저 정리한 뒤 처리한다.

    dep_id/upper_dep_id/team_layer는 build_rows_from_records()가 1/2/3단계
    부서명 경로에서 자동 계산하므로, "이번 저장에 없는 옛 dep_id"를 사람이
    직접 표시할 방법이 이제 없다 — 대신 ptr.tombstone_missing_dep_ids()로
    "이번 저장 내용에 없는, 현재 살아있는 dep_id"를 자동으로 찾아
    deleted='Y' 톰스톤 행을 추가한다(그리드는 매번 "현재 조직 전체"를
    불러와 그 전체를 다시 저장하는 구조이므로 process()의 xlsx 일괄
    업로드와 동일한 원리가 그대로 적용된다).

    CSV(data/processed/team_refer.csv)에는 항상 반영하고, DB가 설정돼
    있으면 DB에도 반영한다(실패해도 CSV 반영은 이미 끝난 상태이므로 함수
    전체가 실패하지 않는다 — db_ok로 호출부가 구분해서 안내).
    """
    records = _renumber_dep_codes(records)
    result = ptr.build_rows_from_records(records)
    duplicate_dep_ids = ptr.find_duplicate_dep_ids(result)
    # "(SAIT)"/"(기술원)" 태그 제거로 서로 다른 원본이 하나로 합쳐진 경우를
    # 확인용으로 함께 반환한다(2026-09-15 확정 — 값 손실이 있는지 확인 필요).
    tag_merges = ptr.find_tag_merges(records)

    result = ptr.stamp_valid_date(result, valid_date)
    result['deleted'] = 'N'

    result = ptr.tombstone_missing_dep_ids(result, valid_date)

    out_path = os.path.join(OUT_DIR, 'team_refer.csv')
    merged = merge_utils.write_merged(out_path, result, merge_utils.TABLE_KEYS['team_refer'])

    db_ok = _upsert_rows_to_db(result)
    return {
        'saved_rows': len(result), 'total_rows': len(merged), 'db_ok': db_ok,
        'tag_merges': tag_merges,
        'duplicate_dep_ids': duplicate_dep_ids,
    }


def _build_workbook(records: list[dict]):
    """records(엑셀 원본 헤더명 키의 행 목록)를 KOREAN_COLUMNS 순서의 openpyxl
    워크북으로 조립한다 — export_snapshot_xlsx()(서버 저장용)와
    current_snapshot_workbook_bytes()(관리자 화면 다운로드 버튼용)가 공유."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '팀_리더_참조'
    ws.append(KOREAN_COLUMNS)
    for r in records:
        ws.append([r.get(c, '') for c in KOREAN_COLUMNS])
    return wb


def export_snapshot_xlsx(records: list[dict], valid_date: date) -> str:
    """data/processed/team_leader_refer/팀_리더_참조_입력날짜(YYMMDD).xlsx로
    이번 저장 시점의 그리드 스냅샷을 남긴다(엑셀 원본 헤더명 그대로).
    파일명이 날짜(YYMMDD)까지만이라 같은 날 다시 저장하면 덮어써 마지막
    저장이 그날의 유효값이 된다(사용자 확정)."""
    folder = os.path.join(OUT_DIR, 'team_leader_refer')
    os.makedirs(folder, exist_ok=True)
    fname = f"팀_리더_참조_입력날짜({valid_date.strftime('%y%m%d')}).xlsx"
    path = os.path.join(folder, fname)
    _build_workbook(records).save(path)
    return path


def current_snapshot_workbook_bytes() -> bytes:
    """관리자 화면 "엑셀 다운로드" 버튼용 — 그리드에서 편집 중인(아직
    저장하지 않은) 내용이 아니라, 저장소에 이미 반영된 최신 값
    (list_editable_rows(), dep_id별 최신·비삭제 행)을 그대로 내려받는다
    (사용자 확정 2026-09-01). export_snapshot_xlsx()와 달리 서버에 파일을
    남기지 않고 바로 바이트로 반환한다."""
    import io

    buf = io.BytesIO()
    _build_workbook(list_editable_rows()).save(buf)
    return buf.getvalue()
