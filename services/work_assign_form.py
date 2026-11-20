"""
업무분장 플랫폼별 양식 자동 생성(2026-11-20).

양식 구조(실제 "업무분장 양식" 구글 시트): 1행 병합 묶음 머리글(A:B "Knox ID, 재직현황" / C:L "'26년 12월 1일자" /
M:V "참고 : '26년 11월 1일자"), 2행 열 이름(Knox ID·재직현황 + 플랫폼~비고 10개 열이 대상월·참고로 반복).

사용자 확정(2026-11-20 개정 — 처음 만든 "지난달 회신 기반" 방식을 바꿈):
- 대상자 = 웹의 최신 인력현황(is_current=Y) 중 직급(position) CL1·CL2·CL3·CL4·H2.
- 채우는 칸 = Knox ID, 재직현황(인력현황 재직상태명), 대상월 묶음의 플랫폼·그룹·과제/파트명(team_refer 1·2·3단계 부서명),
  성명. 담당업무~비고는 부서가 작성하도록 비운다.
- "참고 : 지난달" 묶음 = 사용자가 대상월마다 따로 올리는 엑셀(지난달 업무분장)에서 Knox ID(없으면 성명)로 찾아 채움. 참고
  엑셀에만 있고 현재 대상자가 아닌 사람은 그 플랫폼 파일 맨 아래에 참고 칸만 채워 붙인다(재직현황 = 인력현황 값 또는
  "현 명단 없음"). 참고 엑셀을 안 올렸으면 지난달 회신(통합표)으로 대신한다.
- 1행 날짜 문구는 대상월에 맞춰 바뀜('27년 1월분이면 '27년 1월 1일자 / 참고 : '26년 12월 1일자).
- 전체 명단을 플랫폼(1단계 부서명) 단위 파일로 나누고, 담당자 명단의 부서가 그 플랫폼인 담당자에게만 그 파일을 보낸다.

양식 원본: 화면에서 올린 엑셀(work_assign_form_template.xlsx)이 있으면 그 서식을 그대로 쓰고, 없으면 같은 구조의 기본 양식.
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
REF_DIR = os.path.join(data_store.DATA_DIR, 'work_assign_ref')        # 대상월별 참고(지난달) 엑셀
TARGET_POSITIONS = ('CL1', 'CL2', 'CL3', 'CL4', 'H2')                # 대상 직급(사용자 확정)
ORG_FIELDS = ('플랫폼', '그룹', '과제/파트명')
FIELDS = ['플랫폼', '그룹', '과제/파트명', '성명', '담당업무', '상세업무', '인력 Assign 형태', '주과제 참여율', '부과제명', '비고']
KNOX, STATUS, NAME = 'Knox ID', '재직현황', '성명'
_DATE_RE = re.compile(r"'?\d{2,4}\s*년\s*\d{1,2}\s*월\s*1\s*일자")


# ── 설정·양식 원본 ──────────────────────────────────────────────────────────

def settings() -> dict:
    f = wa._settings().get('form') or {}
    return {'enabled': bool(f.get('enabled')),
            'template_name': f.get('template_name', '') if os.path.exists(TEMPLATE_PATH) else ''}


def save_settings(enabled: bool) -> dict:
    wa._require_use()
    f = wa._settings().get('form') or {}
    wa._update_settings(form={**f, 'enabled': bool(enabled)})
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


# ── 대상자·참고 데이터 ──────────────────────────────────────────────────────

def _ref_path(target: str) -> str:
    wa._month(target)
    return os.path.join(REF_DIR, f'{target}.xlsx')


def ref_info(target: str) -> dict:
    """대상월의 참고 엑셀 정보 {'name','rows','at'} — 없으면 {}."""
    return dict(((wa._settings().get('form') or {}).get('ref') or {}).get(target) or {}) \
        if os.path.exists(_ref_path(target)) else {}


def save_ref(target: str, name: str, content: bytes) -> dict:
    """참고(지난달 업무분장) 엑셀 저장 — 양식 그대로(대상월·참고 묶음)든 단순 표든 첫 묶음 열을 쓴다."""
    from datetime import datetime
    wa._require_use()
    df = wa.read_table(name, content)
    main = [c for c in df.columns if not c.startswith(wa.REF_PREFIX)]
    if not ({KNOX, NAME} & set(main)):
        raise ValueError('참고 엑셀에서 Knox ID 또는 성명 열을 찾지 못했습니다.')
    os.makedirs(REF_DIR, exist_ok=True)
    with open(_ref_path(target), 'wb') as fh:
        fh.write(content)
    f = wa._settings().get('form') or {}
    ref = dict(f.get('ref') or {})
    ref[target] = {'name': os.path.basename(name), 'rows': int((df[main] != '').any(axis=1).sum()),
                   'at': datetime.now().isoformat(timespec='seconds')}
    wa._update_settings(form={**f, 'ref': ref})
    return ref[target]


def delete_ref(target: str) -> None:
    wa._require_use()
    try:
        os.remove(_ref_path(target))
    except OSError:
        pass


def _ref_table(target: str) -> tuple[pd.DataFrame, str]:
    """참고 데이터(지난달) 표와 출처 설명. 올린 참고 엑셀 → 없으면 지난달 회신 통합표."""
    try:
        with open(_ref_path(target), 'rb') as fh:
            df = wa.read_table('ref.xlsx', fh.read())
        return df[[c for c in df.columns if not c.startswith(wa.REF_PREFIX)]], '올린 참고 엑셀'
    except OSError:
        pass
    y, m = wa._month(target)
    py, pm = wa._shift_month(y, m, -1)
    df = wa.merged(f'{py:04d}-{pm:02d}')
    return df, ('지난달 회신 통합표' if not df.empty else '')


def _key(knox: str, name: str) -> str:
    knox = (knox or '').strip().lower()
    return f'k:{knox}' if knox and knox != 'nan' else f'n:{(name or "").strip()}'


def _s(v) -> str:
    v = '' if v is None else str(v).strip()
    return '' if v.lower() == 'nan' else v


def target_people() -> list:
    """대상자 [{'knox','status','플랫폼','그룹','과제/파트명','성명','_order'}] — 최신 인력현황, 대상 직급만."""
    df = data_store.read_processed('researchers')
    if df.empty:
        return []
    if 'is_current' in df.columns:
        df = df[df['is_current'].astype(str) == 'Y']
    if 'position' not in df.columns:
        return []
    df = df[df['position'].astype(str).str.strip().str.upper().isin(TARGET_POSITIONS)]
    from services import similarity_map as sm
    levels = sm.org_code_level_name_map()
    order = sm.org_code_dep_code_map()
    out = []
    for r in df.to_dict('records'):
        oc = _s(r.get('org_code'))
        l1, l2, l3 = levels.get(oc, ('', '', ''))
        l1 = l1 or sm.dep_name_for_org_code(oc) or _s(r.get('department'))
        out.append({'knox': _s(r.get('knox_id')), 'status': _s(r.get('employment_status')) or '재직',
                    '플랫폼': l1, '그룹': l2, '과제/파트명': l3 or oc, NAME: _s(r.get('name')),
                    '_order': (str(order.get(oc, '')), _s(r.get('name')))})
    out.sort(key=lambda p: p['_order'])
    return out


def platforms(people: list | None = None) -> list:
    """대상자가 있는 플랫폼(조직 순서)."""
    out = []
    for p in people if people is not None else target_people():
        if p['플랫폼'] and p['플랫폼'] not in out:
            out.append(p['플랫폼'])
    return out


def platform_rows(target: str, platform: str | None, people: list | None = None, ref: pd.DataFrame | None = None
                  ) -> list:
    """한 플랫폼 파일의 행 [{'common': {...}, 'target': {...}, 'ref': {...}}]. platform=None이면 전체 명단."""
    people = people if people is not None else target_people()
    if ref is None:
        ref = _ref_table(target)[0]
    ref_by_key = {}
    for rec in ref.to_dict('records') if not ref.empty else []:
        k = _key(rec.get(KNOX, ''), rec.get(NAME, ''))
        if k not in ('n:', 'k:'):
            ref_by_key.setdefault(k, {f: _s(rec.get(f)) for f in FIELDS if f in rec})
    rows, used = [], set()
    for p in people:
        if platform is not None and p['플랫폼'] != platform:
            continue
        k = _key(p['knox'], p[NAME])
        alt = _key('', p[NAME])
        ref_rec = ref_by_key.get(k) or (ref_by_key.get(alt) if not p['knox'] else None) or {}
        used.update({k, alt} if ref_rec else set())
        rows.append({'common': {KNOX: p['knox'], STATUS: p['status']},
                     'target': {f: p[f] for f in ORG_FIELDS + (NAME,)}, 'ref': ref_rec})
    # 참고에만 있는(이번 대상이 아닌) 같은 플랫폼 사람 — 참고 칸만 채워 뒤에 붙임
    all_status = _all_status()
    for k, rec in ref_by_key.items():
        if k in used or (platform is not None and rec.get('플랫폼', '') != platform):
            continue
        knox = k[2:] if k.startswith('k:') else ''
        rows.append({'common': {KNOX: knox, STATUS: all_status.get(knox, '현 명단 없음')}, 'target': {}, 'ref': rec})
    return rows


def _all_status() -> dict:
    """Knox ID(소문자) → 최신 인력현황 재직상태(대상 직급이 아니어도) — 참고에만 있는 사람 표시용."""
    df = data_store.read_processed('researchers')
    if df.empty or 'knox_id' not in df.columns:
        return {}
    if 'is_current' in df.columns:
        df = df[df['is_current'].astype(str) == 'Y']
    st = df['employment_status'] if 'employment_status' in df.columns else pd.Series(['재직'] * len(df), index=df.index)
    return {_s(k).lower(): (_s(v) or '재직') for k, v in zip(df['knox_id'], st) if _s(k)}


def _fmt_date_label(y: int, m: int) -> str:
    return f"'{y % 100:02d}년 {m}월 1일자"


def file_name(target: str, platform: str | None) -> str:
    y, m = wa._month(target)
    return f"업무분장_{y % 100:02d}년{m}월_{wa._safe(platform) if platform else '전체'}.xlsx"


def build_form(target: str, platform: str | None, people: list | None = None, ref: pd.DataFrame | None = None
               ) -> tuple[str, bytes]:
    """플랫폼 하나의 양식(파일명, xlsx bytes). platform=None이면 전체 명단 한 파일(확인용)."""
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
    for i, row in enumerate(platform_rows(target, platform, people, ref)):
        for part in ('common', 'target', 'ref'):
            for name, val in row[part].items():
                col = lay[part].get(name)
                if col and val not in (None, ''):
                    ws.cell(row=start + i, column=col, value=val)
    buf = io.BytesIO()
    wb.save(buf)
    return file_name(target, platform), buf.getvalue()


def build_all(target: str) -> dict:
    """전체 명단을 플랫폼별 파일로 {플랫폼: (파일명, bytes)} — 대상자·참고 데이터는 한 번만 읽는다."""
    people = target_people()
    ref = _ref_table(target)[0]
    return {p: build_form(target, p, people, ref) for p in platforms(people)}


def build_all_zip(target: str) -> bytes:
    forms = build_all(target)
    if not forms:
        raise ValueError('대상자(최신 인력현황의 CL1~CL4·H2)가 없습니다.')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, content in forms.values():
            z.writestr(name, content)
    return buf.getvalue()


def plan(target: str) -> dict:
    """발송 전 확인용 — {'platforms': [{'platform','count','contacts':[...]}], 'unmatched_contacts': [...], 'ref': 출처}."""
    people = target_people()
    contacts = wa.load_contacts()
    plats = platforms(people)
    out = [{'platform': p, 'count': sum(1 for x in people if x['플랫폼'] == p),
            'contacts': [c for c in contacts if c.get('dept') == p]} for p in plats]
    return {'platforms': out, 'unmatched_contacts': [c for c in contacts if c.get('dept') not in plats],
            'ref': _ref_table(target)[1]}


def per_contact_forms(target: str):
    """발송용 — 담당자 부서(= 플랫폼) 파일만 붙이는 함수(겸직이면 맡은 플랫폼 파일 모두). 하나도 없으면 보내지 않음(실패 기록)."""
    forms = build_all(target)

    def _for(c: dict) -> list:
        depts = c.get('depts') or [c.get('dept', '')]          # 겸직 담당자는 맡은 플랫폼 파일을 모두 한 메일에
        files = [forms[d] for d in depts if d in forms]
        if not files:
            raise ValueError(f"'{' · '.join(depts)}' 플랫폼 대상자가 없어 보내지 않았습니다(담당자 부서명 확인)")
        return files
    return _for
