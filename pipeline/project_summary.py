"""
과제별 컨플루언스 요약 공용 유틸리티

컨플루언스 페이지 본문을 사내 LLM으로 요약(핵심 연구 대상 기술/최종 산출물/
기술적 장벽·난제/국영문 키워드)한다. process_project_search.py(유사 기업/학계
탐색)와 process_project_expertise.py(과제 전문성 분석)가 같은 과제에 대해
Confluence 조회 + LLM 요약을 중복으로 수행하지 않도록 결과를 캐시해 재사용한다.

캐시는 두 종류다.
  - 컨플루언스 원문 캐시(project_page_cache.json): profile(사내 LLM 모델)과
    무관하게 공유. 페이지 조회는 네트워크 호출이라 모델 비교 시에도 한 번만
    수행한다.
  - 요약 캐시(project_summary_cache.json / project_summary_cache.<profile>.json):
    실제 LLM 요약 결과이므로 모델(profile)별로 분리 저장한다.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import confluence_client  # noqa: E402
from llm_client import call_llm, extract_json  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed')
PAGE_CACHE_PATH = os.path.join(OUT_DIR, 'project_page_cache.json')

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


def _summary_cache_path(profile: str) -> str:
    suffix = '' if profile == 'default' else f'.{profile}'
    return os.path.join(OUT_DIR, f'project_summary_cache{suffix}.json')


def load_cache(profile: str = 'default') -> dict:
    path = _summary_cache_path(profile)
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def save_cache(cache: dict, profile: str = 'default'):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(_summary_cache_path(profile), 'w', encoding='utf-8') as f:
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


def _get_page_text(project_name: str, confl_address: str, page_cache: dict):
    """confl_address 기준 컨플루언스 원문 캐시(profile과 무관하게 공유). 실패 시 None."""
    if confl_address in page_cache:
        return page_cache[confl_address]
    try:
        page_text = confluence_client.fetch_page_text(confl_address)
    except confluence_client.ConfluenceError as exc:
        print(f'  [{project_name}] 컨플루언스 조회 실패: {exc}')
        return None
    page_cache[confl_address] = page_text
    return page_text


def _summarize(page_text: str, profile: str = 'default'):
    raw = call_llm(page_text[:_MAX_PAGE_CHARS], _SUMMARY_SYSTEM_PROMPT, temperature=0.1, max_tokens=800,
                    profile=profile)
    if not raw:
        # call_llm() 자체에서 이미 실패 원인(HTTP 오류/빈 응답 등)을 로그로 남긴다.
        return None
    try:
        return json.loads(extract_json(raw))
    except json.JSONDecodeError as exc:
        preview = raw[:300].replace('\n', ' ')
        print(f'  [LLM 경고] 과제 요약 응답이 JSON 형식이 아님 (profile={profile}): {exc}\n'
              f'    원본 응답 미리보기: {preview}')
        return None


def get_project_summary(project_name: str, confl_address: str, page_cache: dict, summary_cache: dict,
                         profile: str = 'default'):
    """confl_address 기준 요약 캐시(profile별 분리)를 확인하고, 없으면 컨플루언스
    원문(page_cache, profile과 무관하게 공유)을 가져와 지정된 profile의 LLM으로
    요약해 summary_cache에 채워 넣는다. 호출부가 두 캐시의 로드/저장을 관리한다
    (배치 처리 시 루프 밖에서 한 번만). 실패 시 None(캐시에 남기지 않아 다음
    실행 때 재시도)."""
    if confl_address in summary_cache:
        return summary_cache[confl_address]

    page_text = _get_page_text(project_name, confl_address, page_cache)
    if page_text is None:
        return None

    summary = _summarize(page_text, profile=profile)
    if summary is None:
        print(f'  [{project_name}] 과제 요약 실패 (profile={profile})')
        return None

    summary_cache[confl_address] = summary
    return summary
