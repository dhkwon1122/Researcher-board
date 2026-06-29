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


def _upsert_comment_db(engine, rid, year, author_type, text, summary):
    """PostgreSQL INSERT ... ON CONFLICT 로 코멘트 upsert."""
    from sqlalchemy import text as sql_text

    stmt = sql_text("""
        INSERT INTO comments
            (researcher_id, year, commenter_type, comment_raw, comment_summary,
             strengths, improvements)
        VALUES (:rid, :year, :ctype, :raw, :summary, '', '')
        ON CONFLICT (researcher_id, year, commenter_type)
        DO UPDATE SET
            comment_raw = EXCLUDED.comment_raw,
            comment_summary = EXCLUDED.comment_summary
    """)
    with engine.begin() as conn:
        conn.execute(stmt, {
            'rid': rid, 'year': str(year), 'ctype': author_type,
            'raw': text, 'summary': summary,
        })


def upsert_comment(rid, year, author_type, text):
    rid = str(rid).zfill(8)
    summary = text[:120] + ('...' if len(text) > 120 else '')

    from services.db import get_engine
    engine = get_engine()
    if engine is not None:
        _upsert_comment_db(engine, rid, year, author_type, text, summary)
        return

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
