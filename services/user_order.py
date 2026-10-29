"""
"사용자/권한 관리" 표의 행 순서(2026-10-29, 사용자 요청: "3번째 행에 있는 사람을 1번째 행으로 옮기는 기능").

계정 저장소(DB app_users 또는 config/users.json)는 다른 시스템과 공유할 수 있어 스키마를 건드리지 않고,
표시 순서만 data/processed/user_order.json에 아이디 목록으로 따로 저장한다.
목록에 없는 계정(새로 추가된 계정 등)은 기존 순서 그대로 맨 뒤에 붙는다.
2026-10-29 개정: 표는 먼저 역할 기준 오름차순으로 묶고(group_key), 저장된 순서는 같은 역할 안에서만 적용한다.
"""
from __future__ import annotations

import json
import os
import threading

from services import data_store

ORDER_PATH = os.path.join(data_store.DATA_DIR, 'user_order.json')
_LOCK = threading.Lock()


def load() -> list:
    try:
        with open(ORDER_PATH, encoding='utf-8') as f:
            ids = json.load(f).get('user_ids') or []
    except (OSError, ValueError, AttributeError):
        return []
    return [str(i) for i in ids]


def _save(ids: list) -> None:
    os.makedirs(os.path.dirname(ORDER_PATH), exist_ok=True)
    tmp = f'{ORDER_PATH}.{threading.get_ident()}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({'user_ids': ids}, f, ensure_ascii=False)
    os.replace(tmp, ORDER_PATH)


def apply(users: list, group_key=None) -> list:
    """group_key(사용자)로 먼저 오름차순 묶고, 그 안에서 저장된 순서대로. 순서에 없는 계정은 그 묶음의 뒤에."""
    rank = {uid: i for i, uid in enumerate(load())}
    indexed = list(enumerate(users))
    indexed.sort(key=lambda t: (group_key(t[1]) if group_key else '',
                                rank.get(t[1].get('user_id'), len(rank)), t[0]))
    return [u for _, u in indexed]


def move(user_ids: list, user_id: str, position: int) -> list:
    """현재 표시 순서(user_ids)에서 user_id를 position(1부터)으로 옮기고 저장. 반환: 새 순서."""
    ids = [str(u) for u in user_ids]
    if user_id not in ids:
        return ids
    ids.remove(user_id)
    position = max(1, min(int(position), len(ids) + 1))
    ids.insert(position - 1, user_id)
    with _LOCK:
        _save(ids)
    return ids
