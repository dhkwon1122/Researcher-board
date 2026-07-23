"""
논문 저널/학회 권위도 조회 모듈 (사내 LLM)

process_researcher_expertise.py가 논문(publications.csv) 저자유형/교신저자
여부와 함께 참고하는 저널 권위도(SCI/SCIE 여부, impact factor 수준, 해당
분야에서의 권위·명성)를 사내 LLM에게 평가받아 캐시한다.

평가 값이 실제로 채워진 저널은 건너뛰고, 값이 비어 있는(신규거나 이전 조회가
실패해 빈 문자열로 남은) 저널만 재조회한다(누적 재사용, profile별 분리).
단순히 캐시에 키가 있는지가 아니라 값이 실제로 있는지로 판단해야, 실패했던
저널이 캐시에 빈 값으로 영구히 박제되지 않는다.

Source:
  data/processed/publications.csv (journal 컬럼)

Output:
  data/processed/journal_authority[.<profile>].json  (저널명별 권위도 평가 캐시)

캐시와 무관하게 전체 저널을 다시 확인하려면:
  python pipeline/journal_authority.py --refresh-journals [--profile thinkingcap]

※ 이 모듈은 사내 LLM을 호출하므로 비용이 발생한다. run_pipeline.py/
  run_expertise.py 자동 실행에는 포함되지 않는다. process_researcher_expertise.py
  실행 시 자동으로 함께 호출되며, 독립적으로도 위 명령으로 직접 실행할 수 있다.
"""

import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OUT_DIR  # noqa: E402
from excel_reader import clean_str  # noqa: E402
from llm_client import call_llm, extract_json, max_concurrency, run_concurrent  # noqa: E402
import rd_specialist_markdown as mmd  # noqa: E402

_JOURNAL_SYSTEM_PROMPT = '당신은 학술 저널/학회의 권위도를 평가하는 전문가입니다. 요청한 JSON 형식만 출력하세요.'


def unique_journals(pub_df: pd.DataFrame) -> list:
    """논문 DataFrame에서 고유 저널명 목록(정렬됨)을 추출."""
    if pub_df.empty or 'journal' not in pub_df.columns:
        return []
    return sorted({clean_str(j) for j in pub_df['journal'] if clean_str(j)})


def cache_path(profile: str = 'default') -> str:
    suffix = mmd.profile_suffix(profile)
    return os.path.join(OUT_DIR, f'journal_authority{suffix}.json')


def load_cache(profile: str = 'default') -> dict:
    path = cache_path(profile)
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def save_cache(cache: dict, profile: str = 'default'):
    with open(cache_path(profile), 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _fetch_authority(journal: str, profile: str) -> str:
    prompt = (
        f'학술지/저널명: {journal}\n'
        f'이 저널의 SCI/SCIE 여부, 대략적인 impact factor 수준, 해당 분야에서의 '
        f'권위·명성 수준을 1~2문장으로 평가해 주세요. 확실하지 않으면 "확인 불가"라고 답하세요.\n'
        f'다음 JSON 형식으로만 출력하세요: {{"authority": "평가 내용"}}'
    )
    raw = call_llm(prompt, _JOURNAL_SYSTEM_PROMPT, max_tokens=300, profile=profile)
    if not raw:
        return ''
    try:
        return json.loads(extract_json(raw)).get('authority', '')
    except json.JSONDecodeError:
        return ''


def update_authority(journals: list, cache: dict, profile: str = 'default', force: bool = False) -> dict:
    """캐시에 실제 평가 값이 채워진 저널은 건너뛰고, 값이 비어 있는 저널(신규거나
    이전 조회가 실패해 빈 문자열로 남은 것)만 사내 LLM으로 재조회한다(누적 재사용,
    profile별 분리). force=True(--refresh-journals)면 캐시 값과 무관하게 전달된
    저널 전체를 다시 조회한다. 호출부가 로드/저장을 위임하므로, 이 함수 안에서
    저장까지 마친다(배치 처리 중간에 실패해도 이미 평가한 저널은 남도록).

    profile의 동시 호출 허용치(llm_client.max_concurrency)만큼 스레드풀로 동시
    조회한다 — 전용 vLLM 서버(thinkingcap)는 continuous batching으로 여러
    요청을 한꺼번에 처리하는 편이 순차 호출보다 훨씬 빠르다. 개별 저널 조회
    중 예기치 못한 예외가 나도(run_concurrent가 잡아 반환) 다른 저널 조회는
    계속 진행하고, 실패한 저널만 에러와 함께 로그로 남긴다."""
    targets = journals if force else [j for j in journals if not cache.get(j)]
    if not targets:
        return cache
    label = '전체 재조회' if force else '신규/미확인'
    workers = max_concurrency(profile)
    print(f'[journal_authority] 저널 권위도 조회 중 ({label} {len(targets)}건, profile={profile}, '
          f'동시 {workers}건)...')

    tasks = [(lambda j=j: _fetch_authority(j, profile)) for j in targets]
    results = run_concurrent(tasks, max_workers=workers)

    for journal, (authority, error) in zip(targets, results):
        if error is not None:
            print(f'    [에러] {journal}: {type(error).__name__}: {error}')
            cache[journal] = ''
        else:
            cache[journal] = authority or ''
            print(f'    [{"OK" if authority else "실패"}] {journal}')

    save_cache(cache, profile)
    return cache


def process(profile: str = 'default', force: bool = False) -> bool:
    """publications.csv를 직접 읽어 저널 권위도를 조회/캐시하는 독립 실행 진입점.
    process_researcher_expertise.py는 이미 읽어둔 DataFrame으로
    unique_journals()/load_cache()/update_authority()를 직접 호출하므로 이
    함수를 거치지 않는다 — publications.csv를 두 번 읽지 않기 위함."""
    pub_path = os.path.join(OUT_DIR, 'publications.csv')
    if not os.path.exists(pub_path):
        print('[journal_authority] publications.csv 없음 — 종료 (먼저 논문 데이터를 준비하세요)')
        return False

    pub_df = pd.read_csv(pub_path, encoding='utf-8-sig', dtype=str).fillna('')
    journals = unique_journals(pub_df)
    if not journals:
        print('[journal_authority] 조회할 저널이 없습니다.')
        return False

    cache = load_cache(profile)
    update_authority(journals, cache, profile, force=force)
    return True


if __name__ == '__main__':
    _profile = mmd.parse_profile_arg(sys.argv)
    process(profile=_profile, force='--refresh-journals' in sys.argv)
