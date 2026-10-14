"""엑셀 "직책": 팀/리더 참조의 현재 스냅샷 기준(2026-10-14 — 과거에만 조직장이던 사람도 직책이 나오던 문제)."""
import pandas as pd

from services import data_store
from services import researcher_profile_export as x


def _tr(dep_id, y, m, rid, title, deleted=''):
    return dict(dep_id=dep_id, valid_year=y, valid_month=m, valid_day='01', researcher_id=rid,
                assignment_name=title, deleted=deleted, org_name_wd=f'ORG{dep_id}')


def test_only_current_leaders_have_title(monkeypatch):
    rows = pd.DataFrame([
        _tr('D1', '2025', '01', '00000001', '그룹장'),      # 과거 리더
        _tr('D1', '2026', '09', '00000002', '그룹장'),      # 현재 리더(같은 조직의 최신 스냅샷)
        _tr('D2', '2025', '01', '00000003', '파트장'),
        _tr('D2', '2026', '09', '', '', deleted='Y'),        # 이후 삭제된 조직
    ])
    real = data_store.read_processed
    monkeypatch.setattr(data_store, 'read_processed',
                        lambda name, **kw: rows.copy() if name == 'team_refer' else real(name, **kw))
    df = x._current_team_refer()
    title = lambda rid: x._col_position_title(rid, {'team_refer': x._rows_for(df, rid)})
    assert title('00000002') == '그룹장'
    assert title('00000001') == '-'
    assert title('00000003') == '-'
