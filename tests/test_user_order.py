"""사용자/권한 관리 표 행 순서(2026-10-29)."""
from services import user_order


def test_move_and_apply(tmp_path, monkeypatch):
    monkeypatch.setattr(user_order, 'ORDER_PATH', str(tmp_path / 'user_order.json'))
    users = [{'user_id': u} for u in ('a', 'b', 'c', 'd')]
    assert [u['user_id'] for u in user_order.apply(users)] == ['a', 'b', 'c', 'd']   # 저장 전엔 원래 순서
    assert user_order.move(['a', 'b', 'c', 'd'], 'c', 1) == ['c', 'a', 'b', 'd']     # 3번째 → 1번째
    users.append({'user_id': 'e'})                                                    # 새 계정은 맨 뒤
    assert [u['user_id'] for u in user_order.apply(users)] == ['c', 'a', 'b', 'd', 'e']
    assert user_order.move(['c', 'a', 'b', 'd', 'e'], 'a', 99)[-1] == 'a'            # 범위 밖은 끝으로


def test_user_rows_render_order_cell():
    from components.admin_users_tab import _build_user_rows
    users = [{'user_id': u, 'display_name': u, 'role': 'recruit', 'email': '', 'permissions': {}}
             for u in ('a', 'b', 'c')]
    rows = _build_user_rows(users, {'column': 'user_id', 'direction': 'desc'})
    assert [r.children[1].children for r in rows] == ['c', 'b', 'a']               # 정렬은 보기만
    assert rows[0].children[0].children.children[0].value == 3                    # 순서 번호는 저장 순서 기준
