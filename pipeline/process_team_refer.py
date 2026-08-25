"""
팀참조시트(조직 계층 구조 + 각 조직 단위 책임자 정보) 처리 모듈

원천 파일: data/raw/팀참조시트.xlsx (헤더: 절대 2행, header_row=1)
출력 파일: data/processed/team_refer.csv

한 행 = 하나의 조직 단위(조직도의 노드 하나)이며, 그 조직 단위 책임자(부서장)의
사번/성명/직책이 함께 표기되어 있다 — 연구원별 1행이 아니라 조직 단위별 1행이다.

컬럼명 매핑(엑셀 헤더명 → 위치와 무관하게 이름으로 찾아 변환):
  비공식소속부서명 → org_name_wd     researchers.csv의 org_code와 매핑되는 조직 단위 키
  구분             → work_type       "R&D"인 행만 보유 전문성 분석 대상
                                     (process_researcher_expertise.py._filter_eligible_researchers)
  부서             → dep_name        "연구원 명단" 화면 부서 검색 필터의 표시값 — 조직도
                                     트리 구조(dep_id/upper_dep_id)와는 무관한 평면 태그
  과제/파트         → pjt_part_name   조직도에 표시할 명칭. 트리 노드 라벨은 이 값만 사용한다
                                     (rd_specialist_markdown.org_tree_html) — dep_name은
                                     트리 라벨에 관여하지 않는다.
  조직 레벨         → team_layer      조직도 깊이(1~4). 비어 있으면 조직도에 표시되지 않는
                                     행이므로 제외한다.
  사번             → researcher_id   해당 조직 단위 책임자(부서장) 사번
  성명             → name            해당 조직 단위 책임자 성명
  직책             → assignment_name 해당 조직 단위 책임자 직책 (예: PL/본부장/파트장)
  조직코드          → dep_code        조직도 상 같은 부모 아래 형제 노드의 표시 순서 코드
                                     (구 code3와 동일한 값)
  부서ID           → dep_id          이 조직 단위 고유 ID
  상위부서ID        → upper_dep_id    상위 조직 단위의 dep_id (없으면 최상위 조직)

dep_id/upper_dep_id는 rd_specialist_markdown.build_org_tree()가 조직도 부모-자식
관계를 판단하는 기준이다(파일에 적힌 행 순서와 무관하게 정확한 계층을 구성).

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
고쳐도 나머지는 각자 마지막 저장 시점 값 그대로 정상 노출된다. 행 삭제는 실제로
지우지 않고 deleted='Y' 표시가 붙은 새 날짜 행을 남기는 방식으로 처리한다(그
dep_id의 최신 상태가 곧 "삭제됨"이 되게 — 과거 이력은 그대로 보존).

이 모듈의 process()(xlsx 일괄 업로드)는 항상 deleted='N'으로 저장하고,
valid_date 인자(기본값 오늘)로 유효 날짜를 지정할 수 있다 — 과거 데이터를
소급 입력해도, 실제로 그 날짜가 해당 dep_id의 최신이 아니면 "현재" 조직도에는
반영되지 않는다("현재" 판정은 항상 실제 최댓값 기준).

컬럼명이 다를 경우 파일 상단의 _COL_MAP을 실제 헤더에 맞게 수정하세요.
"""

import os
import sys
from datetime import date

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR, OUT_DIR  # noqa: E402
from excel_reader import clean_str as _clean, is_blank, norm_id, read_xlsx  # noqa: E402
from merge_utils import TABLE_KEYS, write_merged  # noqa: E402

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


def _clean_id(val) -> str:
    """dep_id/upper_dep_id 값을 정규화. 엑셀이 숫자로 읽어 100.0 처럼 실수형으로
    들어오면 '100'으로 맞추고, 문자/숫자 혼합 코드(예: ORG01)는 그대로 둔다."""
    s = _clean(val)
    if not s:
        return ''
    try:
        f = float(s)
    except ValueError:
        return s
    return str(int(f)) if f.is_integer() else s

# ── 컬럼명 매핑(엑셀 헤더명 → 출력 컬럼명) — 순서 무관, 이름으로 찾아 변환 ──────
_COL_MAP = {
    '비공식소속부서명': 'org_name_wd',
    '구분': 'work_type',
    '부서': 'dep_name',
    '과제/파트': 'pjt_part_name',
    '조직 레벨': 'team_layer',
    '사번': 'researcher_id',
    '성명': 'name',
    '직책': 'assignment_name',
    '조직코드': 'dep_code',
    '부서ID': 'dep_id',
    '상위부서ID': 'upper_dep_id',
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
    """레코드 리스트(엑셀 헤더명을 키로 쓰는 dict — xlsx 일괄 업로드의
    df.to_dict('records')든, 관리자 화면 그리드의 행이든 동일한 형태)를
    _COL_MAP 기준으로 컬럼 매핑 + 정제해 표준 스키마(영문 컬럼명)
    DataFrame으로 변환한다. 조직 레벨(team_layer)이 없거나 dep_id가 없는
    행은 조직도에 나타날 수 없고 누적 자연키도 만들 수 없으므로 제외한다.
    valid_year/valid_month/valid_day/deleted는 이 함수가 붙이지 않는다 —
    호출부가 stamp_valid_date()로 붙인다(저장 시점을 여기서 강제하지
    않기 위함)."""
    df = pd.DataFrame(records)
    for col in _COL_MAP:
        if col not in df.columns:
            df[col] = ''

    result = pd.DataFrame({
        out_col: df[src_col].apply(_clean)
        for src_col, out_col in _COL_MAP.items()
    })
    result['researcher_id'] = result['researcher_id'].apply(norm_id)
    result['team_layer'] = df['조직 레벨'].apply(_clean_int)  # '1.0' 같은 실수형 표기 정리
    result['dep_id'] = df['부서ID'].apply(_clean_id)
    result['upper_dep_id'] = df['상위부서ID'].apply(_clean_id)

    return result[(result['team_layer'] != '') & (result['dep_id'] != '')].reset_index(drop=True)


def process(valid_date: date | None = None) -> bool:
    """valid_date: 이번 업로드분의 유효 날짜(기본값 오늘) — 과거 데이터
    소급 입력 시 지정."""
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

    result = build_rows_from_records(df.to_dict('records'))
    result = stamp_valid_date(result, valid_date or date.today())
    result['deleted'] = 'N'

    out_path = os.path.join(OUT_DIR, 'team_refer.csv')
    merged = write_merged(out_path, result, TABLE_KEYS['team_refer'])

    print(f'[OK]   team_refer.csv 저장 (이번 업로드 {len(result)}행 반영, 누적 총 {len(merged)}행)')
    return True


if __name__ == '__main__':
    process()
