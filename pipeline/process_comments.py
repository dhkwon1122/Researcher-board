"""
부서장 코멘트 처리 모듈

사용법:
  python pipeline/process_comments.py

처리 흐름:
  data/raw/comments_raw.xlsx  →  data/processed/comments.csv

comments_raw.xlsx 필수 컬럼:
  researcher_id, year, comment_raw

선택 컬럼 (없으면 LLM 요약으로 자동 생성):
  comment_summary, strengths, improvements
"""

import csv
import os
import sys
import pandas as pd

DATA_RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'raw')
DATA_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed')

# xlwings 기반 Excel 읽기 (DRM 보호 파일 지원)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from excel_reader import read_xlsx


# ─────────────────────────────────────────────────────────────────────────────
# LLM 요약 함수 — 사내 LLM API 연동 가이드
# ─────────────────────────────────────────────────────────────────────────────
def summarize_with_llm(comment_raw: str, researcher_name: str = '') -> dict:
    """
    사내 LLM API를 호출하여 부서장 코멘트를 요약합니다.

    ┌─── 구현 가이드 (사내 환경에 맞게 수정 필요) ──────────────────────────┐

    [1] 필요 정보 확인
        - 사내 LLM API 엔드포인트 URL
        - 인증 방식 (API Key / Bearer Token / OAuth 등)
        - 요청/응답 JSON 스키마 (OpenAI 호환 여부 확인)

    [2] 예시 구현 (REST API / OpenAI 호환 포맷 기준)

        import requests

        INTERNAL_LLM_URL = "http://사내서버주소:포트/v1/chat/completions"
        API_KEY = os.environ.get("INTERNAL_LLM_API_KEY", "")   # 환경변수 권장

        prompt = f\"""
        아래 부서장 코멘트를 다음 JSON 형식으로 정확히 요약해 주세요.
        응답은 JSON만 출력하고 다른 텍스트는 포함하지 마세요.

        {{
          "comment_summary": "2~3문장 핵심 요약",
          "strengths": "강점1, 강점2, 강점3",
          "improvements": "개선점1, 개선점2"
        }}

        대상 연구원: {researcher_name}
        원문 코멘트:
        {comment_raw}
        \"""

        payload = {{
            "model": "사내_모델명",          # 예: "llama3-70b", "gpt-4o" 등
            "messages": [
                {{"role": "system", "content": "당신은 HR 전문 요약 어시스턴트입니다."}},
                {{"role": "user",   "content": prompt}},
            ],
            "temperature": 0.2,
            "max_tokens": 400,
        }}

        headers = {{
            "Content-Type": "application/json",
            "Authorization": f"Bearer {{API_KEY}}",
        }}

        response = requests.post(INTERNAL_LLM_URL, json=payload, headers=headers, timeout=30)
        response.raise_for_status()

        content = response.json()["choices"][0]["message"]["content"]

        import json
        result = json.loads(content)
        return {{
            "comment_summary": result.get("comment_summary", ""),
            "strengths":       result.get("strengths", ""),
            "improvements":    result.get("improvements", ""),
        }}

    [3] 사내 API 포맷이 다를 경우 payload / 응답 파싱 부분만 수정하세요.
        예) Azure OpenAI, HuggingFace Inference API, Ollama 등

    └───────────────────────────────────────────────────────────────────────────┘

    현재는 미구현 상태입니다. 위 가이드를 참고하여 사내 환경에 맞게 채워 넣으세요.
    그 전까지는 원문 앞 120자를 요약으로 사용합니다.
    """
    # ↓ 아래를 실제 LLM 호출 코드로 교체하세요
    return {
        'comment_summary': comment_raw[:120] + ('...' if len(comment_raw) > 120 else ''),
        'strengths': '(LLM 요약 미구현 — 직접 입력)',
        'improvements': '(LLM 요약 미구현 — 직접 입력)',
    }


def process(use_llm: bool = False):
    """
    comments_raw.xlsx 를 읽어 comments.csv 로 저장합니다.

    Args:
        use_llm: True 이면 summarize_with_llm() 호출. 사내 LLM 구현 후 True 로 설정하세요.
    """
    raw_path = os.path.join(DATA_RAW, 'comments_raw.xlsx')
    if not os.path.exists(raw_path):
        print(f'[SKIP] {raw_path} 파일 없음')
        return

    # xlwings로 읽어 DRM 보호 파일 지원
    df = read_xlsx(raw_path)
    required = {'researcher_id', 'year', 'comment_raw'}
    if not required.issubset(df.columns):
        raise ValueError(f'필수 컬럼 누락: {required - set(df.columns)}')

    # researchers 이름 조회 (요약 프롬프트용)
    res_path = os.path.join(DATA_OUT, 'researchers.csv')
    name_map = {}
    if os.path.exists(res_path):
        res_df = pd.read_csv(res_path, dtype={'researcher_id': str})
        name_map = res_df.set_index('researcher_id')['name'].to_dict()

    results = []
    for _, row in df.iterrows():
        raw = str(row['comment_raw'])
        name = name_map.get(row['researcher_id'], '')

        if use_llm:
            summary = summarize_with_llm(raw, name)
        else:
            summary = {
                'comment_summary': row.get('comment_summary', raw[:120] + '...'),
                'strengths': row.get('strengths', ''),
                'improvements': row.get('improvements', ''),
            }

        results.append({
            'researcher_id': row['researcher_id'],
            'year': row['year'],
            'comment_raw': raw,
            **summary,
        })

    out_df = pd.DataFrame(results)
    os.makedirs(DATA_OUT, exist_ok=True)
    out_path = os.path.join(DATA_OUT, 'comments.csv')
    out_df.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
    print(f'comments.csv 저장 완료 ({len(out_df)}행)')


if __name__ == '__main__':
    process(use_llm=False)
