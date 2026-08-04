# data/processed — 작업 히스토리 & 컨텍스트

이 디렉터리에서 작업할 때 먼저 읽을 문서. `Researcher-board`는 연구원 인사/성과
데이터를 다루는 Dash 대시보드로, `data/raw/`의 원천 엑셀/csv를 `pipeline/process_*.py`
스크립트가 정제해 이 디렉터리(`data/processed/`)에 CSV/JSON으로 쌓고,
`services/data_store.py`를 통해 Dash 화면이 읽는다.

## 이 디렉터리의 두 종류 파일

1. **원천 1:1 정제 테이블** (CSV, `pipeline/process_*.py`가 원천 엑셀을 그대로
   컬럼 정리만 해서 생성 — LLM 미사용): `researchers.csv`, `education.csv`,
   `tasks.csv`/`tasks_information.csv`, `publications.csv`, `patents.csv`,
   `evaluations.csv`, `leadership.csv`, `succession.csv`, `incentive_selection.csv`,
   `awards.csv`, `certifications.csv`, `nurturing.csv`, `comments.csv`,
   `technology_transfer.csv`, `transfers.csv`, `hr_orders.csv`, `core_technology.csv`,
   `tech_ownership.csv`, `job_profile.csv`, `work_objective.csv`,
   `project_confl_address.csv`, `analysis_dep.csv`, `team_refer.csv` 등.
   `DATABASE_URL`이 설정돼 있으면 `pipeline/load_to_db.py`가 이 CSV들을 PostgreSQL로
   그대로 적재하고(테이블명 = 파일명), `services/data_store.read_processed()`가
   DB 유무에 따라 자동으로 CSV/DB를 오간다(`docs/database.md` 참고). **`DATABASE_URL`
   미설정이 기본값**이며, 이 저장소(개발 환경)에는 `.env`가 없다 — 실제 운영 환경에
   DB가 붙어 있는지는 세션마다 확인 필요.

2. **LLM 파생 분석 산출물** (JSON/HTML, `pipeline/process_*.py`가 사내 LLM 프롬프트로
   생성 — 원본 데이터를 요약/판단/구조화한 결과): `연구원 보유 전문성 분석.json/.html`,
   `project_expertise_analysis.json/.html`, `project_fit_by_project.json`,
   `project_fit_by_researcher.json`, `project_researcher_fit.html`,
   `researcher_similarity.json/.html`, `researcher_pair_judgment.json`(쌍 판정 캐시),
   `journal_authority.json`(캐시), `strength_taxonomy*.json`(표준화 작업, 아래 참고),
   `embedding_cache.json`(BGE-M3 벡터 캐시, 텍스트 해시 키). 전체 LLM 프롬프트
   목록·원문은 세션 산출물로 사용자에게 전달된 `LLM_프롬프트_전체_목록.md` 참고
   (이 파일 자체는 저장소에 커밋돼 있지 않음 — 필요하면 재생성 가능).

## 핵심 설계 원칙 (지금까지 지켜온 것)

- **PII를 LLM 프롬프트에 절대 포함하지 않음**: `researcher_id`/이름은 프롬프트 밖에서
  결과에 매핑. 모든 `pipeline/process_*.py`의 LLM 호출이 이 원칙을 지킴.
- **구조화 출력 강제, 자유 생성 최소화**: 대부분 "① 임베딩/규칙으로 후보를 싸게
  추린 뒤 ② LLM에는 JSON만 강제 출력"하는 패턴(`researcher_fit.py`,
  `process_researcher_similarity.py`). 환각 방지를 위해 랭킹/판정 자체를 LLM 자유
  생성에 맡기지 않음.
- **캐시 우선**: 저널 권위도/과제 요약/쌍 판정/임베딩은 전부 텍스트 해시 또는 키
  기준으로 캐시해 재호출 비용을 줄임.
- **동시성 제어**: `pipeline/llm_client.call_llm()`이 모듈 전역 세마포어
  (`llm_config.LLM2_MAX_CONCURRENT`, 기본 8)로 배치 스크립트 전체의 동시 LLM 호출을
  제한. 화면에서 실시간으로 응답을 기다리는 호출(`services/nl_query.py`)은
  `max_wait`(기본 15초, `LLM2_QUERY_MAX_WAIT_SECONDS`)로 슬롯을 못 얻으면 무한
  대기 대신 빠르게 실패 처리.
  ⚠️ **`services/text2sql.py`는 이 세마포어를 안 씀** — `pipeline/llm_client.py`가
  아니라 `services/llm.py`의 `chat()`을 직접 호출해 동시성 제한이 없는 별도 경로임
  (아래 "진행 중인 논의" 참고).

## 지금까지의 진행 히스토리 (요약)

같은 세션에서 이어져 온 작업 순서(오래된 것 → 최근):

1. **기반 대시보드**: 조직별 비교/연구원 목록/연구원 프로필 3개 탭 + 밀도 적응형
   타임라인 컴포넌트 구축.
2. **보유 전문성 파이프라인 신설**: `process_project_expertise.py`(과제 직무
   딥다이브), `process_researcher_expertise.py`(연구원 전문성 분석),
   `process_project_researcher_fit.py`(과제↔연구원 매칭), `process_researcher_similarity.py`
   (연구원↔연구원 유사도) 4개 스크립트를 사내 LLM + BGE-M3 임베딩으로 구축.
   모두 콘솔형 정적 HTML 리포트(`rd_specialist_markdown.py` 공용 셸) + JSON으로 저장.
3. **"보유 전문성" Dash 탭 통합**: 연구원/연구원↔연구원/연구원↔과제/전문성 MAP
   4개 서브탭(`pages/researcher_similarity_map.py`)으로 묶고, UMAP 산점도 +
   HDBSCAN 2단계 클러스터링, 조직도 트리 사이드바(`team_refer.csv` 기반), 이름/사번
   검색, 지도↔카드 상호 이동(하이라이트) 등을 반복 개선.
4. **신뢰도 보강**: 근거 없는 유사도 후보 필터링, LLM 프롬프트에 "근거 필수" 명시,
   커버리지 스탯 카드("분석 완료/분석 대상", "마지막 갱신") 4개 리포트에 추가,
   소규모 파일럿 검증 가이드 문서 작성.
5. **UI 미세 조정**: 연구원↔연구원 표시 개수(3/5/10)를 "시니어 N + 주니어 N"(그룹당)
   의미로 재정의 — `<tbody>`를 그룹별로 분리해 기존 CSS `:nth-child` 토글이 그룹별로
   독립 적용되게 함. 전문성 MAP 호버 라벨을 `researcher_id name` → `name(id)(E직군/R직군)`
   로 변경(`tech_ownership.csv`의 `E_support` 조인). 대시보드 상단 탭 순서 변경,
   조직도 사이드바 기본폭 400→500px/최대 500→600px.
6. **`strength_fields`/`strength_keywords` 표준화 착수**: 자유 생성이라 표기가
   제각각인 문제(예: "로봇 제어"/"로봇제어") 해결 위해 3단계 계획(①현황 집계+
   클러스터링 → ②표준 목록 정의 → ③재할당) 수립. `pipeline/build_strength_taxonomy.py`
   신설 — BGE-M3 임베딩 코사인 유사도로 유사 표기를 묶어 `strength_taxonomy_review.json/html`
   (사람이 보는 현황), `strength_taxonomy_draft.json`(초안, 매번 재생성),
   `strength_taxonomy.json`(확정본, **최초 1회만 자동 생성 — 이미 있으면 절대 덮어쓰지
   않음**, 사람이 직접 수정하는 파일)을 생성. **③ 재할당(연구원별 실제 태그를 표준
   목록으로 다시 매핑) 단계는 아직 미착수.**
7. **카드 라벨 명확화**: `strength_fields`/`strength_keywords` 칩이 라벨 없이
   붙어 있던 것을 "Strength Field"/"Strength Keywords" 라벨로 분리(`rd_specialist_markdown.py`
   의 `strength_section_html()` 공용 헬퍼로 통합 — 정적 리포트 2곳 + Dash
   `components/detail_tabs.py`가 공유).
8. **자연어 질문 기능 1차 버전** (`services/nl_query.py`, "보유 전문성" 탭 상단):
   질문 → 사내 LLM이 **3개 intent(find_researchers_by_expertise/
   find_researchers_for_project/find_projects_for_researcher) + unsupported**로
   구조화 분류만 하고, 실제 조회는 이미 계산된 배치 산출물(연구원 보유 전문성
   분석.json, project_fit_by_project/by_researcher.json, tasks.csv)을 파이썬
   코드가 결정적으로 필터링. LLM은 "질문 이해"만, "답"은 항상 기존 데이터 조회
   결과 — 환각 방지. 전문성 검색은 `strength_taxonomy.json` 동의어 확장 →
   원문 substring → BGE-M3 임베딩 유사도 순으로 폴백.
9. **연구원 보유 전문성 분석 프롬프트 스키마 변경**: 출력 필드를
   `hard_skills`(하위 3항목)/`domain_knowledge`(하위 3항목) 고정 dict →
   `key_responsibilities`(주요 역할·책임, 과제 수행이력/직무 이력/업무목표 근거)/
   `domain_knowledge_skill`(전문지식 및 역량, 학력/핵심기술/보유기술/논문/특허 근거)
   두 개의 자유 리스트로 교체. `strength_fields`/`strength_keywords`는 유지.
   `researcher_fit.researcher_profile_text()`(임베딩 입력 텍스트 생성 — 유사도/
   매칭/자연어질문이 전부 공유)도 함께 갱신.
10. **자연어 질문 기능에 개방형 질의(`open_data_query`) 폴백 추가**: 아래
    "완료: 개방형 질의(open_data_query) 확장" 섹션 참고.
11. **자연어 질문 결과 → 연구원 프로필 엑셀 다운로드**: 아래 "완료: 연구원
    프로필 엑셀 다운로드" 섹션 참고.

## 완료: 연구원 프로필 엑셀 다운로드

"보유 전문성" 탭 자연어 질문 결과(구조화 3-intent든 open_data_query든)에서
찾은 연구원 중 원하는 대상을 선택해 인사 프로필을 엑셀로 내보내는 기능.
컬럼 구성과 각 필드 표기 규칙(날짜 축약, 다중 이력 줄바꿈 표기 등)은 전부
사용자 인터뷰로 확정한 것을 그대로 코드화했다 — 규칙을 바꾸려면
`services/researcher_profile_export.py`의 `_COLUMNS`와 `_col_*` 함수만
고치면 된다.

- **`services/researcher_profile_export.py`** (신규): `build_profile_workbook
  (researcher_ids)`가 openpyxl로 xlsx 바이트를 만든다. 양식은 바탕체 11pt,
  전체 셀 검정 테두리, 헤더 행만 볼드, 여러 줄 값은 자동 줄바꿈. 컬럼은 사번/
  Knox ID/성명(성별·나이)/부서(비공식소속명)/입사일(근속연수)/학력(박→석→학
  순, "코드)학교 전공" 줄바꿈 나열)/평가('24~'26 등급 슬래시)/직급·연차
  (승격기준일로부터 다음 3/1까지 연차, 소수 첫째자리 버림)/과제수행이력·
  양성이력·핵심이력(전부 다중 이력을 줄바꿈으로 나열, 값 없으면 "-"). 값이
  없는 원천 컬럼(예: 이 저장소 개발 샘플 데이터엔 없는 `knox_id`/`hire_date`/
  `promotion_date` — 운영 환경에선 `pipeline/process_researchers.py`가
  채운다)은 전부 "-"로 안전하게 처리.
- **`pages/researcher_similarity_map.py`**: `_nl_query_bar()`에 "엑셀
  다운로드" 버튼(`nl-query-excel-btn`, 결과에 researcher_id 후보가 있을
  때만 표시 — open_data_query 결과 로직에 이미 있던 "컴포넌트는 고정, 속성만
  콜백 갱신" 패턴 재사용) + 대상 선택 모달(`nl-query-excel-modal`, 체크리스트
  + 전체선택/해제 토글) + `dcc.Download`. `_extract_candidates(result)`가
  intent별로(구조화 intent는 `items[].researcher_id`, open_data_query는
  결과 컬럼에 `researcher_id`가 있을 때만) 후보 목록을 뽑는다. 다운로드
  파일명은 `연구원_프로필_YYYYMMDDHHMM.xlsx`(분 단위까지).

## 완료: 개방형 질의(open_data_query) 확장

8번 항목(폐쇄형 3-intent 라우터)을 유지한 채, 그 밖의 질문("물리학 전공한 사람
찾아줘", "양자컴 과제 수행 중인 연구원 보여줘")을 `data/processed`의 원천 CSV +
LLM 파생 JSON 전체를 대상으로 사내 LLM이 즉석 SQL을 생성해 답하는 4번째 intent로
구현 완료. 설계 확정 과정(사용자 인터뷰, `text2sql.py` 선행 조사, 대안 검토)은
아래 "설계 결정 기록"에 남겨둠 — 실제 구현은 다음 파일:

- **`services/open_data_query.py`** (신규): `answer(question)` 진입점.
  `data/processed/*.csv`를 매 질의 시점에 동적 스캔(`_discover_csv_tables()`,
  `services.data_store.read_processed()` 재사용 — DB 생기면 자동으로 DB로 전환)
  + LLM 파생 JSON 3종(`expertise_profiles`/`project_fit_by_project`/
  `project_fit_by_researcher`, `_discover_json_tables()`)을 flat DataFrame으로
  등록. DuckDB(`:memory:`, `requirements.txt`에 `duckdb>=0.10.0` 추가)에
  `con.register()`로 붙여 SQL 실행. SQL 생성은 `pipeline/llm_client.call_llm(
  ..., max_wait=...)` 경유(동시성 보호 적용 — `text2sql.py`엔 없던 보호를
  여기선 적용). `services/text2sql.py`의 `sanitize_sql()`을 그대로 재사용해
  쓰기/DDL 차단 + LIMIT 자동 부착. 결과는 Python 레이어에서 항상 상위 50건
  (`DISPLAY_LIMIT`)으로 자름. SQL 1차 실행이 0건이면 LLM이 함께 준
  `fallback_table`/`fallback_column`/`fallback_term`으로 BGE-M3 코사인 유사도
  폴백(`_semantic_fallback()`, threshold 0.75, `nl_query.expand_term()`과 동일
  철학).
- **`services/nl_query.py`**: `_KNOWN_INTENTS`/`QUERY_SYSTEM_PROMPT`에
  `open_data_query` 5번째(unsupported 포함) 추가, `execute_query()`가
  `open_data_query.answer(parsed['question'])`로 위임.
- **`pages/researcher_similarity_map.py`**: 결과 저장용 `dcc.Store`
  (`nl-query-full-result`) + 펼침 상태 `dcc.Store`(`nl-query-expanded`) 2개와
  콜백 3개(`_run_nl_query`/`_render_nl_query_store`/`_toggle_nl_query_expand`)로
  "기본 10건 표시 + 전체 N건 보기(최대 50)" UI 구현. LLM 재호출 없이 이미 받아온
  최대 50건 중 몇 건을 보여줄지만 토글.

**⚠️ 구현 중 발견한 Dash 함정 (재발 방지용 기록)**: "전체 보기" 버튼을
`_render_open_data_query_result()` 안에서 매번 새로 `dbc.Button(id='nl-query-toggle-btn', ...)`
으로 만들어 반환했더니, 클릭이 서버 로그상 200으로 정상 처리되는데도 화면이
안 바뀌는 버그가 있었다. 원인: Dash는 `prevent_initial_call=True`여도, 콜백의
Input으로 걸린 컴포넌트가 **레이아웃에 처음 나타나는 시점**(동적으로 삽입될 때
포함)에 한 번 "유령 실행"을 시킨다 — 즉 버튼이 렌더링되자마자 클릭 없이
`_toggle_nl_query_expand`가 한 번 실행돼 상태를 뒤집어 버리고, 그 직후 실제
클릭이 다시 뒤집어서 순 효과가 0이 되어 "아무 반응 없음"처럼 보였다(Playwright로
네트워크 요청/응답 바디를 직접 캡처해 `nl-query-expanded.data`가 클릭 전에
이미 한 번 바뀌어 있는 것을 확인해 특정). **해결**: 버튼을 매 렌더링마다
새로 만들지 않고 레이아웃에 상시 존재하는 고정 컴포넌트로 두고(`_nl_query_bar()`
에서 `style={'display': 'none'}`로 최초 삽입), 렌더 콜백이 버튼의 `children`
(라벨)/`style`(표시 여부)만 별도 Output으로 갱신하도록 변경(`_toggle_button_props()`).
→ **다음에 "결과에 따라 동적으로 나타나는 버튼/인풋에 콜백을 건다"류 UI를
추가할 때는 이 패턴(컴포넌트는 고정, 속성만 콜백으로 갱신)을 기본으로 쓸 것.**

### 설계 결정 기록 (구현 전 인터뷰 내용)

**배경**: 기존(8번 항목)은 이미 계산된 전문성 분석 결과 안에서만 답하는 **폐쇄형
3-intent 라우터**. "물리학 전공한 사람", "양자컴 과제 수행 중인 연구원"처럼
`data/processed`의 원천 정제 테이블 전체를 대상으로 사내 LLM이 즉석에서 원하는
데이터를 뽑아내는 **개방형 질의**로 확장하기로 함.

**중요 사전 조사**: 이 저장소에는 이미 유사 기능(`services/text2sql.py`)이 있음 —
"연구원 목록" 탭 "AI 검색"이 자연어 → PostgreSQL SELECT 생성 → `sanitize_sql()`
안전 검증(쓰기/DDL 차단, LIMIT 자동 부착, read-only 트랜잭션, 10초 timeout) →
실행까지 구현/문서화(`docs/text2sql.md`)돼 있음. 단 PostgreSQL 필수(CSV 폴백 없음)
이고 동시성 제한이 없어(아래 결정에 따라) 그대로 재사용은 어려움 — `sanitize_sql`
등 안전 검증 로직 자체는 DB 비의존적이라 재사용 가능.

**사용자 인터뷰 결과 (확정)**:
1. **재사용 방향** → `nl_query.py`의 구조화 우선 라우터는 유지하고, 기존 3개
   intent 밖 질문에 대해서만 새 개방형 폴백 경로를 추가(완전 재설계 아님).
2. **민감정보 범위** → 전체 테이블 허용(전문성 테이블로 제한하지 않음). ⚠️ 이
   앱에는 로그인/역할 기반 접근 제어가 없으므로, 이 결정은 "보유 전문성" 탭에
   접근 가능한 사람이면 누구나 평가등급/리더십진단/승계후보 등 인사 민감정보도
   조회 가능해짐을 의미 — 실제 배포 전 접근 제어 도입 여부를 별도로 재확인할 것.
3. **DB vs CSV** → 운영 환경에 PostgreSQL 없음, CSV만 사용. 즉 `text2sql.py`를
   그대로 못 쓰고, `data/processed/*.csv`(pandas DataFrame)를 대상으로 하는
   새 질의 엔진이 필요 — DuckDB(SQL-over-DataFrame, 서버 불필요, `requirements.txt`
   에 아직 없음)를 실행 계층 후보로 검토 중.
4. **매칭 방식** → 키워드/컬럼 매칭에서 끝나지 않고 의미 기반(임베딩) 매칭까지
   지원. 1차 SQL/키워드 매칭이 0건이거나 애매하면 BGE-M3 임베딩 유사도로 2차
   매칭(`nl_query.py`의 `expand_term()`이 이미 쓰는 패턴과 동일한 폴백 철학).

**구체 설계안 확정** (구현 직전 단계):

- **아키텍처**: `nl_query.py`에 4번째 intent `open_data_query` 추가. 라우팅
  프롬프트(1단계, 가벼움)는 그대로 두고, `open_data_query`로 분류된 질문만
  스키마 전체를 실은 2단계 프롬프트로 SQL 생성(`text2sql.py`의 `generate_sql()`
  패턴 재사용, DuckDB 방언).
- **스키마 소스**: 수동 테이블 목록 대신 `data/processed/*.csv`를 매 질의 시점에
  동적 스캔(`services.data_store.read_processed()`로 로드 — DB 생기면 자동으로
  DB를 씀) + LLM 파생 JSON(연구원 보유 전문성 분석/project_fit_by_*)도 flat
  DataFrame으로 변환해 함께 등록. 한글 파일명은 영문 별칭으로 등록(예:
  `연구원 보유 전문성 분석.json` → `expertise_profiles`) — 별칭 네이밍은 구현
  시 자유롭게 정하기로 함.
- **실행 계층**: DuckDB(신규 의존성, `requirements.txt`에 추가 예정) — pandas
  DataFrame을 그대로 SQL로 조회, 별도 서버 불필요.
- **안전장치**: `text2sql.sanitize_sql()` 그대로 재사용(DB 비의존적 순수 문자열
  검증). SQL 생성 호출은 `services.llm.chat()`이 아니라 `pipeline/llm_client.call_llm(
  ..., max_wait=...)`로 라우팅해 기존 동시성 보호(세마포어 공유 + 타임아웃)를
  적용(`text2sql.py`엔 없던 보호를 여기선 적용).
- **의미 기반 폴백**: SQL 1차 실행이 0건이면, LLM이 SQL과 함께 준
  `fallback_table`/`fallback_column`/`fallback_term`을 `nl_query.expand_term()`과
  동일한 패턴(BGE-M3 코사인 유사도, threshold 0.75)으로 재매칭 — 재-SQL 생성
  없이 끝남.
- **결과 개수/정렬** (사용자 확정):
  - SQL 자체 실행 결과는 Python 레이어에서 **항상 상위 50건으로 자름**(SQL의
    LIMIT 절과 무관하게 사후 slice — `sanitize_sql`이 붙이는 LIMIT은 쿼리
    자체의 안전장치일 뿐, 응답에 실제로 담기는 건 최대 50건).
  - **정렬**: 의미 기반 폴백 결과는 코사인 유사도 내림차순(자연스러운 "유사도
    순"). 일반 SQL 조회 결과는 "유사도"라는 개념이 없으므로, 질문이 순위를
    암시하면(예: "논문이 가장 많은") LLM이 SQL에 `ORDER BY`를 포함하도록
    프롬프트에 지시하고, 그 외에는 SQL이 반환한 순서 그대로 — 이 한계를
    화면에 별도 경고하진 않지만 알아둘 것.
  - **표시**: 기본 10건만 렌더링하고, 50건까지 받아온 전체 결과는
    `dcc.Store`에 담아 둔 채 "전체 N건 보기" 버튼으로 펼치는 방식(Dash
    callback으로 구현 가능, 재질의/재호출 없음 — 이미 받아온 데이터를
    보여주기만 전환).
  - **SQL 노출**: "연구원 목록" 탭의 기존 AI 검색과 동일하게, 실행된 SQL을
    접이식으로 화면에 표시(기존 기능과 UX 통일).

위 설계대로 구현 완료 — 실제 파일 경로/함수명 및 구현 중 발견한 이슈는 위
"완료: 개방형 질의(open_data_query) 확장" 섹션 참고.
