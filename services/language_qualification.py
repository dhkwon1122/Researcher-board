"""
어학자격(language_qualification.csv) 관련 공용 표시 로직 — 연구원 프로필
화면·A4 인쇄 카드(components/profile_sections.py)와 엑셀 다운로드
(services/researcher_profile_export.py) 양쪽에서 같은 표기 규칙을 쓰기
위해 한 곳으로 모았다(services/evaluations.py와 동일한 목적).

원본 파일 처리·저장 규칙은 pipeline/process_language_qualification.py
참고 — 이 모듈은 이미 저장된 language_qualification.csv를 사람별로
읽어 표시 문자열로 조립하는 역할만 한다.
"""

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


def format_lines(rows: list[dict]) -> list[str]:
    """행 목록을 "{언어} {등급}(만료일 {날짜})" 문자열 리스트로 변환한다.
    만료일이 없으면 그 부분을 생략한다(예: "영어 2등급")."""
    lines = []
    for r in rows:
        language = str(r.get('language', '') or '').strip()
        grade = str(r.get('speak_grade', '') or '').strip()
        if not language or not grade:
            continue
        expiration = str(r.get('expiration_date', '') or '').strip()
        expiration = '' if expiration.lower() in ('', 'nan', 'none', 'nat') else expiration
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
