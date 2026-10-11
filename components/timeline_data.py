"""
연구원 프로필 타임라인/실적 탭에서 공유하는 원천 데이터 가공 유틸리티.
detail_tabs.py(과제·논문·특허 탭)와 timeline_view.py(타임라인 카드) 양쪽에서 사용한다.
"""

from datetime import datetime

import pandas as pd

from pipeline.excel_reader import clean_str as clean, is_blank


def parse_ts(val):
    s = str(val).strip() if val is not None else ''
    if is_blank(s):
        return None
    try:
        return pd.Timestamp(s)
    except (ValueError, TypeError):
        return None


def cell(row, *keys, default='-'):
    for key in keys:
        value = str(row.get(key, ''))
        if value and value not in ('', 'nan', 'None'):
            return value
    return default


def is_registered(value):
    return '등록' in str(value)


def truncate(text, maxlen=30):
    """maxlen을 넘으면 단어 중간을 자르지 않고 단어 경계에서 잘라 '...'을 붙인다."""
    text = str(text).strip()
    if len(text) <= maxlen:
        return text
    cut = text[:maxlen]
    if ' ' in cut:
        cut = cut.rsplit(' ', 1)[0]
    return cut.rstrip() + '...'


def yymm(ts):
    return ts.strftime('%y.%m') if isinstance(ts, pd.Timestamp) else ''


def task_points(task_df):
    if task_df.empty:
        return []
    today = pd.Timestamp(datetime.now().date())
    points = []
    from services.task_history import close_stale_open_rows
    rows = close_stale_open_rows(task_df.to_dict('records'), close_with='start')
    for row in rows:
        start = parse_ts(row.get('start_date'))
        if start is None:
            continue
        end_raw = row.get('end_date')
        end = parse_ts(end_raw)
        end_label = end.strftime('%Y-%m-%d') if end is not None else '진행중'
        ongoing = end is None or end < start
        if ongoing:
            end = today
        # 참여기간 30일 이하의 짧은 과제는 제외하되, 진행중인 과제는 방금 시작했어도
        # 항상 보여준다(2026-10-08 — 10월 1일 시작 과제가 30일 규칙 때문에 빠지던 문제).
        if not ongoing and (end - start).days <= 30:
            continue
        # the_task_name(pipeline/process_tasks.py가 tasks_information.csv 개명
        # 이력으로 보정한, 참여 당시 실제 과제명)이 있으면 그걸 쓰고, 없으면
        # (구버전 CSV/매핑 실패 폴백) 원본 task_name.
        the_name = clean(row.get('the_task_name', ''))
        name = the_name or str(row.get('task_name', '')).strip()
        points.append({
            'task_name': name,
            'start': start,
            'end': end,
            'start_label': start.strftime('%Y-%m-%d'),
            'end_label': end_label,
        })
    points.sort(key=lambda p: p['start'])
    return points


def job_points(job_df):
    """job_df: researcher_id로 필터링된 job_profile 행(0~1개). wide 포맷
    (job_profile_name_1..N, job_start_date_1..N, job_end_date_1..N)을 슬롯별로
    풀어서 [{'name','start','end'}, ...]로 반환한다. end=None은 진행중(종료일 없음)."""
    if job_df.empty:
        return []
    row = job_df.iloc[0]
    slot_idxs = sorted({
        int(c.rsplit('_', 1)[1]) for c in job_df.columns
        if c.startswith('job_profile_name_') and c.rsplit('_', 1)[1].isdigit()
    })
    points = []
    for i in slot_idxs:
        name = clean(row.get(f'job_profile_name_{i}', ''))
        start = parse_ts(row.get(f'job_start_date_{i}'))
        if not name or start is None:
            continue
        end = parse_ts(row.get(f'job_end_date_{i}'))
        points.append({'name': name, 'start': start, 'end': end})
    points.sort(key=lambda p: p['start'])
    return points


def hr_points(hr_df):
    if hr_df.empty:
        return []
    points = []
    for _, row in hr_df.iterrows():
        date = parse_ts(row.get('order_date'))
        if date is None:
            continue
        points.append({
            'date': date,
            'order_date': clean(row.get('order_date', '')),
            'order_name': clean(row.get('order_name', '')),
            'order_dep': clean(row.get('order_dep', '')),
            'order_cl': clean(row.get('order_cl', '')),
            'order_assignment': clean(row.get('order_assignment', '')),
        })
    points.sort(key=lambda p: p['date'])
    return points


def pub_points(pub_df):
    if pub_df.empty:
        return []
    points = []
    for _, row in pub_df.iterrows():
        pub_date = str(row.get('pub_date', '')).strip()
        if not pub_date or pub_date in ('nan', 'None'):
            pub_year = str(row.get('pub_year', '')).strip()
            pub_date = f'{pub_year}-01-01' if pub_year and pub_year not in ('nan', 'None') else ''
        date = parse_ts(pub_date)
        if date is None:
            continue
        points.append({
            'date': date,
            'title': str(row.get('title', '')).strip(),
            'journal': clean(row.get('journal', '')),
            'author_type': clean(row.get('author_type', '')),
            'contribution': clean(row.get('contribution', '')),
            'project_name': clean(row.get('project_name', '')),
            'project_code': clean(row.get('project_code', '')),
        })
    points.sort(key=lambda p: p['date'])
    return points


def pat_points(pat_df):
    if pat_df.empty:
        return []
    points = []
    for _, row in pat_df.iterrows():
        app_date = clean(row.get('application_date', ''))
        reg_date = clean(row.get('registration_date', ''))
        date = parse_ts(reg_date if reg_date else app_date)
        if date is None:
            continue
        title = patent_title(row)
        grade = clean(row.get('patent_grade', ''))
        grade_a = clean(row.get('patent_grade_a_sub', ''))
        grade_a = grade_a if grade_a == '전략출원' else ''  # 전략출원일 때만 표기(2026-10)
        share = clean(row.get('share_ratio', ''))
        is_lead = clean(row.get('is_lead_inventor', ''))
        points.append({
            'date': date,
            'title': title,
            'grade': grade,
            'grade_a': grade_a,
            'share': share,
            'is_lead': is_lead,
            'project_name': clean(row.get('project_name', '')),
            'project_code': clean(row.get('project_code', '')),
        })
    points.sort(key=lambda p: p['date'])
    return points


def task_code_map(tasks_info_df) -> dict:
    """task_name → task_code. tasks_information.csv(process_task_information.py)를
    과제명 기준 다리 삼아, patents.csv/publications.csv의 project_code와 tasks.csv의
    과제(task_name)를 연결하는 데 쓴다. 과제명 하나에 코드 하나로 가정."""
    if tasks_info_df is None or tasks_info_df.empty:
        return {}
    if 'task_name' not in tasks_info_df.columns or 'task_code' not in tasks_info_df.columns:
        return {}
    df = tasks_info_df.drop_duplicates('task_name')
    result = {}
    for _, row in df.iterrows():
        name = clean(row.get('task_name', ''))
        if name:
            result[name] = clean(row.get('task_code', ''))
    return result


def linked_task_names(project_name: str, project_code: str, task_names: set, code_map: dict) -> list:
    """특허/논문 한 건의 project_name/project_code가 이 연구원의 어떤 과제
    (task_name)에 연결되는지 반환. 과제코드가 있으면 코드로 우선 매칭하고,
    코드가 없거나 일치하는 과제가 없으면 과제명 문자열 일치로 폴백한다.
    연결된 과제가 없으면 빈 리스트(= 회색 아이콘으로 표시할 항목)."""
    code = clean(project_code)
    name = clean(project_name)

    if code:
        matched = [t for t in task_names if code_map.get(t) == code]
        if matched:
            return matched
    if name and name in task_names:
        return [name]
    return []


def dedupe_patents(pat):
    id_col = 'application_id' if 'application_id' in pat.columns else None
    if not id_col:
        return pat.copy()

    def _merge_countries(series):
        seen = {}
        for value in series:
            text = str(value).strip()
            if text in ('', 'nan', 'None', '-'):
                continue
            for part in text.split(','):
                part = part.strip()
                if part:
                    seen[part] = None
        return ', '.join(seen.keys()) if seen else '-'

    def _agg_status(series):
        values = series.astype(str).tolist()
        for value in values:
            if is_registered(value):
                return value
        return values[0] if values else ''

    def _first_filled(series):
        for value in series:
            if not is_blank(value):
                return value
        return ''

    agg_dict = {col: 'first' for col in pat.columns if col not in (id_col, 'researcher_id', 'country', 'status')}
    # 출원번호/등록번호는 국가별 행 중 값이 있는 첫 행을 쓴다 — 출원·등록 건수를
    # "번호 유무"로 세므로(2026-10) 첫 행이 비어 있다고 번호가 없는 것으로
    # 오인되면 안 된다.
    for col in ('application_no', 'registration_no'):
        if col in pat.columns:
            agg_dict[col] = _first_filled
    if 'status' in pat.columns:
        agg_dict['status'] = _agg_status
    if 'country' in pat.columns:
        agg_dict['country'] = _merge_countries
    return pat.groupby(id_col, sort=False).agg(agg_dict).reset_index()


def patent_title(row):
    """발명 명칭 표시값 — 국문(title_ko)을 우선하고 비어 있으면 영문(title)으로
    대체한다(2026-10, 사용자 확정)."""
    return cell(row, 'title_ko', 'title')


def is_strategic_patent(row):
    """'현재등급 - A급구분'(patent_grade_a_sub)이 '전략출원'인 건."""
    return str(row.get('patent_grade_a_sub', '')).strip() == '전략출원'


def _has_number(df, col):
    if col not in df.columns:
        return pd.Series(False, index=df.index)
    return ~df[col].apply(is_blank)


def _share_total(df):
    if df.empty or 'share_ratio' not in df.columns:
        return '-'
    shares = pd.to_numeric(df['share_ratio'], errors='coerce').dropna()
    return f'{round(shares.sum(), 1)}%' if not shares.empty else '-'


def patent_summary(pat_dedup):
    """dedupe_patents() 결과(기술건 Y만 남은 접수ID당 1건)에서 특허 요약 수치를
    한 곳에서 계산한다 — 프로필 특허 탭/인쇄본/명단/엑셀이 같은 정의를 쓰도록.
      total          : 전체 발명 수
      lead           : 대표 발명 수(대표발명자여부 Y)
      applied        : 출원 수(출원번호가 있는 건)
      registered     : 등록 수(등록번호가 있는 건 — 출원번호도 있는 건만)
      applied_share  : 출원 건 지분율 합계('12.3%' 또는 '-')
      strategic      : 전략출원 수(A급구분 == '전략출원')
      strategic_share: 전략출원 건 지분율 합계"""
    if pat_dedup.empty:
        return {'total': 0, 'lead': 0, 'applied': 0, 'registered': 0,
                'applied_share': '-', 'strategic': 0, 'strategic_share': '-'}
    applied_mask = _has_number(pat_dedup, 'application_no')
    registered_mask = applied_mask & _has_number(pat_dedup, 'registration_no')
    strategic_mask = pat_dedup.apply(is_strategic_patent, axis=1)
    return {
        'total': len(pat_dedup),
        'lead': count_true(pat_dedup, 'is_lead_inventor'),
        'applied': int(applied_mask.sum()),
        'registered': int(registered_mask.sum()),
        'applied_share': _share_total(pat_dedup[applied_mask]),
        'strategic': int(strategic_mask.sum()),
        'strategic_share': _share_total(pat_dedup[strategic_mask]),
    }


def count_true(df, col):
    if col not in df.columns:
        return 0
    return int(df[col].astype(str).isin(['Y', 'y', '1', 'True', 'true']).sum())


def count_us_registered(df):
    if 'country' not in df.columns or 'status' not in df.columns:
        return 0
    us_mask = df['country'].astype(str).str.contains('미국|USA|US', case=False, na=False)
    return int((us_mask & df['status'].apply(is_registered)).sum())


def share_sum(df):
    if 'share_ratio' not in df.columns:
        return '-'
    shares = pd.to_numeric(df['share_ratio'], errors='coerce').dropna()
    return f'{round(shares.sum(), 1)}%' if not shares.empty else '-'
