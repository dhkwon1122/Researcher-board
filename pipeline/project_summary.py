"""
과제별 컨플루언스 요약 공용 유틸리티

컨플루언스 페이지 본문을 사내 LLM으로 상세 분석(핵심 연구 대상 기술/최종
산출물/기술적 장벽·난제/연구 배경/추진 일정/기대효과/국영문 키워드 + 문서에
언급된 인력과 그 담당 업무)한다. process_project_search.py(유사 기업/학계
탐색)와 process_project_expertise.py(과제 전문성 분석)가 같은 과제에 대해
Confluence 조회 + LLM 분석을 중복으로 수행하지 않도록 결과를 캐시해 재사용한다.
process_project_search.py는 이 중 core_tech/deliverable/challenge/keywords_*
필드만 쓰고 나머지(background/milestones/expected_impact/personnel)는 무시하므로,
필드가 늘어나도 그쪽은 영향받지 않는다.

confl_address가 비어 있는 과제는 data/raw/conflue_MPR/{과제명}.pdf 파일이
있으면 그 본문 텍스트로 대체해 이후 요약 과정을 동일하게 진행한다
(pdf_reader.py). 이 폴백은 두 스크립트 모두에 공통 적용된다.

캐시는 두 종류다.
  - 원문 캐시(project_page_cache.json): Confluence 조회/PDF 추출 결과.
    키는 confl_address가 있으면 그 값, 없으면 'pdf:{project_name}'.
  - 요약 캐시(project_summary_cache.json): 실제 LLM 요약 결과. 키는 원문
    캐시와 동일한 규칙(confl_address 또는 'pdf:{project_name}').
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT_DIR  # noqa: E402
import confluence_client  # noqa: E402
import pdf_reader  # noqa: E402
from llm_client import call_llm, extract_json  # noqa: E402

PAGE_CACHE_PATH = os.path.join(OUT_DIR, 'project_page_cache.json')

_MAX_PAGE_CHARS = 6000

_SUMMARY_SYSTEM_PROMPT = """당신은 R&D 과제 문서 분석 전문가입니다. 입력된 과제 관련 문서(Monthly Report,
과제계획서 등) 원문에서 아래 정보를 최대한 상세하고 구체적으로 추출하세요.
한두 문장짜리 요약이 아니라, 문서에 있는 세부 내용(구체적 수치, 방법론, 절차,
조건 등)을 최대한 살려서 작성하세요. 문서에 명시되지 않은 내용은 추정하지
말고 "확인 불가"라고 쓰세요.

# 인력(연구원) 추출 지침
문서 안에 등장하는 사람 이름과, 그 사람이 이 과제에서 담당하는 구체적 업무를
찾아 personnel 목록에 담으세요.
- 이름 옆에 "김재연(17)"처럼 괄호 숫자가 붙어 있으면 그 숫자를 name_suffix에
  그대로 담으세요(동명이인을 구분하기 위한 사내 표기 관례입니다). 괄호 숫자가
  없으면 name_suffix는 빈 문자열로 두세요.
- role_description에는 그 사람이 이 과제에서 실제로 무엇을 담당하는지(역할,
  수행 업무)를 문서에 근거해 구체적으로 쓰세요. "참여"처럼 뭉뚱그리지 말고,
  문서에서 확인되는 실제 업무 내용을 담으세요.
- 같은 사람이 문서 여러 곳에 언급되면 하나의 항목으로 통합하세요.
- 실제 사람 이름이 아니라 조직명/팀명만 언급된 경우는 포함하지 마세요.
- 문서에 인력 언급이 전혀 없으면 빈 배열로 두세요.

반드시 아래 JSON 형식으로만 출력하고, 그 외 텍스트는 출력하지 마세요.
{
  "core_tech": "핵심 연구 대상 기술 (상세)",
  "deliverable": "최종 산출물(Deliverables) (상세)",
  "challenge": "현재 직면한 기술적 장벽/난제 (상세)",
  "background": "연구 배경 및 필요성",
  "milestones": ["주요 추진 일정/마일스톤 1", "주요 추진 일정/마일스톤 2"],
  "expected_impact": "기대효과/파급효과",
  "keywords_kr": ["국문 키워드1", "국문 키워드2"],
  "keywords_en": ["English keyword1", "English keyword2"],
  "personnel": [
    {"name": "이름", "name_suffix": "괄호 숫자(있으면), 없으면 빈 문자열", "role_description": "이 과제에서의 구체적 담당 업무"}
  ]
}
"""


SUMMARY_CACHE_PATH = os.path.join(OUT_DIR, 'project_summary_cache.json')


def load_cache() -> dict:
    if not os.path.exists(SUMMARY_CACHE_PATH):
        return {}
    with open(SUMMARY_CACHE_PATH, encoding='utf-8') as f:
        return json.load(f)


def save_cache(cache: dict):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(SUMMARY_CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def load_page_cache() -> dict:
    if not os.path.exists(PAGE_CACHE_PATH):
        return {}
    with open(PAGE_CACHE_PATH, encoding='utf-8') as f:
        return json.load(f)


def save_page_cache(cache: dict):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(PAGE_CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _page_cache_key(project_name: str, confl_address: str) -> str:
    return confl_address if confl_address else f'pdf:{project_name}'


def _get_page_text(project_name: str, confl_address: str, page_cache: dict):
    """confl_address 기준 원문 캐시. 실패 시 None.
    confl_address가 비어 있으면 data/raw/conflue_MPR/{project_name}.pdf로
    폴백한다(pdf_reader.py). 캐시 키도 이 경우 'pdf:{project_name}'을 쓴다
    (confl_address가 비어 있는 여러 과제가 같은 '' 키를 공유해 캐시가
    섞이는 것을 방지)."""
    cache_key = _page_cache_key(project_name, confl_address)
    if cache_key in page_cache:
        return page_cache[cache_key]

    if confl_address:
        try:
            page_text = confluence_client.fetch_page_text(confl_address)
        except confluence_client.ConfluenceError as exc:
            print(f'  [{project_name}] 컨플루언스 조회 실패: {exc}')
            return None
    else:
        try:
            page_text = pdf_reader.fetch_pdf_text(project_name)
        except pdf_reader.PdfNotFoundError as exc:
            print(f'  [{project_name}] 컨플루언스 주소 없음, PDF 폴백도 실패: {exc}')
            return None

    page_cache[cache_key] = page_text
    return page_text


def _summarize(page_text: str):
    # 상세 분석 + 인력 추출까지 함께 요구하므로 예전(3000)보다 여유 있게 잡는다.
    # 추론형 모델의 사고 과정 토큰 소모도 감안(finish_reason=length 방지).
    raw = call_llm(page_text[:_MAX_PAGE_CHARS], _SUMMARY_SYSTEM_PROMPT, temperature=0.1, max_tokens=6000)
    if not raw:
        # call_llm() 자체에서 이미 실패 원인(HTTP 오류/빈 응답 등)을 로그로 남긴다.
        return None
    try:
        return json.loads(extract_json(raw))
    except json.JSONDecodeError as exc:
        preview = raw[:300].replace('\n', ' ')
        print(f'  [LLM 경고] 과제 요약 응답이 JSON 형식이 아님: {exc}\n'
              f'    원본 응답 미리보기: {preview}')
        return None


def get_project_summary(project_name: str, confl_address: str, page_cache: dict, summary_cache: dict):
    """요약 캐시를 확인하고, 없으면 원문(page_cache — confl_address가 있으면
    Confluence, 없으면 data/raw/conflue_MPR/{project_name}.pdf 폴백)을 가져와
    LLM으로 요약해 summary_cache에 채워 넣는다. 호출부가 두 캐시의 로드/저장을
    관리한다(배치 처리 시 루프 밖에서 한 번만). 실패 시 None(캐시에 남기지
    않아 다음 실행 때 재시도)."""
    cache_key = _page_cache_key(project_name, confl_address)
    if cache_key in summary_cache:
        return summary_cache[cache_key]

    page_text = _get_page_text(project_name, confl_address, page_cache)
    if page_text is None:
        return None

    summary = _summarize(page_text)
    if summary is None:
        print(f'  [{project_name}] 과제 요약 실패')
        return None

    summary_cache[cache_key] = summary
    return summary
