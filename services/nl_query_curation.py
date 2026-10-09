"""
AI 검색 개선 반영(2026-10, 사용자 요청) — 관리자가 "AI 검색 테스트" 결과 엑셀에 직접 적은 올바른
접근방법을 AI 검색에 반영하는 백엔드.

엑셀의 5개 입력 열(CURATION_HEADERS)을 채워 다시 올리면 "반영 구분"에 따라 세 갈래로 처리한다.
  규칙  : 한 줄 규칙 문장을 "규칙 설정"(services/query_settings)의 자동 관리 블록에 추가 — 모든 질문의
          라우팅/SQL 생성 프롬프트에 즉시 적용. 항목별로 끄기/삭제 가능, 기존 수기 규칙은 건드리지 않음.
  예시  : 질문 → 올바른 접근/SQL을 "검증된 예시"로 저장. 비슷한 질문이 들어오면(임베딩 유사도, 정확히 같은
          질문은 임베딩 없이도) 상위 3건을 라우팅/SQL 생성 프롬프트에 예시로 붙인다.
  코드  : 서버에서 적용하지 않고 "코드 수정 요청서"(마크다운)로 내려받아 개발 쪽에 전달 — 소스 코드는
          저장소에서 테스트와 함께 고쳐 커밋한다(실행 중인 컨테이너의 코드를 화면에서 고치지 않는다).
  무시  : 기록만.
"기대 사번"을 적은 항목은 AI 검색 테스트의 "정답 대조" 질문으로도 자동 편입된다.
모든 반영은 이력(nl_query_curation_history.jsonl)에 남고, 규칙/예시는 개별로 끄거나 삭제할 수 있다.
"""

import io
import json
import os
import re
import threading
from datetime import datetime

from services import data_store

H_APPROACH = '올바른 결과/접근방법'
H_SQL = '올바른 SQL'
H_IDS = '기대 사번'
H_KIND = '반영 구분'
H_RULE = '규칙 문장'
CURATION_HEADERS = [H_APPROACH, H_SQL, H_IDS, H_KIND, H_RULE]
KINDS = ['규칙', '예시', '코드', '무시']

MAX_RULE_LEN = 300
MAX_HINT_EXAMPLES = 3
SIMILARITY_THRESHOLD = 0.75
_BLOCK_START = '# [AI 검색 테스트에서 반영한 규칙 — 자동 관리 블록, 화면에서만 수정하세요]'
_BLOCK_END = '# [/자동 관리 블록]'
_lock = threading.Lock()


# ── 저장소 ───────────────────────────────────────────────────────────────────

def _path(name: str) -> str:
    os.makedirs(data_store.DATA_DIR, exist_ok=True)
    return os.path.join(data_store.DATA_DIR, name)


def _read(name: str) -> list:
    try:
        with open(_path(name), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _write(name: str, data: list) -> None:
    tmp = _path(name) + f'.{os.getpid()}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _path(name))


def _history(event: str, **fields) -> None:
    rec = {'시각': datetime.now().isoformat(timespec='seconds'), '이벤트': event, **fields}
    with open(_path('nl_query_curation_history.jsonl'), 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')


def list_rules() -> list[dict]:
    return _read('nl_query_curated_rules.json')


def list_examples() -> list[dict]:
    return _read('nl_query_verified_examples.json')


def _next_id(prefix: str, items: list) -> str:
    nums = [int(i['id'][1:]) for i in items if str(i.get('id', '')).startswith(prefix) and i['id'][1:].isdigit()]
    return f'{prefix}{max(nums, default=0) + 1}'


# ── 규칙 블록 동기화 ──────────────────────────────────────────────────────────

_BLOCK_RE = re.compile(re.escape(_BLOCK_START) + r'.*?' + re.escape(_BLOCK_END), re.S)


def _compose_rules_text(manual_text: str, rules: list[dict]) -> str:
    active = [r for r in rules if r.get('active', True)]
    manual = _BLOCK_RE.sub('', manual_text or '').strip()
    if not active:
        return manual
    block = '\n'.join([_BLOCK_START, *[f'- {r["text"]}' for r in active], _BLOCK_END])
    return f'{manual}\n\n{block}'.strip()


def _sync_rules(rules: list[dict]) -> None:
    """query_settings의 규칙 텍스트에서 자동 관리 블록만 갈아 끼운다(수기 규칙은 보존)."""
    from services import query_settings
    text = _compose_rules_text(query_settings.read_rules(), rules)
    if len(text) > query_settings._MAX_LEN:
        raise ValueError(f'규칙 설정이 {query_settings._MAX_LEN}자 상한을 넘습니다({len(text)}자) — '
                         '기존 규칙을 정리하거나 일부를 "예시"로 바꿔 주세요.')
    query_settings.write_rules(text)


# ── 검증된 예시 → 프롬프트 힌트 ───────────────────────────────────────────────

def _norm(q: str) -> str:
    return re.sub(r'\s+', '', str(q or '')).lower()


def find_similar_examples(question: str, top_n: int = MAX_HINT_EXAMPLES,
                          threshold: float = SIMILARITY_THRESHOLD) -> list[dict]:
    examples = [e for e in list_examples() if e.get('active', True)]
    question = (question or '').strip()
    if not examples or not question:
        return []
    exact = [e for e in examples if _norm(e['question']) == _norm(question)]
    rest = [e for e in examples if e not in exact]
    picked = list(exact)
    if rest and len(picked) < top_n:
        try:
            import researcher_fit as fit
            vectors = fit.cached_embed([question] + [e['question'] for e in rest])
            sims = fit.cosine_sim_matrix(vectors[:1], vectors[1:])[0]
            ranked = sorted(range(len(rest)), key=lambda i: -sims[i])
            picked += [rest[i] for i in ranked if sims[i] >= threshold][:top_n - len(picked)]
        except Exception:  # noqa: BLE001 — 임베딩이 없어도 검색 자체는 계속돼야 한다(정확 일치만 사용)
            pass
    return picked[:top_n]


def examples_hint_for(question: str, for_router: bool = False) -> str:
    """프롬프트 뒤에 붙일 텍스트 조각. 비슷한 검증 예시가 없으면 빈 문자열(프롬프트 영향 없음)."""
    matches = find_similar_examples(question)
    if not matches:
        return ''
    lines = []
    for m in matches:
        if for_router:
            kind = 'open_data_query' if m.get('sql') else '(접근방법 참고)'
            lines.append(f'- 질문 "{m["question"]}" → 분류: {kind}. 올바른 접근: {m.get("approach", "")}')
        else:
            parts = [f'- 질문: "{m["question"]}"']
            if m.get('approach'):
                parts.append(f'  올바른 접근: {m["approach"]}')
            if m.get('sql'):
                parts.append(f'  올바른 SQL: {m["sql"]}')
            lines.append('\n'.join(parts))
    return ('\n\n# 관리자가 검증한 예시 (비슷한 질문을 올바르게 처리한 방식 — 참고하되, 지금 질문의 조건이 실제로 '
            '다르면 그대로 따르지 말고 조건에 맞게 조정할 것)\n' + '\n'.join(lines))


# ── 엑셀 업로드 파싱 / 검증 ───────────────────────────────────────────────────

def _split_ids(text) -> list[str]:
    ids = []
    for tok in re.split(r'[\s,;/]+', str(text or '')):
        tok = tok.strip()
        if tok and tok.lower() != 'none':
            tok = tok.split('.')[0] if re.fullmatch(r'\d+\.0+', tok) else tok
            ids.append(tok.zfill(8))
    return list(dict.fromkeys(ids))


def parse_upload(content: bytes) -> tuple[list[dict], list[str]]:
    """수정한 결과 엑셀 → (반영 구분이 적힌 행 목록, 안내/오류). 반영 구분이 빈 행은 건너뛴다."""
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(content), data_only=True)
    except Exception as exc:  # noqa: BLE001
        return [], [f'엑셀을 읽지 못했습니다: {type(exc).__name__}: {exc}']
    ws = wb['결과'] if '결과' in wb.sheetnames else wb.worksheets[0]
    headers = {str(c.value).strip(): c.column - 1 for c in ws[1] if c.value is not None}
    notes = []
    for needed in ('질문', H_KIND):
        if needed not in headers:
            return [], [f'"{needed}" 열이 없습니다 — AI 검색 테스트에서 내려받은 엑셀을 수정해 올려 주세요.']

    def cell(row, name):
        i = headers.get(name)
        v = row[i] if i is not None and i < len(row) else None
        return '' if v is None else str(v).strip()

    entries, skipped = [], 0
    for r_no, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        question = cell(row, '질문')
        kind = cell(row, H_KIND)
        if not question or not kind:
            skipped += 1 if question else 0
            continue
        entries.append({'row': r_no, 'question': question, 'category': cell(row, '카테고리'),
                        'status': cell(row, '상태'), 'kind': kind, 'approach': cell(row, H_APPROACH),
                        'sql': cell(row, H_SQL), 'expected_ids': _split_ids(cell(row, H_IDS)),
                        'rule_text': cell(row, H_RULE), 'sys_sql': cell(row, 'SQL'),
                        'intent': cell(row, '유형(intent)'), 'judge_reason': cell(row, '심사 이유'),
                        'judge_issue': cell(row, '문제 유형')})
    if skipped:
        notes.append(f'"{H_KIND}"이 비어 있는 {skipped}행은 건너뛰었습니다.')
    return entries, notes


def _open_tables_connection():
    import duckdb
    from services import auth, open_data_query
    tables = open_data_query._discover_csv_tables()
    tables.update(open_data_query._discover_json_tables())
    tables = auth.filter_permitted_tables(tables)
    con = duckdb.connect(':memory:', config={'enable_external_access': False})
    for name, df in tables.items():
        con.register(name, df)
    return con


def dry_run_sql(sql: str, expected_ids: list[str], con=None) -> dict:
    """SQL을 안전 검증 후 읽기 전용으로 실행해 건수/(기대 사번이 있으면) 정답 대조 F1을 돌려준다."""
    from services import ai_search_lab, open_data_query, text2sql
    safe = text2sql.sanitize_sql(open_data_query._cap_limit(sql))
    own = con is None
    con = con or _open_tables_connection()
    try:
        columns, rows = open_data_query._execute(con, safe)
    finally:
        if own:
            con.close()
    out = {'rows': len(rows), 'columns': list(columns)}
    if expected_ids and 'researcher_id' in columns:
        idx = list(columns).index('researcher_id')
        got = {str(r[idx]).strip().zfill(8) for r in rows if r[idx] not in (None, '')}
        g = ai_search_lab._golden_compare(expected_ids, got)
        out['f1'] = g['f1']
        out['precision'], out['recall'] = g['precision'], g['recall']
    return out


def validate(entries: list[dict], run_sql: bool = True) -> list[dict]:
    """각 항목에 ok/problem/check(검증 결과 문구)를 채운다. 규칙 총 길이 초과도 미리 알려준다."""
    from services import text2sql
    con = None
    sql_entries = [e for e in entries if e['kind'] == '예시' and e['sql']]
    if run_sql and sql_entries:
        try:
            con = _open_tables_connection()
        except Exception:  # noqa: BLE001 — 연결을 못 열면 문법 검증만 한다
            con = None
    try:
        for e in entries:
            e['ok'], e['problem'], e['check'] = True, '', ''
            kind = e['kind']
            if kind not in KINDS:
                e['ok'], e['problem'] = False, f'"{kind}"은(는) 알 수 없는 반영 구분입니다(규칙/예시/코드/무시).'
            elif kind == '규칙':
                if not e['rule_text']:
                    e['ok'], e['problem'] = False, '규칙 문장이 비어 있습니다.'
                elif len(e['rule_text']) > MAX_RULE_LEN:
                    e['ok'], e['problem'] = False, f'규칙 문장이 {MAX_RULE_LEN}자를 넘습니다({len(e["rule_text"])}자).'
            elif kind == '예시':
                if not (e['approach'] or e['sql']):
                    e['ok'], e['problem'] = False, '올바른 결과/접근방법 또는 올바른 SQL이 필요합니다.'
                elif e['sql']:
                    try:
                        if run_sql:
                            r = dry_run_sql(e['sql'], e['expected_ids'], con)
                            e['check'] = f'SQL 실행 {r["rows"]}건' + (f', 기대 대비 F1 {r["f1"]}' if 'f1' in r else '')
                            if 'f1' in r and r['f1'] < 0.8:
                                e['check'] += ' (기대와 차이가 큼 — SQL을 다시 확인하세요)'
                        else:
                            text2sql.sanitize_sql(e['sql'])
                            e['check'] = 'SQL 문법 검증 통과'
                    except text2sql.Text2SQLError as exc:
                        e['ok'], e['problem'] = False, f'SQL이 허용되지 않습니다: {exc}'
                    except Exception as exc:  # noqa: BLE001
                        e['ok'], e['problem'] = False, f'SQL 실행 오류: {str(exc)[:150]}'
            elif kind == '코드':
                if not e['approach']:
                    e['ok'], e['problem'] = False, '코드 수정 요청에는 올바른 결과/접근방법을 적어 주세요.'
    finally:
        if con is not None:
            con.close()
    return entries


# ── 반영 ─────────────────────────────────────────────────────────────────────

def _upsert_golden(entries: list[dict]) -> int:
    """기대 사번이 있는 항목을 AI 검색 테스트의 질문 목록(정답 대조)으로 편입/갱신."""
    from services import ai_search_lab
    draft = ai_search_lab.load_draft()
    by_q = {d['question']: d for d in draft}
    n = 0
    for e in entries:
        if not e['expected_ids']:
            continue
        exp = {'ids': e['expected_ids'], 'desc': f'관리자 지정 정답 — 기대 {len(e["expected_ids"])}명'}
        if e['question'] in by_q:
            by_q[e['question']]['expected'] = exp
        else:
            draft.append({'id': '', 'category': e['category'] or ai_search_lab.GOLDEN_CATEGORY,
                          'question': e['question'], 'expected': exp})
        n += 1
    if n:
        ai_search_lab.save_draft(draft)
    return n


def apply_entries(entries: list[dict], user_id: str = '', run_id: str = '') -> dict:
    """검증을 통과한 항목을 반영한다. 규칙 글자수 상한을 넘으면 아무것도 바꾸지 않고 ValueError."""
    entries = [e for e in entries if e.get('ok', True) and e['kind'] in KINDS]
    now = datetime.now().isoformat(timespec='seconds')
    with _lock:
        rules = list_rules()
        examples = list_examples()
        new_rules, new_examples, code_entries, ignored = [], [], [], 0
        known_rules = {r['text'] for r in rules}
        for e in entries:
            if e['kind'] == '규칙' and e['rule_text'] not in known_rules:
                known_rules.add(e['rule_text'])
                new_rules.append({'id': '', 'text': e['rule_text'], 'active': True, 'question': e['question'],
                                  'created_at': now, 'created_by': user_id, 'run_id': run_id})
            elif e['kind'] == '예시':
                new_examples.append(e)
            elif e['kind'] == '코드':
                code_entries.append(e)
            elif e['kind'] == '무시':
                ignored += 1

        merged_rules = list(rules)
        for r in new_rules:
            r['id'] = _next_id('R', merged_rules)
            merged_rules.append(r)
        if new_rules:
            _sync_rules(merged_rules)            # 상한 초과면 여기서 ValueError — 아직 아무것도 저장 안 됨
            _write('nl_query_curated_rules.json', merged_rules)
            for r in new_rules:
                _history('규칙 추가', id=r['id'], 문장=r['text'], 질문=r['question'], 반영자=user_id, run_id=run_id)

        updated = 0
        for e in new_examples:
            same = next((x for x in examples if _norm(x['question']) == _norm(e['question'])), None)
            fields = {'question': e['question'], 'category': e['category'], 'approach': e['approach'],
                      'sql': e['sql'], 'expected_ids': e['expected_ids'], 'active': True,
                      'created_at': now, 'created_by': user_id, 'run_id': run_id}
            if same:
                same.update(fields)
                updated += 1
                _history('예시 갱신', id=same['id'], 질문=e['question'], 반영자=user_id, run_id=run_id)
            else:
                fields['id'] = _next_id('E', examples)
                examples.append(fields)
                _history('예시 추가', id=fields['id'], 질문=e['question'], 반영자=user_id, run_id=run_id)
        if new_examples:
            _write('nl_query_verified_examples.json', examples)

    golden = _upsert_golden(entries)
    code_md = build_code_request(code_entries) if code_entries else ''
    for e in code_entries:
        _history('코드 수정 요청', 질문=e['question'], 접근=e['approach'][:200], 반영자=user_id, run_id=run_id)
    return {'rules': len(new_rules), 'examples': len(new_examples) - updated, 'examples_updated': updated,
            'code': len(code_entries), 'ignored': ignored, 'golden': golden, 'code_request': code_md,
            'skipped_duplicate_rules': sum(1 for e in entries if e['kind'] == '규칙') - len(new_rules)}


def build_code_request(entries: list[dict]) -> str:
    """코드 수정이 필요한 항목들을 개발 쪽에 전달할 마크다운 요청서로 만든다."""
    lines = ['# AI 검색 코드 수정 요청서', '',
             f'작성: {datetime.now().strftime("%Y-%m-%d %H:%M")} · 항목 {len(entries)}건', '',
             '> 아래 각 항목은 AI 검색 테스트에서 결과가 잘못 나온 질문과, 관리자가 직접 적은 올바른 접근방법입니다.',
             '> 프롬프트 규칙/예시로는 해결되지 않는 코드 수정 건입니다. 해당 스크립트를 고치고 테스트를 추가해 주세요.', '']
    for i, e in enumerate(entries, 1):
        lines += [f'## {i}. {e["question"]}', '',
                  f'- 카테고리: {e.get("category") or "-"} · 시스템 판정: {e.get("status") or "-"} · 분류: {e.get("intent") or "-"}']
        if e.get('judge_issue') or e.get('judge_reason'):
            lines.append(f'- LLM 심사: {e.get("judge_issue") or ""} — {e.get("judge_reason") or ""}')
        lines += ['', '**올바른 결과/접근방법 (관리자 작성)**', '', e['approach'] or '(없음)', '']
        if e.get('sys_sql'):
            lines += ['**시스템이 만든 SQL (잘못된 결과)**', '', '```sql', e['sys_sql'], '```', '']
        if e.get('sql'):
            lines += ['**관리자가 제시한 올바른 SQL**', '', '```sql', e['sql'], '```', '']
        if e.get('expected_ids'):
            lines += [f'**기대 사번 ({len(e["expected_ids"])}명)**: ' + ', '.join(e['expected_ids'][:50]), '']
    return '\n'.join(lines)


# ── 관리(끄기/삭제) ──────────────────────────────────────────────────────────

def set_active(kind: str, ids: list[str], active: bool, user_id: str = '') -> int:
    name = 'nl_query_curated_rules.json' if kind == 'rule' else 'nl_query_verified_examples.json'
    with _lock:
        items = _read(name)
        n = 0
        for it in items:
            if it['id'] in ids and bool(it.get('active', True)) != active:
                it['active'] = active
                n += 1
        if kind == 'rule':
            _sync_rules(items)
        _write(name, items)
    for i in ids:
        _history('활성화' if active else '비활성화', 종류=kind, id=i, 반영자=user_id)
    return n


def delete(kind: str, ids: list[str], user_id: str = '') -> int:
    name = 'nl_query_curated_rules.json' if kind == 'rule' else 'nl_query_verified_examples.json'
    with _lock:
        items = _read(name)
        kept = [it for it in items if it['id'] not in ids]
        if kind == 'rule':
            _sync_rules(kept)
        _write(name, kept)
    for i in ids:
        _history('삭제', 종류=kind, id=i, 반영자=user_id)
    return len(items) - len(kept)


def disable_all_once(user_id: str = 'system') -> int:
    """2026-10-09 사용자 확정: 관리자 화면의 "개선 반영/반영된 규칙·예시 관리"를 없애면서, 이미 반영돼
    있던 규칙·검증된 예시를 전부 끈다(삭제하지 않고 기록은 보존). 표식 파일이 있으면 다시 하지 않는다
    (이후 코드에서 직접 켠 항목은 건드리지 않기 위해). 반환: 이번에 끈 항목 수."""
    marker = _path('nl_query_curation_disabled.flag')
    if os.path.exists(marker):
        return 0
    n = 0
    with _lock:
        for kind, name in (('rule', 'nl_query_curated_rules.json'), ('example', 'nl_query_verified_examples.json')):
            items = _read(name)
            changed = False
            for it in items:
                if it.get('active', True):
                    it['active'] = False
                    changed = True
                    n += 1
                    _history('비활성화', 종류=kind, id=it.get('id', ''), 반영자=user_id)
            if changed:
                if kind == 'rule':
                    _sync_rules(items)
                _write(name, items)
        with open(marker, 'w', encoding='utf-8') as f:
            f.write('disabled 2026-10-09\n')
    return n
