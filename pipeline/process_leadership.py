"""
리더십 진단 처리 모듈

원천: source_reader.read_source('leadership')
  → DB leadership_stg 테이블 또는 data/raw_csv/leadership.csv
  (1단계 xlsx_to_raw_csv.py가 data/raw/리더십진단.xlsx를 DRM 제거해 만든 사본)
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

※ COL_ID(진단대상자ID)는 사번이 아니라 Knox ID다 — 다른 원천 파일들과
  달리 이 파일만 그렇다. 그래서 사번 8자리 zero-padding용 norm_id() 대신,
  이미 처리된 data/processed/researchers.csv의 knox_id 컬럼을 조회해
  researcher_id로 변환한다(_knox_id_map() 참고) — run_pipeline.py에서
  process_researchers가 process_leadership보다 먼저 실행되므로 이 파일이
  항상 먼저 존재한다. researchers.csv가 없거나 매칭되지 않는 Knox ID는
  경고를 남기고 제외한다.
"""

import os
import sys
from datetime import datetime

import pandas as pd

LEADERSHIP_FILE = '리더십진단.xlsx'
_LEADERSHIP_HEADER_ROW = 0  # sources.py 매니페스트 기준 (1번째 행)

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
from paths import RAW_DIR, OUT_DIR  # noqa: E402
from excel_reader import clean_str, is_blank, read_xlsx
from merge_utils import GROUP_REPLACE_KEYS, TABLE_KEYS, write_merged
from source_reader import read_source


def _knox_id_map() -> dict:
    """researchers.csv의 knox_id → researcher_id 매핑(대소문자 무시,
    앞뒤 공백 제거해서 비교). researchers.csv가 없거나 knox_id 컬럼이
    없으면 빈 dict — 호출부가 그 경우를 에러로 처리한다."""
    path = os.path.join(OUT_DIR, 'researchers.csv')
    if not os.path.exists(path):
        return {}
    r = pd.read_csv(path, encoding='utf-8-sig', dtype=str).fillna('')
    if 'knox_id' not in r.columns or 'researcher_id' not in r.columns:
        return {}
    return {
        str(knox).strip().lower(): str(rid).strip().zfill(8)
        for knox, rid in zip(r['knox_id'], r['researcher_id'])
        if str(knox).strip()
    }


def process(raw_dir: str = RAW_DIR) -> bool:
    if raw_dir == RAW_DIR:
        df = read_source('leadership')
        if df is None:
            print('[SKIP] leadership 원천 데이터 없음 '
                  '(DB leadership_stg 또는 data/raw_csv/leadership.csv) — leadership_raw 폴백 시도')
    else:
        raw_path = os.path.join(raw_dir, LEADERSHIP_FILE)
        if os.path.exists(raw_path):
            df = read_xlsx(raw_path, header_row=_LEADERSHIP_HEADER_ROW)
        else:
            df = None
            print(f'[SKIP] {LEADERSHIP_FILE} 파일 없음({raw_dir})')

    if df is None:
        return False

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

    knox_map = _knox_id_map()
    if not knox_map:
        print(
            '[ERROR] data/processed/researchers.csv에서 knox_id 매핑을 찾을 수 없습니다.\n'
            '  process_researchers를 먼저 실행하세요(run_pipeline.py는 순서를 자동으로 맞춤).'
        )
        return False

    df['researcher_id'] = df[COL_ID].apply(lambda v: knox_map.get(str(v).strip().lower(), ''))
    unmatched = sorted({str(v).strip() for v in df.loc[df['researcher_id'] == '', COL_ID] if str(v).strip()})
    if unmatched:
        shown = unmatched[:20]
        more = f' 외 {len(unmatched) - 20}건' if len(unmatched) > 20 else ''
        print(f'[WARN] Knox ID 매칭 실패 {len(unmatched)}건(제외): {shown}{more}')
    df = df[df['researcher_id'] != ''].copy()

    # 매칭 실패가 전부(또는 사실상 전부)라 남은 행이 하나도 없으면, 아래
    # groupby/점수 계산이 빈 리스트로 DataFrame을 만들다 컬럼 자체가 없어져
    # 'evaluator_group' KeyError로 죽던 버그가 있었다(2026-09-01, 실제
    # 프로덕션에서 재현·확인). Knox ID/researcher_id가 안 맞는 것 자체는
    # "그 사람 데이터를 지금 못 붙인다"는 데이터 이슈일 뿐, 파이프라인
    # 전체가 죽을 이유는 아니다(사용자 확정 — 매칭은 나중에 다시 시도해도
    # 됨) — 기존 leadership.csv/leadership_comments.csv는 그대로 두고 이번
    # 파일은 안전하게 건너뛴다.
    if df.empty:
        print(
            '[WARN] Knox ID가 researchers.csv의 knox_id와 하나도 매칭되지 않아 '
            '이번 리더십진단 파일을 반영하지 못했습니다(기존 leadership.csv는 그대로 유지).\n'
            '  확인: 리더십진단.xlsx의 "진단대상자ID" 값이 researchers.csv(인력현황)의 '
            'knox_id 컬럼과 형식이 같은지 점검하세요.'
        )
        return False

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
        if is_blank(s) and is_blank(i):
            continue
        cmt_rows.append({
            'researcher_id':   row['researcher_id'],
            'year':            row['year'],
            'commenter_type':  f'리더십_{str(row[COL_GROUP]).strip()}',
            'comment_raw':     '',
            'comment_summary': '',
            'strengths':       clean_str(s),
            'improvements':    clean_str(i),
        })
    if cmt_rows:
        cmt_df = pd.DataFrame(cmt_rows)
        cmt_path = os.path.join(OUT_DIR, 'leadership_comments.csv')
        cmt_merged = write_merged(
            cmt_path, cmt_df, GROUP_REPLACE_KEYS['leadership_comments'], group_replace=True,
        )
        print(f'[OK]   leadership_comments.csv 저장 (총 {len(cmt_merged)}행, 이번 파일 {len(cmt_df)}행으로 해당 (연구원,연도,그룹) 통째 교체) '
              f'— process_comments가 comments.csv에 병합')

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

    out_path = os.path.join(OUT_DIR, 'leadership.csv')
    merged = write_merged(out_path, result, TABLE_KEYS['leadership'])

    n = merged['researcher_id'].nunique()
    groups = sorted(merged['evaluator_group'].unique())
    print(f'[OK]   leadership.csv 저장 (총 {len(merged)}행, {n}명, 그룹: {groups}, 이번 파일 {len(result)}행 반영)')
    return True


if __name__ == '__main__':
    process()
