"""
연구원 개별 프로필 인쇄/PDF 출력 — 항목 배치(레이아웃) 저장/조회.

components/profile_print.py가 실제 내용을 렌더링할 때 이 모듈의 좌표를 읽어
각 항목을 A4 한 장(고정 그리드) 위의 정확한 칸에 배치한다. "어떤 항목을
넣을지"(체크리스트, BLOCK_DEFS의 key)와 "어디에 놓을지"(레이아웃, 이 모듈이
저장하는 x/y/w/h)를 분리해서, 배치는 전 사용자 공통 템플릿 하나로 관리하고
(사용자 확정 — 인원별로 따로 저장하지 않음), 어떤 항목을 포함할지만 매번
인쇄할 때 고른다.

그리드: 가로 GRID_COLS × 세로 GRID_ROWS 칸으로 A4 한 장(210×297mm)을 나눈다.
칸을 벗어나는 좌표는 저장 시 clamp하고, 겹치는 배치는 막지 않는다(사용자가
직접 조정하는 걸 막을 이유가 없음 — 화면에서 겹쳐 보이면 사용자가 바로
알아차리고 옮길 수 있음).
"""

import json
import os

GRID_COLS = 10
GRID_ROWS = 14

# (key, 라벨, 그룹 — 'personnel'|'expertise', 필요 권한 — None이면 항상 노출)
# 'identity'(사진+기본 인적사항)는 체크리스트에 없는 항상-포함 블록이라 아래
# BLOCK_DEFS 맨 앞에 그룹 'identity'로 별도 표시한다.
BLOCK_DEFS = [
    ('identity', '사진 · 기본 인적사항', 'identity', None),
    ('education', '학력', 'personnel', None),
    ('evaluation', '평가 · 인센티브 이력', 'personnel', 'view_evaluation'),
    ('nurturing', '양성 이력', 'personnel', None),
    ('award', '시상 이력', 'personnel', None),
    ('hr_orders', '인사발령 이력', 'personnel', None),
    ('leadership', '리더십 진단', 'personnel', None),
    ('comments', '인물 코멘트', 'personnel', 'view_comments'),
    ('expertise_summary', '전문성 요약 (LLM) · 유사 연구원', 'expertise', None),
    ('owned_expertise', '보유 전문성 표', 'expertise', None),
    ('tasks', '과제 수행 이력', 'expertise', None),
    ('job_profile', '직무 이력', 'expertise', None),
    ('publications', '논문 요약', 'expertise', None),
    ('patents', '특허 요약', 'expertise', None),
]
BLOCK_LABELS = {key: label for key, label, _group, _perm in BLOCK_DEFS}

PERSONNEL_FIELDS = [(k, l, p) for k, l, g, p in BLOCK_DEFS if g == 'personnel']
EXPERTISE_FIELDS = [(k, l, p) for k, l, g, p in BLOCK_DEFS if g == 'expertise']
DEFAULT_PERSONNEL = ['education', 'evaluation', 'nurturing', 'award', 'hr_orders', 'leadership']
DEFAULT_EXPERTISE = [key for key, _label, _perm in EXPERTISE_FIELDS]

# 기본 배치 — 10×14 칸을 빈틈없이 채운 시작 템플릿(관리자가 이후 자유롭게
# 재배치). (x, y, w, h) — x/y는 0부터, w/h는 칸 수.
DEFAULT_LAYOUT = {
    'identity':           {'x': 0, 'y': 0,  'w': 3, 'h': 4},
    'education':          {'x': 3, 'y': 0,  'w': 2, 'h': 2},
    'evaluation':         {'x': 5, 'y': 0,  'w': 3, 'h': 2},
    'nurturing':          {'x': 3, 'y': 2,  'w': 2, 'h': 2},
    'award':               {'x': 5, 'y': 2,  'w': 3, 'h': 2},
    'hr_orders':          {'x': 8, 'y': 0,  'w': 2, 'h': 4},
    'leadership':         {'x': 0, 'y': 4,  'w': 4, 'h': 2},
    'comments':           {'x': 4, 'y': 4,  'w': 6, 'h': 2},
    'expertise_summary':  {'x': 0, 'y': 6,  'w': 6, 'h': 4},
    'owned_expertise':    {'x': 6, 'y': 6,  'w': 4, 'h': 4},
    'tasks':               {'x': 0, 'y': 10, 'w': 3, 'h': 4},
    'job_profile':        {'x': 3, 'y': 10, 'w': 2, 'h': 4},
    'publications':       {'x': 5, 'y': 10, 'w': 3, 'h': 4},
    'patents':             {'x': 8, 'y': 10, 'w': 2, 'h': 4},
}

_LAYOUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'print_layout.json',
)


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def sanitize_layout(layout: dict | None) -> dict:
    """저장/사용 전 항상 이 함수를 거친다 — 알 수 없는 key는 버리고, 좌표는
    그리드 범위 안으로 clamp하며, 값이 없거나 잘못된 블록은 기본 배치로
    채운다(에디터가 일부 블록만 옮긴 상태로 저장돼도 나머지는 항상 유효한
    좌표를 갖게 하기 위함)."""
    layout = layout or {}
    out = {}
    for key, _label, _group, _perm in BLOCK_DEFS:
        block = layout.get(key) if isinstance(layout.get(key), dict) else None
        default = DEFAULT_LAYOUT[key]
        try:
            w = _clamp(int(block['w']), 1, GRID_COLS) if block else default['w']
            h = _clamp(int(block['h']), 1, GRID_ROWS) if block else default['h']
            x = _clamp(int(block['x']), 0, GRID_COLS - w) if block else default['x']
            y = _clamp(int(block['y']), 0, GRID_ROWS - h) if block else default['y']
        except (KeyError, TypeError, ValueError):
            x, y, w, h = default['x'], default['y'], default['w'], default['h']
        out[key] = {'x': x, 'y': y, 'w': w, 'h': h}
    return out


def read_layout() -> dict:
    if not os.path.exists(_LAYOUT_PATH):
        return dict(DEFAULT_LAYOUT)
    try:
        with open(_LAYOUT_PATH, encoding='utf-8') as f:
            return sanitize_layout(json.load(f))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_LAYOUT)


def write_layout(layout: dict) -> dict:
    clean = sanitize_layout(layout)
    os.makedirs(os.path.dirname(_LAYOUT_PATH), exist_ok=True)
    with open(_LAYOUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)
    return clean
