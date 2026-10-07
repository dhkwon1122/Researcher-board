"""
"석세션 플랜" 편집(pages/org_comparison.py) 전용 저장소.

사용자 요청(2026-10-07): 지금까지 succession.csv를 입력할 방법이 없었다
("샘플 생성기로만 만들어지거나, data/raw에 succession_raw.xlsx/csv를 직접
갖다 놓아야 하는" 원천 raw-passthrough 뿐 — 전용 process_succession.py가
없다, pipeline/sources.py 참고). 조직별로 연구원을 리스트업해 우선순위
(Ready Now/Ready Later × 1/2순위)와 코멘트를 입력하는 화면을 추가하고,
편집 권한은 조회 권한과 동일하게 임원조직 담당자(services.auth.
can_view_succession_plan())로 제한한다(사용자 확정 — 조회/편집 권한을
분리하지 않음).

── 핵심 설계: 조직은 "연구원의 현재 소속"으로만 정해진다 ──────────────────────
pages/org_comparison.py의 조회 화면은 succession.csv에 저장된 org_code를
전혀 보지 않고, 항상 그 연구원의 researchers.csv 현재 department로 다시
조인해서 부서 섹션을 나눈다(org_code는 자연키 구성 요소일 뿐 화면 표시에는
쓰이지 않는 사실상 사문화된 필드). 그래서 편집 화면에서 "조직"을 자유
입력란으로 두면 실제로 어느 섹션에 카드가 뜨는지와 전혀 무관한, 혼란만
주는 필드가 된다 — 이 저장소는 조직을 사용자가 직접 입력하지 않고 "부서
선택 → 그 부서 소속 연구원 중에서 고르기" 방식으로 처리하고, org_code는
저장 시점에 그 연구원의 현재 org_code를 그대로 채워 자연키만 만족시킨다.

── 저장 단위: 부서 × 연도 × 4슬롯 ───────────────────────────────────────────
조회 화면(_dept_section())이 실제로 카드로 그리는 조합은 정확히 4개
(Ready Now 1·2순위, Ready Later 1·2순위)뿐이다 — 이 4슬롯 밖의 조합을
succession.csv에 넣어도 조용히 화면에 안 보이므로, 편집도 이 4슬롯
단위로만 받는다. 저장은 "그 부서 소속 연구원 중 해당 연도의 4슬롯에
해당하는 기존 행을 지우고, 이번에 채운 슬롯만 다시 넣는" 범위로 한정한
delete+insert다(다른 부서/다른 연도의 데이터는 건드리지 않음).

DB 반영은 team_refer_store.py 같은 전용 SQLAlchemy 테이블을 새로 만드는
대신, CSV를 먼저 정상적으로 저장한 뒤 pipeline.load_to_db.load(tables=
['succession'])로 테이블 전체를 그 CSV 기준으로 다시 동기화한다(이미
"팀/리더 참조" 탭의 "DB 반영" 버튼이 쓰는 것과 동일한 범용 함수 재사용 —
석세션 데이터는 양이 작아 전체 재동기화 비용이 무시할 만하다). DATABASE_URL
미설정/실패 시에도 CSV 저장은 항상 먼저 끝나므로 화면 동작에는 영향 없다.
"""
from __future__ import annotations

import os
import sys

import pandas as pd

from services.data_store import filter_current, read_processed

_PIPELINE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'pipeline')
sys.path.insert(0, os.path.abspath(_PIPELINE_DIR))

from paths import OUT_DIR  # noqa: E402

# pages/org_comparison.py의 RANK_META/SLOTS와 정확히 같은 조합이어야 한다 —
# 조회 화면이 그리는 카드 슬롯과 편집 화면이 받는 입력 슬롯이 어긋나면,
# 편집에서 저장한 값이 화면에 안 보이는 혼란이 생긴다.
SLOTS: list[tuple[str, int]] = [
    ('Ready Now', 1),
    ('Ready Now', 2),
    ('Ready Later', 1),
    ('Ready Later', 2),
]

_COLUMNS = ['researcher_id', 'org_code', 'rank_type', 'rank_order', 'nominated_year', 'comment']

_SUCCESSION_PATH = os.path.join(OUT_DIR, 'succession.csv')


def _researchers_df(current_only: bool = True) -> pd.DataFrame:
    df = read_processed('researchers', dtype=str)
    return filter_current(df, current_only=current_only)


def list_departments() -> list[str]:
    """현재 소속자 기준 department 고유값(가나다순) — 편집 화면의 "부서"
    드롭다운. 조회 화면(_dept_section)이 쓰는 것과 동일한 기준(현재
    department)이라 편집에서 고른 부서가 곧 그 카드가 뜰 섹션이다."""
    res = _researchers_df()
    if res.empty or 'department' not in res.columns:
        return []
    names = sorted({
        str(d).strip() for d in res['department'].tolist()
        if str(d).strip() and str(d).strip().lower() != 'nan'
    })
    return names


def department_researcher_options(department: str) -> list[dict]:
    """그 부서 소속 현재 연구원 선택 옵션 — "성명 (사번)" 라벨, 이름
    가나다순."""
    res = _researchers_df()
    if res.empty or not department:
        return []
    dept_rows = res[res['department'].astype(str).str.strip() == str(department).strip()]
    dept_rows = dept_rows.sort_values('name')
    return [
        {'label': f"{row.get('name', '-')} ({row['researcher_id']})", 'value': row['researcher_id']}
        for _, row in dept_rows.iterrows()
    ]


def _org_code_for(res: pd.DataFrame, researcher_id: str) -> str:
    if res.empty or not researcher_id:
        return ''
    match = res[res['researcher_id'] == str(researcher_id)]
    if match.empty:
        return ''
    return str(match.iloc[0].get('org_code', '') or '')


def _read_succession() -> pd.DataFrame:
    df = read_processed('succession', dtype=str)
    if df.empty:
        return pd.DataFrame(columns=_COLUMNS)
    for col in _COLUMNS:
        if col not in df.columns:
            df[col] = ''
    return df.fillna('')


def load_slots(department: str, year: str) -> dict:
    """그 부서(현재 소속 기준) × 연도의 4슬롯 현재값 —
    {(rank_type, rank_order): {'researcher_id': ..., 'comment': ...}}.
    슬롯에 데이터가 없으면 키 자체가 없다(호출부가 .get()으로 빈 값 처리)."""
    res = _researchers_df()
    if res.empty or not department or not str(year).strip():
        return {}
    dept_ids = set(
        res.loc[res['department'].astype(str).str.strip() == str(department).strip(), 'researcher_id']
    )
    if not dept_ids:
        return {}

    suc = _read_succession()
    if suc.empty:
        return {}
    suc = suc[
        (suc['researcher_id'].isin(dept_ids))
        & (suc['nominated_year'].astype(str).str.strip() == str(year).strip())
    ]

    result = {}
    for rank_type, rank_order in SLOTS:
        match = suc[
            (suc['rank_type'].astype(str).str.strip().str.lower() == rank_type.lower())
            & (pd.to_numeric(suc['rank_order'], errors='coerce') == rank_order)
        ]
        if match.empty:
            continue
        row = match.iloc[0]
        result[(rank_type, rank_order)] = {
            'researcher_id': str(row['researcher_id']),
            'comment': str(row.get('comment', '') or ''),
        }
    return result


def _db_sync() -> bool:
    from services.db import get_engine
    if get_engine() is None:
        return False
    try:
        from load_to_db import load as _load_to_db
        _load_to_db(tables=['succession'])
        return True
    except Exception as exc:
        print(f'[succession_store] DB 반영 실패(CSV에는 반영됨): {exc}')
        return False


def save_slots(department: str, year: str, assignments: dict) -> dict:
    """assignments: {(rank_type, rank_order): {'researcher_id': rid_or_empty,
    'comment': text}}. 그 부서(현재 소속 기준) × 연도 × 4슬롯 범위만 지우고
    이번에 채운 슬롯만 다시 넣는다 — 다른 부서/다른 연도 데이터는 그대로
    둔다. 반환: {'saved_rows': int, 'cleared_rows': int, 'db_ok': bool}."""
    department = str(department or '').strip()
    year = str(year or '').strip()
    if not department or not year:
        raise ValueError('부서와 연도를 모두 선택해야 합니다.')

    res = _researchers_df()
    dept_ids = set(
        res.loc[res['department'].astype(str).str.strip() == department, 'researcher_id']
    ) if not res.empty else set()

    suc = _read_succession()
    if dept_ids:
        in_scope = (
            suc['researcher_id'].isin(dept_ids)
            & (suc['nominated_year'].astype(str).str.strip() == year)
            & suc.apply(
                lambda r: any(
                    str(r['rank_type']).strip().lower() == rt.lower()
                    and str(r['rank_order']).strip() == str(ro)
                    for rt, ro in SLOTS
                ),
                axis=1,
            )
        )
    else:
        in_scope = pd.Series([False] * len(suc), index=suc.index)

    cleared_rows = int(in_scope.sum())
    kept = suc[~in_scope].copy()

    new_rows = []
    for (rank_type, rank_order), slot in (assignments or {}).items():
        rid = str((slot or {}).get('researcher_id') or '').strip()
        if not rid:
            continue
        new_rows.append({
            'researcher_id': rid,
            'org_code': _org_code_for(res, rid),
            'rank_type': rank_type,
            'rank_order': str(rank_order),
            'nominated_year': year,
            'comment': str((slot or {}).get('comment') or '').strip(),
        })

    result = pd.concat([kept, pd.DataFrame(new_rows, columns=_COLUMNS)], ignore_index=True) \
        if new_rows else kept

    os.makedirs(OUT_DIR, exist_ok=True)
    result = result[_COLUMNS]
    result.to_csv(_SUCCESSION_PATH, index=False, encoding='utf-8-sig')

    db_ok = _db_sync()
    return {'saved_rows': len(new_rows), 'cleared_rows': cleared_rows, 'db_ok': db_ok}
