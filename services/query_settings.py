"""
AI 검색(자연어 질문) 프롬프트에 화면에서 추가하는 커스텀 규칙 저장/조회.

components/nl_query_bar.py의 "규칙 설정" 패널에서 편집한 텍스트를
data/processed/nl_query_custom_rules.txt에 그대로 저장한다. 코드에 있는
기존 시스템 프롬프트(services/nl_query.QUERY_SYSTEM_PROMPT,
services/open_data_query._SQL_GEN_SYSTEM_TEMPLATE)는 손대지 않고, 매 호출
시점에 이 텍스트를 "# 사용자 정의 추가 규칙" 섹션으로 프롬프트 끝에
덧붙이는 방식이다. "상위평가=가/나" 같은 용어 정의든 "근거를 더 자세히
보여줘" 같은 출력 형식 지시든 구분하지 않고 한 덩어리로 취급해 라우팅
프롬프트/SQL 생성 프롬프트 양쪽에 동일하게 주입한다(사용자 확정: 규칙을
하나로 통합, 둘로 나누지 않음).
"""

import os

from services import data_store

_RULES_PATH = os.path.join(data_store.DATA_DIR, 'nl_query_custom_rules.txt')
_MAX_LEN = 4000  # 프롬프트 비대화·토큰 낭비 방지용 상한


def read_rules() -> str:
    if not os.path.exists(_RULES_PATH):
        return ''
    try:
        with open(_RULES_PATH, encoding='utf-8') as f:
            return f.read()
    except OSError:
        return ''


def write_rules(text: str) -> None:
    text = (text or '').strip()[:_MAX_LEN]
    os.makedirs(os.path.dirname(_RULES_PATH), exist_ok=True)
    with open(_RULES_PATH, 'w', encoding='utf-8') as f:
        f.write(text)


def apply(system_prompt: str) -> str:
    """system_prompt 끝에 저장된 커스텀 규칙을 덧붙인다. 규칙이 없으면 원본 그대로."""
    rules = read_rules().strip()
    if not rules:
        return system_prompt
    return (
        f'{system_prompt}\n\n'
        '# 사용자 정의 추가 규칙 (아래 내용을 최우선으로 반영하세요)\n'
        f'{rules}'
    )
