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
  {업적 연도}_first_half_grade, {업적 연도}_second_half_grade × 3
점수(score) 컬럼은 두지 않는다(사용자 확정 — 어차피 다운스트림에서 안 씀).
"""

from datetime import date, datetime

SALARY_GRADES = ('가', '나', '다', '라', '마')
HALF_GRADES = ('EM', 'ES', 'MT')


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
    """상/하반기업적 두 자리를 "{첫자리}/{둘째자리}"로 — 값이 없는 자리는
    '-'로 채운다(둘 다 없으면 '-/-'). 자리를 항상 유지해 어느 반기가
    비어있는지 헷갈리지 않게 한다."""
    first_half = (first_half or '').strip()
    second_half = (second_half or '').strip()
    return f"{first_half or '-'}/{second_half or '-'}"


def format_half_display(salary_grade: str, first_half: str, second_half: str) -> str:
    """엑셀 다운로드의 "평가" 컬럼 둘째 줄(연도별 반기 표기)에 쓰는 조각 —
    format_evaluation_cell()과 같은 판단이지만, 연봉등급 부분은 첫째 줄에
    이미 따로 있으므로 괄호 안에 들어갈 반기 부분만 돌려준다.
      - 연봉등급이 있으면: 있는 반기만 이어붙임(둘 다 없으면 '-') — 예:
        연봉등급 O/상반기 X/하반기 O → "EM"(하반기만, '-' 없이).
      - 연봉등급이 없으면: format_half_pair()로 반기 두 자리를 항상 표시
        (없는 자리는 '-', 예: "-/MT") — 이 경우는 그대로 유지(사용자 확정,
        연봉등급이 있을 때만 '표시하지 말아달라'는 요청)."""
    salary_grade = (salary_grade or '').strip()
    first_half = (first_half or '').strip()
    second_half = (second_half or '').strip()

    if salary_grade:
        halves = '/'.join(h for h in (first_half, second_half) if h)
        return halves if halves else '-'
    return format_half_pair(first_half, second_half)


def format_evaluation_cell(salary_grade: str, first_half: str, second_half: str) -> str:
    """한 해(연봉등급 연도 기준)의 평가를 한 셀 표기로 합성한다.
      - 연봉등급이 있으면: "{연봉등급}({있는 반기만 이어붙임})" — 반기가 둘 다
        없으면 괄호 없이 연봉등급만("다").
      - 연봉등급이 없으면: format_half_pair()로 반기 두 자리를 항상 표시
        (없는 자리는 '-', 예: "-/MT")."""
    salary_grade = (salary_grade or '').strip()
    first_half = (first_half or '').strip()
    second_half = (second_half or '').strip()

    if salary_grade:
        halves = '/'.join(h for h in (first_half, second_half) if h)
        return f'{salary_grade}({halves})' if halves else salary_grade
    return format_half_pair(first_half, second_half)
