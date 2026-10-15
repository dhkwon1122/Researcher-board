"""석세션 플랜: 부서 표시를 팀/리더 참조 1단계부서명으로(저장 기준은 현소속부서명 그대로, 2026-10-15)."""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_department_display_map(monkeypatch):
    from services import similarity_map as sm
    from services import succession_store as ss
    res = pd.DataFrame({'researcher_id': ['1', '2', '3', '4', '5'],
                        'department': ['AI센터', 'AI센터', '소재팀', '소재2팀', '미매칭'],
                        'org_code': ['o1', 'o2', 'o3', 'o4', 'oX']})
    monkeypatch.setattr(ss, '_researchers_df', lambda current_only=True: res)
    names = {'o1': 'AI플랫폼', 'o2': 'AI플랫폼', 'o3': '소재플랫폼', 'o4': '소재플랫폼'}
    monkeypatch.setattr(sm, 'org_code_level_names', lambda org: (names.get(org, ''), '', ''))
    m = ss.department_display_map()
    assert m['AI센터'] == 'AI플랫폼'
    assert m['소재팀'] == '소재플랫폼 (소재팀)' and m['소재2팀'] == '소재플랫폼 (소재2팀)'   # 같은 1단계로 겹치면 구분
    assert '미매칭' not in m                                                              # 호출부가 원래 이름으로
