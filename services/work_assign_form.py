"""
업무분장 부서별 양식 자동 생성(2026-11-20, 사용자 요청 "부서별 양식 자동 생성 기능도 넣어줘").

양식 구조(실제 "업무분장 양식" 구글 시트): 1행 병합 묶음 머리글(A:B "Knox ID, 재직현황" / C:L "'26년 12월 1일자" /
M:V "참고 : '26년 11월 1일자"), 2행 열 이름(Knox ID·재직현황 + 플랫폼~비고 10개 열이 대상월·참고로 반복).

부서마다 이 양식에 다음을 채운 엑셀을 만든다.
- 참고(이전 달) 칸: 그 부서가 지난달(대상월-1) 회신한 업무분장(대상월 칸 내용). 지난달 회신이 없으면 비움.
- 대상월 칸: 설정(prefill_target)이 켜져 있으면 지난달 내용을 그대로 복사 — 바뀐 부분만 고쳐 회신하도록.
- Knox ID·재직현황: 지난달 명단의 Knox ID + 현재 인력현황 대조 결과(재직 / 부서 변경(확인) / 미재직(확인)).
  현재 인력현황상 그 부서인데 지난달 명단에 없던 사람은 "신규(확인)"으로 성명·Knox ID만 넣어 뒤에 붙인다.
  지난달 회신이 아예 없으면 현재 인력현황의 부서원 명단(성명·Knox ID·재직)으로 시작.
- 1행 날짜 문구('26년 12월 1일자 / 참고 : '26년 11월 1일자)를 대상월에 맞게 바꾼다.

양식 원본: 화면에서 올린 엑셀(work_assign_form_template.xlsx)이 있으면 그 서식을 그대로 쓰고, 없으면 같은 구조의 기본
양식을 만든다. 부서는 담당자 명단의 부서명 = 인력현황 org_code의 1단계 부서명(similarity_map.dep_name_for_org_code).
"""
from __future__ import annotations

import io
import os
import re
import zipfile

import pandas as pd

from services import data_store
from services import work_assign as wa

TEMPLATE_PATH = os.path.join(data_store.DATA_DIR, 'work_assign_form_template.xlsx')
FIELDS = ['플랫폼', '그룹', '과제/파트명', '성명', '담당업무', '상세업무', '인력 Assign 형태', '주과제 참여율', '부과제명', '비고']
KNOX, STATUS, NAME = 'Knox ID', '재직현황', '성명'
_DATE_RE = re.compile(r"'?\d{2,4}\s*년\s*\d{1,2}\s*월\s*1\s*일자")


# ── 설정·양식 원본 ──────────────────────────────────────────────────────────

def settings() -> dict:
    f = wa._settings().get('form') or {}
    return {'enabled': bool(f.get('enabled')), 'prefill_target': f.get('prefill_target', True) is not False,
            'template_name': f.get('template_name', '') if os.path.exists(TEMPLATE_PATH) else ''}


def save_settings(enabled: bool, prefill_target: bool) -> dict:
    wa._require_use()
    f = wa._settings().get('form') or {}
    wa._update_settings(form={**f, 'enabled': bool(enabled), 'prefill_target': bool(prefill_target)})
    return settings()


def save_template(name: str, content: bytes) -> dict:
    """양식 원본(엑셀) 저장 — 머리글(Knox ID·성명 등)을 찾을 수 있는지 확인한 뒤 저장."""
    wa._require_use()
    if not name.lower().endswith(('.xlsx', '.xlsm')):
        raise ValueError('양식 원본은 엑셀(xlsx) 파일만 올릴 수 있습니다.')
    layout = _layout(_load(content).active)
    if not layout['target']:
        raise ValueError('양식에서 대상월 열(플랫폼·성명·담당업무 등) 머리글을 찾지 못했습니다.')
    os.makedirs(os.path.dirname(TEMPLATE_PATH), exist_ok=True)
    with open(TEMPLATE_PATH, 'wb') as fh:
        fh.write(content)
    f = wa._settings().get('form') or {}
    wa._update_settings(form={**f, 'template_name': os.path.basename(name)})
    return settings()


def delete_template() -> None:
    wa._require_use()
    try:
        os.remove(TEMPLATE_PATH)
    except OSError:
        pass


def _load(content: bytes):
    from openpyxl import load_workbook
    try:
        return load_workbook(io.BytesIO(content))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f'엑셀을 열지 못했습니다({type(exc).__name__}).') from exc


def default_template() -> bytes:
    """구글 시트 "업무분장 양식"과 같은 구조의 기본 양식."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    wb = Workbook()
    ws = wb.active
    ws.title = '업무분장'
    ws['A1'], ws['C1'], ws['M1'] = 'Knox ID, 재직현황', "'26년 12월 1일자", "참고 : '26년 11월 1일자"
    for rng in ('A1:B1', 'C1:L1', 'M1:V1'):
        ws.merge_cells(rng)
    for i, h in enumerate([KNOX, STATUS] + FIELDS + FIELDS, start=1):
        ws.cell(row=2, column=i, value=h)
    thin = Side(style='thin', color='999999')
    fills = {1: 'E7E6E6', 3: 'DDEBF7', 13: 'F2F2F2'}
    for col in range(1, 23):
        fill = fills[1 if col <= 2 else 3 if col <= 12 else 13]
        for row in (1, 2):
            c = ws.cell(row=row, column=col)
            c.font = Font(bold=True, color='7F7F7F' if col > 12 else '000000')
            c.fill = PatternFill('solid', fgColor=fill)
            c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            c.border = Border(left=thin, right=thin, top=thin, bottom=thin)
        width = {KNOX: 14, '상세업무': 30, '담당업무': 20, '과제/파트명': 18}.get(ws.cell(row=2, column=col).value, 12)
        ws.column_dimensions[ws.cell(row=2, column=col).column_letter].width = width
    ws.freeze_panes = 'C3'
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def template_bytes() -> bytes:
    try:
        with open(TEMPLATE_PATH, 'rb') as fh:
            return fh.read()
    except OSError:
        return default_template()


# ── 양식 구조 파악 ───────────────────────────────────────────────────────────

def _layout(ws) -> dict:
    """머리글 행·묶음 행을 찾아 {'header_row', 'group_row', 'common': {이름: 열}, 'target': {...}, 'ref': {...}}."""
    best, best_n = None, 0
    for r in range(1, min(ws.max_row, 10) + 1):
        vals = [str(c.value).strip() for c in ws[r] if c.value is not None and str(c.value).strip()]
        n = sum(1 for v in vals if v in FIELDS or v in (KNOX, STATUS))
        if n > best_n:
            best, best_n = r, n
    if not best:
        return {'header_row': None, 'group_row': None, 'common': {}, 'target': {}, 'ref': {}}
    group_row = best - 1 if best > 1 else None
    groups = {}
    if group_row:
        merged = {}
        for rng in ws.merged_cells.ranges:
            if rng.min_row <= group_row <= rng.max_row:
                for col in range(rng.min_col, rng.max_col + 1):
                    merged[col] = ws.cell(row=rng.min_row, column=rng.min_col).value
        last = ''
        for col in range(1, ws.max_column + 1):
            v = merged.get(col, ws.cell(row=group_row, column=col).value)
            if v is not None and str(v).strip():
                last = str(v).strip()
            groups[col] = last
    common, target, ref = {}, {}, {}
    for col in range(1, ws.max_column + 1):
        v = ws.cell(row=best, column=col).value
        name = str(v).strip() if v is not None else ''
        if not name:
            continue
        if groups.get(col, '').startswith('참고'):
            ref.setdefault(name, col)
        elif name in (KNOX, STATUS) and name not in common:
            common[name] = col
        elif name not in target:
            target[name] = col
    return {'header_row': best, 'group_row': group_row, 'common': common, 'target': target, 'ref': ref}


# ── 부서별 데이터 ────────────────────────────────────────────────────────────

def _researchers() -> pd.DataFrame:
    df = data_store.read_processed('researchers')
    if df.empty:
        return df
    from services.similarity_map import dep_name_for_org_code
    df = df.copy()
    cache = {}
    df['_dept'] = [cache.setdefault(oc, dep_name_for_org_code(str(oc or ''))) for oc in df.get('org_code', '')]
    if 'knox_id' in df.columns:
        df['_knox'] = df['knox_id'].fillna('').astype(str).str.strip().str.lower().replace('nan', '')
    else:
        df['_knox'] = ''
    if 'is_current' in df.columns:
        df = df[df['is_current'].astype(str) == 'Y']
    return df


def department_rows(target: str, dept: str, prefill_target: bool = True) -> list:
    """양식에 쓸 행 [{'common': {...}, 'target': {...}, 'ref': {...}}]."""
    y, m = wa._month(target)
    py, pm = wa._shift_month(y, m, -1)
    prev = wa.submission_file(f'{py:04d}-{pm:02d}', dept)
    cur = _researchers()
    by_knox = {k: r for k, r in zip(cur['_knox'], cur.to_dict('records'))} if not cur.empty else {}
    members = cur[cur['_dept'] == dept] if not cur.empty else cur
    rows, seen = [], set()
    if prev:
        try:
            df = wa.read_table(*prev)
        except ValueError:
            df = pd.DataFrame()
        cols = [c for c in df.columns if not c.startswith(wa.REF_PREFIX)]
        for rec in df[cols].to_dict('records') if not df.empty else []:
            if not any(str(v).strip() for v in rec.values()):
                continue
            fields = {k: rec.get(k, '') for k in FIELDS if k in rec}
            knox = str(rec.get(KNOX, '') or '').strip()
            hit = by_knox.get(knox.lower()) if knox else None
            if knox:
                seen.add(knox.lower())
            status = ('재직' if hit is not None and hit['_dept'] == dept else
                      '부서 변경(확인)' if hit is not None else '미재직(확인)') if knox else ''
            rows.append({'common': {KNOX: knox, STATUS: status}, 'ref': fields,
                         'target': dict(fields) if prefill_target else {}})
    new_status = '신규(확인)' if prev else '재직'
    for rec in members.sort_values('name').to_dict('records') if not members.empty else []:
        if rec['_knox'] and rec['_knox'] in seen:
            continue
        knox = str(rec.get('knox_id', '') or '').strip()
        knox = '' if knox.lower() == 'nan' else knox
        rows.append({'common': {KNOX: knox, STATUS: new_status}, 'ref': {},
                     'target': {NAME: str(rec.get('name', '') or '')}})
    return rows


def _fmt_date_label(y: int, m: int) -> str:
    return f"'{y % 100:02d}년 {m}월 1일자"


def file_name(target: str, dept: str) -> str:
    y, m = wa._month(target)
    return f'업무분장_{y % 100:02d}년{m}월_{wa._safe(dept)}.xlsx'


def build_form(target: str, dept: str, prefill_target: bool | None = None) -> tuple[str, bytes]:
    """부서 하나의 양식(파일명, xlsx bytes)."""
    if prefill_target is None:
        prefill_target = settings()['prefill_target']
    wb = _load(template_bytes())
    ws = wb.active
    lay = _layout(ws)
    if not lay['header_row']:
        raise ValueError('양식 원본에서 머리글을 찾지 못했습니다.')
    y, m = wa._month(target)
    py, pm = wa._shift_month(y, m, -1)
    if lay['group_row']:
        for c in ws[lay['group_row']]:
            if isinstance(c.value, str) and _DATE_RE.search(c.value):
                label = _fmt_date_label(py, pm) if c.value.strip().startswith('참고') else _fmt_date_label(y, m)
                c.value = _DATE_RE.sub(label, c.value)
    start = lay['header_row'] + 1
    all_cols = list(lay['common'].values()) + list(lay['target'].values()) + list(lay['ref'].values())
    for r in range(start, ws.max_row + 1):          # 원본에 남아 있던 예시 값 지우기(서식은 유지)
        for col in all_cols:
            cell = ws.cell(row=r, column=col)
            if not type(cell).__name__ == 'MergedCell':
                cell.value = None
    for i, row in enumerate(department_rows(target, dept, prefill_target)):
        for part in ('common', 'target', 'ref'):
            for name, val in row[part].items():
                col = lay[part].get(name)
                if col and val not in (None, ''):
                    ws.cell(row=start + i, column=col, value=val)
    buf = io.BytesIO()
    wb.save(buf)
    return file_name(target, dept), buf.getvalue()


def build_all_zip(target: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for d in wa.departments():
            name, content = build_form(target, d)
            z.writestr(name, content)
    return buf.getvalue()


def per_contact_forms(target: str):
    """발송용 — 담당자(c['dept'])마다 그 부서 양식을 붙이는 함수(부서별 한 번만 생성)."""
    cache = {}

    def _for(c: dict) -> list:
        d = c.get('dept', '')
        if d not in cache:
            cache[d] = [build_form(target, d)] if d else []
        return cache[d]
    for d in wa.departments():                      # 스레드 발송 전에 미리 만들어 둠
        _for({'dept': d})
    return _for

