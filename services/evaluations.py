"""
평가(evaluations.csv) 관련 공용 로직 — 회계연도 계산과 셀 서식을
pipeline(process_tp_evaluation.py)과 화면·엑셀(researcher_profile_export.py,
components/profile_sections.py, pages/researcher_list.py) 양쪽에서 동일하게
쓰기 위해 한 곳으로 모았다. 어느 한쪽만 고치고 다른 쪽을 깜빡하는 걸 막기 위함
(사용자 확정: 두 쪽 모두 같은 서식 규칙 적용).

회계연도: 매년 3월 시작 — 예) 2026-01(1월)은 아직 2025 회계연도
(2025-03~2026-02), 2026-03(3월)부터 2026 회계연도로 넘어간다.
  - 연봉등급 3개년 = [FY, FY-1, FY-2]
  - 상/하반기업적 3개년 = [FY-1, FY-2, FY-3]
    (그 해 연봉등급은 전년도 업적 평가를 반영하므로 항상 연봉등급 연도 - 1)

evaluations.csv 스키마(wide, researcher_id당 1행):
  researcher_id,
  {연봉등급 연도}_salary_grade × 3,
  {업적 연도}_first_half_grade, {업적 연도}_second_half_grade
점수(score) 컬럼은 두지 않는다(사용자 확정 — 어차피 다운스트림에서 안 씀).
역량(competency_grade)은 2026-09-09부로 원본처리에서 완전히 제외한다
(사용자 확정 — 상/하반기업적만 남김).

값 표기: 연봉등급(SALARY_GRADES)만 허용값을 제한한다. 상/하반기업적은
원본 파일에 실제로 어떤 표기 체계가 쓰였는지(EM/ES/MT뿐 아니라 T/MS/NM/
VG/EX/GD/NG 등 과거 체계가 섞여 있을 수 있음)가 이 코드가 알 수 있는
범위 밖이라, 공백만 정리하고 값 자체는 원본 그대로 저장한다(2026-08-29
사용자 확정 — 예전엔 EM/ES/MT로 제한해 그 밖의 값을 전부 비웠었다).

서식 규칙(2026-09-09 확정, format_evaluation_cell()/format_half_display()
공통 — is_exception은 evaluation_exception.csv(researcher_id 목록)에
등록된 사람인지 여부):
  1) 연봉등급 있음 → "{연봉등급}({하반기업적})", 하반기업적 없으면
     연봉등급만("다"). 상반기업적은 이 분기에서 아예 쓰지 않는다.
  2) 연봉등급 없고 예외자 아님 → "{상반기업적 또는 '-'}/{하반기업적 또는
     '-'}", 단 둘 다 없으면 "-/-"가 아니라 "-" 하나만.
  3) 연봉등급 없고 예외자 → 하반기업적만("MT"), 없으면 "-".
"""

from datetime import date, datetime

SALARY_GRADES = ('가', '나', '다', '라', '마')


def current_fiscal_year(today: date | None = None) -> int:
    today = today or datetime.now().date()
    return today.year if today.month >= 3 else today.year - 1


def evaluation_years(today: date | None = None) -> tuple[list[int], list[int]]:
    """(연봉등급 3개년, 상/하반기업적 3개년) — 둘 다 내림차순(최신 연도 먼저)."""
    fy = current_fiscal_year(today)
    return [fy, fy - 1, fy - 2], [fy - 1, fy - 2, fy - 3]


def salary_grade_column(year: int) -> str:
    return f'{year}_salary_grade'


def first_half_column(year: int) -> str:
    return f'{year}_first_half_grade'


def second_half_column(year: int) -> str:
    return f'{year}_second_half_grade'


def format_half_pair(first_half: str, second_half: str) -> str:
    """연봉등급 없고 예외자도 아닌 경우의 상/하반기업적 두 자리 —
    "{첫자리}/{둘째자리}"(값이 없는 자리는 '-'), 단 둘 다 없으면 "-/-"가
    아니라 "-" 하나만 돌려준다(2026-09-09 확정)."""
    first_half = (first_half or '').strip()
    second_half = (second_half or '').strip()
    if not first_half and not second_half:
        return '-'
    return f"{first_half or '-'}/{second_half or '-'}"


def format_half_display(salary_grade: str, first_half: str, second_half: str,
                         is_exception: bool = False) -> str:
    """엑셀 다운로드의 "평가" 컬럼 둘째 줄(연도별 반기 표기)에 쓰는 조각 —
    format_evaluation_cell()과 같은 판단이지만, 연봉등급 부분은 첫째 줄에
    이미 따로 있으므로 괄호 안에 들어갈 부분만 돌려준다."""
    return format_evaluation_cell(salary_grade, first_half, second_half, is_exception)


def format_evaluation_cell(salary_grade: str, first_half: str, second_half: str,
                            is_exception: bool = False) -> str:
    """한 해(연봉등급 연도 기준)의 평가를 한 셀 표기로 합성한다(2026-09-09
    확정, 모듈 독스트링의 서식 규칙 1)~3) 참고):
      1) 연봉등급 있음 → "{연봉등급}({하반기업적})", 하반기업적 없으면
         연봉등급만.
      2) 연봉등급 없고 예외자 아님 → format_half_pair()로 상/하반기업적
         두 자리(둘 다 없으면 "-" 하나).
      3) 연봉등급 없고 예외자 → 하반기업적만, 없으면 "-"."""
    salary_grade = (salary_grade or '').strip()
    first_half = (first_half or '').strip()
    second_half = (second_half or '').strip()

    if salary_grade:
        return f'{salary_grade}({second_half})' if second_half else salary_grade
    if is_exception:
        return second_half or '-'
    return format_half_pair(first_half, second_half)
