"""
코멘트 처리 모듈

처리 흐름:
  data/raw/comments_raw.xlsx        — 부서장 코멘트 (선택)
  data/processed/leadership_comments.csv — 리더십진단 강점·개선점 (process_leadership이 생성)
  ↓
  data/processed/comments.csv       — 모든 코멘트 통합
  (commenter_type='종합요약' 행에 연구원별 LLM 통합 요약 포함)

사용법:
  python pipeline/process_comments.py           # LLM 요약 없이 실행
  python pipeline/process_comments.py --llm     # LLM 통합 요약 포함
"""

import csv
import json
import os
import re
import sys
import uuid

import pandas as pd

DATA_RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'raw')
DATA_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from excel_reader import read_xlsx, norm_researcher_id_col

# ── 사내 LLM 설정: pipeline/llm_config.py 에서 로드 ─────────────────────────
try:
    import llm_config as _cfg
except ModuleNotFoundError:
    print('[WARN] pipeline/llm_config.py 없음 — llm_config.example.py를 복사 후 값을 채워주세요.')
    _cfg = None  # type: ignore

COLS = ['researcher_id', 'year', 'commenter_type',
        'comment_raw', 'comment_summary', 'strengths', 'improvements']


def _parse_sse(text: str) -> str:
    """SSE(text/event-stream) 응답에서 content 조각을 이어붙여 반환."""
    parts = []
    for line in text.splitlines():
        if not line.startswith('data:'):
            continue
        data = line[5:].strip()
        if data == '[DONE]':
            break
        try:
            chunk = json.loads(data)
            piece = chunk['choices'][0].get('delta', {}).get('content', '')
            if piece:
                parts.append(piece)
        except (json.JSONDecodeError, KeyError, IndexError):
            continue
    return ''.join(parts)


def _extract_json(text: str) -> str:
    """응답 텍스트에서 첫 번째 JSON 객체 블록만 추출."""
    # 코드 펜스 제거 (``` json, ```json, ``` 모두)
    text = re.sub(r'```(?:json)?', '', text).replace('```', '').strip()
    m = re.search(r'\{[\s\S]*\}', text)
    return m.group(0) if m else text


def _call_llm(prompt: str) -> str:
    """사내 LLM API 호출 → 응답 텍스트 반환. 실패 시 빈 문자열."""
    if _cfg is None:
        print('  [LLM 오류] llm_config.py 가 없어 API 호출을 건너뜁니다.')
        return ''

    import requests

    headers = {
        'Content-Type':      _cfg.CONTENT_TYPE,
        'Accept':            _cfg.ACCEPT,
        'x-dep-ticket':      _cfg.LLM_API_KEY,
        'Send-System-Name':  _cfg.SEND_SYSTEM_NAME,
        'User-Id':           _cfg.USER_ID,
        'User-Type':         _cfg.USER_TYPE,
        'Prompt-Msg-Id':     str(uuid.uuid4()),
        'Completion-Msg-Id': str(uuid.uuid4()),
    }
    payload = {
        'model': _cfg.LLM_MODEL,
        'messages': [
            {'role': 'system', 'content': '당신은 HR 전문 요약 어시스턴트입니다. 요청한 JSON 형식만 출력하세요.'},
            {'role': 'user',   'content': prompt},
        ],
        'temperature': 0.2,
        'max_tokens':  1200,
    }
    try:
        resp = requests.post(_cfg.LLM_API_URL, json=payload, headers=headers, timeout=_cfg.LLM_TIMEOUT)
        resp.raise_for_status()
        ct = resp.headers.get('Content-Type', '')
        if 'event-stream' in ct:
            return _parse_sse(resp.text)
        return resp.json()['choices'][0]['message']['content'].strip()
    except requests.HTTPError as exc:
        status = exc.response.status_code
        body   = exc.response.text[:300]
        print(f'  [LLM HTTP 오류] {status} — {body}')
        return ''
    except Exception as exc:
        print(f'  [LLM 오류] {type(exc).__name__}: {exc}')
        return ''


def summarize_with_llm(comment_raw: str, researcher_name: str = '') -> dict:
    """단일 부서장 코멘트 → 요약 dict (comment_summary / strengths / improvements)."""
    if not comment_raw.strip():
        return {'comment_summary': '', 'strengths': '', 'improvements': ''}

    prompt = f"""아래 코멘트를 다음 JSON 형식으로 요약하세요. JSON 외 텍스트는 출력하지 마세요.

{{
  "comment_summary": "2~3문장 핵심 요약",
  "strengths": "강점1, 강점2, 강점3",
  "improvements": "개선점1, 개선점2"
}}

대상 연구원: {researcher_name}
코멘트:
{comment_raw}"""

    raw = _call_llm(prompt)
    if not raw:
        return {
            'comment_summary': comment_raw[:120] + ('...' if len(comment_raw) > 120 else ''),
            'strengths': '', 'improvements': '',
        }
    try:
        result = json.loads(_extract_json(raw))
        return {
            'comment_summary': result.get('comment_summary', ''),
            'strengths':       result.get('strengths', ''),
            'improvements':    result.get('improvements', ''),
        }
    except json.JSONDecodeError:
        return {'comment_summary': raw[:200], 'strengths': '', 'improvements': ''}


def summarize_researcher(rid: str, name: str, rows: pd.DataFrame) -> dict | None:
    """
    한 연구원의 모든 코멘트(부서장 + 리더십진단)를 통합 요약.
    종합요약 행으로 저장할 dict 반환. LLM 실패 시 None.
    """
    parts = []

    # 부서장 코멘트
    mgr = rows[rows['commenter_type'] == '부서장']
    for _, r in mgr.iterrows():
        raw = str(r.get('comment_raw', '')).strip()
        if raw and raw not in ('nan', 'None'):
            yr = str(r.get('year', ''))
            parts.append(f'[{yr} 부서장] {raw}')

    # 리더십 진단 강점·개선점
    lea = rows[rows['commenter_type'].str.startswith('리더십_', na=False)]
    for _, r in lea.iterrows():
        c_type = str(r.get('commenter_type', ''))
        s = str(r.get('strengths', '')).strip()
        i = str(r.get('improvements', '')).strip()
        yr = str(r.get('year', ''))
        if s and s not in ('nan', 'None'):
            parts.append(f'[{yr} {c_type} 강점] {s}')
        if i and i not in ('nan', 'None'):
            parts.append(f'[{yr} {c_type} 개선점] {i}')

    if not parts:
        return None

    combined = '\n'.join(parts)
    prompt = f"""아래는 연구원 {name}에 대한 평가자별 코멘트 모음입니다.
전체 내용을 종합하여 다음 JSON 형식으로 요약하세요. JSON 외 텍스트는 출력하지 마세요.

{{
  "comment_summary": "이 연구원의 전반적인 특징을 3~5문장으로 요약",
  "strengths": "핵심 강점 3~5가지를 간결하게 나열 (쉼표 구분)",
  "improvements": "주요 개선 필요 사항 2~3가지 (쉼표 구분)"
}}

평가 내용:
{combined}"""

    raw = _call_llm(prompt)
    if not raw:
        return None
    try:
        result = json.loads(_extract_json(raw))
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


def process(use_llm: bool = False):
    """
    comments_raw.xlsx + leadership_comments.csv → comments.csv

    Args:
        use_llm: True 이면 LLM API를 호출하여 연구원별 종합요약 생성.
                 False 이면 종합요약 없이 원본 코멘트만 저장.
    """
    results = []

    # ── 부서장 코멘트 (comments_raw.xlsx) ────────────────────────────────────
    raw_path = os.path.join(DATA_RAW, 'comments_raw.xlsx')
    if os.path.exists(raw_path):
        df = norm_researcher_id_col(read_xlsx(raw_path))
        required = {'researcher_id', 'year', 'comment_raw'}
        if not required.issubset(df.columns):
            print(f'[WARN] comments_raw.xlsx 필수 컬럼 누락: {required - set(df.columns)}')
        else:
            # researchers 이름 조회
            res_path = os.path.join(DATA_OUT, 'researchers.csv')
            name_map = {}
            if os.path.exists(res_path):
                res_df = pd.read_csv(res_path, dtype={'researcher_id': str})
                name_map = res_df.set_index('researcher_id')['name'].to_dict()

            for _, row in df.iterrows():
                raw = str(row['comment_raw'])
                name = name_map.get(str(row['researcher_id']), '')
                if use_llm:
                    summary = summarize_with_llm(raw, name)
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
        print(f'[SKIP] comments_raw.xlsx 없음')

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
            summary = summarize_researcher(rid, name, r_rows)
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

    os.makedirs(DATA_OUT, exist_ok=True)
    out_path = os.path.join(DATA_OUT, 'comments.csv')
    out_df.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
    print(f'comments.csv 저장 완료 ({len(out_df)}행)')


if __name__ == '__main__':
    import sys as _sys
    process(use_llm='--llm' in _sys.argv)
