"""
연구원 프로필 타임라인/실적 탭에서 공유하는 원천 데이터 가공 유틸리티.
detail_tabs.py(과제·논문·특허 탭)와 timeline_view.py(타임라인 카드) 양쪽에서 사용한다.
"""

from datetime import datetime

import pandas as pd


def parse_ts(val):
    s = str(val).strip() if val is not None else ''
    if not s or s in ('nan', 'None', 'NaT'):
        return None
    try:
        return pd.Timestamp(s)
    except (ValueError, TypeError):
        return None


def clean(value):
    s = str(value).strip()
    return '' if s in ('nan', 'None', 'NaT') else s


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


def has_input_rate(val) -> bool:
    """투입률이 0이거나 비어있으면 False (해당 과제는 목록/타임라인에서 제외)."""
    s = str(val).strip() if val is not None else ''
    if not s or s.lower() in ('nan', 'none', 'nat'):
        return False
    try:
        return float(s) > 0
    except (ValueError, TypeError):
        return False


def task_points(task_df):
    if task_df.empty:
        return []
    today = pd.Timestamp(datetime.now().date())
    points = []
    for _, row in task_df.iterrows():
        if not has_input_rate(row.get('input_rate')):
            continue
        start = parse_ts(row.get('start_date'))
        if start is None:
            continue
        end_raw = row.get('end_date')
        end = parse_ts(end_raw)
        end_label = end.strftime('%Y-%m-%d') if end is not None else '진행중'
        if end is None or end < start:
            end = today
        if (end - start).days <= 30:
            continue
        points.append({
            'task_name': str(row.get('task_name', '')).strip(),
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
            'order_date': str(row.get('order_date', '')).strip(),
            'order_name': str(row.get('order_name', '')).strip(),
            'order_dep': str(row.get('order_dep', '')).strip(),
            'order_cl': str(row.get('order_cl', '')).strip(),
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
        title = cell(row, 'title', 'title_ko')
        grade = clean(row.get('patent_grade', ''))
        grade_a = clean(row.get('patent_grade_a_sub', ''))
        grade_a = '' if grade_a == '없음' else grade_a
        share = clean(row.get('share_ratio', ''))
        is_lead = clean(row.get('is_lead_inventor', ''))
        points.append({
            'date': date,
            'title': title,
            'grade': grade,
            'grade_a': grade_a,
            'share': share,
            'is_lead': is_lead,
        })
    points.sort(key=lambda p: p['date'])
    return points


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

    agg_dict = {col: 'first' for col in pat.columns if col not in (id_col, 'researcher_id', 'country', 'status')}
    if 'status' in pat.columns:
        agg_dict['status'] = _agg_status
    if 'country' in pat.columns:
        agg_dict['country'] = _merge_countries
    return pat.groupby(id_col, sort=False).agg(agg_dict).reset_index()


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
