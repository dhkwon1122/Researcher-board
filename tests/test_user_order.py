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


def test_role_grouped_order_and_move_limited_to_role(tmp_path, monkeypatch):
    """역할 이름 오름차순으로 묶고 같은 역할 안에서만 옮긴다(2026-10-29 개정)."""
    from components import admin_users_tab as t
    monkeypatch.setattr(user_order, 'ORDER_PATH', str(tmp_path / 'user_order.json'))
    users = [{'user_id': uid, 'display_name': uid, 'role': role, 'email': '', 'permissions': {}}
             for uid, role in [('r1', 'recruit'), ('h1', 'hr_planning'), ('r2', 'recruit'), ('h2', 'hr_planning')]]
    ordered = t._ordered_users(users)                       # HR기획 담당자 < 채용 담당자
    assert [u['user_id'] for u in ordered] == ['h1', 'h2', 'r1', 'r2']
    assert t._role_range(ordered, 'r2') == (3, 4)
    user_order.move([u['user_id'] for u in ordered], 'r2', 3)
    assert [u['user_id'] for u in t._ordered_users(users)] == ['h1', 'h2', 'r2', 'r1']
    user_order.move(['h1', 'h2', 'r2', 'r1'], 'r1', 1)      # 다른 역할 자리로 옮겨도 역할 묶음은 유지
    assert [u['user_id'] for u in t._ordered_users(users)] == ['h1', 'h2', 'r1', 'r2']
    cell = t._build_user_rows(t._ordered_users(users), None)[0].children[0].children
    assert cell.children[1].disabled and not cell.children[2].disabled  # 묶음 첫 줄은 ↑ 비활성
