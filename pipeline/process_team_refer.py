"""
팀참조시트(조직 계층 구조 + 각 조직 단위 책임자 정보) 처리 모듈

원천 파일: data/raw/팀참조시트.xlsx (헤더 행 위치는 자동 인식, _read_source() 참고)
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
DB/스테이징 경로가 없다(관리자가 웹 업로드 전 Excel에서 DRM을 해제한
사본을 올린다는 전제는 web_pipeline_runner의 다른 항목과 동일).

── xlsx뿐 아니라 CSV도 직접 읽는다(2026-09-11 추가) ────────────────────────────
scripts/build_team_refer_intake.py(인력현황 원본 → team_refer 인텔이크
전처리 스크립트, 신설)의 산출물은 xlsx가 아니라 CSV다(과거 xlsx를 새로 쓸 때
openpyxl의 OOXML 메타데이터 손상 이력 — docs/CLAUDE.md 2026-08-31/09-02
참고). 그 CSV를 사람이 검토·보정한 뒤 xlsx로 옮겨 담을 필요 없이 그대로
다시 업로드할 수 있도록, `팀참조시트.xlsx`가 없으면 `.csv` 확장자도 찾는다
(_find_source_file() 참고) — 웹 업로드 경로(services.web_pipeline_runner가
team_refer 항목을 'wildcard' 모드로 등록해 원본 파일명을 그대로 보존)에서는
그 폴더 안의 유일한 xlsx/csv 파일을 그대로 찾아 쓴다.
"""

import glob
import os
import re
import sys
from datetime import date

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR, OUT_DIR  # noqa: E402
from excel_reader import clean_str as _clean, norm_id, read_xlsx  # noqa: E402
from merge_utils import TABLE_KEYS, write_merged  # noqa: E402
from team_hierarchy import FIELDS, LEVEL_FIELDS, derive_hierarchy, own_path, slug  # noqa: E402
import team_refer_intake  # noqa: E402

SOURCE_FILE = '팀참조시트.xlsx'
SOURCE_FILE_CSV = '팀참조시트.csv'

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


# ── "(SAIT)"/"(기술원)" 표기 제거(2026-09-15 확정) ────────────────────────────
# 같은 팀이 조직 관점(종합기술원 vs SAIT)에 따라 다르게 표기돼 들어오는
# 경우가 있어("AI융합기술팀(SAIT)"/"AI융합기술팀(기술원)"), 1/2/3단계부서명
# 값에서 이 태그만 지우고 실제로는 같은 조직으로 합쳐지게 한다(사용자 확정 —
# 두 태그가 동시에 한 값에 붙는 경우는 없어 정규식으로 단순 제거해도 안전).
# team_refer.csv를 만드는 이 함수(build_rows_from_records)에서 지워 저장하므로
# 그리드/조직도 사이드바/엑셀 다운로드/AI 검색 등 team_refer.csv를 쓰는 모든
# 화면에 자동으로 반영된다.
_ORG_TAG_PATTERN = re.compile(r'\(SAIT\)|\(기술원\)')


def _strip_org_tags(value) -> str:
    return _ORG_TAG_PATTERN.sub('', str(value or '')).strip()


def _cleaned_records(records: list) -> list:
    """레코드 리스트(엑셀 헤더명 키)를 _COL_MAP 기준으로 컬럼 매핑·정제한
    dict 리스트로 변환한다(태그 제거 전 단계) — build_rows_from_records()와
    find_tag_merges()가 공유(정제 로직이 갈라지지 않도록 한 곳에서만 정의)."""
    df = pd.DataFrame(records)
    for col in _COL_MAP:
        if col not in df.columns:
            df[col] = ''

    cleaned = pd.DataFrame({
        out_col: df[src_col].apply(_clean)
        for src_col, out_col in _COL_MAP.items()
    })
    cleaned['researcher_id'] = cleaned['researcher_id'].apply(norm_id)
    return cleaned.to_dict('records')


def _strip_record_tags(record: dict) -> dict:
    stripped = dict(record)
    for field in LEVEL_FIELDS:
        stripped[field] = _strip_org_tags(stripped[field])
    return stripped


def build_rows_from_records(records: list) -> pd.DataFrame:
    """레코드 리스트(엑셀 헤더명을 키로 쓰는 dict — "전체 경로 포함" 인텔이크
    형태, 각 행이 자기 소속 경로를 자기 레벨까지 전부 채움)를 _COL_MAP 기준으로
    컬럼 매핑·정제하고 1/2/3단계부서명의 "(SAIT)"/"(기술원)" 태그를 제거한 뒤
    team_hierarchy.derive_hierarchy()에 넘겨 조직 단위별 1행(자기 레벨 이름만
    채운 저장 스키마 — dep_id/upper_dep_id/team_layer 자동 계산)으로 변환한다.

    valid_year/valid_month/valid_day/deleted는 이 함수가 붙이지 않는다 —
    호출부가 stamp_valid_date()로 붙인다(저장 시점을 여기서 강제하지
    않기 위함)."""
    pre_records = _cleaned_records(records)
    stripped_records = [_strip_record_tags(r) for r in pre_records]
    nodes = derive_hierarchy(stripped_records)
    return pd.DataFrame(nodes, columns=list(FIELDS))


def find_tag_merges(records: list) -> list[dict]:
    """"(SAIT)"/"(기술원)" 태그 제거로 서로 다른 원본 조직 경로가 같은
    조직으로 합쳐지는 경우를 찾는다(예: "...AI융합기술팀(SAIT)"와
    "...AI융합기술팀(기술원)"가 둘 다 "...AI융합기술팀"이 되는 경우) —
    build_rows_from_records()가 실제로 적용하는 것과 동일한 정제·태그 제거
    단계를 거쳐, 태그 제거 "전" 경로 기준으로 그룹핑한 뒤 같은 "후" 경로로
    묶이는 그룹이 2개 이상이면 병합으로 본다.

    반환: [{'merged_name': 태그 제거 후 이름, 'kept': {최종 저장된 값},
    'variants': [{'original_name': 태그 제거 전 이름, ...원본 속성}, ...]}]
    (병합이 없으면 빈 리스트)."""
    pre_records = _cleaned_records(records)
    stripped_records = [_strip_record_tags(r) for r in pre_records]

    groups: dict = {}  # post_path -> {pre_path: representative pre_record}
    for pre, post in zip(pre_records, stripped_records):
        post_path = own_path(post)
        if not post_path:
            continue
        pre_path = own_path(pre)
        groups.setdefault(post_path, {}).setdefault(pre_path, pre)

    merge_groups = {path: variants for path, variants in groups.items() if len(variants) > 1}
    if not merge_groups:
        return []

    nodes_by_id = {n['dep_id']: n for n in derive_hierarchy(stripped_records)}
    attr_fields = ('org_name_wd', 'dep_code', 'researcher_id', 'name', 'assignment_name')

    def _attrs(rec: dict) -> dict:
        return {f: rec.get(f, '') for f in attr_fields}

    results = []
    for post_path, variants in merge_groups.items():
        final_node = nodes_by_id.get(slug(post_path), {})
        results.append({
            'merged_name': post_path[-1] if post_path else '',
            'kept': _attrs(final_node),
            'variants': [
                {'original_name': pre_path[-1] if pre_path else '', **_attrs(rec)}
                for pre_path, rec in variants.items()
            ],
        })
    return results


# ── 신규 업로드 시 책임자(사번/성명/직책) 과거값 자동 채움(2026-09-16 확정,
# 2026-09-17 시점 조건 추가) ─────────────────────────────────────────────────
# 인력현황 원본을 scripts/build_team_refer_intake.py로 전처리한 인텔이크는
# 사번/성명/직책이 항상 빈 값이다(그 스크립트 docstring 참고 — "이 사람이
# 이 조직의 대표 책임자"라는 판단은 별도 정보가 필요해 범위 밖). 매번
# 관리자가 새로 다 채워 넣지 않아도 되도록, 같은 비공식소속부서명(org_name_wd,
# researchers.csv의 org_code와 매칭되는 안정적인 조직 키)을 가진 "현재"
# 조직(read_team_refer()가 반환하는, 톰스톤되지 않은 가장 최근 저장값)의
# 값을 그대로 채운다 — 이번 업로드에 이미 값이 있는 필드는 덮어쓰지 않는다
# (팀참조시트.xlsx처럼 사람이 직접 채워 올리는 입력은 그대로 존중).
# 관리자가 그리드에서 이 값을 수동으로 고쳐 저장하면 그 수정값이 곧
# "현재" 값이 되므로, 다음 업로드부터는 자동으로 그 수정된 값이 채워진다 —
# 별도의 이력 저장소 없이 team_refer.csv 자체가 "마지막으로 확인된 값"의
# 원천이 된다. services.team_refer_store.save_snapshot()(관리자 화면 그리드
# 저장)에는 적용하지 않는다 — 그리드는 항상 "현재 전체 + 편집분"을 다시
# 제출하는 구조라, 관리자가 일부러 값을 비워 저장(담당자 공석 처리 등)해도
# 여기서 과거값으로 도로 채워버리면 의도적인 공백 처리가 불가능해진다.
#
# 2026-09-17 확정: 무조건 "가장 최근 저장값"을 채우지 않고, 이번 업로드의
# 유효 날짜(valid_date)가 그 조직의 기존 저장값의 유효 날짜보다 같거나
# 늦을 때만 채운다. 예: AI융합팀이 2026-09-04일자로 사번/성명/직책이 이미
# 저장돼 있을 때, 2026-09-14일자로 업로드하면(9/4보다 미래 시점 — "그
# 뒤로도 그대로 유지됐다"고 가정할 수 있음) 그대로 채우지만, 2026-09-01
# 일자로(과거 시점 소급 입력) 업로드하면 채우지 않고 공란으로 남긴다 —
# 9/4에 알게 된 값을 9/4 이전 시점에도 똑같았다고 가정할 근거가 없기
# 때문(9/4 시점에 새로 배정됐을 수도 있음).
def _backfill_leader_fields(result: pd.DataFrame, valid_date: date) -> pd.DataFrame:
    """result(이번 업로드로 만들어진 조직 단위별 1행)에서 사번/성명/직책이
    빈 행을, 같은 비공식소속부서명을 가진 "현재" 조직의 값으로 채운다 —
    단, valid_date(이번 업로드의 유효 날짜)가 그 "현재" 값이 저장된 날짜보다
    같거나 미래일 때만(과거 시점 소급 입력에는 채우지 않음)."""
    from rd_specialist_markdown import read_team_refer  # 지연 임포트: 순환 참조 회피

    current_by_org = {}
    for row in read_team_refer(OUT_DIR):
        org = str(row.get('org_name_wd') or '').strip()
        if org:
            current_by_org[org] = row

    if not current_by_org or result.empty:
        return result

    leader_fields = ['researcher_id', 'name', 'assignment_name']

    def _prev_valid_date(prev: dict) -> date | None:
        try:
            return date(int(prev.get('valid_year') or 0),
                        int(prev.get('valid_month') or 0),
                        int(prev.get('valid_day') or 0))
        except (TypeError, ValueError):
            return None  # 옛 스키마 등으로 날짜를 알 수 없으면 채우지 않음(보수적으로 처리)

    def _fill(row):
        org = str(row['org_name_wd'] or '').strip()
        prev = current_by_org.get(org) if org else None
        if not prev:
            return row
        prev_date = _prev_valid_date(prev)
        if prev_date is None or valid_date < prev_date:
            return row
        for field in leader_fields:
            if not str(row[field] or '').strip():
                row[field] = prev.get(field, '')
        return row

    return result.apply(_fill, axis=1)


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


def _print_merge_warning(merges: list[dict]) -> None:
    if not merges:
        return
    print(f'[WARN] "(SAIT)"/"(기술원)" 태그 제거로 {len(merges)}건이 하나의 조직으로 합쳐졌습니다 '
          f'— 확인용으로 병합된 항목을 나열합니다(값 손실은 없는지 확인해주세요):')
    for m in merges:
        print(f"  · 합쳐진 이름: {m['merged_name']}")
        for v in m['variants']:
            print(f"      - 원래 표기: {v['original_name']} (조직코드={v['org_name_wd']}, "
                  f"사번={v['researcher_id']}, 성명={v['name']}, 직책={v['assignment_name']})")
        k = m['kept']
        print(f"      → 최종 유지된 값: 조직코드={k['org_name_wd']}, 사번={k['researcher_id']}, "
              f"성명={k['name']}, 직책={k['assignment_name']}")


_KNOWN_ROOT_NAMES = {'SAIT', '종합기술원'}


def reparent_orphan_roots(result: pd.DataFrame) -> pd.DataFrame:
    """1단계부서명만 채워진(2/3단계부서명 전부 빈) 그 1단계부서명이 실제
    최상위 루트("SAIT"/"종합기술원")가 아닌 행을 찾아 upper_dep_id를 그
    루트의 dep_id로 채운다(2026-09-16, 사용자 확정 — "보유 전문성"의
    조직도가 부모-자식 관계를 올바르게 그리도록 하기 위함).

    인력현황 원본에서 만드는 intake(scripts/build_team_refer_intake.py
    산출물)에는 사람 배정이 없는 조직이 1단계부서명만 채워진 채로 들어올
    수 있는데(예: "AI융합팀"), 2/3단계 정보가 없어 겉보기엔 최상위
    조직처럼 보일 뿐 실제로는 SAIT나 종합기술원 밑에 속한다.

    upper_dep_id만 바꾸고 team_layer/1~3단계부서명 컬럼 값은 그대로
    둔다 — build_org_tree()의 부모-자식 관계는 dep_id/upper_dep_id로만
    정해지고 team_layer는 라벨 표시용일 뿐이라, 이미 3단계 깊이인 하위
    조직(예: ADDP>공정>파트1의 "파트1")이 있어도 스키마에 없는 4단계
    칸이 필요 없이 그대로 안전하게 동작한다.

    2026-09-17 확정: `org_name_wd`가 채워져 있어도(=collapse_repeated_
    levels()로 진짜 조직명이 붙은 1단계 노드여도) 그대로 재부모화 대상에
    포함한다 — "내부 데이터상 부서단위가 명확하지 않아 담당자 의도대로
    SAIT 산하에 편입시킨다"는 원칙은 org_name_wd 유무와 무관하게 적용됨
    (최초 2026-09-16 버전은 org_name_wd가 빈 자리표시자 노드만 대상으로
    했었으나, 실제 명명된 1단계 조직도 동일하게 편입해야 한다는 사용자
    확정에 따라 조건을 완화).

    같은 업로드 파일 안에 "SAIT"와 "종합기술원"이 동시에 루트로 존재할
    일은 없다는 전제(사용자 확정)로, 실제로 존재하는 쪽 하나만 찾아 그
    dep_id를 쓴다. 이번 파일에 루트 자체가(SAIT도 종합기술원도) 없으면
    아무것도 바꾸지 않는다(기존과 동일하게 최상위로 남김, 사용자 확정).

    엑셀 일괄 업로드(process()) 전용이다 — 관리자 화면 그리드 저장
    (services.team_refer_store.save_snapshot())에는 적용하지 않는다
    (사용자 확정 — "이건 보유 전문성의 조직도에서 부모-자식 관계 반영
    하기 위한 작업"이라 배치 업로드 경로에만 필요하다고 판단)."""
    root_rows = result[
        (result['team_layer'] == '1') & (result['dep_1st_name'].isin(_KNOWN_ROOT_NAMES))
    ]
    if root_rows.empty:
        return result
    root_dep_id = root_rows.iloc[0]['dep_id']

    orphan_mask = (
        (result['team_layer'] == '1')
        & (~result['dep_1st_name'].isin(_KNOWN_ROOT_NAMES))
        & (result['dep_2nd_name'] == '')
        & (result['dep_3rd_name'] == '')
    )
    result = result.copy()
    result.loc[orphan_mask, 'upper_dep_id'] = root_dep_id
    return result


_LEVEL_COLS = ('1단계부서명', '2단계부서명', '3단계부서명')


def collapse_repeated_levels(records: list) -> list:
    """1/2/3단계부서명 중 어떤 레벨의 값이 바로 위 레벨의 값과 같으면, 그
    레벨은 실제로 새로운 깊이가 아니라 "이 상위 레벨 자체에는 별도 하위
    구분이 없다"는 것을 사람이 미관상 반복 입력해 표현한 것으로 보고
    접는다(2026-09-17 확정). 값이 붙어 있던 칸은 비우는 대신 뒤 칸들을
    앞으로 당겨 채운다 — own_path()가 첫 빈 값에서 경로 읽기를 멈추므로,
    중간 칸만 비우고 뒤 칸 값을 그대로 두면 그 뒤 값이 통째로 무시된다.

    예: (ADDP,ADDP,ADDP) → 2·3단계 모두 바로 위와 같아 전부 접힘 → (ADDP,'','')
        (ADDP,ADDP,2D)   → 2단계만 접힘(2D는 3단계 칸에서 2단계 칸으로 당겨짐)
                            → (ADDP,'2D','')
        (ADDP,공정,공정)  → 3단계만 접힘 → (ADDP,'공정','')
        (ADDP,공정,파트1) → 전부 다름, 접힐 것 없음 → 변화 없음

    "ADDP 산하에 우연히 같은 이름 'ADDP'인 별도 하위조직이 있는" 경우는
    이 휴리스틱으로 구분할 수 없다는 한계가 있으나, 실제 데이터에는 그런
    경우가 없다고 사용자가 확인함.

    엑셀 일괄 업로드(process())와 관리자 화면 그리드 저장(services.
    team_refer_store.save_snapshot()) 양쪽 다 쓴다. 최초엔 그리드에는
    적용하지 않기로 했었으나(그리드에서 사람이 이 반복 표기를 그대로
    입력해서 쓸 수 있어야 한다는 이유), 2026-09-17에 "그리드도 team_
    refer.csv 저장 형식(process_team_refer.reshape_storage_columns())과
    동일하게 보여달라"는 요청으로 그리드 자체가 이제 재배치된(레벨
    중복이 생기는) 값을 그대로 보여주게 되면서, 저장 시 그 중복을 다시
    접어 원래 깊이로 복원해야 own_path()가 오작동하지 않아 범위를
    넓혔다(save_snapshot() 2026-09-17 수정 참고) — reshape가 만드는
    중복 패턴과 이 함수의 되감기 규칙이 정확히 역함수 관계라 안전하다."""
    result = []
    for record in records:
        new_record = dict(record)
        kept = []
        for col in _LEVEL_COLS:
            value = str(record.get(col) or '').strip()
            if not value:
                break
            if not kept or value != kept[-1]:
                kept.append(value)
        for i, col in enumerate(_LEVEL_COLS):
            new_record[col] = kept[i] if i < len(kept) else ''
        result.append(new_record)
    return result


_STORAGE_LAYER_IDX = {'1': 0, '2': 1, '3': 2}


def reshape_storage_columns(result: pd.DataFrame) -> pd.DataFrame:
    """team_refer.csv 저장 형식 전용 재배치(2026-09-17 확정, 같은 날 2차
    수정 — "칸 고정 hop" 규칙으로 재정의) — dep_id/upper_dep_id/team_layer
    (내부 트리 구조·조직코드 순서 결정에 쓰이는 값)는 전혀 건드리지 않고,
    1/2/3단계부서명 3개 컬럼의 "표시 값"만 외부 시스템 요구사항에 맞춰
    다시 채운다: 외부 시스템이 team_refer.csv를 직접 읽는데 "비공식소속
    부서명(org_name_wd)은 무조건 3단계부서명 칸에 있어야 한다"는 내부
    규정이 있어, own-level-only 저장 스키마(자기 team_layer 칸만 채움)
    그대로는 1·2단계 조직의 org_name_wd가 엉뚱한 칸(1·2단계부서명 칸)에
    남는다.

    규칙(사용자 확정, 2차): 각 칸은 "자기 자신에서 몇 hop 위 조상을
    보여줄지"가 칸 위치로 고정된다 — 3단계 칸(i=2)은 0-hop(자기 자신),
    2단계 칸(i=1)은 1-hop(직속 부모), 1단계 칸(i=0)은 2-hop(조부모).
    실제 hop 수는 `min(목표 hop, 자기 깊이-1)`로 캡을 건다 — 조부모/부모가
    없으면(즉 자기 깊이가 그 hop 수보다 얕으면) 있는 데까지만 올라간
    조상(=가장 가까운 실제 조상, 없으면 자기 자신)을 대신 채운다.
    예) 2단계(깊이 2) 노드는 조부모가 없으므로 1단계 칸도 1-hop(부모)으로
    캡돼, 1단계·2단계 칸에 똑같이 부모 이름이 들어간다(2D → 1단계=ADDP,
    2단계=ADDP, 3단계=2D). 1단계(깊이 1) 노드는 부모도 없어 모든 칸이
    0-hop(자기 자신)으로 캡돼 3칸 다 자기 이름이 들어간다.

    **1차 버전(own_idx 이상=자기 이름) 대비 달라진 점**: 2단계 노드의
    2단계부서명 칸이 예전엔 "자기 이름"이었는데 이번엔 "부모 이름"으로
    바뀐다 — 그 결과 own_level_name()(자기 team_layer 칸만 읽어 조직도
    라벨을 결정)이 2단계 노드의 라벨로 부모 이름을 잘못 읽는 문제가
    생긴다. 이건 이 함수가 아니라 own_level_name() 쪽에서 org_name_wd를
    우선 사용하도록 고쳐서 해결했다(rd_specialist_markdown.py 참고) —
    "own_idx 칸=항상 자기 이름"이라는 전제가 이제 2단계 노드에는 더 이상
    성립하지 않기 때문에, 라벨을 그 칸에서 다시 읽어오면 안 된다.

    조상 이름은 upper_dep_id 체인을 값을 바꾸기 전 원본 result 기준으로
    거슬러 올라가 찾는다(reparent_orphan_roots()가 이미 반영한 SAIT 강제
    편입 뒤에 이 함수가 실행되므로, ADDP/인사처럼 SAIT 밑으로 편입된
    1단계 조직은 자기 깊이가 1이라 hop 캡이 0에서 멈춰 SAIT 이름이 섞여
    들어올 일이 없다 — hop 캡은 항상 "SAIT 재편입 이전의 원래 트리 깊이"
    기준이라는 뜻).

    **org_name_wd가 없는 행(경로상으로만 존재하는 조상 전용 노드 — 예:
    아무도 2단계 "공정" 자체에 직접 소속되지 않고 다들 그 밑 3단계에만
    있는 경우)은 이 함수가 아예 건드리지 않고 원래 값(own-level-only
    스키마 그대로, 자기 칸=경로 텍스트/나머지 칸=공백) 그대로 둔다.**
    이유: 조상 조회(`_ancestor_self`)는 org_name_wd가 없으면 그 칸의
    원래 경로 텍스트로 폴백하지만, 그 폴백은 그 노드 "자신의" 칸이 아직
    원본 그대로일 때만 유효하다 — 이 노드 자신을 재배치 규칙으로 다시
    써버리면(위 규칙상 2단계 노드는 자기 칸에 "부모 이름"이 들어갈 수
    있음) 원래 경로 텍스트가 영영 사라져 그 어디에도 남지 않는다
    (org_name_wd도 없고, 자기 칸도 부모 이름으로 덮였으므로 복구 불가).
    반면 org_name_wd가 없는 행은 애초에 외부 시스템이 매칭할 org_name_wd
    자체가 없어 "org_name_wd를 3단계에 넣어야 한다"는 요구사항이 적용될
    대상도 아니므로, 건드리지 않아도 요구사항 위반이 아니다.

    process()(xlsx 일괄 업로드)와 services.team_refer_store.save_snapshot()
    (관리자 화면 그리드 저장) 양쪽 다 최종 저장 직전에 호출한다 — 외부
    시스템은 두 경로로 저장된 team_refer.csv를 구분하지 않고 읽으므로 저장
    형식은 항상 일관돼야 한다. 관리자 그리드(services.team_refer_store.
    list_editable_rows())는 이 함수가 물리적으로 재배치한 칸 값을 그대로
    믿지 않고 org_name_wd 기준으로 매번 다시 복원하므로(team_hierarchy.
    backfill_full_path() 2026-09-17 수정 참고) 그리드 UX는 바뀌지 않는다."""
    if result.empty:
        return result
    by_dep_id = result.set_index('dep_id', drop=False).to_dict('index')

    def _effective_self(node: dict) -> str:
        own_idx = _STORAGE_LAYER_IDX.get(str(node.get('team_layer')))
        org_name_wd = str(node.get('org_name_wd') or '').strip()
        if org_name_wd:
            return org_name_wd
        if own_idx is None:
            return ''
        return str(node.get(LEVEL_FIELDS[own_idx]) or '')

    def _ancestor_self(dep_id: str, hops: int) -> str:
        node = by_dep_id.get(dep_id)
        for _ in range(hops):
            if not node:
                return ''
            node = by_dep_id.get(node.get('upper_dep_id'))
        return _effective_self(node) if node else ''

    def _reshape(row):
        own_idx = _STORAGE_LAYER_IDX.get(str(row['team_layer']))
        if own_idx is None or not str(row.get('org_name_wd') or '').strip():
            return row
        depth = own_idx + 1
        for i, col in enumerate(LEVEL_FIELDS):
            hops = min(2 - i, depth - 1)
            row[col] = _ancestor_self(row['dep_id'], hops)
        return row

    return result.copy().apply(_reshape, axis=1)


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


def _find_source_file(raw_dir: str) -> str | None:
    """raw_dir에서 읽을 파일 하나를 찾는다. CLI(data/raw/) 사용 시에는
    다른 테이블용 원본까지 섞여 있을 수 있어 정확한 파일명(SOURCE_FILE
    또는 그 csv 버전)을 우선 찾는다. 둘 다 없으면(웹 업로드 —
    data/web_updates/team_refer/처럼 이 폴더에 team_refer 관련 파일 하나만
    있는 폴더, services.web_pipeline_runner가 'wildcard' 모드로 원본
    파일명을 그대로 보존해 저장한다) 그 폴더 안의 xlsx/csv 파일이 정확히
    1개뿐이면 그걸 쓴다(임시 잠금 파일 '~$*' 제외) — 여러 개면 어느 걸
    읽어야 할지 알 수 없으므로 실패 처리."""
    exact_xlsx = os.path.join(raw_dir, SOURCE_FILE)
    if os.path.exists(exact_xlsx):
        return exact_xlsx
    exact_csv = os.path.join(raw_dir, SOURCE_FILE_CSV)
    if os.path.exists(exact_csv):
        return exact_csv

    candidates = sorted(
        p for p in glob.glob(os.path.join(raw_dir, '*.xlsx')) + glob.glob(os.path.join(raw_dir, '*.csv'))
        if not os.path.basename(p).startswith('~$')
    )
    return candidates[0] if len(candidates) == 1 else None


def _read_source(path: str) -> pd.DataFrame:
    """.xlsx는 read_xlsx()(xlwings, DRM 파일용)로, .csv는
    scripts/build_team_refer_intake.py의 산출물과 동일한 방식
    (`pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')`, 1번째
    행 헤더)으로 읽는다 — xlwings/Excel이 전혀 필요 없어 DRM 자동화 문제와
    무관하다.

    xlsx는 header_row='auto'(공란 행을 건너뛰고 실제 값이 있는 첫 행을
    헤더로 자동 인식)를 쓴다 — 원본 팀참조시트.xlsx(1행 공란, 2행 헤더)와
    관리자 화면 "엑셀 다운로드" 산출물(1행이 바로 헤더,
    services.team_refer_store._build_workbook()) 둘 다 이 업로드 섹션에
    다시 올릴 수 있어야 하는데, 예전처럼 header_row=1로 고정하면 다운로드
    파일은 진짜 헤더 행이 통째로 버려지고 첫 데이터 행이 헤더로 잘못
    읽혀 "[ERROR] 필수 컬럼 없음"으로 실패했다(2026-09-17 실제 재현 후
    발견 — "엑셀 다운로드 → 그대로 재업로드" 마이그레이션 경로가 이
    수정 전에는 동작하지 않았다)."""
    if path.lower().endswith('.csv'):
        return pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')
    return read_xlsx(path, header_row='auto')


def process(raw_dir: str = RAW_DIR, valid_date: date | None = None, skip_tombstone: bool = False) -> bool:
    """raw_dir: 팀참조시트.xlsx(또는 .csv)를 찾을 폴더(기본값 data/raw —
    웹 업로드 시 services.web_pipeline_runner가 data/web_updates/team_refer/를
    넘긴다). valid_date: 이번 업로드분의 유효 날짜(기본값 오늘) — 과거
    데이터 소급 입력 시 지정.

    skip_tombstone(기본 False, 2026-09-17 추가): True면 tombstone_missing_
    dep_ids() 단계를 건너뛴다 — scripts/backfill_team_refer_history.py
    (과거 여러 달치 인력현황 원본을 한 번에 소급 반영하는 스크립트) 전용
    옵션이다. tombstone_missing_dep_ids()는 "현재(전체 파일 기준 가장 최근
    날짜) 살아있는 dep_id인데 이번 실행 결과에 없으면 사라진 것으로
    본다"는 로직이라, 이미 더 미래 시점(예: 2026-09)의 "현재" 데이터가
    쌓여 있는 상태에서 그보다 과거 시점(예: 2020-03)을 나중에 소급
    반영하면, 미래에만 존재하는 온갖 조직이 전부 "2020-03에 사라짐"으로
    잘못 톰스톤 처리된다 — "현재" 조직도 표시 자체는(항상 dep_id별 가장
    최근 날짜를 고르므로) 영향받지 않지만, 기간 지정 조회(_latest_rows_
    in_period() 등 특정 시점 기준 조직도 재구성)가 그 잘못된 톰스톤을
    "2020-03 시점의 실제 상태"로 오인해 과거 조직도가 깨진다. 정상적인
    웹 업로드/그리드 저장(항상 "지금" 또는 그 이후 시점만 다루므로 이
    문제가 없음)에는 기본값 False 그대로 둔다."""
    raw_path = _find_source_file(raw_dir)
    if not raw_path:
        others = sorted(
            os.path.basename(p) for p in
            glob.glob(os.path.join(raw_dir, '*.xlsx')) + glob.glob(os.path.join(raw_dir, '*.csv'))
            if not os.path.basename(p).startswith('~$')
        )
        if others:
            print(f'[ERROR] {SOURCE_FILE}(또는 .csv)를 특정할 수 없습니다 — '
                  f'{raw_dir} 안에 파일이 여러 개 있습니다: {others}')
        else:
            print(f'[SKIP] {SOURCE_FILE}(또는 .csv) 파일 없음({raw_dir})')
        return False

    df = _read_source(raw_path)
    df.columns = [str(c).strip() for c in df.columns]

    # 인력현황 원본("1단계부서명"/"현소속부서명"/"비공식소속부서명" 3개
    # 헤더만 있는 raw 파일)을 그대로 올린 경우, 예전엔 scripts/build_team_
    # refer_intake.py를 사람이 먼저 로컬에서 실행해 인텔이크 형식으로
    # 바꾼 뒤에야 이 업로드 섹션에 올릴 수 있었다. 이제 그 변환 로직
    # (pipeline/team_refer_intake.py로 분리)을 여기서 자동 감지해 바로
    # 적용한다(2026-09-16, 사용자 요청: "원본을 넣으면 intake.py 모듈을
    # 거쳐서 들어갈 수 있도록") — 이미 인텔이크 형식(_COL_MAP 컬럼)으로
    # 변환된 파일을 올리는 기존 방식도 그대로 지원한다(원본 헤더가 없으면
    # 이 블록은 아무것도 하지 않고 지나간다).
    if team_refer_intake.is_raw_format(df):
        print('[INFO] 인력현황 원본 형식 감지 — team_refer 인텔이크 형식으로 자동 변환합니다.')
        df = team_refer_intake.transform(df)

    missing = [col for col in _COL_MAP if col not in df.columns]
    if missing:
        print(
            f'[ERROR] 필수 컬럼 없음: {missing}\n'
            f'  process_team_refer.py 상단의 _COL_MAP을 실제 헤더에 맞게 수정하세요.\n'
            f'  현재 파일 헤더: {list(df.columns)}'
        )
        return False

    valid_date = valid_date or date.today()

    records = df.to_dict('records')
    records = collapse_repeated_levels(records)
    result = build_rows_from_records(records)
    result = reparent_orphan_roots(result)
    result = _backfill_leader_fields(result, valid_date)
    _print_duplicate_warning(find_duplicate_dep_ids(result))
    _print_merge_warning(find_tag_merges(records))

    result = reshape_storage_columns(result)

    result = stamp_valid_date(result, valid_date)
    result['deleted'] = 'N'

    if not skip_tombstone:
        result = tombstone_missing_dep_ids(result, valid_date)

    out_path = os.path.join(OUT_DIR, 'team_refer.csv')
    merged = write_merged(out_path, result, TABLE_KEYS['team_refer'])

    print(f'[OK]   team_refer.csv 저장 (이번 업로드 {len(result)}행 반영, 누적 총 {len(merged)}행)')
    return True


if __name__ == '__main__':
    process()
