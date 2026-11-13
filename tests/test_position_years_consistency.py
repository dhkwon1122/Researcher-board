"""직급-년차 계산 통일(2026-10-29) — 프로필 카드·석세션 플랜이 엑셀 "CL/년차"(position_years)와 같은 값,
승격산정기준일자가 없으면 직급만."""
from datetime import date

from services import researcher_profile_export as rpe


def _texts(node):
    if isinstance(node, str):
        return [node]
    if isinstance(node, list):
        return sum((_texts(c) for c in node), [])
    ch = getattr(node, 'children', None)
    if ch is None:
        return []
    return sum((_texts(c) for c in (ch if isinstance(ch, list) else [ch])), [])


def test_profile_and_succession_match_excel(monkeypatch):
    import app  # noqa: F401 — 페이지 모듈은 앱 생성 뒤에
    from components.profile_sections import photo_block
    from pages import org_comparison as oc
    monkeypatch.setattr(rpe, '_next_promotion_ref_date', lambda _today: date(2027, 3, 1))
    assert rpe.position_years('2020-03-01') == 7                       # 예전 프로필·석세션(올림)은 8
    row = {'name': '홍길동', 'gender': '남', 'birth_year': 1980, 'position': 'CL3',
           'promotion_date': '2020-03-01', 'hire_date': '2010-01-01'}
    assert oc._info_lines(row)[1] == 'CL3-7년차'
    assert any(t.startswith('CL3-7(') for t in _texts(photo_block('X', '홍길동', row)))
    no_promo = {**row, 'promotion_date': ''}
    assert oc._info_lines(no_promo)[1] == 'CL3'
    assert any(t.startswith('CL3(') for t in _texts(photo_block('X', '홍길동', no_promo)))


def test_age_tenure_missing_values_show_dash():
    """출생연도·입사일이 없으면 지어내지 않고 '-'/생략 — 엑셀과 같은 규칙(2026-10-29)."""
    import app  # noqa: F401
    from components.profile_sections import photo_block
    from pages import org_comparison as oc
    row = {'name': '홍길동', 'gender': '남', 'birth_year': float('nan'), 'position': 'CL3',
           'promotion_date': '', 'hire_date': ''}
    texts = _texts(photo_block('X', '홍길동', row))
    assert '홍길동(남/-)' in texts and 'CL3' in texts                    # 예전: "30세", "CL3-…(…년)"
    assert oc._info_lines(row)[0] == '홍길동(남/-)'
    row2 = {**row, 'birth_year': 1990.0}
    assert f'홍길동(남/{date.today().year - 1990}세)' in _texts(photo_block('X', '홍길동', row2, 2000))  # 넘겨준 연도 무시


def test_eval_years_follow_today(monkeypatch):
    """평가 3개년은 호출 시점 회계연도 — 서버 재시작 없이 3/1에 넘어감(2026-10-29)."""
    from services import evaluations, report_builder as rb
    monkeypatch.setattr(evaluations, 'current_fiscal_year', lambda today=None: 2027)
    assert rpe.eval_salary_years() == [2025, 2026, 2027] and rpe.eval_header().endswith("('25~'27)")
    assert rb.FIELDS['eval_salary_0']['label'] == '2025 연봉등급'
    assert rb.FIELDS['eval_summary']['label'] == "평가 ('25~'27)"
    rows = {'permissions': {'view_evaluation': True}, 'evaluations': [{'2025_salary_grade': '가'}]}
    assert rb.FIELDS['eval_salary_0']['fn']('R', rows) == '가'


def test_incentive_label_same_as_excel():
    import pandas as pd
    from components.profile_sections import _inc_label
    inc = pd.DataFrame([{'year': 2025, 'selected': 'True', 'category': '최우수 인센티브'},
                        {'year': 2026, 'selected': 'yes', 'category': '우수'}])
    assert _inc_label(inc, 2025) == '최우수 인센티브'                          # 예전: '최우수'로 축약
    assert _inc_label(inc, 2026) == '-'                                         # 엑셀과 같이 true/1만 선정
    assert rpe._col_incentive('R', {'permissions': {'view_incentive': True},
                                    'incentive_selection': inc.to_dict('records')}) == "'25 : 최우수 인센티브"
