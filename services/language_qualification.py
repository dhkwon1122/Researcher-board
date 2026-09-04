"""
어학자격(language_qualification.csv) 관련 공용 표시 로직 — 연구원 프로필
화면·A4 인쇄 카드(components/profile_sections.py)와 엑셀 다운로드
(services/researcher_profile_export.py) 양쪽에서 같은 표기 규칙을 쓰기
위해 한 곳으로 모았다(services/evaluations.py와 동일한 목적).

원본 파일 처리·저장 규칙은 pipeline/process_language_qualification.py
참고 — 이 모듈은 이미 저장된 language_qualification.csv를 사람별로
읽어 표시 문자열로 조립하는 역할만 한다.
"""

import re

import pandas as pd

from services import data_store


def read_rows(researcher_id: str) -> list[dict]:
    """한 연구원의 어학자격 행(언어별 1행)을 원본 파일에 등장한 순서대로
    반환한다(정렬은 pipeline 쪽에서 researcher_id, language 기준으로 이미
    돼 있어 특별히 재정렬하지 않음)."""
    df = data_store.read_processed('language_qualification')
    if df.empty or 'researcher_id' not in df.columns:
        return []
    rows = df[df['researcher_id'] == researcher_id]
    return rows.to_dict('records')


def _clean_str(val) -> str:
    """read_processed()로 CSV를 읽을 때 그 컬럼에 빈 셀이 섞여 있으면
    pandas가 컬럼 전체를 float로 추론해 빈 값이 float('nan')이 되고,
    str(nan)이 문자열 "nan"이 되어(파이썬에서 NaN은 참으로 평가되므로
    `or ''` 처리로는 안 걸러짐) 그대로 "nan"으로 새어나갈 수 있다
    (services/work_experience.py에서 근무경력이 "nan( ~ , nan)"으로
    새던 것과 동일한 문제, 2026-09-03 — 여기 language/speak_grade는
    실제로는 파이프라인이 항상 채워서 저장하지만, 만료일과 동일한
    가드를 예방적으로 함께 적용)."""
    s = str(val).strip() if val is not None else ''
    return '' if s.lower() in ('', 'nan', 'none', 'nat') else s


_DATE_ONLY_RE = re.compile(r'^(\d{4}-\d{2}-\d{2})(?:[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?)?$')


def _clean_date(val) -> str:
    """만료일처럼 날짜만 필요한 값에서 시분초를 뗀다. pipeline/
    process_language_qualification.py가 excel_reader.parse_flexible_date()로
    저장하는데, 그 함수는 pandas Timestamp 표현 범위(~2262년)를 벗어나는
    "9999-12-31"류 "영구/만료없음" sentinel 날짜를 만나면(예외 발생 시
    원본 문자열 그대로 반환) 시분초까지 포함된 "9999-12-31 00:00:00"을
    그대로 저장할 수 있었다(2026-09-03 확인 — pipeline 쪽 근본 원인은
    excel_reader.py에서 함께 수정). 이미 그렇게 저장된 CSV도 파이프라인
    재실행 없이 바로 정상 표시되도록, 여기서도 한 번 더 날짜 부분만
    뽑아낸다."""
    s = _clean_str(val)
    if not s:
        return ''
    m = _DATE_ONLY_RE.match(s)
    return m.group(1) if m else s


def format_lines(rows: list[dict]) -> list[str]:
    """행 목록을 "{언어} {등급}(만료일 {날짜})" 문자열 리스트로 변환한다.
    만료일이 없으면 그 부분을 생략한다(예: "영어 2등급")."""
    lines = []
    for r in rows:
        language = _clean_str(r.get('language'))
        grade = _clean_str(r.get('speak_grade'))
        if not language or not grade:
            continue
        expiration = _clean_date(r.get('expiration_date'))
        line = f'{language} {grade}'
        if expiration:
            line += f'(만료일 {expiration})'
        lines.append(line)
    return lines


def format_block(researcher_id: str, *, label: str = '어학') -> str | None:
    """프로필 화면/인쇄 카드에 쓰는 "어학 : {첫 줄}\\n{둘째 줄}..." 형태의
    한 덩어리 텍스트. 어학 데이터가 전혀 없으면 None(호출부가 그 줄
    자체를 렌더링하지 않도록 — 재직상태처럼 값 없으면 조용히 생략)."""
    lines = format_lines(read_rows(researcher_id))
    if not lines:
        return None
    first, *rest = lines
    text = f'{label} : {first}'
    if rest:
        text += '\n' + '\n'.join(rest)
    return text
