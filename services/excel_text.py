"""엑셀(openpyxl) 셀에 쓸 수 없는 제어문자 제거(2026-10-14).

원천 데이터(특허/논문 제목 등)에 섞인 보이지 않는 제어문자(\\x00~\\x1f 중 탭·줄바꿈 제외)가 있으면
openpyxl이 IllegalCharacterError를 내 엑셀 다운로드 전체가 실패한다. 셀에 쓰기 직전에 이 함수로 거른다.
"""
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE


def excel_safe(value):
    """문자열이면 엑셀 금지 문자를 지운 값, 그 외(숫자/None 등)는 그대로."""
    if isinstance(value, str):
        return ILLEGAL_CHARACTERS_RE.sub('', value)
    return value
