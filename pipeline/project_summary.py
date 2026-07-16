"""
과제별 컨플루언스 요약 공용 유틸리티

컨플루언스 페이지 본문을 사내 LLM으로 요약(핵심 연구 대상 기술/최종 산출물/
기술적 장벽·난제/국영문 키워드)한다. process_project_search.py(유사 기업/학계
탐색)와 process_project_expertise.py(과제 전문성 분석)가 같은 과제에 대해
Confluence 조회 + LLM 요약을 중복으로 수행하지 않도록, 결과를
data/processed/project_summary_cache.json에 confl_address 기준으로 캐시해
재사용한다.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import confluence_client  # noqa: E402
from llm_client import call_llm, extract_json  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed')
CACHE_PATH = os.path.join(OUT_DIR, 'project_summary_cache.json')

_MAX_PAGE_CHARS = 6000

_SUMMARY_SYSTEM_PROMPT = """당신은 R&D 과제 문서 분석 전문가입니다. 입력된 과제 관련 문서(Monthly Report,
과제계획서 등) 원문에서 다음 정보를 정확하게 추출하세요. 문서에 명시되지 않은
내용은 추정하지 말고 "확인 불가"라고 쓰세요.

반드시 아래 JSON 형식으로만 출력하고, 그 외 텍스트는 출력하지 마세요.
{
  "core_tech": "분석된 핵심 연구 대상 기술",
  "deliverable": "최종 산출물(Deliverables)",
  "challenge": "현재 직면한 기술적 장벽/난제",
  "keywords_kr": ["국문 키워드1", "국문 키워드2"],
  "keywords_en": ["English keyword1", "English keyword2"]
}
"""


def load_cache() -> dict:
    if not os.path.exists(CACHE_PATH):
        return {}
    with open(CACHE_PATH, encoding='utf-8') as f:
        return json.load(f)


def save_cache(cache: dict):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _summarize(page_text: str) -> dict:
    raw = call_llm(page_text[:_MAX_PAGE_CHARS], _SUMMARY_SYSTEM_PROMPT, temperature=0.1, max_tokens=800)
    if not raw:
        return None
    try:
        return json.loads(extract_json(raw))
    except json.JSONDecodeError:
        return None


def get_project_summary(project_name: str, confl_address: str, cache: dict) -> dict:
    """confl_address 기준 캐시를 확인하고, 없으면 Confluence 조회 + LLM 요약을
    수행해 cache에 채워 넣는다(호출부가 cache 로드/저장을 관리 — 배치 처리 시
    루프 밖에서 한 번만 로드/저장하도록). 실패(컨플루언스 조회 실패/LLM 요약
    실패)한 경우는 캐시에 남기지 않아 다음 실행 때 재시도한다. 실패 시 None."""
    if confl_address in cache:
        return cache[confl_address]

    try:
        page_text = confluence_client.fetch_page_text(confl_address)
    except confluence_client.ConfluenceError as exc:
        print(f'  [{project_name}] 컨플루언스 조회 실패: {exc}')
        return None

    summary = _summarize(page_text)
    if summary is None:
        print(f'  [{project_name}] 과제 요약 실패')
        return None

    cache[confl_address] = summary
    return summary
