"""사용자/권한 관리 표 행 순서(2026-10-29) — 체크 후 맨 위로/위로/아래로/맨 아래로, 임시 비밀번호 초기화."""
import json

from services import user_order


def test_move_selected_and_apply(tmp_path, monkeypatch):
    monkeypatch.setattr(user_order, 'ORDER_PATH', str(tmp_path / 'user_order.json'))
    users = [{'user_id': u} for u in ('a', 'b', 'c', 'd')]
    assert [u['user_id'] for u in user_order.apply(users)] == ['a', 'b', 'c', 'd']   # 저장 전엔 원래 순서
    assert user_order.move_selected(['a', 'b', 'c', 'd'], ['c'], 'top') == (['c', 'a', 'b', 'd'], 0)  # 3번째 → 1번째
    users.append({'user_id': 'e'})                                                    # 새 계정은 맨 뒤
    assert [u['user_id'] for u in user_order.apply(users)] == ['c', 'a', 'b', 'd', 'e']
    assert user_order.move_selected(['c', 'a', 'b', 'd', 'e'], ['c', 'b'], 'up') == (['c', 'b', 'a', 'd', 'e'], 1)
    assert user_order.move_selected(['c', 'b', 'a', 'd', 'e'], ['c', 'b'], 'down')[0] == ['a', 'c', 'b', 'd', 'e']
    assert user_order.move_selected(['a', 'c', 'b', 'd', 'e'], ['a', 'b'], 'bottom')[0] == ['c', 'd', 'e', 'a', 'b']
    assert [u['user_id'] for u in user_order.apply(users)] == ['c', 'd', 'e', 'a', 'b']


def test_user_rows_keep_selection_and_sort_is_view_only():
    from components.admin_users_tab import _build_user_rows
    users = [{'user_id': u, 'display_name': u, 'role': 'recruit', 'email': '', 'permissions': {}}
             for u in ('a', 'b', 'c')]
    rows = _build_user_rows(users, {'column': 'user_id', 'direction': 'desc'}, ['b'])
    assert [r.children[1].children for r in rows] == ['c', 'b', 'a']               # 정렬은 보기만
    assert [r.children[0].children.value for r in rows] == [False, True, False]   # 체크 유지


def test_reset_to_temp_password(tmp_path, monkeypatch):
    from werkzeug.security import check_password_hash, generate_password_hash
    from services import auth
    path = tmp_path / 'users.json'
    path.write_text(json.dumps({'u1': {'password_hash': generate_password_hash('Old!pass1'), 'display_name': 'u1',
                                       'role': 'recruit', 'must_change_password': False}}), encoding='utf-8')
    monkeypatch.setattr(auth, '_database_configured', lambda: False)
    monkeypatch.setattr(auth, '_load_users_json', lambda: json.loads(path.read_text(encoding='utf-8')))
    monkeypatch.setattr(auth, '_save_users_json', lambda d: path.write_text(json.dumps(d), encoding='utf-8'))
    assert auth.reset_to_temp_password('u1') and not auth.reset_to_temp_password('없음')
    u = json.loads(path.read_text(encoding='utf-8'))['u1']
    assert check_password_hash(u['password_hash'], auth.DEFAULT_TEMP_PASSWORD) and u['must_change_password']
