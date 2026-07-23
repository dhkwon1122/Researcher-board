"""
과제별 유사 기업/학계 탐색 모듈 (사내 Confluence + 사내 LLM)

data/processed/project_confl_address.csv의 각 과제에 대해:
  1) project_summary.py로 컨플루언스 페이지를 요약(핵심 기술/최종 산출물/
     기술적 난제/국영문 키워드) — process_project_expertise.py와 공유하는
     캐시(project_summary_cache.json)를 사용해 중복 조회를 피한다.
  2) "R&D Enterprise & Academia Discovery Agent" 역할의 사내 LLM에게 위 요약을
     전달해, 유사 연구를 진행 중인 국내외 기업·스타트업·대학 연구실을 탐색.
  3) 탐색 리포트의 기업/학계 표(마크다운 테이블)를 파싱해 CSV로 저장.

Source:
  data/processed/project_confl_address.csv (dep_name, project_name, confl_address)

Output:
  data/processed/project_searched_list.csv

※ 사내 LLM은 실시간 웹 검색 기능이 없어 사전 학습 지식만으로 답변한다.
  할루시네이션을 줄이기 위해 (1) 확신 없는 기업명/URL은 "확인 필요"로 표시하고
  지어내지 말 것을 명시적으로 지시하고, (2) 행마다 LLM 자기평가 확신도(상/중/하)
  컬럼을 받아 신뢰도 낮은 항목을 쉽게 구분할 수 있게 한다. 그럼에도 이 리스트는
  사내 LLM의 사전 학습 지식에 기반한 결과이므로, 실제 활용 전 반드시 수기로
  사실 확인이 필요하다.

사용법:
  python pipeline/process_project_search.py
"""

import csv
import os
import re
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT_DIR  # noqa: E402
import project_summary  # noqa: E402
from llm_client import call_llm  # noqa: E402

# R&D Enterprise & Academia Discovery Agent — 원문 페르소나/프로세스는 그대로 두고,
# Output Format에는 CSV 추출에 필요한 "홈페이지"/"확신도" 컬럼과, 할루시네이션을
# 줄이기 위한 "4. 중요 원칙"만 추가했다.
_DISCOVERY_SYSTEM_PROMPT = """# Role: R&D Enterprise & Academia Discovery Agent (R&D 기술·기업·학계 탐색 전문 에이전트)

## 1. Persona & Goal
당신은 기업 연구소 및 R&D 기획 부서에서 활용하는 '기술, 기업 및 학계 연구 네트워크 분석 전문 에이전트'입니다.
제공받은 과제의 상세 정보(Monthly Report, 과제 계획서 등)를 분석하여 핵심 기술과 해결하려는 난제를 식별하고, 이와 유사한 연구개발을 진행 중인 [국내외 대기업], [유망 스타트업] 및 원천 기술을 리딩하는 [국내외 최정상 대학 연구실(Lab) 및 구루급 교수]를 정밀하게 탐색하여 구조화된 리포트를 제공합니다.

## 2. Task Process

### [Phase 1: 과제 기술 분석]
- 입력된 텍스트에서 '핵심 연구 대상 기술', '최종 산출물(Deliverables)', '현재 직면한 기술적 장벽/난제'를 명확히 도출합니다.
- 국내외 검색에 필요한 국문/영문 표준 기술명 및 유의어 키워드 셋을 정의합니다.

### [Phase 2: 다각도 검색 및 타깃 발굴]
- 다음 4가지 그룹을 중심으로 유사 연구 개발 현황을 탐색합니다.
  1. 해외 글로벌 대기업 (글로벌 시장 리더, 빅테크)
  2. 국내 대기업 및 중견기업 (국내 시장 리더, 주요 연구소)
  3. 국내외 유망 스타트업 (시리즈 A~C 단계, 최근 투자 유치 및 특허 출원 활발한 기업)
  4. 국내외 핵심 대학 연구실 (국내: 서울대, 카이스트, 포항공대, 연세대, 고려대 등 상위 대학 / 해외: 해당 분야 최고 권위자 및 구루급 교수의 Lab)
- 각 그룹당 1~3건씩 선정합니다.

### [Phase 3: 유사도 검증 및 필터링]
- 단순히 키워드가 일치하는 수준을 넘어, 실제로 해결하고자 하는 '물리적/알고리즘적 문제 해결 방식'이나 '산출물 형태'가 유사한지 대조합니다.
- 우리 과제의 [현재 수준 / 최종 목표] 대비 해당 기업/대학 연구실의 기술 수준 및 진척도(특허, 상용 제품, 최근 논문 기준)를 객관적으로 비교합니다.

## 3. Output Format
모든 탐색 결과는 사용자가 내부 보고용 및 벤치마킹 자료로 활용할 수 있도록 아래 양식에 맞춰 작성해야 합니다. 표는 마크다운 파이프 테이블 형식을 정확히 지키세요.

### [1] 과제 요약 및 기술 매핑 정보
* **분석된 핵심 기술:** (예: 수소 연료전지용 고분자 전해질막(PEM) 내구성 개선 기술)
* **해결 대상 핵심 난제:** (예: 고온 다습한 환경에서의 화학적 열화 현상 억제)
* **정밀 검색 키워드 셋:** `Keyword A`, `Keyword B`, `Keyword C`

---

### [2] 국내외 유사 R&D 진행 기업 탐색 (Industry)

| 구분 | 기업명 (국가) | 유사 연구 내용 및 기술적 특징 | 우리 과제와의 유사도 | 비고 (특허/상용화 현황/최근 소식) | 홈페이지 | 확신도 |
| :--- | :--- | :--- | :--- | :--- | :--- | :---: |
| 해외 대기업 | 예: DuPont (미국) | 신규 불소계 이오노머 바인더 배합 및 제막 기술 연구 | High (85%) | 고내구성 이오노머 특허 다수 보유, 시제품 출시 단계 | https://www.dupont.com | 상 |

### [3] 글로벌 선도 대학 연구실 및 구루급 연구자 탐색 (Academia)

| 구분 | 대학명 (국가) | 연구실명 / 지도 교수 | 핵심 연구 분야 및 최근 성과 (논문/특허) | 우리 과제와의 매칭 포인트 (산학/자문) | 홈페이지 | 확신도 |
| :--- | :--- | :--- | :--- | :--- | :--- | :---: |
| 국내 대학 | 예: 서울대학교 | 신소재연구실 / 김OO 교수 | 다기능성 화학 첨가제를 이용한 막 열화 방지 메커니즘, 최근 3년간 Advanced Materials 등 논문 다수 게재 | 첨가제 배합 최적화를 위한 기초 메커니즘 분석 자문 적합 | https://... | 상 |

---

### [4] 기술 갭(Gap) 및 종합 벤치마킹 시사점
* **우리 과제의 차별성:** (시장/학계 대비 본 과제만의 차별점)
* **오픈 이노베이션 / 협력 제안:** (스타트업 연계, 산학 연구 연계 등 제안)

## 4. 중요 원칙 (Fact-Based Discipline — 반드시 준수)
- 당신은 실시간 웹 검색이 불가능하며 사전 학습된 지식만으로 답변합니다. 이 점을 항상 명심하세요.
- 실제로 존재한다고 확신할 수 없는 기업명/스타트업명/교수명/URL을 절대 지어내지 마세요. 확신이 없으면 해당 셀에 "확인 필요"라고 쓰고 확신도를 "하"로 표시하세요.
- "홈페이지"는 정확한 URL을 알고 있는 경우에만 채우고, 불확실하면 공란으로 두세요.
- "확신도"는 상(매우 확실)/중(대체로 확실하나 세부 사실 검증 필요)/하(불확실, 반드시 수기 확인 필요) 중 하나로 모든 행에 표시하세요.
"""

_INDUSTRY_HEADERS = {
    'group': '구분', 'name': '기업명 (국가)',
    'reason': '유사 연구 내용 및 기술적 특징', 'level': '우리 과제와의 유사도',
    'evidence': '비고 (특허/상용화 현황/최근 소식)', 'web': '홈페이지', 'confidence': '확신도',
}
_ACADEMIA_HEADERS = {
    'group': '구분', 'name': '대학명 (국가)', 'lab': '연구실명 / 지도 교수',
    'evidence': '핵심 연구 분야 및 최근 성과 (논문/특허)',
    'reason': '우리 과제와의 매칭 포인트 (산학/자문)', 'web': '홈페이지', 'confidence': '확신도',
}

_DOMESTIC_COUNTRY_NAMES = {'한국', '대한민국', 'korea', 'south korea', 'kr'}

_OUT_COLS = [
    'dep_name', 'project_name', 'search_group', 'searched_region', 'searched_type',
    'searched_name', 'searched_web_address', 'similarity_level', 'similarity_reason',
    'evidence', 'confidence', 'tech_keyword',
]


def _read_projects() -> pd.DataFrame:
    path = os.path.join(OUT_DIR, 'project_confl_address.csv')
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')


def _discovery_user_prompt(project_name: str, summary: dict) -> str:
    keywords_kr = ', '.join(summary.get('keywords_kr') or [])
    keywords_en = ', '.join(summary.get('keywords_en') or [])
    return f"""다음은 한 R&D 과제의 핵심 정보입니다. 이 정보를 바탕으로 유사 기업/학계를 탐색해 주세요.

과제명: {project_name}
핵심 연구 대상 기술: {summary.get('core_tech') or '확인 불가'}
최종 산출물: {summary.get('deliverable') or '확인 불가'}
현재 직면한 기술적 장벽/난제: {summary.get('challenge') or '확인 불가'}
국문 키워드: {keywords_kr or '확인 불가'}
영문 키워드: {keywords_en or '확인 불가'}"""


def _discover(project_name: str, summary: dict) -> str:
    prompt = _discovery_user_prompt(project_name, summary)
    return call_llm(prompt, _DISCOVERY_SYSTEM_PROMPT, temperature=0.2, max_tokens=4000)


def _split_bracket_sections(text: str) -> dict:
    """'### [N] ...' 헤더 기준으로 섹션 본문을 분리해 {N: body} 형태로 반환."""
    parts = re.split(r'(?m)^(?=###\s*\[\d+\])', text)
    sections = {}
    for part in parts:
        part = part.strip()
        m = re.match(r'^###\s*\[(\d+)\]', part)
        if m:
            sections[int(m.group(1))] = part
    return sections


def _strip_md_inline(text: str) -> str:
    text = text.replace('<br>', ' ').replace('<br/>', ' ').replace('<br />', ' ')
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    return text.strip()


def _parse_md_table(section_text: str) -> list:
    """마크다운 파이프 테이블(헤더+구분선+데이터행)을 파싱해 dict 리스트로 반환."""
    lines = [line.strip() for line in section_text.split('\n') if line.strip().startswith('|')]
    if len(lines) < 2:
        return []
    header = [_strip_md_inline(c) for c in lines[0].strip('|').split('|')]
    rows = []
    for line in lines[1:]:
        cells_raw = [c.strip() for c in line.strip('|').split('|')]
        if all(re.fullmatch(r':?-{2,}:?', c) for c in cells_raw if c):
            continue  # 구분선(|:---|:---:|) 건너뜀
        if len(cells_raw) != len(header):
            continue
        rows.append({h: _strip_md_inline(c) for h, c in zip(header, cells_raw)})
    return rows


def _split_name_country(name_field: str) -> tuple:
    m = re.match(r'^(.+?)\s*\(([^)]+)\)\s*$', name_field.strip())
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return name_field.strip(), ''


def _derive_region(search_group: str, country: str) -> str:
    if '해외' in search_group:
        return '해외'
    if '국내' in search_group:
        return '국내'
    if country:
        return '국내' if country.strip().lower() in _DOMESTIC_COUNTRY_NAMES else '해외'
    return ''


def _clean_web(val: str) -> str:
    return '' if val in ('', '-', '확인 필요', '확인불가', '확인 불가') else val


def _industry_rows(table_rows: list) -> list:
    out = []
    for r in table_rows:
        search_group = r.get(_INDUSTRY_HEADERS['group'], '')
        name, country = _split_name_country(r.get(_INDUSTRY_HEADERS['name'], ''))
        out.append({
            'search_group': search_group,
            'searched_region': _derive_region(search_group, country),
            'searched_type': '기업체',
            'searched_name': name,
            'searched_web_address': _clean_web(r.get(_INDUSTRY_HEADERS['web'], '')),
            'similarity_level': r.get(_INDUSTRY_HEADERS['level'], ''),
            'similarity_reason': r.get(_INDUSTRY_HEADERS['reason'], ''),
            'evidence': r.get(_INDUSTRY_HEADERS['evidence'], ''),
            'confidence': r.get(_INDUSTRY_HEADERS['confidence'], ''),
        })
    return out


def _academia_rows(table_rows: list) -> list:
    out = []
    for r in table_rows:
        search_group = r.get(_ACADEMIA_HEADERS['group'], '')
        name, country = _split_name_country(r.get(_ACADEMIA_HEADERS['name'], ''))
        lab = r.get(_ACADEMIA_HEADERS['lab'], '')
        out.append({
            'search_group': search_group,
            'searched_region': _derive_region(search_group, country),
            'searched_type': '학교',
            'searched_name': f'{name} - {lab}' if lab else name,
            'searched_web_address': _clean_web(r.get(_ACADEMIA_HEADERS['web'], '')),
            'similarity_level': '',
            'similarity_reason': r.get(_ACADEMIA_HEADERS['reason'], ''),
            'evidence': r.get(_ACADEMIA_HEADERS['evidence'], ''),
            'confidence': r.get(_ACADEMIA_HEADERS['confidence'], ''),
        })
    return out


def process() -> bool:
    projects = _read_projects()
    if projects.empty:
        print('[process_project_search] project_confl_address.csv 없음 — 종료 '
              '(process_project_confl.py 먼저 실행)')
        return False

    page_cache = project_summary.load_page_cache()
    summary_cache = project_summary.load_cache()
    all_rows = []
    print(f'[process_project_search] 과제 {len(projects)}건 처리 중...')
    for _, proj in projects.iterrows():
        dep_name = proj['dep_name']
        project_name = proj['project_name']
        confl_address = proj['confl_address']

        summary = project_summary.get_project_summary(project_name, confl_address, page_cache, summary_cache)
        if summary is None:
            print(f'  [{project_name}] 건너뜀')
            continue

        report = _discover(project_name, summary)
        if not report:
            print(f'  [{project_name}] 기업/학계 탐색 실패 — 건너뜀')
            continue

        sections = _split_bracket_sections(report)
        keyword_text = ', '.join((summary.get('keywords_kr') or []) + (summary.get('keywords_en') or []))

        industry_rows = _industry_rows(_parse_md_table(sections.get(2, '')))
        academia_rows = _academia_rows(_parse_md_table(sections.get(3, '')))

        for row in industry_rows + academia_rows:
            all_rows.append({'dep_name': dep_name, 'project_name': project_name, 'tech_keyword': keyword_text, **row})

        print(f'  [{project_name}] {len(industry_rows) + len(academia_rows)}건 발굴 '
              f'(기업 {len(industry_rows)} / 학계 {len(academia_rows)})')

    project_summary.save_page_cache(page_cache)
    project_summary.save_cache(summary_cache)

    result = pd.DataFrame(all_rows, columns=_OUT_COLS)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'project_searched_list.csv')
    result.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
    print(f'[OK]   project_searched_list.csv 저장 ({len(result)}행)')
    return True


if __name__ == '__main__':
    process()
