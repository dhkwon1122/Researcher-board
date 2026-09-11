"""
팀참조시트(조직 계층 구조 + 각 조직 단위 책임자 정보) 처리 모듈

원천 파일: data/raw/팀참조시트.xlsx (헤더: 절대 2행, header_row=1)
출력 파일: data/processed/team_refer.csv

한 행 = 하나의 조직 단위(조직도의 노드 하나)이며, 그 조직 단위 책임자(부서장)의
사번/성명/직책이 함께 표기되어 있다 — 연구원별 1행이 아니라 조직 단위별 1행이다.

── 3단계 부서 체계(2026-09-11 설계 변경) ──────────────────────────────────────
기존에는 team_refer.csv가 부서(dep_name)/과제·파트(pjt_part_name) 2단 구분이었는데,
이제 1/2/3단계 부서명(dep_1st_name/dep_2nd_name/dep_3rd_name)의 3단 구조로
바뀌었다 — 부서-과제/파트 사이에 중간 계층이 하나 더 생긴 것.

인텔이크(입력) 형태는 "전체 경로 포함"이다 — 팀참조시트.xlsx의 각 행이 자기
소속 경로를 자기 레벨까지 전부 채운다(예: 3단계 소속이면 1/2/3단계 이름을
전부 채움). 이걸 pipeline.team_hierarchy.derive_hierarchy()가 조직 단위별
1행(자기 레벨 이름만 채운 저장 스키마)으로 변환하고, dep_id/upper_dep_id/
team_layer를 텍스트 경로에서 결정적으로 계산해 사람이 이 3개 값을 직접
관리할 필요 자체를 없앤다(team_hierarchy.py 모듈 docstring에 설계 배경 상세
기술 — dep_id는 연속성을 이어갈 필요가 없어 매번 새로 계산해도 안전하다는
점이 핵심).

컬럼명 매핑(엑셀 헤더명 → 위치와 무관하게 이름으로 찾아 변환):
  비공식소속부서명 → org_name_wd     researchers.csv의 org_code와 매핑되는 조직 단위 키
  구분             → work_type       "R&D"인 행만 보유 전문성 분석 대상
                                     (process_researcher_expertise.py._filter_eligible_researchers,
                                     비어 있으면 team_hierarchy.derive_hierarchy()가 'R&D'로 기본 채움)
  1단계부서명       → dep_1st_name   (아래 3개는 team_hierarchy.derive_hierarchy()로
  2단계부서명       → dep_2nd_name    조직 단위별 1행으로 재구성된 뒤에는 자기 레벨
  3단계부서명       → dep_3rd_name    이름만 채워짐 — 조상 이름은 upper_dep_id를
                                     따라가면 알 수 있으므로 중복 저장하지 않는다)
  조직코드          → dep_code        조직도 상 같은 부모 아래 형제 노드의 표시 순서 코드.
                                     입력에 없으면 처음 등장한 순서를 기본값으로 채움
                                     (사람이 조정해야 하는 값이라 이미 정해진 값은 그대로 존중).
  사번             → researcher_id   해당 조직 단위 책임자(부서장) 사번
  성명             → name            해당 조직 단위 책임자 성명
  직책             → assignment_name 해당 조직 단위 책임자 직책 (예: PL/본부장/파트장)

dep_id/upper_dep_id/team_layer는 이제 엑셀 컬럼이 아니라
team_hierarchy.derive_hierarchy()가 1/2/3단계 부서명 경로에서 자동으로 계산한다
(rd_specialist_markdown.build_org_tree()가 이 dep_id/upper_dep_id로 조직도
부모-자식 관계를 판단하는 것은 기존과 동일).

── 날짜 기반 누적 ───────────────────────────────────────────────────────────
과거에는 실행할 때마다 team_refer.csv를 전량 덮어썼다. 지금은 관리자 화면
("팀/리더 참조" 탭)에서도 개별 조직 단위(행)가 수시로 부분 수정될 수 있어,
"이번 파일에 없으면 사라진 것"(researchers.csv의 is_current 판정 방식 — 매번
전체를 다시 올린다는 전제가 있어야 성립)을 그대로 쓸 수 없다 — 그 방식을 그대로
쓰면, 오늘 조직 하나만 고쳐 저장했을 때 건드리지 않은 나머지 조직이 전부
"사라짐"으로 판정돼버린다.

그래서 자연키를 (dep_id, valid_year, valid_month, valid_day)로 두고 계속
누적하며, dep_id별로 "그 dep_id의 가장 최근 날짜 행"을 독립적으로 "현재" 상태로
취급한다(rd_specialist_markdown.read_team_refer() 참고) — 오늘 조직 하나만
고쳐도 나머지는 각자 마지막 저장 시점 값 그대로 정상 노출된다. dep_id는 텍스트
경로에서 결정적으로 재계산되므로(team_hierarchy.py 참고) 조직명이 바뀌어도
매번 다시 계산해 안전하지만, 이번 실행 결과에 없는 옛 dep_id는 process()가
"현재" 저장값과 비교해 자동으로 deleted='Y' 톰스톤 처리한다(그래야 이번
목록에서 사라진 조직이 "현재" 조직도에서 유령처럼 계속 남지 않는다).

이 모듈의 process()(xlsx 일괄 업로드)는 이 톰스톤 처리를 제외하고는 항상
deleted='N'으로 저장하고, valid_date 인자(기본값 오늘)로 유효 날짜를 지정할
수 있다 — 과거 데이터를 소급 입력해도, 실제로 그 날짜가 해당 dep_id의 최신이
아니면 "현재" 조직도에는 반영되지 않는다("현재" 판정은 항상 실제 최댓값 기준).

컬럼명이 다를 경우 파일 상단의 _COL_MAP을 실제 헤더에 맞게 수정하세요.

── 웹 업로드(관리자 "데이터 업데이트" 탭) ─────────────────────────────────────
process()는 다른 process_*.py처럼 raw_dir 매개변수를 받는다(2026-08-29
추가) — services.web_pipeline_runner가 이 값을 data/web_updates/team_refer/
로 넘겨 업로드된 파일을 읽게 한다(기본값은 기존과 동일한 data/raw). 이
모듈은 pipeline/sources.py(1단계 DRM 제거 파이프라인)에 등록돼 있지 않은
독립 스크립트라 다른 대부분의 process_*.py와 달리 source_reader.read_source()
DB/스테이징 경로가 없다 — raw_dir 안의 팀참조시트.xlsx를 항상 직접 읽는다
(관리자가 웹 업로드 전 Excel에서 DRM을 해제한 사본을 올린다는 전제는
web_pipeline_runner의 다른 항목과 동일).
"""

import os
import sys
from datetime import date

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR, OUT_DIR  # noqa: E402
from excel_reader import clean_str as _clean, norm_id, read_xlsx  # noqa: E402
from merge_utils import TABLE_KEYS, write_merged  # noqa: E402
from team_hierarchy import FIELDS, derive_hierarchy  # noqa: E402

SOURCE_FILE = '팀참조시트.xlsx'

# ── 컬럼명 매핑(엑셀 헤더명 → 인텔이크 컬럼명) — 순서 무관, 이름으로 찾아 변환 ──
_COL_MAP = {
    '비공식소속부서명': 'org_name_wd',
    '구분': 'work_type',
    '1단계부서명': 'dep_1st_name',
    '2단계부서명': 'dep_2nd_name',
    '3단계부서명': 'dep_3rd_name',
    '조직코드': 'dep_code',
    '사번': 'researcher_id',
    '성명': 'name',
    '직책': 'assignment_name',
}
# ─────────────────────────────────────────────────────────────────────────────


def stamp_valid_date(df: pd.DataFrame, valid_date: date) -> pd.DataFrame:
    """valid_year/valid_month/valid_day 컬럼을 붙인다. process()(xlsx 일괄
    업로드)와 관리자 화면(services.team_refer_store)의 웹 CRUD 저장 경로가
    공유하는 헬퍼 — 자연키((dep_id, valid_year, valid_month, valid_day))
    형식을 한 곳에서만 정의해 두 경로가 어긋나지 않게 한다."""
    df = df.copy()
    df['valid_year'] = f'{valid_date.year:04d}'
    df['valid_month'] = f'{valid_date.month:02d}'
    df['valid_day'] = f'{valid_date.day:02d}'
    return df


def build_rows_from_records(records: list) -> pd.DataFrame:
    """레코드 리스트(엑셀 헤더명을 키로 쓰는 dict — "전체 경로 포함" 인텔이크
    형태, 각 행이 자기 소속 경로를 자기 레벨까지 전부 채움)를 _COL_MAP 기준으로
    컬럼 매핑·정제한 뒤 team_hierarchy.derive_hierarchy()에 넘겨 조직 단위별
    1행(자기 레벨 이름만 채운 저장 스키마 — dep_id/upper_dep_id/team_layer
    자동 계산)으로 변환한다.

    valid_year/valid_month/valid_day/deleted는 이 함수가 붙이지 않는다 —
    호출부가 stamp_valid_date()로 붙인다(저장 시점을 여기서 강제하지
    않기 위함)."""
    df = pd.DataFrame(records)
    for col in _COL_MAP:
        if col not in df.columns:
            df[col] = ''

    cleaned = pd.DataFrame({
        out_col: df[src_col].apply(_clean)
        for src_col, out_col in _COL_MAP.items()
    })
    cleaned['researcher_id'] = cleaned['researcher_id'].apply(norm_id)

    nodes = derive_hierarchy(cleaned.to_dict('records'))
    return pd.DataFrame(nodes, columns=list(FIELDS))


def find_duplicate_dep_ids(result: pd.DataFrame) -> list[dict]:
    """같은 업로드/저장 안에서 부서ID(dep_id)가 중복된 행을 찾는다.

    team_hierarchy.derive_hierarchy()가 이미 같은 경로(=같은 dep_id)를 하나의
    조직 단위 행으로 합치기 때문에 이 함수가 실제로 중복을 찾아내는 경우는
    거의 없다 — 다만 관리자 화면(services.team_refer_store)이 그리드의
    수동 입력 행을 그대로 이 결과에 이어붙이는 등 이 함수의 입력이 항상
    derive_hierarchy()를 거친 것이라는 보장이 없어, 진단용으로 계속 남겨둔다.

    반환: [{'dep_id': ..., 'count': N, 'rows': [{...행 정보...}, ...]}, ...]
    (dep_id 오름차순, 문자열 정렬 — 화면/콘솔 표시용이라 정확한 정렬 기준은
    중요하지 않음)."""
    if result.empty:
        return []
    dupes = result[result.duplicated('dep_id', keep=False)]
    if dupes.empty:
        return []

    display_cols = ['dep_id', 'dep_code', 'dep_1st_name', 'dep_2nd_name',
                     'dep_3rd_name', 'upper_dep_id', 'researcher_id', 'name']
    groups = []
    for dep_id, grp in dupes.groupby('dep_id'):
        groups.append({
            'dep_id': dep_id,
            'count': len(grp),
            'rows': grp[display_cols].to_dict('records'),
        })
    return sorted(groups, key=lambda g: g['dep_id'])


def _print_duplicate_warning(dupes: list[dict]) -> None:
    if not dupes:
        return
    print(f'[WARN] 부서ID(dep_id) 중복 {len(dupes)}건 발견 — 업서트 시 각 부서ID당 '
          f'마지막 행만 남고 나머지는 저장되지 않습니다:')
    for g in dupes:
        print(f"  · dep_id={g['dep_id']} ({g['count']}행)")
        for i, row in enumerate(g['rows'], start=1):
            print(f"      {i}) 조직코드={row['dep_code']} 1단계={row['dep_1st_name']} "
                  f"2단계={row['dep_2nd_name']} 3단계={row['dep_3rd_name']} "
                  f"상위부서ID={row['upper_dep_id']} 사번={row['researcher_id']} 성명={row['name']}")


def tombstone_missing_dep_ids(result: pd.DataFrame, valid_date: date) -> pd.DataFrame:
    """이번 처리 결과(result — build_rows_from_records()가 만든, 이번에
    "살아있어야 할" 조직 전체)에 없는, 현재 "살아있는" dep_id를 찾아
    deleted='Y' 톰스톤 행으로 만든다 — 텍스트 경로에서 dep_id를 매번 새로
    계산하는 이 설계에서는(team_hierarchy.py 참고) "이번 목록에 없는 옛
    dep_id"를 그대로 두면 read_team_refer()가 계속 "현재"로 취급해 유령
    노드가 남기 때문에 process()(xlsx 일괄 업로드)와
    services.team_refer_store.save_snapshot()(관리자 화면 그리드 저장)
    양쪽 모두 저장 직전에 이 함수를 거쳐 자동으로 마감 처리한다 — 관리자
    화면도 매번 "현재 조직 전체"를 그리드로 불러와 그 전체를 다시 저장하는
    구조라(부분 패치가 아님) 같은 원리가 그대로 적용된다. 값은 마지막으로
    알려진 그대로 보존하고 deleted만 'Y'로 바꾼 새 날짜 행을 추가한다(이력
    보존)."""
    from rd_specialist_markdown import read_team_refer  # 지연 임포트: 순환 참조 회피

    current_dep_ids = {row.get('dep_id') for row in read_team_refer(OUT_DIR)}
    this_run_dep_ids = set(result['dep_id'])
    missing = current_dep_ids - this_run_dep_ids
    if not missing:
        return result

    current_by_dep = {row.get('dep_id'): row for row in read_team_refer(OUT_DIR)}
    tombstones = []
    for dep_id in missing:
        src = current_by_dep.get(dep_id) or {}
        base = {c: src.get(c, '') for c in FIELDS}
        base['dep_id'] = dep_id
        tombstones.append(base)
    tomb_df = pd.DataFrame(tombstones, columns=list(FIELDS))
    tomb_df = stamp_valid_date(tomb_df, valid_date)
    tomb_df['deleted'] = 'Y'
    return pd.concat([result, tomb_df], ignore_index=True)


def process(raw_dir: str = RAW_DIR, valid_date: date | None = None) -> bool:
    """raw_dir: 팀참조시트.xlsx를 찾을 폴더(기본값 data/raw — 웹 업로드 시
    services.web_pipeline_runner가 data/web_updates/team_refer/를 넘긴다).
    valid_date: 이번 업로드분의 유효 날짜(기본값 오늘) — 과거 데이터
    소급 입력 시 지정."""
    raw_path = os.path.join(raw_dir, SOURCE_FILE)
    if not os.path.exists(raw_path):
        print(f'[SKIP] {SOURCE_FILE} 파일 없음({raw_dir})')
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

    result = build_rows_from_records(df.to_dict('records'))
    _print_duplicate_warning(find_duplicate_dep_ids(result))

    valid_date = valid_date or date.today()
    result = stamp_valid_date(result, valid_date)
    result['deleted'] = 'N'

    result = tombstone_missing_dep_ids(result, valid_date)

    out_path = os.path.join(OUT_DIR, 'team_refer.csv')
    merged = write_merged(out_path, result, TABLE_KEYS['team_refer'])

    print(f'[OK]   team_refer.csv 저장 (이번 업로드 {len(result)}행 반영, 누적 총 {len(merged)}행)')
    return True


if __name__ == '__main__':
    process()
