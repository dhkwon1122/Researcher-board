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
12. **자연어 질문 결과 화면 전면 개편(4개 intent 통합 표, 정렬/필터, 인라인
    선택)**: 아래 "완료: 자연어 질문 결과 표 통합 개편" 섹션 참고.

## 완료: 자연어 질문 결과 표 통합 개편

"보유 전문성" 자연어 질문 결과 화면을 사용자 피드백 6건 반영해 다시 짰다.
핵심은 **4개 intent(정형 3개 + open_data_query)가 전부 같은
{columns, labels, rows} 표 형태로 결과를 내도록 통일**한 것 — 그 덕에
정렬/필터/체크박스 선택/엑셀 다운로드를 렌더러 하나로 4개 intent 모두에
동시에 적용할 수 있었다(사용자가 "구조 자체를 바꿔도 된다"고 허용한 부분).
단, 정형 3-intent의 실제 조회/판단 로직(임베딩 매칭, 배치 매칭 결과 필터링
등)은 그대로 유지 — LLM SQL 생성으로 바꾸진 않았다(이 프로젝트가 계속
지켜온 "구조화 출력 강제, 자유 생성 최소화" 원칙을 깨지 않기 위해). 바뀐
건 **최종 결과를 포장하는 방식**뿐이다.

- **`services/data_labels.py`**(신규): `data/processed/*.csv` + LLM 파생
  JSON 전체 컬럼 → 한글 라벨 사전(`label_for()`/`label_columns()`, 매핑에
  없으면 원래 이름 그대로 폴백). 소스 파일마다 원본 헤더 표현이 달라도
  (사원번호/KNOXID 등) 같은 개념은 항상 같은 한글 라벨로 통일(사용자
  선택: 원본 헤더 재사용이 아니라 통일된 라벨).
- **`services/researcher_profile_export.py`**: `PERSON_BASE_COLUMNS`
  (`researcher_id/name/department/org_code/position/degree_major/age`)와
  `person_base_table(researcher_ids)` 추가 — 엑셀 다운로드와 자연어 질문
  결과 표가 "같은 사람은 어디서 봐도 같은 학력·나이 표기"를 공유하도록
  로직을 여기 한 곳에 모았다(학력은 엑셀처럼 전체 이력이 아니라
  `_highest_degree_str()`로 최종 학력 1건만).
- **`services/open_data_query.py`**: `DISPLAY_LIMIT`/`_cap_limit` 50→1000건
  (상한만 올리고 화면 기본 표시는 30건 — 아래 UI). `inject_person_columns()`
  신규 — 결과에 `researcher_id`가 있으면(=사람 데이터로 판단) 사번/성명/
  부서/과제/CL/학력·전공/나이 7개를 항상 앞에 붙이고, 겹치는 원본 컬럼
  (department/org_code/position/degree/major/birth_year 등)은 제거해
  중복 표시하지 않는다. SQL 생성 프롬프트에 "사람에 대한 질문이면
  researcher_id를 SELECT에 반드시 포함하라" 규칙 추가(이 판단 로직이
  기댈 신호를 LLM이 빠뜨리지 않도록). 응답에 `labels`(표시용 한글) 필드
  추가(`columns`는 정렬/필터가 참조할 원본명 그대로 유지).
- **`services/nl_query.py`**: 정형 3-intent
  (`find_researchers_by_expertise`/`find_researchers_for_project`/
  `find_projects_for_researcher`)의 반환값을 기존 `items: [...]`(카드/표
  각각 다른 모양)에서 `open_data_query`와 동일한 `columns/labels/rows`
  구조로 변경(`_build_table_result()` 공용 헬퍼, 내부적으로
  `open_data_query.inject_person_columns()` 재사용) — 조회/판단 로직
  자체는 한 줄도 안 바꾸고 마지막 포장만 바꿨다.
- **`pages/researcher_similarity_map.py`**: 결과 표 렌더링을 전면 재작성.
  - **표시 개수**: 기본 30건, 상한 1000건까지 "전체 N건 보기"로 펼침
    (건수는 필터 적용 여부와 무관하게 항상 헤더 위에 "총 N건" 상시 표시).
  - **정렬**: 컬럼 헤더 옆 드롭다운(오름차순/내림차순), `department`
    컬럼만 추가로 "건재순"(advanced device platform(sait) 등 사용자 지정
    7개 우선순위 + 나머지는 이름순, `_DEPT_ORDER`/`_dept_sort_key()`).
    "정렬 해제" 링크로 초기화.
  - **필터**: 모든 컬럼에 값 다중선택 드롭다운(현재 받아온 전체 데이터
    기준 고유값 목록) — 재질의 없이 브라우저에서만 걸러낸다
    (`_passes_filters()`). "필터 초기화" 링크로 초기화.
  - **엑셀 다운로드**: 별도 모달을 없애고, 결과 표 각 행에 체크박스를
    바로 두는 방식으로 변경(헤더 체크박스로 전체선택/해제). 선택된 행
    수가 버튼 라벨에 실시간 반영되고, researcher_id가 있는 결과에서만
    버튼이 나타난다.
  - **Dash 팬텀 트리거 대응**: 정렬/필터/체크박스는 모두 매 렌더링마다
    새로 그려지는 동적 컴포넌트라(컬럼 수 자체가 질문마다 달라 고정
    컴포넌트로 둘 수 없음), 이전 엑셀 모달 버그 때처럼 컴포넌트를 고정하는
    대신 **콜백을 전부 "현재 상태로부터 다음 상태를 그대로 계산"하는 순수
    함수**로 짜서(토글/증가 없음) 팬텀 트리거가 와도 상태가 그대로
    유지되게 했다. n_clicks 기반 콜백(정렬/필터 초기화, 엑셀 다운로드)은
    추가로 `if not n_clicks: return dash.no_update`로 방어.
  - **알려진 제약**: 부서 "건재순" 우선순위 목록은 이 저장소의 개발
    샘플 데이터(`AI융합연구팀` 등 한글 팀명)엔 매칭되는 값이 없어 전부
    "나머지" 취급(이름순)으로 보임 — 운영 데이터의 `department` 값이
    실제로 `advanced device platform(sait)` 형태인지 확인 필요(사용자
    확인 완료, 운영 데이터 기준으로는 정상 동작 예상).

**후속 개선 (같은 세션, 사용자 피드백 반영)**:
- **근거 컬럼 노출**: `open_data_query.py`의 SQL 생성 프롬프트에 "질문의
  판단 근거로 쓰는 컬럼(WHERE/LIKE/JOIN 조건에 쓴 컬럼)은 SELECT에도 반드시
  포함하라, 최대 3개"는 규칙 추가 — 예를 들어 "미생물 관련 연구이력이 있는
  사람 찾아줘"처럼 물으면 `task_name`(또는 판단에 쓰인 컬럼)이 기본 7컬럼
  뒤에 추가로 붙어 "왜 이 사람이 뽑혔는지"가 보인다. 프롬프트 지시일 뿐이라
  100% 보장은 아님(사용자도 인지, 우선 이 정도로 진행하기로 확정) — 자주
  빠지면 추후 강화 검토.
- **CL → CL/년차**: `PERSON_BASE_COLUMNS`의 `position` 슬롯을
  `position_year`로 교체, 값은 엑셀 다운로드의 `_col_position_year()`를
  그대로 재사용(`services/researcher_profile_export.py`) — 브라우저 결과
  표와 엑셀이 "CL4-17"/"CL4"(승격기준일 없으면 CL만) 표기를 공유한다.
  엑셀 헤더도 "직급/년차" → "CL/년차"로 통일.
- **필터 정리**: 사번/성명/나이 컬럼은 정렬만 남기고 값 필터를 제거(식별자
  성격이라 필터가 의미 없다는 사용자 판단, `_NO_FILTER_COLUMNS`). 학력/전공
  컬럼은 "박)학교 전공" 원문 그대로 필터 목록을 만들면 사실상 다 다른 값이
  되어 필터가 무의미해지므로, 전공만 필터에서 빼고 학위 구분(박/석/학/전문대/
  고교)은 전부 필터 대상에 남긴다(`_degree_prefix()`, `_DEGREE_FILTER_OPTIONS`
  5개 옵션). ⚠️ 처음엔 박/석/학 3개만 필터로 남기고 전문대/고교를 실수로
  빼버렸었다 — "전공만 빼고 학력은 다 남겨달라"는 재확인을 받아 5개로
  수정. 이에 맞춰 `_highest_degree_str()`(자연어 질문 화면 전용, 엑셀의
  `_col_education()`과는 별개)도 박/석/학 3개 제한을 풀고
  `_DEGREE_ORDER_FULL`(박사>석사>학사>전문대>고교, `pipeline/
  process_education.py`의 `DEG_ORDER`와 동일한 5단계 우선순위)로 확장 —
  education.csv 자체가 이미 "학사 이상이 있으면 전문대/고교는 제외"하고
  저장하므로, 여기 남아 있는 전문대/고교 레코드는 그게 그 사람의 진짜 최종
  학력이라는 뜻이라 그대로 인정한다. 엑셀 다운로드의 `_col_education()`
  (박/석/학 3개만, 나머지 제외)은 훨씬 이전에 사용자가 명시적으로 확정한
  별개의 규칙이라 이번 변경 대상이 아니다 — 그대로 유지.

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
  다운로드" 버튼(`nl-query-excel-btn`) + `dcc.Download`. 다운로드 파일명은
  `연구원_프로필_YYYYMMDDHHMM.xlsx`(분 단위까지).
  ⚠️ **UI는 이후 "자연어 질문 결과 표 통합 개편"(위 12번 항목)에서 다시
  바뀌었다** — 처음엔 대상 선택 모달(`nl-query-excel-modal`) 방식이었지만,
  지금은 모달 없이 결과 표에 체크박스를 바로 두는 방식으로 교체됐다.
  아래 두 문단은 그 이전 버전(모달) 설명이니 최신 구현은 위 12번 섹션을
  참고할 것 — 남겨두는 이유는 "컴포넌트 고정 + 속성만 갱신"이라는 팬텀
  트리거 대응 패턴이 처음 등장한 사례라 히스토리로서 가치가 있어서다.

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

## 완료: AI 검색 전역화 + 조직별 비교 표시 안 되던 문제 수정

사용자 요청 3건: (1) "연구원 목록" 탭 전용 AI 검색(text2sql 기반, DB
전용) 삭제, (2) "보유 전문성" 탭에 있던 자연어 질문 바를 전 탭 공용으로
이동, (3) "조직별 비교" 탭 내용이 안 보이는 원인 확인.

- **`components/nl_query_bar.py`**(신규): `pages/researcher_similarity_map.py`
  안에 있던 자연어 질문 바 UI+콜백 11개를 그대로 옮겨 온 모듈. 페이지가
  아니라 `app.py`가 `Dash()` 인스턴스 생성 직후 한 번 import해서
  module-level `@callback`을 등록하고, `render()`를 `app.layout`에서
  `dash.page_container` 위(네비게이션 바로 아래)에 직접 삽입 — 탭을
  이동해도 다시 생성되지 않고 항상 같은 자리에 유지된다. 기존 "연구원
  목록"의 페이지 전용 AI 검색(`services/text2sql.py`, PostgreSQL 전용,
  DB 없으면 동작 안 함)은 완전히 삭제하고 이 전역 바 하나로 통합.
- **`pages/researcher_list.py`** / **`pages/researcher_similarity_map.py`**:
  각각 구 AI 검색 카드/콜백, 이동된 nl-query 바 블록 제거. 남은 미사용
  import(`db_enabled`, `text2sql`, `json`, `ALL`, `nl_query`,
  `researcher_profile_export`) 정리.
- **조직별 비교 표시 안 되던 원인**: `_dept_section()`이 succession
  데이터의 `rank_type`을 `'Ready Now'`/`'Ready Later'` 문자열과
  **완전 일치**로만 매칭했다. 원본(raw) 데이터에 대소문자/공백이 조금만
  달라도(엑셀 수기 입력 특성상 흔함) 4개 슬롯이 전부 매칭 실패 →
  해당 부서 카드가 0개 → `_dept_section`이 `None`을 반환해 그 부서
  섹션 자체가 화면에서 조용히 사라짐(에러 없이 헤더+인쇄버튼만 남는
  빈 화면). 샘플 데이터 생성기는 문자열을 정확히 하드코딩해서 만들기
  때문에 개발 샌드박스에서는 재현되지 않았다.
  - **수정**: `rank_type` 매칭을 `strip()` + 소문자 비교로 완화해
    표기 차이에 영향받지 않도록 함.
  - **추가 안전장치**: 그래도 카드가 0개인 부서는 조용히 사라지는 대신,
    "rank_type 값이 일치하지 않습니다(원본 값: …)" 또는 "researcher_id가
    researchers 데이터에 없습니다(…)" 같은 구체적 사유를 담은
    `dbc.Alert`를 해당 부서 자리에 표시(`pages/org_comparison.py`
    `_dept_section()`) — 향후 같은 유형의 원천 데이터 표기 문제가
    생겨도 화면에서 바로 원인이 보이도록 함.

## 완료: AI 검색에 5번째 intent `find_similar_researchers` 추가

사용자가 "홍길동 연구원의 전문성과 유사한 전문성을 가진 연구원 찾아줘"라고
질문하면 "홍길동"을 `find_researchers_by_expertise`의 전문성 키워드로
잘못 분류해(사람 이름을 강점 태그로 오인) `expand_term()`이 매칭 실패하고
"해당하는 표기를 찾지 못했습니다"만 반환하던 문제. 실제로 이 질문이
가리키는 기능은 이미 배치로 계산돼 있는 "연구원↔연구원 유사도"
(`pipeline/process_researcher_similarity.py` → `researcher_similarity.json`,
LLM 근거 판정까지 끝난 값, `data_store.read_similar_researchers()`로 이미
읽고 있었음 — 보유 전문성 탭의 "연구원 ↔ 연구원" 서브탭에서 씀)인데,
자연어 질문 라우터에는 이 intent가 아예 없었다.

- **`services/nl_query.py`**: `QUERY_SYSTEM_PROMPT`에 5번째 intent
  `find_similar_researchers` 추가(researcher_query에 이름/사번, 기존
  `find_projects_for_researcher`와 같은 필드 재사용) — "전문성 키워드로
  찾기"가 아니라 "특정 사람과 비슷한 사람 찾기"임을 예시와 함께 명시해
  `find_researchers_by_expertise`와 혼동하지 않도록 라우팅 규칙을
  분리했다. `find_similar_researchers()` 함수 신규 — `_resolve_researcher()`
  로 이름→사번 해석(동명이인 처리 동일 패턴) 후
  `data_store.read_similar_researchers()`의 배치 결과를 그대로 표로
  변환(researcher_id/name/department/level/score/evidence, 새로 계산하지
  않음). `execute_query()`에 라우팅 분기 추가.
- **`services/data_labels.py`**: `level`(유사도 등급)/`evidence`(유사
  근거) 라벨 추가. `score`는 기존에 이미 '유사도점수'로 매핑돼 있던 것을
  그대로 재사용(다만 이 매핑이 `evaluations.csv`의 일반 `score`(점수)
  라벨을 덮어쓰고 있는 기존 dict 중복 키 이슈를 발견 — 이번 작업 범위
  밖이라 손대지 않았고, 자연어 질문 화면에는 영향 없음).
- **한계**: 이 sandbox에는 `llm_config.py`(LLM 자격증명)가 없어 실제
  질문→intent 분류가 되는지는 라이브로 확인하지 못했다. 대신 (1)
  `find_similar_researchers()`를 모의 `researcher_similarity.json`으로
  직접 호출, (2) `execute_query()`에 라우터가 반환할 법한 parsed dict를
  직접 넣어 호출 — 두 경로 모두 정상 동작 확인(7개 기본 컬럼 + level/
  score/evidence 정상 조립). 실제 사용자 환경에서 질문 분류 자체가
  잘 되는지는 배포 후 확인 필요.

## 완료: 개방형 질의(open_data_query) 커버리지 확장 — "가능한 모든 질문에 답"

사용자 요청: 자연어 질문이 LLM/임베딩 파생 산출물이든 원천 CSV든 가리지
않고 최대한 많은 질문에 답할 수 있게 해달라는 것. 점검해 보니 구멍 2개.

- **`services/open_data_query.py`**: `_discover_json_tables()`에
  `researcher_similarity` 테이블 추가(`_researcher_similarity_table()`,
  `researcher_similarity.json`을 researcher_id/similar_researcher_id/
  score/level/evidence 행으로 평탄화) — 방금 추가한
  `find_similar_researchers` intent가 못 잡아내는 변형 질문(예: "유사도
  0.8 이상인 연구원 쌍이 몇 개야?" 같은 집계성 질문)도 개방형 SQL
  경로로는 답할 수 있게 됨.
- **`services/nl_query.py`**: 라우터가 6개 intent 어디에도 못 넣고
  `unsupported`로 분류하면, 예전에는 그 즉시 안내 문구만 반환하고
  끝냈다. 이제는 포기하기 전에 `open_data_query.answer()`를 한 번 더
  시도(마지막 수단 폴백) — 결과가 있으면 그걸 보여주고, 그래도 없으면
  기존 안내 문구로 폴백. `parse_question()`의 `unsupported` 조기 반환에
  `question` 필드를 추가로 실어 보내야 이 폴백 호출이 가능해서 함께
  수정.
- **의도적으로 안 한 것**: 4개 구조화 intent(전문성/과제매칭/유사도)가
  매칭은 됐지만 결과가 0건인 경우까지 개방형 SQL로 재시도하지는 않음
  — 그 경우는 이미 구체적인 사유("~데이터가 없습니다" 등)를 보여주고
  있어, 이걸 다른 답으로 덮어쓰면 오히려 혼란을 줄 수 있다고 판단.
  폴백은 순수 "unsupported"(질문 자체를 못 알아들은 경우)에만 적용.

## 완료: 화면에서 편집 가능한 AI 검색 커스텀 규칙

사용자 요청: "상위평가=가/나 등급" 같은 용어 정의나 "답변에 근거를 더
자세히 포함해줘" 같은 출력 형식 지시를, 코드 배포 없이 화면에서 직접
추가/수정하고 싶다. 확인 결과 사용자가 선택한 설계: (1) 용어 정의와
출력 형식 지시를 굳이 나누지 않고 규칙 텍스트 하나로 통합, (2) 편집
패널은 별도 관리자 페이지가 아니라 AI 검색 바 바로 옆에 토글로 열리는
작은 패널.

- **`services/query_settings.py`**(신규): 규칙 텍스트를
  `data/processed/nl_query_custom_rules.txt`에 저장/조회
  (`read_rules()`/`write_rules()`, 최대 4000자). `apply(system_prompt)`가
  기존 시스템 프롬프트 뒤에 "# 사용자 정의 추가 규칙" 섹션으로 그대로
  덧붙여 반환 — 코드에 있는 원본 프롬프트 상수(`nl_query.QUERY_SYSTEM_PROMPT`,
  `open_data_query._SQL_GEN_SYSTEM_TEMPLATE`)는 건드리지 않는다. 저장
  파일은 `data/processed/*`라 다른 CSV/JSON 산출물과 마찬가지로
  형상관리 대상이 아니다(파이프라인 산출물은 아니지만, 배포 환경마다
  다른 사용자 입력이라는 점에서 성격이 같음).
- **`services/nl_query.py`** / **`services/open_data_query.py`**: 각각
  LLM 호출 직전에 `query_settings.apply()`를 거치도록 한 줄씩 수정
  (라우팅 프롬프트, SQL 생성 프롬프트 양쪽 다 적용).
- **`components/nl_query_bar.py`**: AI 검색 제목 오른쪽에 "규칙 설정"
  버튼(`nl-query-rules-toggle-btn`) 추가, 클릭 시 `dbc.Collapse` 패널이
  열리며 `dcc.Textarea` + 저장 버튼 노출. 패널을 열 때마다(저장 후
  재오픈 포함) `query_settings.read_rules()`로 디스크에서 다시
  읽어와 텍스트영역에 채운다 — `render()`가 앱 시작 시 딱 한 번만
  호출되므로, 초기 레이아웃에 값을 미리 심어두면 다른 세션이 그 사이
  저장한 최신 내용을 못 보는 문제가 생겨 매번 재조회하는 방식으로 짬.
  저장 버튼은 이 세션 전용 콜백 규약(`if not n_clicks: return
  dash.no_update`)을 그대로 따름.
- Playwright로 패널 열기→입력→저장→닫기→재열기까지 end-to-end 확인,
  저장된 텍스트가 `query_settings.apply()`를 통해 프롬프트 끝에 정상
  결합되는 것도 별도 확인.

## 완료: "과제 직무/대상자 검증" 탭 신설 — 직무기술서 ↔ 인사데이터 대조

사용자 요청: 특정 과제의 채용 근거 문서(.docx, 직무기술서 형태 — 예:
"AI 과제는 Knowledge/Validation/Reasoning/공통 4개 직무, 각 5/3/2/1명")를
업로드하면, 그 과제에 실제 배정된 인사데이터 인원 중 각 직무에 전문성이
있다고 판단되는 사람을 근거와 함께 매핑해 문서 수치와 데이터 기반 판정을
대조해 달라는 것. 사용자(HR 담당자, 직무 비전문가)가 이해할 수 있도록
근거는 쉬운 말로. 여러 라운드에 걸쳐 설계를 확정한 뒤 구현:
- 과제는 화면 드롭다운에서 직접 선택(문서에서 자동 추출한 이름을
  신뢰하지 않음).
- 검증 실행마다 결과를 이력으로 저장, 화면에서 다시 조회 가능.
- 새 탭 "과제 직무/대상자 검증"(경로 `/jd-reconciliation`).
- 문서에 표와 서술형이 둘 다 있을 수 있어 각각 추출하고, 표의 "현인원"을
  authoritative로 삼되 서술형과 다르면 "문서 내부 불일치"로 노출.
- 사람별로 "가장 가까운 직무 1개"만 매핑(다중 매핑 안 함).

- **`services/jd_reconciliation.py`**(신규, 모듈 docstring에 전체 흐름
  정리): 
  - `list_project_names()`/`get_project_members()` — `tasks.csv` 기준
    과제 목록/현재 배정 인원 조회(결정적, LLM 미사용). `tasks.csv`는
    `pipeline/process_tasks.py` 산출물이며 이 개발 sandbox에는 현재
    파일이 없어(원천 데이터 미제공) 목록이 비어 있을 수 있음 — 정상
    동작이며, 화면은 빈 목록을 그대로 보여준다(별도 에러 처리 불필요한
    수준의 정상 상태로 취급).
  - `extract_docx()` — `python-docx`로 표/서술형을 분리해서 텍스트로
    추출(표는 셀을 `' | '`로 이어 붙여 LLM이 열 구조를 스스로 해석하게
    함 — 문서마다 헤더/열 순서가 달라 고정 파싱은 깨지기 쉬움).
  - `_extract_roles()` — 표/서술형 각각을 LLM으로 구조화 추출(판단 없이
    추출만, 이 프로젝트의 "구조화 출력 강제" 원칙 유지).
  - `merge_roles()` — role_name 정규화 매칭으로 표/서술형을 병합, 표의
    headcount를 최종 비교 기준으로 삼고 서술형과 다르면
    `consistency_notes`에 기록.
  - `match_members_to_roles()` — 실제 배정자 각각에 대해 LLM 1회 호출로
    "가장 가까운 직무 1개"만 판정(`_MATCH_SYSTEM_PROMPT`가 "HR 담당자가
    이해할 수 있는 쉬운 말로 설명"을 명시적으로 지시 — 전문 용어 금지).
    전문성 분석 데이터가 없는 사람은 LLM 호출 없이 바로 "미분류" 처리.
  - `build_report()` — 직무별 문서 인원 vs 실제 매칭 인원 대조표,
    미분류 인원, 총원 비교, 쉬운 말 요약 문장 조립.
  - `save_history()`/`list_history()`/`load_history()` —
    `data/processed/jd_reconciliation/{과제명}_{실행시각}.json`에 실행마다
    저장. `load_history()`는 `os.path.basename()`으로 경로 조작을 막음.
- **`pages/jd_reconciliation.py`**(신규): 과제 드롭다운 + `dcc.Upload`
  (.docx) + "검증 시작" 버튼 → 결과 카드(직무별 대조, 미분류, 불일치
  경고) + 이력 테이블(행마다 "보기" 버튼으로 재조회,
  `{'type':'jd-history-view','file':...}` 패턴매칭 id 사용, 이 세션의
  팬텀 트리거 방지 규약대로 `n_clicks` 가드 적용).
- **`app.py`**: 네비게이션에 "과제 직무/대상자 검증" 링크 추가.
- **`requirements.txt`**: `python-docx` 추가.
- **테스트**: 실제 LLM 없이(이 sandbox에 `llm_config.py` 없음)
  `services/jd_reconciliation.py`의 결정적 로직(`extract_docx`,
  `merge_roles`의 불일치 감지, `get_project_members`의 종료 배정 제외,
  `build_report`, 이력 저장/재조회)은 모의 데이터로 직접 검증했고,
  `match_members_to_roles`는 `llm_client.call_llm`을 모킹해 라벨→직무명
  역매핑까지 검증. 페이지 자체는 Playwright로 과제 선택 → .docx 업로드 →
  검증 시작 → 결과 렌더링 → 이력 재조회까지 end-to-end 확인(LLM 미설정
  환경이라 역할 추출 자체는 빈 값으로 나왔지만, 그 상태에서도 화면이
  깨지지 않고 "미분류"로 안전하게 처리되는 것까지 확인). 실제 LLM
  연결 환경에서 추출 정확도(특히 표/서술형 구분 인식)는 배포 후 확인
  필요.
