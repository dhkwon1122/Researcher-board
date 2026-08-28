"""
대량 소급 백필용 파일명 규칙 — "관리자 지정 시점" 그룹(evaluations/
tech_ownership/core_technology/work_objective_24~26, 2026-08-28 참고)은
원본 파일 자체에 시점 컬럼이 없어, 한 번에 파일 1개 + 관리자가 고른 날짜
1개만 반영할 수 있었다. 여러 달치를 한꺼번에 올리고 싶을 때는, 파일명
끝에 "_YYYYMM"을 붙여서 그 파일이 어느 시점 기준인지 파일명 자체에서
알 수 있게 한다(예: "T&P 기본 인사 정보_202305.xlsx", "보유기술_202305.xlsx").

원본 엑셀 내용은 건드리지 않고 파일명만 규칙에 맞게 바꿔서 여러 개를
한 번에 올리면, services/web_pipeline_runner.py가 이 규칙으로 각 파일의
기준 연/월을 알아내 순서대로(오래된 시점부터) 각각 반영한다.
"""

import re
from datetime import date

# 확장자 바로 앞의 "_YYYYMM" — 연도 4자리(2000~2099) + 월 2자리(01~12).
_SUFFIX_RE = re.compile(r'_(\d{4})(\d{2})(?=\.[^.]+$)')


def parse_backfill_date(filename: str) -> date | None:
    """파일명에서 "_YYYYMM" 접미사를 찾아 그 달 1일을 date로 반환한다.
    접미사가 없거나 연/월 값이 말이 안 되면(월이 1~12를 벗어나는 등) None —
    이 경우 "백필 대상이 아닌 일반 업로드 파일"로 취급된다."""
    m = _SUFFIX_RE.search(filename or '')
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    if not (1 <= month <= 12) or not (2000 <= year <= 2099):
        return None
    return date(year, month, 1)
