import pandas as pd

from components.timeline_data import dedupe_patents, patent_summary, patent_title


def _pat():
    return pd.DataFrame([
        {'researcher_id': '1', 'application_id': 'A1', 'title': 'En1', 'title_ko': '국문1', 'share_ratio': '50',
         'is_lead_inventor': 'Y', 'patent_grade_a_sub': '전략출원', 'application_no': '10', 'registration_no': '',
         'country': 'US'},
        {'researcher_id': '1', 'application_id': 'A2', 'title': 'En2', 'title_ko': '', 'share_ratio': '30',
         'is_lead_inventor': 'N', 'patent_grade_a_sub': '없음', 'application_no': '20', 'registration_no': 'R',
         'country': 'KR'},
        {'researcher_id': '1', 'application_id': 'A3', 'title': 'En3', 'title_ko': '국문3', 'share_ratio': '20',
         'is_lead_inventor': 'N', 'patent_grade_a_sub': '없음', 'application_no': '', 'registration_no': '',
         'country': 'KR'},
    ])


def test_patent_summary_uses_numbers_not_status():
    st = patent_summary(dedupe_patents(_pat()))
    assert st == {'total': 3, 'lead': 1, 'applied': 2, 'registered': 1, 'applied_share': '80%',
                  'strategic': 1, 'strategic_share': '50%'}


def test_title_prefers_korean_then_english():
    rows = _pat().to_dict('records')
    assert patent_title(rows[0]) == '국문1'
    assert patent_title(rows[1]) == 'En2'
