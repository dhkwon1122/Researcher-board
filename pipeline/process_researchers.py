"""
연구원 기본 정보 처리 모듈

원천: 기본은 source_reader.read_source('researchers')
  → DB researchers_stg 테이블 또는 data/raw_csv/researchers.csv
  (1단계 xlsx_to_raw_csv.py가 data/raw/인력현황.xlsx를 DRM 제거해 만든 사본)
  raw_dir이 명시적으로 오버라이드되면(예: data/web_updates/<key>) 그 폴더의
  인력현황.xlsx를 직접 읽는다 — 아래 참고.
출력 파일: data/processed/researchers.csv, data/processed/researchers_history.csv

읽는 컬럼:
  사원번호, 성명, 현소속부서명, CL, 비공식소속부서명, 직무, 4직종,
  국적, 근속 기준일_그룹입사일(YYYYMMDD), 법적생년월일성별, 성별,
  승격산정기준일자, Knox ID, 인원실적년도, 인원실적월, 재직상태명

계산 항목:
  birth_date    : 법적생년월일성별 앞 6자리(YYMMDD) → YYYY-MM-DD로 변환
  birth_year    : birth_date의 연도(파싱 실패 시 빈 값)
  age           : 올해연도 - birth_year  (표시 전용, CSV에는 저장 안 함)
  hire_date     : 근속 기준일_그룹입사일 (원본 YYYYMMDD → YYYY-MM-DD로 변환)
  tenure        : (오늘 - hire_date).days / 365, 소수 첫째자리 (표시 전용)
  promotion_date: 승격산정기준일자 (YYYY-MM-DD)
  position_year : ceil((2027-03-01 - promotion_date).days / 365) (표시 전용)
  valid_year    : 인원실적년도 (YYYY, 4자리)
  valid_month   : 인원실적월   (MM, 2자리 제로패딩)
  employment_status: 재직상태명 원본 그대로(휴직/재직/퇴직 등) — is_current(최신
                    인력현황 파일에 있었는지 여부, 위 참고)와는 별개 개념이다.
                    예: 휴직 중인 사람도 이번 달 인력현황엔 있으므로 is_current='Y'
                    이면서 employment_status='휴직'일 수 있다.

컬럼명이 다를 경우 파일 상단의 COL_* 상수를 수정하세요.

── 데이터 적재 방식(업서트) ────────────────────────────────────────────────
매 실행마다 전량 덮어쓰지 않는다. researchers.csv는 researcher_id 기준
업서트다 — 이번 파일에 있는 사람은 행 전체를 최신값으로 교체하고, 이번
파일에 없는 사람(전배·퇴사 등)은 이전 행을 그대로 보존한다(삭제하지 않음).

researchers.csv에 병합된 뒤, 파일 전체에서 (valid_year, valid_month)의
최댓값(가장 최근 인원실적월)을 구해 각 행에 is_current(Y/N)를 다시 계산해
채운다 — 그 행의 (valid_year, valid_month)가 전체 최신월과 같으면 'Y'
(현재 소속), 다르면(더 과거면) 'N'(현재 미소속: 이번 달 인력현황에 없었다는
뜻 — 전배/퇴사를 구분하진 못하지만 "지금 우리 조직 소속이 아님"은 알 수
있다). valid_year/valid_month가 비어 있는 행(구버전 데이터, 또는 원본에
인원실적년도/월 컬럼이 없는 경우)은 판단 근거가 없으므로 항상 'Y'로 둔다.

researchers_history.csv는 별도로 (researcher_id, valid_year, valid_month)
키로 계속 누적된다(같은 키는 교체, 다른 키는 새 행 추가, 절대 삭제하지
않음) — "누적기준" 검색(한 번이라도 등록된 적 있는 전체 인원, 월별 스냅샷)
전용이며, 다른 화면(명단/조직도/JOB Market/AI 검색 등)은 계속 researchers.csv
(=현재 상태 1인 1행)만 그대로 사용하면 되므로 이 파일이 생겨도 영향받지
않는다.

raw_dir 인자로 원본 위치를 바꿀 수 있다 — 기본은 data/raw(최초 적재),
그 외 폴더(예: 관리자 웹 "데이터 업데이트" 탭이 쓰는 data/web_updates/<key>)를
넘기면 그 폴더의 파일로 업서트만 수행한다.
"""

import csv
import math
import os
import sys
from datetime import date, datetime

import pandas as pd

RESEARCHERS_PATTERNS = ['*That Month Headcount*.xlsx', '*End of Month Headcount*.xlsx']
_RESEARCHERS_HEADER_ROW = 1  # sources.py 매니페스트 기준 (2번째 행)

# ── 컬럼명 설정 (파일 헤더와 다를 경우 여기서 수정) ──────────────────────────
COL_ID         = '사원번호'
COL_NAME       = '성명'
COL_DEPT       = '현소속부서명'
COL_POSITION   = 'CL'
COL_ORG        = '비공식소속부서명'
COL_JOB        = '직무'
COL_JOB_TYPE   = '4직종'
COL_NATION     = '국적'
COL_HIRE_DATE  = '근속 기준일_그룹입사일'
COL_BIRTH_SEX  = '법적생년월일성별'
COL_GENDER     = '성별'
COL_PROMO_DATE = '승격산정기준일자'
COL_KNOX       = 'Knox ID'
COL_VALID_YEAR  = '인원실적년도'
COL_VALID_MONTH = '인원실적월'
COL_EMPLOYMENT_STATUS = '재직상태명'
# 직급연차 기준일 (2027-03-01)
POSITION_YEAR_REF = date(2027, 3, 1)

# CL 컬럼(COL_POSITION) 원본 값 중 영문 임원/특별 직책 표기를 한글로 통일
# (그 외 값, 예: CL1~CL6은 원본 그대로 사용 — 사용자 확정 매핑).
POSITION_LABEL_MAP = {
    'Corporate VP': '상무',
    'Corporate President': '사장',
    'Senior Advisor': '고문',
    'Corporate EVP': '부사장',
}
# ─────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR, OUT_DIR  # noqa: E402
from excel_reader import is_blank, read_xlsx, norm_id  # noqa: E402
from merge_utils import TABLE_KEYS, read_existing, write_merged_with_valid_period  # noqa: E402
from source_files import find_latest  # noqa: E402
from source_reader import read_source  # noqa: E402


def _parse_date(val) -> date | None:
    """날짜 셀을 date 객체로 변환. 실패 시 None."""
    if val is None:
        return None
    if isinstance(val, (date, datetime)):
        return val.date() if isinstance(val, datetime) else val
    s = str(val).strip()
    if is_blank(s):
        return None
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d', '%Y%m%d'):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _date_str(d: date | None) -> str:
    return d.strftime('%Y-%m-%d') if d else ''


def _parse_birth_date(birth_sex: str) -> date | None:
    """법적생년월일성별 앞 6자리(YYMMDD)를 생년월일로 변환한다(원본 확인 결과
    6자리 전체가 생년월일 — 성별은 뒤에 붙는 게 아니라 COL_GENDER 원본 컬럼을
    따로 읽는다). 연도는 birth_year와 같은 규칙(26 이상 → 1900+, 미만 →
    2000+). 6자리 숫자가 아니거나 실제 날짜로 성립하지 않으면(예: 13월,
    32일) None."""
    s = str(birth_sex or '').strip()
    if len(s) < 6 or not s[:6].isdigit():
        return None
    yy, mm, dd = int(s[0:2]), int(s[2:4]), int(s[4:6])
    year = (1900 + yy) if yy >= 26 else (2000 + yy)
    try:
        return date(year, mm, dd)
    except ValueError:
        return None


def _valid_year_str(val) -> str:
    s = str(val).strip()
    if is_blank(s) or s.lower() == 'nan':
        return ''
    s = s.split('.')[0]  # 엑셀이 숫자를 float로 읽었을 때 '2026.0' 방지
    digits = ''.join(ch for ch in s if ch.isdigit())
    return digits[:4] if len(digits) >= 4 else ''


def _valid_month_str(val) -> str:
    s = str(val).strip()
    if is_blank(s) or s.lower() == 'nan':
        return ''
    s = s.split('.')[0]
    digits = ''.join(ch for ch in s if ch.isdigit())
    if not digits:
        return ''
    try:
        m = int(digits)
    except ValueError:
        return ''
    return f'{m:02d}' if 1 <= m <= 12 else ''


def _compute_is_current(df: pd.DataFrame) -> pd.DataFrame:
    """전체 파일에서 가장 최근 (valid_year, valid_month)를 찾아, 각 행이 그
    최신월과 같으면 'Y', 다르면(비어있지 않은 채 더 과거면) 'N'을 채운다.
    valid_year/valid_month가 비어 있는 행은 판단 근거가 없으므로 'Y'."""
    df = df.copy()
    if 'valid_year' not in df.columns or 'valid_month' not in df.columns:
        df['is_current'] = 'Y'
        return df

    def _period(row):
        y, m = row['valid_year'], row['valid_month']
        if not y or not m:
            return None
        try:
            return (int(y), int(m))
        except ValueError:
            return None

    periods = df.apply(_period, axis=1)
    valid_periods = periods.dropna()
    if valid_periods.empty:
        df['is_current'] = 'Y'
        return df

    latest = valid_periods.max()
    df['is_current'] = periods.apply(lambda p: 'Y' if (p is None or p == latest) else 'N')
    return df


def process(raw_dir: str = RAW_DIR) -> bool:
    if raw_dir == RAW_DIR:
        df = read_source('researchers')
        if df is None:
            print('[SKIP] researchers 원천 데이터 없음 '
                  '(DB researchers_stg 또는 data/raw_csv/researchers.csv) — researchers_raw 폴백 시도')
    else:
        raw_path = find_latest(raw_dir, RESEARCHERS_PATTERNS)
        if raw_path is not None:
            df = read_xlsx(raw_path, header_row=_RESEARCHERS_HEADER_ROW)
        else:
            df = None
            print(f'[SKIP] {RESEARCHERS_PATTERNS} 파일 없음({raw_dir}) — researchers_raw 폴백 시도')

    if df is None:
        return False
    # 컬럼명 좌우 공백 제거 (탭 포함)
    df.columns = [str(c).strip() for c in df.columns]

    required = [COL_ID, COL_NAME]
    for col in required:
        if col not in df.columns:
            print(
                f'[ERROR] 필수 컬럼 없음: [{col}]\n'
                f'  process_researchers.py 상단의 COL_* 상수를 실제 헤더에 맞게 수정하세요.\n'
                f'  현재 파일 헤더: {list(df.columns)}'
            )
            return False

    rows = []
    for _, row in df.iterrows():
        rid = norm_id(row.get(COL_ID))
        if not rid:
            continue

        # 생년월일: 법적생년월일성별 앞 6자리(YYMMDD) 전체를 파싱(_parse_birth_date
        # 참고) — 실패하면(형식이 다르거나 날짜가 아니면) birth_year도 함께 빈 값.
        birth_sex = str(row.get(COL_BIRTH_SEX, '')).strip()
        birth_dt = _parse_birth_date(birth_sex)
        birth_year = birth_dt.year if birth_dt else ''

        # 입사일 (근속기준일)
        hire_dt = _parse_date(row.get(COL_HIRE_DATE))

        # 승격산정기준일
        promo_dt = _parse_date(row.get(COL_PROMO_DATE))

        position_raw = str(row.get(COL_POSITION, '')).strip()
        rows.append({
            'researcher_id':   rid,
            'name':            str(row.get(COL_NAME, '')).strip(),
            'department':      str(row.get(COL_DEPT, '')).strip(),
            'org_code':        str(row.get(COL_ORG, '')).strip(),
            'position':        POSITION_LABEL_MAP.get(position_raw, position_raw),
            'job_function':    str(row.get(COL_JOB, '')).strip(),
            'job_type':        str(row.get(COL_JOB_TYPE, '')).strip(),
            'nationality':     str(row.get(COL_NATION, '')).strip(),
            'gender':          str(row.get(COL_GENDER, '')).strip(),
            'birth_year':      birth_year,
            'birth_date':      _date_str(birth_dt),
            'hire_date':       _date_str(hire_dt),
            'promotion_date':  _date_str(promo_dt),
            'knox_id':         str(row.get(COL_KNOX, '')).strip(),
            'employment_status': str(row.get(COL_EMPLOYMENT_STATUS, '')).strip(),
            'valid_year':      _valid_year_str(row.get(COL_VALID_YEAR)),
            'valid_month':     _valid_month_str(row.get(COL_VALID_MONTH)),
        })

    result = pd.DataFrame(rows)
    result = result[result['researcher_id'] != ''].reset_index(drop=True)
    # researcher_id로만 정렬하면 안 된다 — 이제 원본이 여러 헤드카운트 다운로드
    # 파일을 합친 것일 수 있어(예: 이번 달 + 지난 달 파일이 동시에 존재), 같은
    # researcher_id가 valid_year/valid_month가 다른 여러 행으로 나타날 수 있다.
    # write_merged()의 업서트가 "같은 키가 중복되면 마지막 행 채택"이므로,
    # valid_year/valid_month를 오름차순 보조키로 둬서 각 사람의 가장 최근
    # 기간 행이 항상 마지막에 오게 만든다(파일명이 아니라 내부 데이터 기준 —
    # 사용자 확정, pipeline/sources.py docstring 참고).
    result = result.sort_values(['researcher_id', 'valid_year', 'valid_month']).reset_index(drop=True)

    os.makedirs(OUT_DIR, exist_ok=True)

    # 1) researchers.csv — researcher_id 업서트 + 시점(valid_year/valid_month) 보호
    #    (evaluations/tech_ownership/job_profile/work_objective와 동일한 이유 —
    #    옛날 헤드카운트 파일을 나중에 실수로 재업로드해도 이미 저장된 더 최근
    #    값이 조용히 덮어써지지 않게 한다. 이 테이블은 admin이 날짜를 따로
    #    지정할 필요가 없다 — 원본 컬럼(인원실적년도/월)에서 행마다 이미
    #    valid_year/valid_month를 추출해뒀으므로 그걸 그대로 시점 키로 쓴다.
    #    write_merged_with_valid_period()가 researchers_history.csv 저장까지
    #    함께 처리한다(건너뛴 사람 포함 전체가 이력에는 그대로 쌓임).
    out_path = os.path.join(OUT_DIR, 'researchers.csv')
    hist_path = os.path.join(OUT_DIR, 'researchers_history.csv')
    outcome = write_merged_with_valid_period(
        out_path, hist_path, result, TABLE_KEYS['researchers'], TABLE_KEYS['researchers_history'])

    # is_current는 "현재상태" 파일 전체를 다시 읽어 재계산(건너뛴 사람의 기존
    # 행도 포함해 전체 최신월 기준으로 판단해야 하므로 outcome이 아니라 파일을
    # 다시 읽는다).
    merged = read_existing(out_path)
    merged = _compute_is_current(merged)
    merged.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)

    n_current = (merged['is_current'] == 'Y').sum()
    n_not_current = (merged['is_current'] == 'N').sum()
    print(f'[OK]   researchers.csv 저장 (총 {len(merged)}명 중 이번 파일 {outcome["updated_rows"]}명 반영, '
          f'현재 소속 {n_current}명, 미소속 {n_not_current}명)')
    if outcome['skipped']:
        print(f'  [WARN] {len(outcome["skipped"])}명은 기존 저장된 값이 더 최신이라 건너뜀:')
        for s in outcome['skipped'][:10]:
            print(f'    · {s["researcher_id"]}: 기존 {s["existing_period"]} > 이번 {s["new_period"]}')
        if len(outcome['skipped']) > 10:
            print(f'    · 외 {len(outcome["skipped"]) - 10}명')

    print(f'[OK]   researchers_history.csv 저장 (누적 {len(read_existing(hist_path))}행)')

    return True


if __name__ == '__main__':
    process()
