"""
사용자 계정 엑셀/CSV 일괄 추가 — 컬럼 스키마와 검증 로직을 한 곳에 모아
scripts/bulk_create_users.py(CLI)와 pages/admin.py의 "엑셀로 사용자 추가"
(관리자 화면, 2026-08-31 신설) 둘 다 공유한다. 같은 파일이 어느 경로로
들어오든 같은 기준(필수 컬럼, 허용 값)으로 처리되게 하기 위함 — 한쪽만
고치고 다른 쪽을 깜빡하는 걸 막는다.

신규 계정은 전부 초기 사용자 등록 용도로 본다(사용자 확정 2026-08-31) —
이미 존재하는 아이디는 갱신하지 않고 건너뛴다(수정은 관리자 화면의
"수정" 버튼으로 개별적으로). 임시 비밀번호는 호출부(services.auth.
DEFAULT_TEMP_PASSWORD)가 정하므로 이 모듈은 비밀번호를 다루지 않는다.
"""
from __future__ import annotations

import io

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.datavalidation import DataValidation

from config.auth_config import ROLE_LABELS

# 업로드 파일에서 반드시 있어야 하는 컬럼 / 있으면 쓰는 선택 컬럼 —
# 관리자 화면의 안내문과 템플릿 헤더가 이 상수를 그대로 쓴다.
REQUIRED_COLUMNS = ('아이디', '이름', '권한')
OPTIONAL_COLUMNS = ('이메일', '관리자')

MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # 사용자 명단은 커봐야 수백 행이라 2MB로 충분

_COL_ALIASES = {
    'user_id': ('아이디', 'user_id', '사번'),
    'display_name': ('이름', 'display_name', '성명'),
    'email': ('이메일', 'email'),
    'role': ('권한', 'role', '역할'),
    'is_admin': ('관리자', 'is_admin', '관리자여부'),
}
_TRUTHY = {'y', 'yes', 'true', '1', 'o', '예', '관리자'}
_ROLE_CODE_BY_LABEL = {v: k for k, v in ROLE_LABELS.items()}


def _find_col(df: pd.DataFrame, key: str) -> str | None:
    for alias in _COL_ALIASES[key]:
        if alias in df.columns:
            return alias
    return None


def _parse_bool(raw) -> bool:
    return str(raw or '').strip().lower() in _TRUTHY


def normalize_role(raw: str) -> str | None:
    """역할 코드(예: talent_dev) 또는 한글 라벨(예: 인재개발 담당자) 둘 다
    받아 코드로 통일한다. 둘 다 아니면 None(허용되지 않는 값)."""
    raw = (raw or '').strip()
    if raw in ROLE_LABELS:
        return raw
    return _ROLE_CODE_BY_LABEL.get(raw)


def read_upload(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """xlsx/xls는 openpyxl로, 그 외(csv로 간주)는 utf-8-sig로 읽는다 —
    scripts/bulk_create_users.py의 _read_input()과 동일한 판별 기준.
    keep_default_na=False가 없으면 빈 셀(이메일 등 선택 컬럼)이 NaN으로
    읽혀, 아래 parse_rows()의 `str(v or '')` 변환에서 "nan" 문자열이 돼
    버린다(NaN은 파이썬에서 참으로 평가됨) — 그러면 이메일 같은 선택
    컬럼에 진짜 "nan"이 저장되거나, 필수 컬럼이 비어 있어도 "nan"이라는
    비어있지 않은 값으로 보여 누락 검사를 통과해버리는 두 가지 문제가
    생긴다. 빈 셀을 처음부터 빈 문자열로 읽어 이 문제 자체를 없앤다."""
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in (filename or '') else ''
    if ext in ('xlsx', 'xls'):
        return pd.read_excel(io.BytesIO(file_bytes), dtype=str, keep_default_na=False, na_filter=False)
    return pd.read_csv(io.BytesIO(file_bytes), encoding='utf-8-sig', dtype=str,
                        keep_default_na=False, na_filter=False)


def parse_rows(df: pd.DataFrame, existing_ids: set) -> dict:
    """업로드된 표를 검증해 실제로 만들 계정 목록과 건너뛴 이유를 정리한다.

    반환:
      rows: [{'user_id', 'display_name', 'email', 'role', 'is_admin'}, ...]
            — 실제로 생성할 계정(형식 정상 + 미존재 + 파일 내 중복 아님).
      skipped_existing: 이미 존재하는 아이디 목록.
      skipped_invalid: [(아이디, 사유), ...] — 필수값 누락/알 수 없는 권한/
            파일 내 아이디 중복.
      missing_columns: 필수 컬럼(REQUIRED_COLUMNS) 중 파일에서 못 찾은 것
            — 이게 비어있지 않으면 rows는 항상 빈 리스트(파싱 자체를
            포기했다는 뜻 — 헤더가 아예 잘못된 파일이므로 행 단위로 더
            보는 게 의미 없음)."""
    col_uid = _find_col(df, 'user_id')
    col_name = _find_col(df, 'display_name')
    col_email = _find_col(df, 'email')
    col_role = _find_col(df, 'role')
    col_admin = _find_col(df, 'is_admin')

    missing = [label for label, col in [('아이디', col_uid), ('이름', col_name), ('권한', col_role)]
               if col is None]
    if missing:
        return {'rows': [], 'skipped_existing': [], 'skipped_invalid': [], 'missing_columns': missing}

    rows, skipped_existing, skipped_invalid = [], [], []
    seen_in_file = set()
    for _, row in df.iterrows():
        uid = str(row.get(col_uid, '') or '').strip()
        name = str(row.get(col_name, '') or '').strip()
        email = str(row.get(col_email, '') or '').strip() if col_email else ''
        role_raw = str(row.get(col_role, '') or '').strip()
        is_admin = _parse_bool(row.get(col_admin, '')) if col_admin else False

        if not uid and not name and not role_raw:
            continue  # 완전히 빈 행(엑셀 하단 여백 등)은 조용히 무시
        if not uid or not name:
            skipped_invalid.append((uid or '(빈 아이디)', '아이디/이름 누락'))
            continue
        role = normalize_role(role_raw)
        if role is None:
            skipped_invalid.append((uid, f'알 수 없는 권한 "{role_raw}"'))
            continue
        if uid in existing_ids:
            skipped_existing.append(uid)
            continue
        if uid in seen_in_file:
            skipped_invalid.append((uid, '파일 안에서 아이디 중복'))
            continue
        seen_in_file.add(uid)
        rows.append({'user_id': uid, 'display_name': name, 'email': email, 'role': role,
                     'is_admin': is_admin})

    return {'rows': rows, 'skipped_existing': skipped_existing, 'skipped_invalid': skipped_invalid,
            'missing_columns': []}


_TEMPLATE_ROWS = 200  # 드롭다운 검증을 미리 걸어둘 빈 행 수 — 초기 등록치고 넉넉한 여유


def build_template_bytes() -> bytes:
    """업로드 템플릿 xlsx — 헤더(필수 3 + 선택 2)만 있고, 권한/관리자 두
    컬럼에는 엑셀 데이터 유효성 검사(드롭다운)를 걸어 정해진 값만 고를 수
    있게 한다(사용자 요청 — "셀에 들어갈 수 있는 내용만 추가해서 정할 수
    있도록"). 코드 값이 아니라 한글 라벨(ROLE_LABELS의 값)을 목록으로
    쓴다 — normalize_role()이 라벨도 그대로 받으므로 관리자가 코드를
    몰라도 채울 수 있다."""
    wb = Workbook()
    ws = wb.active
    ws.title = '사용자 명단'

    headers = list(REQUIRED_COLUMNS) + list(OPTIONAL_COLUMNS)
    header_font = Font(bold=True)
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
    widths = [16, 12, 24, 20, 10]
    for col_idx, width in enumerate(widths, start=1):
        ws.column_dimensions[chr(ord('A') + col_idx - 1)].width = width
    ws.freeze_panes = 'A2'

    role_col = headers.index('권한') + 1
    admin_col = headers.index('관리자') + 1
    last_row = _TEMPLATE_ROWS + 1

    role_list = ','.join(ROLE_LABELS.values())
    dv_role = DataValidation(type='list', formula1=f'"{role_list}"', allow_blank=True,
                              showErrorMessage=True, errorTitle='허용되지 않는 값',
                              error='목록에 있는 역할명만 입력할 수 있습니다.')
    ws.add_data_validation(dv_role)
    dv_role.add(f'{chr(ord("A") + role_col - 1)}2:{chr(ord("A") + role_col - 1)}{last_row}')

    dv_admin = DataValidation(type='list', formula1='"예,아니오"', allow_blank=True,
                               showErrorMessage=True, errorTitle='허용되지 않는 값',
                               error='"예" 또는 "아니오"만 입력할 수 있습니다(비워두면 아니오).')
    ws.add_data_validation(dv_admin)
    dv_admin.add(f'{chr(ord("A") + admin_col - 1)}2:{chr(ord("A") + admin_col - 1)}{last_row}')

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
