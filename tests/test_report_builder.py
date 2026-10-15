"""업무 시나리오 > 조서 작성 — 묶는 방식, 여러 건 제한, 양식 저장 권한, 권한 항목(2026-10-15)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services import report_builder as rb  # noqa: E402


def test_join_and_limit():
    assert rb.join_values(['홍길동', '남', '40세'], 'paren') == '홍길동 (남/40세)'
    assert rb.join_values(['홍길동', '남', '40세'], 'paren_newline') == '홍길동\n(남/40세)'
    assert rb.join_values(['a', 'b'], 'comma') == 'a, b'
    assert rb.join_values(['-', '-'], 'paren_newline') == '-'
    assert rb._limit('a\nb\nc', 2) == 'a\nb\n외 1건' and rb._limit('a\nb', 2) == 'a\nb' and rb._limit('a\nb', None) == 'a\nb'


def test_field_options_respect_permissions():
    none = {o['value'] for o in rb.field_options({'view_evaluation': False, 'view_incentive': False})}
    full = {o['value'] for o in rb.field_options({'view_evaluation': True, 'view_incentive': True})}
    assert 'eval_summary' not in none and 'incentive' not in none and {'eval_summary', 'incentive'} <= full
    assert {'name', 'gender', 'age', 'dept', 'project'} <= none


def test_template_store(tmp_path, monkeypatch):
    monkeypatch.setattr(rb, 'TEMPLATES_PATH', str(tmp_path / 't.json'))
    cols = [{'header': '', 'fields': ['name', 'age'], 'join': 'paren'}, {'header': 'x', 'fields': [], 'join': 'slash'}]
    t = rb.save_template('u1', '내 양식', cols, '2')
    assert t['columns'] == [{'header': '성명 (나이)', 'fields': ['name', 'age'], 'join': 'paren'}] and t['max_items'] == 2
    assert [x['name'] for x in rb.list_templates('u1')][1:] == ['내 양식'] and len(rb.list_templates('u2')) == 1
    with pytest.raises(PermissionError):
        rb.save_template('u1', '공용', cols, None, shared=True, is_admin=False)
    s = rb.save_template('admin', '공용', cols, None, shared=True, is_admin=True)
    assert any(x['id'] == s['id'] for x in rb.list_templates('u2'))
    with pytest.raises(PermissionError):
        rb.delete_template(s['id'], 'u2')
    with pytest.raises(PermissionError):
        rb.save_template('u2', '남의 것', cols, None, template_id=t['id'])
    rb.save_template('u1', '이름 변경', cols, None, template_id=t['id'])
    assert [x['name'] for x in rb.list_templates('u1') if not x.get('shared')] == ['이름 변경']
    rb.delete_template(t['id'], 'u1')
    with pytest.raises(ValueError):
        rb.save_template('u1', '', cols, None)
