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

## 진행 중인 논의 (아직 결론 안 남 — 다음 세션에서 이어갈 것)

**"보유 전문성" 탭 자연어 질문 기능의 범위를 확장하는 논의 시작됨**:
- 기존(8번 항목): 이미 계산된 전문성 분석 결과 안에서만 답하는 **폐쇄형 3-intent 라우터**.
- 요청받은 변경 방향: "물리학 전공한 사람", "양자컴 과제 수행 중인 연구원"처럼
  `data/raw`(→`data/processed`) 전체를 대상으로 사내 LLM이 즉석에서 원하는 데이터를
  뽑아내는 **개방형 질의**로 확장.
- **중요 발견**: 이 저장소에는 이미 정확히 이런 기능(`services/text2sql.py`)이
  존재함 — "연구원 목록" 탭의 "AI 검색"이 자연어 → PostgreSQL SELECT 생성 →
  `sanitize_sql()` 안전 검증(쓰기/DDL 차단, LIMIT 자동 부착, read-only 트랜잭션,
  10초 timeout) → 실행까지 이미 구현/문서화(`docs/text2sql.md`)돼 있음. 단,
  **PostgreSQL(`DATABASE_URL`) 필수 — CSV 모드 폴백 없음**, 스키마 전체(민감한
  인사 테이블 `evaluations`/`leadership`/`succession`/`incentive_selection`/
  `awards`/`hr_orders` 포함)를 LLM에 노출, 동시성 제한 없음(위 참고).
- **아직 결정 안 된 핵심 질문들**(다음 세션에서 사용자와 인터뷰 예정):
  1. `text2sql.py`를 재사용/확장할지, `nl_query.py`의 구조화 우선 방식을 유지한
     채 "3개 intent 밖" 질문에 한해서만 개방형 폴백을 추가할지, 완전 재설계할지.
  2. 개방형 질의가 인사 민감 테이블(평가등급/리더십진단/승계후보/인센티브/포상/
     인사발령)까지 접근 가능해야 하는지, 전문성 관련 테이블로 제한해야 하는지.
  3. 실제 운영 환경에 PostgreSQL이 있는지(`text2sql.py` 그대로 재사용 가능) 아니면
     CSV만 쓰는지(새로 CSV/pandas 기반 질의 엔진이 필요).
  4. "양자컴 과제 수행 중"처럼 명시적 컬럼/키워드가 없는 질문까지 지원할지
     (의미 기반 매칭 필요) 아니면 1차로는 키워드/컬럼 매칭 범위로 한정할지.
