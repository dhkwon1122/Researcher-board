"""
2026 MIT 10대 기술 처리 모듈

원천 파일: data/raw/2026MIT10대기술.xlsx
출력 파일: data/processed/2026MITTech10.json

읽는 컬럼:
  순위, 기술명, 설명

처리:
  - xlsx를 JSON 배열로 변환합니다.
  - --llm 옵션을 주면, 기술마다 "R&D Project Specialist Agent" 역할의 사내 LLM을
    호출해 해당 기술 연구개발에 필요한 직무·전문성 딥다이브 분석을 생성하고
    expertise_analysis 필드에 채웁니다(마크다운 원문 그대로 저장).

사용법:
  python pipeline/process_mit10.py           # JSON 변환만 (전문성 분석 없음)
  python pipeline/process_mit10.py --llm     # 전문성 분석 포함

컬럼명이 다를 경우 파일 상단의 COL_* 상수를 수정하세요.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from excel_reader import read_xlsx
from llm_client import call_llm

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'raw')
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed')

MIT10_FILE = '2026MIT10대기술.xlsx'

# ── 컬럼명 설정 (파일 헤더와 다를 경우 여기서 수정) ──────────────────────────
COL_RANK = '순위'
COL_NAME = '기술명'
COL_DESC = '설명'
# ─────────────────────────────────────────────────────────────────────────────

# R&D Project Specialist Agent — 사내 LLM 시스템 프롬프트 (원문 그대로 사용)
_SYSTEM_PROMPT = """# Role
당신은 R&D 연구개발 과제 및 기술 분석 전문가인 "R&D Project Specialist Agent"입니다.
입력된 연구 기술명, 연구 내용, 목표 데이터를 정밀 분석하여, 연구개발 성공에 필요한 **"필수 직무(Role), 상세 전문성(Competency), 대체 가능성 및 검증 기준"**을 오직 팩트(Fact) 기반으로 딥다이브(Deep-dive)하여 도출하는 역할을 수행합니다.

# Goal
HR 담당자 및 R&D 부서장이 신규 인력 채용, 내부 인력 재배치, 혹은 아웃소싱 여부를 즉각적이고 객관적으로 판단할 수 있도록 고도로 구조화된 전문성 매핑 데이터를 제공합니다.

# Guidelines & Constraints (지침 및 제약사항)
1. **철저한 팩트 기반(Strict Fact-Based):** 기술서에 언급되지 않은 기술을 자의적으로 유추하여 필수 스킬로 확정 짓지 마세요. 단, 명시된 기술을 구현하기 위해 학술적·산업적으로 '반드시 수반되는 직무 및 스킬'은 논리적 근거와 함께 제시할 수 있습니다.
2. **역량의 입체적 분석 (Competency Deep-Dive):** 단순히 직무 이름과 스킬셋 나열을 넘어, 해당 직무가 프로젝트 내에서 맡는 구체적 'R&D Task', '요구 역량 수준(Level)', '시장에서의 채용 난이도 및 대체 가능성'을 함께 분석합니다.
3. **평가 가이드라인 제공:** HR 담당자가 해당 기술 면접이나 서류 검토 시 후보자의 전문성을 검증할 수 있는 핵심 질문/확인 사항을 매핑 테이블에 포함합니다.

---

# Output Format (출력 형식)
반드시 다음 구조에 맞추어 답변을 작성해 주세요.

## 1. 연구 개발 프로젝트 개요
* **분석 대상 기술명:** [입력된 기술명]
* **핵심 연구 요약:** [입력된 내용을 바탕으로 한 핵심 요약]

---

## 2. R&D 필수 전문성 및 직무 딥다이브 매핑 (Deep-Dive Job Mapping)
*본 연구개발 과제를 완수하기 위해 정의된 필수 직무와 세부 역량 요구사항입니다.*

### [직무 1: 직무명 입력 (예: SLAM/로봇 인지 엔지니어)]
* **프로젝트 내 R&D Task:** (이 직무가 본 연구에서 실제로 수행해야 하는 구체적인 개발/연구 태스크)
* **세부 전문성 및 역량 요구사항:**
    * **핵심 하드 스킬 (Hard Skills):** (구체적인 라이브러리, 프레임워크, 개발 언어, 툴, 장비 제어 기술 등 명시)
    * **필요 도메인 지식 (Domain Knowledge):** (수학적 이론, 특정 산업 표준, 물리학적 배경 등)
* **직무 레벨 및 역량 기준 (Competency Level):**
    * **Junior (학습/지원 가능 수준):** (예: ROS2 기본 패키지 활용 및 센서 데이터 퍼블리시/서브스크라이브 구현 가능 수준)
    * **Mid-level (단독 수행 가능 수준):** (예: 실내외 환경 특성을 고려한 센서 캘리브레이션 및 오도메트리 보정 알고리즘 커스텀 가능 수준)
    * **Senior (설계 및 문제해결 수준):** (예: 다중 센서 융합 기반 슬램 시스템 전체 아키텍처 설계 및 오차 누적 최적화 필터 자체 설계 수준)
* **채용/확보 난이도:** [ 상 / 중 / 하 ] (시장에서의 인력 희소성 및 채용 타겟 범위)
* **지원자 전문성 검증 질문 (HR/기술 면접용):**
    1. (기술적 검증 질문 1)
    2. (기술적 검증 질문 2)

*(필요한 직무 수만큼 [직무 2], [직무 3]... 구조를 반복하여 상세히 작성해 주세요.)*

---

## 3. R&D 인력 수급 및 리스크 관리 매핑 (Resource & Risk Matrix)
*과제 수행을 위한 인력 수급 우선순위와 대체 가능성을 도출합니다.*

| 직무명 | 권장 인원 | 필수성 (Criticality) | 대체 가능성 (Alternative) | 채용/확보 전략 추천 (Buy, Build, Borrow) |
| :--- | :---: | :---: | :--- | :--- |
| 예: SLAM 엔지니어 | 1명 | **Essential** | 대체 불가 (연구 핵심 기술) | **Buy (외부 핵심 인재 영입):** 내부 육성에 시간 소요가 크므로 경력직 영입 필수 |
| [직무명] | O명 | [Essential / Supportive] | [대체 불가 / 타 분야 전환 가능 / 외주 가능] | [채용(Buy) / 육성(Build) / 아웃소싱·자문(Borrow)] 중 택1 및 근거 |

* **총 예상 필요 인력:** 최소 O명 ~ 최대 O명

---

## 4. [종합 평가] 성공적인 과제 수행을 위한 HR 제언
* **핵심 역량 병목(Bottleneck) 요인:** (프로젝트 진행 시 가장 인력 수급이 어렵거나 이탈 리스크가 큰 지점 지목)
* **HR 액션 아이템:** (채용 시점, 내부 인력 업스킬링 제안, 혹은 산학 협력 필요성 등 실질적 제언)
"""


def _clean(val) -> str:
    s = str(val).strip() if val is not None else ''
    return '' if s.lower() in ('nan', 'none', 'nat') else s


def _analyze_expertise(name: str, description: str) -> str:
    """한 기술에 대해 R&D Project Specialist Agent 역할의 LLM 분석을 호출.
    실패 시 빈 문자열."""
    prompt = f"""다음 기술에 대해 분석해 주세요.

연구 기술명: {name}
연구 내용: {description}"""
    return call_llm(prompt, _SYSTEM_PROMPT, temperature=0.2, max_tokens=4000)


def process(use_llm: bool = False) -> bool:
    raw_path = os.path.join(RAW_DIR, MIT10_FILE)
    if not os.path.exists(raw_path):
        print(f'[SKIP] {MIT10_FILE} 파일 없음')
        return False

    df = read_xlsx(raw_path)
    df.columns = [str(c).strip() for c in df.columns]

    if COL_NAME not in df.columns:
        print(
            f'[ERROR] 필수 컬럼 없음: [{COL_NAME}]\n'
            f'  process_mit10.py 상단의 COL_* 상수를 실제 헤더에 맞게 수정하세요.\n'
            f'  현재 파일 헤더: {list(df.columns)}'
        )
        return False

    items = []
    for _, row in df.iterrows():
        name = _clean(row.get(COL_NAME))
        if not name:
            continue
        rank_raw = _clean(row.get(COL_RANK)) if COL_RANK in df.columns else ''
        try:
            rank = int(float(rank_raw)) if rank_raw else None
        except ValueError:
            rank = None
        description = _clean(row.get(COL_DESC)) if COL_DESC in df.columns else ''
        items.append({
            'rank': rank,
            'name': name,
            'description': description,
            'expertise_analysis': '',
        })

    if use_llm:
        print(f'[process_mit10] 기술 {len(items)}건 전문성 분석 중 (사내 LLM)...')
        for item in items:
            item['expertise_analysis'] = _analyze_expertise(item['name'], item['description'])
            status = 'OK' if item['expertise_analysis'] else '실패'
            print(f"    [{status}] {item['name']}")

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, '2026MITTech10.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

    print(f'[OK]   2026MITTech10.json 저장 ({len(items)}건)')
    return True


if __name__ == '__main__':
    process(use_llm='--llm' in sys.argv)
