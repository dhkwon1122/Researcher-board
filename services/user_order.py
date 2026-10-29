"""
"사용자/권한 관리" 표의 행 순서(2026-10-29, 사용자 요청: "3번째 행에 있는 사람을 1번째 행으로 옮기는 기능").

계정 저장소(DB app_users 또는 config/users.json)는 다른 시스템과 공유할 수 있어 스키마를 건드리지 않고,
표시 순서만 data/processed/user_order.json에 아이디 목록으로 따로 저장한다.
목록에 없는 계정(새로 추가된 계정 등)은 기존 순서 그대로 맨 뒤에 붙는다.
이동은 "팀/리더 참조" 탭과 같은 방식 — 체크한 행을 맨 위로/위로/아래로/맨 아래로(move_selected).
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


def apply(users: list) -> list:
    """저장된 순서대로 정렬한 사용자 목록. 순서에 없는 계정은 원래 순서로 뒤에."""
    rank = {uid: i for i, uid in enumerate(load())}
    indexed = list(enumerate(users))
    indexed.sort(key=lambda t: (rank.get(t[1].get('user_id'), len(rank)), t[0]))
    return [u for _, u in indexed]


def move_selected(user_ids: list, selected: list, direction: str) -> tuple[list, int]:
    """체크한 계정들을 옮기고 저장 — direction: top/up/down/bottom. 반환: (새 순서, 더 못 움직인 개수).
    위/아래는 한 칸씩(여러 개면 이동 방향 쪽부터 처리해 붙어 있는 선택끼리 함께 밀림),
    맨 위/맨 아래는 선택끼리·나머지끼리의 상대 순서를 유지한 채 한 번에 보낸다(팀/리더 참조 탭과 같은 규칙)."""
    ids = [str(u) for u in user_ids]
    picked = {str(u) for u in selected} & set(ids)
    blocked = 0
    if direction in ('top', 'bottom'):
        chosen = [u for u in ids if u in picked]
        rest = [u for u in ids if u not in picked]
        ids = chosen + rest if direction == 'top' else rest + chosen
    else:
        order = [i for i, u in enumerate(ids) if u in picked]
        if direction == 'down':
            order.reverse()
        for i in order:
            j = i - 1 if direction == 'up' else i + 1
            if j < 0 or j >= len(ids) or ids[j] in picked:
                blocked += 1
                continue
            ids[i], ids[j] = ids[j], ids[i]
    with _LOCK:
        _save(ids)
    return ids, blocked
