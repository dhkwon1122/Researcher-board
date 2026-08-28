"""
근무 경력(work_experience.csv) 관련 공용 표시 로직 — 연구원 프로필
화면·A4 인쇄 카드(components/profile_sections.py)와 엑셀 다운로드
(services/researcher_profile_export.py) 양쪽에서 같은 표기 규칙을 쓰기
위해 한 곳으로 모았다(services/language_qualification.py와 동일한 목적).

표시 형식(사용자 확정, 2026-08-29): "{회사명}({시작'YY.MM} ~ {종료'YY.MM},
{직무명})" — 예) "Cornell Univ.('04.02 ~ '07.12, Post Doc.)". 종료일이
없으면 "현재"로 채우지 않고 그냥 공란으로 둔다(예: "Samsung('08.01 ~ ,
Researcher)").

원본 파일 처리·저장(researcher_id 단위 그룹 교체) 규칙은
pipeline/process_work_experience.py 참고 — 이 모듈은 이미 저장된
work_experience.csv를 사람별로 읽어 표시 문자열로 조립하는 역할만 한다.
파이프라인이 이미 researcher_id, work_start_date 내림차순으로 정렬해
저장하므로(최신 경력이 먼저), 첫 행이 곧 "최근 1건"이다.
"""

from services import data_store


def read_rows(researcher_id: str) -> list[dict]:
    """한 연구원의 근무 경력 행(회사별 1행)을 최신 시작일 순으로 반환."""
    df = data_store.read_processed('work_experience')
    if df.empty or 'researcher_id' not in df.columns:
        return []
    rows = df[df['researcher_id'] == researcher_id]
    return rows.to_dict('records')


def _format_ym(date_str) -> str:
    """'YYYY-MM-DD' -> "'YY.MM". 빈 값/파싱 불가면 빈 문자열."""
    s = str(date_str or '').strip()
    if not s or s.lower() in ('nan', 'none', 'nat'):
        return ''
    parts = s.split('-')
    if len(parts) < 2:
        return ''
    year, month = parts[0], parts[1]
    if len(year) != 4 or not year.isdigit() or not month.isdigit():
        return ''
    return f"'{year[2:]}.{month.zfill(2)}"


def format_line(row: dict) -> str | None:
    """행 하나를 "회사명(시작'YY.MM ~ 종료'YY.MM, 직무명)"로 변환.
    회사명이 비어 있으면 None(표시할 게 없음)."""
    company = str(row.get('company_name', '') or '').strip()
    if not company:
        return None
    start = _format_ym(row.get('work_start_date'))
    end = _format_ym(row.get('work_end_date'))
    role = str(row.get('role_name', '') or '').strip()
    line = f'{company}({start} ~ {end}'
    if role:
        line += f', {role}'
    line += ')'
    return line


def format_lines(rows: list[dict]) -> list[str]:
    """행 목록 전체를 표시용 줄 리스트로 변환(빈 회사명 행은 제외)."""
    lines = []
    for r in rows:
        line = format_line(r)
        if line:
            lines.append(line)
    return lines


def format_latest_line(researcher_id: str) -> str | None:
    """가장 최근 경력 1건만 한 줄로(인쇄 카드 전용, 사용자 확정
    2026-08-29). 데이터가 없으면 None."""
    for row in read_rows(researcher_id):
        line = format_line(row)
        if line:
            return line
    return None


def format_block(researcher_id: str, *, label: str = '근무 경력') -> str | None:
    """프로필 화면(전체 경력)에 쓰는 "근무 경력 : {첫 줄}\\n{둘째 줄}..."
    형태의 한 덩어리 텍스트. 데이터가 전혀 없으면 None."""
    lines = format_lines(read_rows(researcher_id))
    if not lines:
        return None
    first, *rest = lines
    text = f'{label} : {first}'
    if rest:
        text += '\n' + '\n'.join(rest)
    return text
