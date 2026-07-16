"""
등급/Lv 기준표(정적 참조 데이터) 생성 모듈

원본 xlsx 없이, 사내에서 정의한 기준을 그대로 코드에 담아 JSON으로 저장한다.
다른 스크립트(process_researcher_expertise.py 등)에서 프롬프트 구성 시
tech_grade/lv 값의 의미를 LLM에게 설명하는 용도로 사용한다.

출력 파일:
  data/processed/core_technology_grade_info.json  (핵심기술 등급 개요: S/A/B)
  data/processed/tech_ownership_lv_info.json      (보유기술 Lv 개요: 1~5)
"""

import json
import os

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed')

GRADE_INFO = [
    {
        'grade': 'S',
        'definition': (
            '해당 분야에서 독보적인 전문성을 보유하여 회사 내부 대체자가 없는 수준. '
            '해당 기술을 최초로 도입 또는 내재화하였거나 기술 구현을 주도하여 부재 시 '
            '기술 발전/유지 불가. 전체 임직원의 5% 수준.'
        ),
    },
    {
        'grade': 'A',
        'definition': (
            '해당 분야에서 매우 높은 수준의 전문성을 보유하여 기술 구현에 주요 역할을 수행. '
            '높은 수준의 이해도로 부재 시 전체 기술 흐름에 큰 장애 발생이 예상되며, '
            '다른 인력이 적응하여 대체하려면 상당 기간의 시간 필요. 전체 임직원의 5~10% 수준.'
        ),
    },
    {
        'grade': 'B',
        'definition': (
            '해당 분야의 단순 숙련된 엔지니어가 아닌 높은 수준의 전문성을 보유한 인력. '
            '전체 임직원 중 절대평가(A, S 제외) 상위권.'
        ),
    },
]

LV_INFO = [
    {
        'lv': 1,
        'definition': (
            '직무 가이드, 코칭을 바탕으로 업무를 수행할 수 있는 수준. '
            '직무에 필요한 기초 직무 교육을 수료한 수준.'
        ),
    },
    {
        'lv': 2,
        'definition': (
            '직무 가이드나 코치 없이 단독 작업이 가능한 수준. '
            '직무에 대한 이론 및 응용 지식을 보유하고 있는 수준.'
        ),
    },
    {
        'lv': 3,
        'definition': (
            '담당 직무에 대한 문제해결, 개선을 스스로 진행할 수 있는 수준. '
            '직무관련 지식을 심화 이해 및 활용할 수 있는 수준.'
        ),
    },
    {
        'lv': 4,
        'definition': (
            '직무 기술적 코칭이 가능하며, 조직에서 핵심적인 과제의 리딩이 가능한 수준. '
            '직무 및 업무 프로세스에서 의사결정이 가능한 수준.'
        ),
    },
    {
        'lv': 5,
        'definition': (
            '기존 기술에서 나아가 새로운 직무기술이나 지식을 선도하는 수준. '
            '조직 전체에 영향을 미칠 수 있는 중요한 사안에 대해 판단하고 책임질 수 있는 수준.'
        ),
    },
]


def process() -> bool:
    os.makedirs(OUT_DIR, exist_ok=True)

    grade_path = os.path.join(OUT_DIR, 'core_technology_grade_info.json')
    with open(grade_path, 'w', encoding='utf-8') as f:
        json.dump(GRADE_INFO, f, ensure_ascii=False, indent=2)
    print(f'[OK]   core_technology_grade_info.json 저장 ({len(GRADE_INFO)}건)')

    lv_path = os.path.join(OUT_DIR, 'tech_ownership_lv_info.json')
    with open(lv_path, 'w', encoding='utf-8') as f:
        json.dump(LV_INFO, f, ensure_ascii=False, indent=2)
    print(f'[OK]   tech_ownership_lv_info.json 저장 ({len(LV_INFO)}건)')

    return True


if __name__ == '__main__':
    process()
