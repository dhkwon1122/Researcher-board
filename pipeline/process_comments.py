"""
코멘트 처리 모듈

처리 흐름:
  source_reader.read_source('comments')   — 부서장 코멘트 (선택)
    → DB comments_stg 테이블 또는 data/raw_csv/comments.csv
    (1단계 xlsx_to_raw_csv.py가 data/raw/comments_raw.xlsx를 DRM 제거해 만든 사본)
  data/processed/leadership_comments.csv — 리더십진단 강점·개선점 (process_leadership이 생성)
  ↓
  data/processed/comments.csv       — 모든 코멘트 통합
  (commenter_type='종합요약' 행에 연구원별 LLM 통합 요약 포함)

사용법:
  python pipeline/process_comments.py           # LLM 요약 없이 실행
  python pipeline/process_comments.py --llm     # LLM 통합 요약 포함
"""

import json
import os
import sys

import pandas as pd

# pipeline 디렉터리 + 프로젝트 루트를 path 에 추가 (llm_client/services 임포트용)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import llm_client  # noqa: E402
from paths import RAW_DIR as DATA_RAW, OUT_DIR as DATA_OUT  # noqa: E402
from excel_reader import is_blank, read_xlsx, norm_researcher_id_col
from merge_utils import TABLE_KEYS, write_merged
from source_reader import read_source

COLS = ['researcher_id', 'year', 'commenter_type',
        'comment_raw', 'comment_summary', 'strengths', 'improvements']

_SYSTEM_PROMPT = '당신은 HR 전문 요약 어시스턴트입니다. 요청한 JSON 형식만 출력하세요.'


def _call_llm(prompt: str) -> str:
    """사내 LLM(OpenAI 호환) 호출 → 응답 텍스트. 실패 시 빈 문자열.

    pipeline/llm_client.py 의 call_llm() 을 재사용한다 — 배치 파이프라인
    나머지(process_researcher_expertise.py 등)와 동일하게 동시 호출 제한
    (세마포어)/재시도가 적용된다. 설정은 .env의 LLM2_*(.env.example 참고).
    """
    return llm_client.call_llm(prompt, _SYSTEM_PROMPT, temperature=0.2, max_tokens=1200)


def summarize_with_llm(comment_raw: str) -> dict:
    """단일 부서장 코멘트 → 요약 dict (comment_summary / strengths / improvements).
    프롬프트에는 researcher_id/이름 등 개인 식별 정보를 절대 포함하지 않는다.
    코멘트 원문(content)만 LLM에 전달하고, 결과는 호출부에서 researcher_id에 매핑한다."""
    if not comment_raw.strip():
        return {'comment_summary': '', 'strengths': '', 'improvements': ''}

    prompt = f"""아래 코멘트를 다음 JSON 형식으로 요약하세요. JSON 외 텍스트는 출력하지 마세요.

{{
  "comment_summary": "2~3문장 핵심 요약",
  "strengths": "강점1, 강점2, 강점3",
  "improvements": "개선점1, 개선점2"
}}

코멘트:
{comment_raw}"""

    # 추론형 모델의 사고 과정 토큰 소모를 감안해 여유 있게 잡는다.
    raw = _call_llm(prompt)
    if not raw:
        return {
            'comment_summary': comment_raw[:120] + ('...' if len(comment_raw) > 120 else ''),
            'strengths': '', 'improvements': '',
        }
    try:
        result = json.loads(llm_client.extract_json(raw))
        return {
            'comment_summary': result.get('comment_summary', ''),
            'strengths':       result.get('strengths', ''),
            'improvements':    result.get('improvements', ''),
        }
    except json.JSONDecodeError:
        return {'comment_summary': raw[:200], 'strengths': '', 'improvements': ''}


def summarize_researcher(rid: str, rows: pd.DataFrame) -> dict | None:
    """
    한 연구원의 모든 코멘트(부서장 + 리더십진단)를 통합 요약.
    종합요약 행으로 저장할 dict 반환. LLM 실패 시 None.
    프롬프트에는 researcher_id/이름 등 개인 식별 정보를 절대 포함하지 않는다.
    코멘트 내용(content)만 사내 LLM에 전달하고, 결과는 호출부에서 rid에 매핑한다.
    """
    parts = []

    # 부서장 코멘트
    mgr = rows[rows['commenter_type'] == '부서장']
    for _, r in mgr.iterrows():
        raw = str(r.get('comment_raw', '')).strip()
        if not is_blank(raw):
            yr = str(r.get('year', ''))
            parts.append(f'[{yr} 부서장] {raw}')

    # 리더십 진단 강점·개선점
    lea = rows[rows['commenter_type'].str.startswith('리더십_', na=False)]
    for _, r in lea.iterrows():
        c_type = str(r.get('commenter_type', ''))
        s = str(r.get('strengths', '')).strip()
        i = str(r.get('improvements', '')).strip()
        yr = str(r.get('year', ''))
        if not is_blank(s):
            parts.append(f'[{yr} {c_type} 강점] {s}')
        if not is_blank(i):
            parts.append(f'[{yr} {c_type} 개선점] {i}')

    if not parts:
        return None

    combined = '\n'.join(parts)
    prompt = f"""아래는 한 연구원에 대한 평가자별 코멘트 모음입니다.
전체 내용을 종합하여 다음 JSON 형식으로 요약하세요. JSON 외 텍스트는 출력하지 마세요.

{{
  "comment_summary": "이 연구원의 전반적인 특징을 3~5문장으로 요약",
  "strengths": "핵심 강점 3~5가지를 간결하게 나열 (쉼표 구분)",
  "improvements": "주요 개선 필요 사항 2~3가지 (쉼표 구분)"
}}

평가 내용:
{combined}"""

    # 추론형 모델의 사고 과정 토큰 소모를 감안해 여유 있게 잡는다.
    raw = _call_llm(prompt)
    if not raw:
        return None
    try:
        result = json.loads(llm_client.extract_json(raw))
        # year는 가장 최근 연도 사용
        try:
            latest_year = int(rows['year'].dropna().astype(str).str.extract(r'(\d{4})')[0].max())
        except Exception:
            latest_year = ''
        return {
            'researcher_id':   rid,
            'year':            latest_year,
            'commenter_type':  '종합요약',
            'comment_raw':     '',
            'comment_summary': result.get('comment_summary', ''),
            'strengths':       result.get('strengths', ''),
            'improvements':    result.get('improvements', ''),
        }
    except json.JSONDecodeError:
        return None


def process(use_llm: bool = False, raw_dir: str = DATA_RAW):
    """
    comments_raw.xlsx + leadership_comments.csv → comments.csv

    Args:
        use_llm: True 이면 LLM API를 호출하여 연구원별 종합요약 생성.
                 False 이면 종합요약 없이 원본 코멘트만 저장.
        raw_dir: comments_raw.xlsx를 찾을 폴더(기본 data/raw, data/updates로 갱신 가능).
    """
    results = []

    # ── 부서장 코멘트 ──────────────────────────────────────────────────────
    # 기본 raw_dir(data/raw)이면 DB 스테이징/raw_csv 우선인 source_reader를
    # 쓰고, run_update.py처럼 raw_dir이 명시적으로 오버라이드되면(예: data/
    # updates) 그 폴더의 xlsx를 직접 읽는다.
    if raw_dir == DATA_RAW:
        df = read_source('comments')
    else:
        raw_path = os.path.join(raw_dir, 'comments_raw.xlsx')
        df = read_xlsx(raw_path) if os.path.exists(raw_path) else None

    if df is not None:
        df = norm_researcher_id_col(df)
        required = {'researcher_id', 'year', 'comment_raw'}
        if not required.issubset(df.columns):
            print(f'[WARN] comments 원천 필수 컬럼 누락: {required - set(df.columns)}')
        else:
            for _, row in df.iterrows():
                raw = str(row['comment_raw'])
                if use_llm:
                    summary = summarize_with_llm(raw)
                else:
                    summary = {
                        'comment_summary': str(row.get('comment_summary', raw[:120] + '...')),
                        'strengths':       str(row.get('strengths', '')),
                        'improvements':    str(row.get('improvements', '')),
                    }
                results.append({
                    'researcher_id':  str(row['researcher_id']),
                    'year':           row['year'],
                    'commenter_type': str(row.get('commenter_type', '부서장')),
                    'comment_raw':    raw,
                    **summary,
                })
            print(f'  부서장 코멘트 {len(df)}행 처리')
    else:
        print('[SKIP] comments 원천 데이터 없음 (DB comments_stg 또는 data/raw_csv/comments.csv)')

    out_df = pd.DataFrame(results)

    # ── 리더십진단 강점·개선점 병합 ──────────────────────────────────────────
    lea_path = os.path.join(DATA_OUT, 'leadership_comments.csv')
    if os.path.exists(lea_path):
        lea_df = pd.read_csv(lea_path, encoding='utf-8-sig', dtype={'researcher_id': str})
        lea_df['researcher_id'] = lea_df['researcher_id'].astype(str).str.zfill(8)
        out_df = pd.concat([out_df, lea_df], ignore_index=True)
        print(f'  리더십진단 코멘트 {len(lea_df)}행 병합')

    for c in COLS:
        if c not in out_df.columns:
            out_df[c] = ''
    out_df = out_df[COLS].copy()

    # ── 연구원별 종합요약 (LLM) ───────────────────────────────────────────────
    if use_llm and not out_df.empty:
        res_path = os.path.join(DATA_OUT, 'researchers.csv')
        name_map = {}
        if os.path.exists(res_path):
            res_df = pd.read_csv(res_path, dtype={'researcher_id': str})
            name_map = res_df.set_index('researcher_id')['name'].to_dict()

        summary_rows = []
        rids = out_df['researcher_id'].unique()
        print(f'  연구원별 종합요약 생성 중 ({len(rids)}명)...')
        for rid in rids:
            name = name_map.get(rid, rid)
            r_rows = out_df[out_df['researcher_id'] == rid]
            summary = summarize_researcher(rid, r_rows)
            if summary:
                summary_rows.append(summary)
                print(f'    [{rid}] {name} 종합요약 완료')
            else:
                print(f'    [{rid}] {name} 종합요약 실패 또는 코멘트 없음')

        if summary_rows:
            out_df = pd.concat([out_df, pd.DataFrame(summary_rows)], ignore_index=True)
            print(f'  종합요약 {len(summary_rows)}건 추가')

    out_df = (out_df[COLS]
              .sort_values(['researcher_id', 'commenter_type', 'year'])
              .reset_index(drop=True))

    out_path = os.path.join(DATA_OUT, 'comments.csv')
    merged = write_merged(out_path, out_df, TABLE_KEYS['comments'])
    print(f'comments.csv 저장 완료 (총 {len(merged)}행, 이번 실행 {len(out_df)}행 반영)')


if __name__ == '__main__':
    import sys as _sys
    process(use_llm='--llm' in _sys.argv)
