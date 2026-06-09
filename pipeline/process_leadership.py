"""
리더십 진단 처리 모듈

원천 파일: data/raw/리더십진단.xlsx
출력 파일:
  data/processed/leadership.csv          — 그룹별 역량 점수
  data/processed/leadership_comments.csv — 강점·개선점 주관식

진단 문항 구성 (총 28문항):
  미래통찰 : 1 ~ 4
  성과창출 : 5 ~ 8
  몰입촉진 : 9 ~ 12
  인재육성 : 13 ~ 16
  자기관리 : 17 ~ 20
  저해행동 : 21 ~ 26
  (27·28번은 역량 분류 외)

leadership.csv 컬럼:
  researcher_id, year, evaluator_group,
  미래통찰, 성과창출, 몰입촉진, 인재육성, 자기관리, 저해행동

  evaluator_group 값: 본인 / 동료 / 상사 / 부서원 / 타인평균(동료+상사+부서원 평균)

leadership_comments.csv 컬럼:
  researcher_id, year, evaluator_group, strength, improvement

  ※ 평가자 1인 1행으로 저장 — 같은 연구원·그룹에 여러 평가자의 응답이
    각 행으로 보존됩니다. 화면에서는 그룹별로 묶어 표시하면 됩니다.

컬럼명이 다를 경우 파일 상단의 COL_* 상수를 수정하세요.
"""

import csv
import os
import sys
from datetime import datetime

import pandas as pd

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'raw')
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed')

LEADERSHIP_FILE = '리더십진단.xlsx'

# ── 컬럼명 설정 (파일 헤더와 다를 경우 여기서 수정) ──────────────────────────
COL_ID    = '진단대상자ID'
COL_GROUP = '평가자그룹명'
COL_YEAR  = ''                    # 연도 컬럼명 (없으면 DEFAULT_YEAR 사용)
COL_STR   = '강점'
COL_IMP   = '개선점'
DEFAULT_YEAR = datetime.now().year
# ─────────────────────────────────────────────────────────────────────────────

COMPETENCY = {
    '미래통찰': [str(i) for i in range(1, 5)],
    '성과창출': [str(i) for i in range(5, 9)],
    '몰입촉진': [str(i) for i in range(9, 13)],
    '인재육성': [str(i) for i in range(13, 17)],
    '자기관리': [str(i) for i in range(17, 21)],
    '저해행동': [str(i) for i in range(21, 27)],
}
DIMS = list(COMPETENCY.keys())
OTHERS_GROUPS = {'동료', '상사', '부서원'}

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from excel_reader import read_xlsx, norm_id


def process() -> bool:
    raw_path = os.path.join(RAW_DIR, LEADERSHIP_FILE)
    if not os.path.exists(raw_path):
        print(f'[SKIP] {LEADERSHIP_FILE} 파일 없음 — leadership_raw 폴백 시도')
        return False

    df = read_xlsx(raw_path)

    # 컬럼명 정규화: xlwings가 숫자 헤더를 float로 읽으면 '1.0' → '1' 변환
    def _norm_col(c):
        s = str(c).strip()
        try:
            f = float(s)
            if f == int(f):
                return str(int(f))
        except (ValueError, TypeError):
            pass
        return s

    df.columns = [_norm_col(c) for c in df.columns]

    # 읽은 컬럼 목록 출력 (매칭 오류 진단용)
    found_q = [c for c in df.columns if c in [str(i) for i in range(1, 29)]]
    print(f'  [진단] 인식된 문항 컬럼: {found_q if found_q else "없음 — 컬럼명 확인 필요"}'
          f'\n         전체 헤더 앞 10개: {list(df.columns[:10])}')

    for required in [COL_ID, COL_GROUP]:
        if required not in df.columns:
            print(
                f'[ERROR] 필수 컬럼 없음: [{required}]\n'
                f'  process_leadership.py 상단의 COL_* 상수를 수정하세요.\n'
                f'  현재 파일 헤더: {list(df.columns)}'
            )
            return False

    df['researcher_id'] = df[COL_ID].apply(norm_id)
    df = df[df['researcher_id'] != ''].copy()

    # 연도
    if COL_YEAR and COL_YEAR in df.columns:
        df['year'] = pd.to_numeric(df[COL_YEAR], errors='coerce').fillna(DEFAULT_YEAR).astype(int)
    else:
        df['year'] = DEFAULT_YEAR

    # 문항 컬럼 숫자 변환 (문자열·float 모두 처리)
    q_all = [str(i) for i in range(1, 29)]
    for c in q_all:
        if c in df.columns:
            df[c] = df[c].apply(
                lambda v: pd.to_numeric(str(v).strip().replace(',', '.'), errors='coerce')
                if v is not None else None
            )

    # ── 강점·개선점 저장 (comments.csv 통합 스키마) ──────────────────────────
    # 평가자 1인 1행으로 보존 (같은 그룹의 여러 평가자 응답이 각 행에 저장됨)
    # commenter_type = '리더십_<평가자그룹>' 형식으로 저장 → process_comments가 병합
    cmt_rows = []
    for _, row in df.iterrows():
        s = str(row.get(COL_STR, '')).strip() if COL_STR in df.columns else ''
        i = str(row.get(COL_IMP,  '')).strip() if COL_IMP  in df.columns else ''
        if s in ('', 'nan', 'None') and i in ('', 'nan', 'None'):
            continue
        cmt_rows.append({
            'researcher_id':   row['researcher_id'],
            'year':            row['year'],
            'commenter_type':  f'리더십_{str(row[COL_GROUP]).strip()}',
            'comment_raw':     '',
            'comment_summary': '',
            'strengths':       '' if s in ('nan', 'None') else s,
            'improvements':    '' if i in ('nan', 'None') else i,
        })
    if cmt_rows:
        cmt_df = pd.DataFrame(cmt_rows)
        cmt_path = os.path.join(OUT_DIR, 'leadership_comments.csv')
        os.makedirs(OUT_DIR, exist_ok=True)
        cmt_df.to_csv(cmt_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
        print(f'[OK]   leadership_comments.csv 저장 ({len(cmt_df)}행) — process_comments가 comments.csv에 병합')

    # ── 역량 점수 계산 ───────────────────────────────────────────────────────
    # 같은 (연구원, 연도, 그룹) 내 여러 평가자 → 문항별 평균 먼저 산출
    grp_cols = ['researcher_id', 'year', COL_GROUP]
    avail_q  = [c for c in q_all if c in df.columns]
    agg = df.groupby(grp_cols)[avail_q].mean().reset_index()
    agg = agg.rename(columns={COL_GROUP: 'evaluator_group'})

    score_rows = []
    for _, row in agg.iterrows():
        d = {
            'researcher_id':   row['researcher_id'],
            'year':            row['year'],
            'evaluator_group': str(row['evaluator_group']).strip(),
        }
        for dim, qs in COMPETENCY.items():
            valid = [row[q] for q in qs if q in agg.columns and pd.notna(row[q])]
            d[dim] = round(sum(valid) / len(valid), 2) if valid else None
        score_rows.append(d)

    scores = pd.DataFrame(score_rows)

    # 타인평균 행 추가 (동료+상사+부서원의 역량 점수 평균)
    others = scores[scores['evaluator_group'].isin(OTHERS_GROUPS)]
    if not others.empty:
        avg = (others.groupby(['researcher_id', 'year'])[DIMS]
               .mean().round(2).reset_index())
        avg['evaluator_group'] = '타인평균'
        scores = pd.concat([scores, avg], ignore_index=True)

    result = (scores
              .sort_values(['researcher_id', 'year', 'evaluator_group'])
              .reset_index(drop=True))

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'leadership.csv')
    result.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)

    n = result['researcher_id'].nunique()
    groups = sorted(result['evaluator_group'].unique())
    print(f'[OK]   leadership.csv 저장 ({len(result)}행, {n}명, 그룹: {groups})')
    return True


if __name__ == '__main__':
    process()
