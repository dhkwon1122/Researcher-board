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
