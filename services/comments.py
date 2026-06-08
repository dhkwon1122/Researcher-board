import csv
import os

import pandas as pd

from services.data_store import processed_path

COMMENT_COLUMNS = [
    'researcher_id',
    'year',
    'commenter_type',
    'comment_raw',
    'comment_summary',
    'strengths',
    'improvements',
]


def upsert_comment(rid, year, author_type, text):
    path = processed_path('comments')
    df = (
        pd.read_csv(path, encoding='utf-8-sig', dtype={'researcher_id': str})
        if os.path.exists(path)
        else pd.DataFrame(columns=COMMENT_COLUMNS)
    )

    if 'commenter_type' not in df.columns:
        df['commenter_type'] = '부서장'

    rid = str(rid).zfill(8)
    year_str = str(year)
    mask = (
        (df['researcher_id'].astype(str).str.zfill(8) == rid) &
        (df['year'].astype(str) == year_str) &
        (df['commenter_type'] == author_type)
    )
    summary = text[:120] + ('...' if len(text) > 120 else '')
    new_row = {
        'researcher_id': rid,
        'year': year,
        'commenter_type': author_type,
        'comment_raw': text,
        'comment_summary': summary,
        'strengths': '',
        'improvements': '',
    }

    if mask.any():
        for key, value in new_row.items():
            df.loc[mask, key] = value
    else:
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
