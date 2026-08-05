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

## 완료: process_project_expertise.py 목적 변경 — 직무 딥다이브 매핑 제거,
## 문서 상세 분석 + 인력 매칭으로 전환 (+ 과제↔연구원 매칭 기능 전체 삭제)

사용자 요청: `process_project_expertise.py`에서 "R&D Project Specialist
Agent"(직무 딥다이브 매핑) 기능을 빼고, 대신 "R&D 과제 문서 분석
전문가"(핵심기술/산출물/난제/키워드 추출) 기능을 심화하고, 문서에 언급된
인력과 그 담당 업무를 함께 추출해 `process_researcher_expertise.py`의 새
근거로 넣어 달라는 것. 조사 결과 "직무 딥다이브 매핑"은
`process_project_researcher_fit.py`(과제↔연구원 매칭)의 유일한 입력이라,
사용자 확인 후 그 기능 전체를 함께 삭제했다.

**사용자가 확정한 세부 결정**:
1. 과제↔연구원 매칭 기능(스크립트/탭/AI 검색 intent 전부) 삭제.
2. 인력 이름 매칭 실패 시 원문 이름만 남김(추측 배정 안 함).
3. 이름 후보 좁히기는 `researchers.csv`의 `org_code == project_name` 기준.
4. 기존 4개 항목은 더 길고 구체적으로, 문서 탐색 중 발견되는 새 하위
   항목(연구 배경/추진 일정/기대효과)도 추가.
5. 컨플루언스 검색으로 찾은 인력을 별도 CSV(`project_personnel.csv`)로
   모아 `process_researcher_expertise.py`의 신규 근거로 추가.

**동명이인 판별 규칙**(사용자 설명 그대로 구현): 문서에 "김재연(17)"처럼
이름 옆 괄호 숫자가 있으면, 그 숫자와 후보 `researcher_id`의 앞 2자리를
비교해 판별. 후보가 1명이면 그대로 매칭, 0명이거나 판별 불가(괄호 숫자
없음/불일치)면 매칭하지 않고 원문 이름만 보존.

### 새 목적 (`pipeline/process_project_expertise.py`)
- `project_summary._SUMMARY_SYSTEM_PROMPT` 심화: 기존
  `core_tech`/`deliverable`/`challenge`/`keywords_kr`/`keywords_en` 5개
  항목을 "한두 문장 요약이 아니라 최대한 상세하게" 쓰도록 지시 강화, 신규
  항목 `background`(연구 배경)/`milestones`(추진 일정, 리스트)/
  `expected_impact`(기대효과) 추가. 새로 `personnel`(문서에 언급된 인력)
  추출 지침도 추가 — `name`/`name_suffix`(괄호 숫자)/`role_description`
  (구체적 담당 업무). `_summarize()` 호출의 `max_tokens`를 3000→6000으로
  올림(심화 분석 + 인력 추출까지 한 번에 요구하므로).
  `process_project_search.py`(유사 기업/학계 탐색)도 같은 캐시를
  공유하지만 새 필드는 무시하고 기존 5개만 쓰므로 영향 없음.
- `process_project_expertise.py`의 `process()`를 재작성: 예전엔 1단계
  (문서 요약, 순차) → 2단계(딥다이브 분석, 동시 LLM 호출)였는데, 딥다이브
  단계가 통째로 없어지고 실제 분석 자체가 이미 1단계(project_summary
  호출) 안에서 끝나므로 2단계 개념이 사라짐. 대신 각 과제 처리 후
  `_resolve_personnel()`로 인력 이름→researcher_id 매핑(위 규칙)을
  수행하고, 매핑 결과를 `project_personnel.csv`로 저장(`_write_personnel_csv`,
  `quoting=csv.QUOTE_NONNUMERIC`로 사번 텍스트 형식 보장 — 이 세션이
  이전에 정한 CSV 저장 관례 그대로 따름).
- `project_expertise_analysis.json`의 항목 구조가 바뀜: 예전엔
  `expertise_analysis`(마크다운 원문) 필드 하나에 딥다이브 내용이 다
  들어 있었는데, 이제는 `background`/`milestones`/`expected_impact`
  + `personnel`(researcher_id 매핑 포함) 필드로 구조화됨.
- **`pipeline/rd_specialist_markdown.py`**: "R&D Project Specialist
  Agent" 페르소나 프롬프트(`RD_SPECIALIST_SYSTEM_PROMPT`)와 그 마크다운
  파싱 헬퍼들(`analyze_expertise`/`split_top_sections`/`is_deepdive_section`/
  `split_job_blocks`/`extract_difficulty`/`extract_job_title`/`job_body`/
  `deepdive_jobs`/`parse_job_fields`/`job_card_html`) 전부 삭제.
  `project_card_html()`을 새 스키마용으로 재작성 — 직무 카드 대신
  핵심기술/산출물/난제/배경/기대효과 요약(`dl.kv`) + 추진 일정(불릿
  목록) + 인력 목록(`.personnel-row`, researcher_id 매핑된 사람은
  전문성 MAP 바로가기 링크가 붙는 배지, 미매칭이면 회색 "미매칭" 배지)을
  렌더링. 이제 아무도 안 쓰는 CSS(`.job-*`, `details.more`, `.tabs`/
  `.tab-bar`/CSS 전용 탭 :has() 동기화 규칙)도 함께 정리.
- **`pipeline/process_researcher_expertise.py`**: 새 근거 섹션 `[과제 내
  담당 업무]` 추가 — `_project_role_text()`가 `project_personnel.csv`에서
  해당 researcher_id 행만 추려 텍스트로 구성, `_build_prompt()`에
  `[과제 수행 이력]` 바로 다음 섹션으로 삽입. 시스템 프롬프트의
  `key_responsibilities` 지침에 "과제 문서에 실제로 기록된 내용 — 있으면
  가장 신뢰도 높은 근거로 우선 활용" 문구 추가. 이 CSV가 없거나 해당
  연구원 행이 없어도(파이프라인 미실행/문서에 언급 안 됨) "(데이터
  없음)"으로 정상 동작 — 필수 입력 아님.

### 삭제한 것 (과제↔연구원 매칭 기능 전체)
- `pipeline/process_project_researcher_fit.py` 파일 자체 삭제.
- `pipeline/researcher_fit.py`: 매칭 전용 함수들(`SYSTEM_PROMPT_BY_TARGET`/
  `SYSTEM_PROMPT_BY_RESEARCHER`/`run_matching_llm`/`_label_of`/
  `match_by_target`/`match_by_researcher`/`job_text`/`FIT_VARIANT`/
  `_fit_pill_html`/`build_fit_html`/`read_json`) 삭제, 공용 유틸
  (`researcher_profile_text`/`cached_embed`/`cosine_sim_matrix`/
  `top_k_idx`/`read_researchers`)만 남김 — `process_researcher_similarity.py`와
  `services/jd_reconciliation.py`가 계속 이 나머지를 재사용.
- **`services/data_store.py`**: `read_project_fit_by_project()`/
  `read_project_fit_by_researcher()` 삭제.
- **`services/open_data_query.py`**: `project_fit_by_project`/
  `project_fit_by_researcher` 테이블 등록 삭제.
- **`services/nl_query.py`**: `find_researchers_for_project`/
  `find_projects_for_researcher` intent와 그 전용 함수
  (`find_researchers_for_project`/`find_projects_for_researcher`/
  `_fit_rank_key`/`_match_project_entries`/`_current_project_names`)
  전부 삭제 — 라우터가 이제 4개 intent(전문성 태그/유사 연구원/개방형
  질의/unsupported)만 분류. `_resolve_researcher()`는
  `find_similar_researchers`와 공유라 유지.
- **`pages/researcher_similarity_map.py`**: "연구원 ↔ 과제" 탭 삭제(4개
  → 3개 탭: 연구원/연구원↔연구원/전문성 MAP). 예전엔 "과제 전문성"
  리포트가 이 탭(`project_researcher_fit.html`) 안 3번째 서브탭으로
  통합돼 있었는데, 그 통합도 함께 사라짐 — `project_expertise_analysis.html`은
  다시 독립 정적 리포트로 돌아갔고(Dash 탭에는 연결 안 됨, 필요하면
  파일을 직접 열어서 봄), 이 부분은 사용자가 별도로 요청하지 않아
  Dash 탭으로 재연결하지 않았다.
- **`pipeline/run_pipeline.py`/`run_expertise.py`/`run_analysis.py`**:
  실행 순서 문서/print 안내에서 과제↔연구원 매칭 단계 제거, 단계
  번호 재정렬. `run_analysis.py`는 실제로 `process_project_researcher_fit.process()`를
  호출하던 3/4단계를 코드에서도 제거(3단계 체인으로 축소).
  `run_expertise.py`의 BGE-M3 사전 기동 이유도
  "process_project_researcher_fit.py 대비" → "process_researcher_similarity.py
  대비"로 정정.
- 그 외 `services/similarity_map.py`/`pipeline/result_archive.py`/
  `pipeline/show_embedding.py`/`pipeline/embed_server.py`/
  `services/bge_server.py`의 docstring에 남아 있던
  `process_project_researcher_fit.py` 언급도 정리(기능 설명, 동작에는
  영향 없음).

### 검증
LLM 없이(이 sandbox) `process_project_expertise.py`의 결정적 로직을
모의 `project_summary.get_project_summary` 응답으로 직접 실행 검증 —
동명이인 2명(표기 다른 접미사) + 단독 이름 1명 + 미등록 이름 1명을
넣어 매칭 규칙(정확히 3명 매칭, 1명 미매칭)을 확인했고, 그 결과가
`project_personnel.csv`/`project_expertise_analysis.json`/`.html`에
올바르게 반영되는 것도 확인했다. `process_researcher_expertise.py`의
`_project_role_text()`/`_build_prompt()`도 이 CSV를 직접 읽어 새 섹션이
프롬프트에 올바르게 삽입되는 것을 확인. 전체 파이프라인(`generate_sample_data.py`로
정상 규모 샘플 재생성 후 `process_researcher_expertise.py` 실행)과 Dash
앱(보유 전문성 3탭 구조, 조직별 비교, 연구원 프로필, 과제 직무/대상자
검증)을 Playwright로 재확인 — 전부 정상, 콘솔 에러 없음(연구원 프로필의
`leadership_figure` `KeyError: 'evaluator_group'`는 이 세션 이전부터
있던 무관한 기존 버그로 별도 확인됨).

## 완료: "과제 직무/대상자 검증" — 과제명 기준을 project_confl_address.csv로
## 통일 + 컨플루언스 요약 기반 쉬운 말 직무 설명 추가

사용자 요청: 드롭다운/인원 조회 기준을 `tasks.csv`가 아니라
`project_confl_address.csv`(컨플루언스 과제명 체계, `process_project_expertise.py`가
분석하는 것과 동일)로 바꾸고, 선택한 과제의 컨플루언스 과제 요약 +
업로드한 직무기술서 내용을 함께 활용해 직무 설명을 기술 비전문가인
인사담당자도 이해하기 쉬운 말로 풀어 달라는 것. 현재 인원수 파악(서술형+표
검증)과, 실 배정 인원 중 문서상 직무에 해당하는 사람을 LLM 전문성 분석
기반으로 매핑해 문서 수치와 대조하는 기능(매칭 인원수는 문서 인원수와
독립적으로 나올 수 있음)은 이미 기존 구현이 요구사항을 충족하는 것으로
확인해 별도 코드 변경 없이 유지했다.

**`services/jd_reconciliation.py` 변경**:
- `list_project_names()`: `tasks.csv`(HR 개인별과제투입기간데이터 기반) 대신
  `project_confl_address.csv`의 `project_name`을 드롭다운 목록으로 사용.
- `get_project_members()`: 예전엔 `tasks.csv`를 `pd.Timestamp.now()` 기준
  시작/종료일로 필터링해 "현재 이 과제에 투입 중인 사람"을 골랐는데,
  `researchers.csv`의 `org_code == project_name`(현재 소속 과제) 기준으로
  단순화 — `process_project_expertise.py`의 `_resolve_personnel()`이 문서 내
  인력 이름을 researcher_id로 매핑할 때 쓰는 것과 동일한 기준이라 두
  기능의 "이 과제 사람" 정의가 일관됨. 이제 `pandas`를 직접 쓰지 않아
  `import pandas as pd` 제거.
- 신규 `_read_confluence_summary(project_name)`: `process_project_expertise.py`가
  만든 `project_expertise_analysis.json`에서 이 과제명과 일치하는 항목을
  찾는다(파일 없음/미일치면 `None` — 컨플루언스 분석 없이도 직무기술서만으로
  동작).
- 신규 `_confluence_context_text(entry)`: 핵심기술/배경/최종산출물/기술적
  난제/기대효과/마일스톤을 텍스트로 정리(값이 "확인 불가"거나 빈 경우
  제외).
- 신규 `_PLAIN_EXPLAIN_SYSTEM_PROMPT` + `_plain_explain_roles(roles,
  confluence_context)`: `merge_roles()`가 만든 직무별 설명(기술 용어 포함
  가능)을, 컨플루언스 맥락을 참고 정보로 삼아 쉬운 말로 다시 쓰는 LLM
  호출 1회(직무 전체를 한 번에 처리). 원문은 `raw_description`으로 보존해
  화면에서 대조 가능하게 하고, LLM 실패/응답에 없는 직무는 원문 그대로
  폴백.
- `build_report()`: `confluence_entry` 파라미터 추가, 반환 dict에
  `confluence_available`/`project_overview` 필드 추가, 각 `role_rows` 항목에
  `description`(쉬운 말)/`raw_description`(원문) 추가. 컨플루언스 분석이
  없는 과제는 `summary_text`에 안내 문구를 덧붙임.
- `run_reconciliation()`: `merge_roles()` 이후 `_read_confluence_summary()` →
  `_plain_explain_roles()`를 거쳐 쉬운 말로 바뀐 `roles`를
  `match_members_to_roles()`/`build_report()`에 전달하도록 흐름 변경.

**`pages/jd_reconciliation.py` 변경**:
- `_role_card()`: 쉬운 말 `description`을 본문에 표시하고, 원문과 다르면
  `raw_description`을 작은 회색 글씨로 "원문: ..."로 함께 노출(검증용).
- `_render_report()`: `confluence_available`이면 요약 알럿 아래에 "과제
  개요(컨플루언스 분석 기반)" 카드를 추가로 표시.
- 상단 안내 문구를 새 흐름(컨플루언스 요약 + 쉬운 말 설명)을 반영해 수정.

**검증**: `project_confl_address.csv`/`project_expertise_analysis.json`
픽스처(기존 `researchers.csv`의 `org_code=ORG01`, 10명)로
`list_project_names`/`get_project_members`/`_read_confluence_summary`/
`_confluence_context_text` 확인. `_plain_explain_roles`는 LLM 응답을
모킹해 정상 매핑과, LLM 실패 시 원문 폴백(둘 다 정상) 확인.
`match_members_to_roles`/`build_report`도 모킹으로 전체 흐름 확인 —
`confluence_available=True`, `project_overview` 채워짐, `role_rows`에
`description`/`raw_description` 정상 반영. `pages/jd_reconciliation.py`의
`_render_report()`/`layout()`도 더미 리포트로 렌더 확인. 테스트 중 만든
픽스처 파일은 스크립트 종료 시 자동 삭제(원래 없던 파일만 정리).

## 완료: process_project_expertise.py에 `--refresh` 캐시 무효화 플래그 추가

배경: `process_project_expertise.py`의 목적을 바꾸며 `project_summary.py`의
`_SUMMARY_SYSTEM_PROMPT`에 `personnel`/`background`/`milestones`/
`expected_impact` 항목을 추가했는데, 프롬프트가 바뀌기 전에 이미 쌓여 있던
`project_summary_cache.json`은 예전 프롬프트 결과 그대로라 이 새 항목들이
비어 있다. `get_project_summary()`는 캐시 키가 있으면 LLM을 다시 부르지
않고 캐시값을 그대로 반환하므로, 이 상태에서 `process_project_expertise.py`를
재실행해도 인력(personnel) 등 새 항목이 계속 빈 값으로 나온다 — 코드
버그가 아니라 캐시 무효화 수단이 없어서 생기는 문제였다.

`journal_authority.py`의 `--refresh-journals`와 동일한 패턴으로 해결:
- `project_summary.get_project_summary()`에 `force: bool = False` 파라미터
  추가 — `force=True`면 `summary_cache`에 값이 있어도 무시하고 다시
  요약한다. 원문 캐시(`project_page_cache.json`)는 그대로 재사용한다
  (Confluence/PDF 재조회는 불필요 — 문서 원문 자체는 안 바뀌었으므로).
- `process_project_expertise.py`의 `process()`에 `force` 파라미터를 추가해
  그대로 전달하고, `--refresh` CLI 인자로 노출(`process(force='--refresh' in sys.argv)`).
- `process_project_search.py`도 같은 `get_project_summary()`를 호출하지만
  `force` 파라미터를 안 넘기므로(기본값 False) 동작에 영향 없음.

사용법: `python pipeline/process_project_expertise.py --refresh`

검증: `get_project_summary()`를 직접 호출하는 단위 테스트로
`force=False`일 때 캐시에 값이 있으면 LLM 호출 없이 캐시값 그대로 반환,
`force=True`일 때는 캐시 무시하고 LLM을 호출해 새 값으로 캐시를 덮어쓰는
것을 확인.

## 완료: "과제 직무/대상자 검증" 업로드 — .pdf 지원 추가 + .docx 오류 메시지 개선

배경: 직무기술서를 .docx로 업로드할 때 "오류가 발생했습니다"만 뜨고 원인을
알기 어렵다는 문의. 원인은 대부분 확장자만 .docx로 바뀐 옛 .doc(바이너리)
파일이거나 손상된 파일 — python-docx의 `Document()`는 이런 경우
`zipfile.BadZipFile`(.docx는 내부적으로 zip/OOXML 포맷이라 zip으로도 못
열림) 또는 `docx.opc.exceptions.PackageNotFoundError`(zip은 맞지만 OOXML
필수 구성요소가 없음)를 던지는데, 예전엔 이걸 그대로 문자열화해 화면에
노출해서 사용자가 원인을 알기 어려웠다. 겸사겸사 .docx 외에 .pdf 직무기술서도
받을 수 있게 확장했다(이미 `pipeline/pdf_reader.py`가 pypdf로 PDF 텍스트를
뽑는 로직을 갖고 있어 재사용 가능했음).

**`pipeline/pdf_reader.py`**: 기존 `fetch_pdf_text(project_name)`(고정 경로
`data/raw/conflue_MPR/{project_name}.pdf`에서 읽음)의 핵심 추출 로직을
`extract_text_from_bytes(file_bytes, label='PDF')`로 분리 — 임의의 PDF
바이트에서 텍스트를 뽑는 범용 함수. `fetch_pdf_text()`는 이제 파일을 읽어
바이트로 넘기는 방식으로 이 함수를 호출(동작은 그대로, 코드만 재사용
가능하게 분리).

**`services/jd_reconciliation.py`**:
- `extract_docx(file_bytes)` → `_extract_docx(file_bytes)`로 이름 변경(내부
  함수화), `DocumentReadError` 신설(스택 트레이스 대신 화면에 그대로 보여줘도
  되는 한국어 메시지를 담는 예외).
  - `Document()` 호출을 `try/except (PackageNotFoundError, zipfile.BadZipFile)`로
    감싸 "올바른 .docx 파일이 아닌 것 같습니다(예: 오래된 .doc 형식이거나
    파일이 손상됨)... 다시 저장한 뒤 업로드해주세요" 메시지로 변환.
  - 그 외 예상 못한 예외도 `except Exception`으로 잡아 최소한 원인 문자열은
    보여주는 `DocumentReadError`로 감쌈(파일 파싱은 외부 입력 경계).
- 신규 `_extract_pdf(file_bytes)`: `pdf_reader.extract_text_from_bytes()`로
  텍스트를 뽑아 전부 `narrative_text`로 취급(`tables_text`는 빈 문자열 —
  일반 PDF에는 docx 같은 구조화된 표 정보가 없음). 실패(암호화/스캔 이미지
  PDF 등)는 `pdf_reader.PdfNotFoundError`를 `DocumentReadError`로 변환.
- 신규 `extract_document(file_bytes, filename)`: 확장자(`.docx`/`.pdf`)로
  분기 호출, 그 외 확장자는 `DocumentReadError`("지원하지 않는 파일
  형식입니다..."). `run_reconciliation()`이 `extract_docx()` 대신 이 함수를
  호출하도록 변경.

**`pages/jd_reconciliation.py`**:
- `dcc.Upload`의 `accept`를 `.docx` → `.docx,.pdf`로, 라벨/안내 문구도 두
  형식을 함께 언급하도록 수정. 업로드된 파일명 표시 아이콘도 확장자에 따라
  Word/PDF 아이콘으로 분기.
- `_run()` 콜백에 `except jd.DocumentReadError` 분기를 추가해 그 메시지를
  그대로(가공 없이) warning 색상 알럿으로 보여줌 — 기존 `except Exception`
  (danger 색상, "검증 중 오류가 발생했습니다: ..." 접두문구)은 진짜 예기치
  못한 오류만 잡도록 남겨둠.

**검증**: 정상 .docx(표+서술형 둘 다 있는 문서), 손상된/가짜 .docx 바이트,
zip이지만 OOXML이 아닌 바이트, 지원하지 않는 확장자(.hwp), 빈 페이지 PDF
(텍스트 없음 경로) 각각에 대해 `extract_document()`를 직접 호출해 기대한
결과/메시지가 나오는지 확인. `run_reconciliation()`을 통해서도
`DocumentReadError`가 그대로 전파되는 것을 확인. `pages/jd_reconciliation.py`의
`layout()` 렌더도 재확인.

## 완료: org_code ↔ project_name 표기 형식 불일치 수정 (대괄호 태그/띄어쓰기)

배경: `project_confl_address.csv`의 `project_name`은 `"[탐색] 가나다라마바사"`
처럼 앞에 대괄호 분류 태그가 붙고 띄어쓰기 유무도 문서마다 다른 반면,
`researchers.csv`의 `org_code`는 `"가나다라마바사"`처럼 태그도 공백도 없는
형태다. `_resolve_personnel()`(`process_project_expertise.py`)과
`get_project_members()`(`jd_reconciliation.py`)는 둘 다
`org_code == project_name` 정확 일치로 비교하고 있어서, 이 형식 차이 때문에
**항상 후보 0명**으로 나오고 있었다 — 인력 매칭도, 과제 직무/대상자 검증
탭의 배정 인원 조회도 조용히 실패하는 상태였다(에러 없이 빈 결과만 나와
알아채기 어려움).

**해결**: `pipeline/researcher_fit.py`에 `normalize_org_code(text)` 공용
함수 추가 — 앞쪽 대괄호 태그(`^\[[^\]]*\]\s*`, 있으면)를 떼고 모든 공백을
제거한다. `org_code`/`project_name` 양쪽에 이 함수를 적용한 뒤 비교하도록
`_resolve_personnel()`과 `get_project_members()`를 수정 — 두 함수가 항상
같은 파일(`researcher_fit.py`)의 같은 정규화 기준을 공유해 드리프트가
안 생기게 했다.

검증: `normalize_org_code()`에 대괄호 태그+띄어쓰기 유무 여러 조합("[탐색]
가나다라마바사", "[탐색 또는 연구] 가나 다라마바사", "[연구]가나다라마바사",
공백 없는 원본 등)을 넣어 전부 "가나다라마바사"로 정규화되는지 확인.
`get_project_members("[탐색] ORG01")`이 `org_code="ORG01"`인 연구원들을
정상적으로 찾는 것, `_resolve_personnel("[탐색] ORG01", ...)`이 동명이인
suffix 판별을 포함해 정상 매칭되는 것을 각각 fixture로 확인.

## 완료: python-docx 미설치 시 ModuleNotFoundError가 그대로 노출되던 문제 수정

배경: "과제 직무/대상자 검증"에서 과제 선택 후 .docx를 업로드하면
"검증 중 오류가 발생했습니다: No module named 'docx'"가 나온다는 문의(PDF는
정상 동작). 원인은 두 가지가 겹쳤다:
1. (환경) `requirements.txt`에는 `python-docx>=1.1.0`이 있지만, 실제로 앱을
   구동하는 서버/컨테이너에 이 의존성이 설치돼 있지 않았음(또는
   requirements.txt에 추가된 뒤 재설치가 안 됨) — `pip install -r
   requirements.txt` 재실행 + 앱 재시작이 필요.
2. (코드) `_extract_docx()`의 `from docx import Document`가 `try` 블록
   *밖*에 있어서, 패키지가 없을 때 나는 `ModuleNotFoundError`가 어떤
   `except`에도 안 잡히고 그대로 `pages/jd_reconciliation.py`의 최종
   `except Exception` 폴백까지 새어나가 원문 그대로("No module named
   'docx'") 노출되고 있었다. `pdf_reader.py`가 `pypdf` 없을 때 이미 하고
   있는 것과 같은 방식으로 고쳤다.

**수정**: `_extract_docx()`의 `from docx import Document`/
`from docx.opc.exceptions import PackageNotFoundError`를 `try/except
ModuleNotFoundError`로 감싸, "python-docx 패키지가 설치되어 있지 않아 .docx
파일을 읽을 수 없습니다. 서버에서 pip install -r requirements.txt(또는 pip
install python-docx)를 실행한 뒤 앱을 재시작해주세요."라는 `DocumentReadError`로
변환. 화면에는 이 메시지가 warning 알럿으로 그대로 표시된다(이전 세션에서
`DocumentReadError`를 warning 색상으로 렌더링하도록 이미 처리해둠).

검증: `builtins.__import__`를 가로채 `docx` 모듈이 없는 상황을 흉내내
`extract_document()`가 원하는 `DocumentReadError` 메시지를 던지는지 확인.
정상 상태(모듈 있음)에서 표+서술형이 있는 .docx 추출도 회귀 테스트로 재확인.

## 완료: "JOB Market" 탭 신설 — 과제 종료 시 보유 전문성 기준 재배치 추천

사용자 요청: 특정 과제가 종료된다고 가정할 때, 그 과제원들이 보유 전문성
기준으로 어떤 다른 과제에 참여 가능한지(가장 가까운 과제가 무엇인지)를
보여주는 새 탭. 개념적으로는 이 세션 초반에 완전히 삭제한
`process_project_researcher_fit.py`(과제↔연구원 매칭)와 비슷한 성격이지만,
"이 과제엔 누가 맞는가"가 아니라 "이 사람들이 다른 어떤 과제로 갈 수
있는가"를 인력 재배치 관점에서 보는 별도 기능으로 새로 설계했다.

**사용자가 확정한 세부 결정**:
1. 근거는 두 가지를 모두 보여주되 구분 표기: A) 과제 분석(컨플루언스 요약)
   기반, B) 그 과제에 배정된 연구원들의 보유 전문성 프로필 기반. 어느 한쪽
   데이터가 없으면 그 항목만 개별적으로 "데이터 없음"으로 표시(과제 전체를
   후보에서 빼지 않음 — 단, 둘 다 없으면 비교 근거가 아예 없으므로 후보에서
   제외).
2. department 드롭다운은 project_confl_address.csv의 dep_name 기준.
3. 표시 항목 중 년차는 "직급연차"(CL/년차), 학력/전공은 최종학력 1개만.
4. 후보 과제 풀은 project_confl_address.csv에 등록된 전체 과제.
5. 계산은 "검색" 버튼 클릭 시 그 자리에서 임베딩+LLM 실행(배치 파이프라인
   아님).
6. 본인이 현재 속한 과제는 항상 자동으로 후보에서 제외되고, 제외 필터도
   동일하게 적용됨(과제 단위/개인별 검색 공통).

### `services/job_market.py` (신규)
- `list_departments()`/`list_projects(department=None)` — 드롭다운용, 결정적.
- `build_roster(researcher_ids)` — 명단(사번/성명/부서/과제/CL·년차/학력·전공/
  나이)을 만든다. 직접 계산하지 않고 `services/researcher_profile_export.py`의
  `person_base_table()`을 그대로 재사용 — 그 모듈이 이미 정확히 이 7개
  컬럼(`PERSON_BASE_COLUMNS`, 라벨도 "CL/년차"·"학력/전공"으로 이미 확정돼
  있음)을 계산해 두고 있어서 새로 만들 필요가 없었다.
- `_dedup_candidate_rows()` — project_confl_address.csv를
  `fit.normalize_org_code()` 기준으로 묶어 대괄호 태그/띄어쓰기가 다른
  중복 표기를 대표 행 하나로 합친다(직전에 고친 org_code/project_name
  정규화 이슈와 동일한 문제가 후보 과제 목록 자체에도 있을 수 있어 여기서도
  적용).
- `_expand_excluded_projects()` — 제외 부서를 그 부서의 모든 과제로 펼치고
  제외 과제와 합쳐 정규화된 제외 집합을 만든다.
- `_build_candidate_pool()` — 후보 과제별로 근거 A 텍스트(있으면,
  `jd_reconciliation.read_confluence_summary`/`confluence_context_text`
  재사용)와 근거 B(현재 배정 인력의 전문성 프로필 텍스트 목록, 있는 사람만)를
  모아 `fit.cached_embed()`로 한 번에 임베딩한다(캐시 재사용 — 후보/인원이
  늘어도 반복 임베딩 호출 없음). A/B 둘 다 없는 과제는 이 단계에서 제외.
- `_score_candidates()` — 결정적 로직(LLM 미사용). 대상자 프로필 임베딩과
  각 후보의 A 임베딩/B 최댓값(가장 가까운 배정 인력 1명)을 코사인 유사도로
  비교해 결합 점수(둘 중 높은 쪽) 내림차순 정렬.
- `_judge_recommendations()` — 임베딩 상위 8개만 LLM에 보여주고 최대 3개를
  사유와 함께 고르게 한다(구조화 출력 강제 — 순위는 이미 Python이 정해
  둔 후보 중에서만 고르게 해 할루시네이션 방지, 목록에 없는 과제명이
  나오면 버림). LLM 프롬프트에는 researcher_id/이름을 전혀 포함하지
  않는다(이 프로젝트 전체 원칙 — 대상자 본인도 B 근거로 쓰는 대표 인력도
  프로필 텍스트만 전달).
- `recommend_for_researcher()` — 위 단계를 묶은 사람 1명 단위 함수.
  `run_project_search()`(과제 단위, 배정 인원 전체에 대해 동시 실행 —
  `llm_client.run_concurrent()` 재사용)와 `run_individual_search()`(개인별
  검색, 이름/사번 검색은 `nl_query._resolve_researcher()`와 같은 방식을
  로컬로 둠)가 candidate_pool을 한 번만 만들어 공유하며 이 함수를 호출한다.

### `services/jd_reconciliation.py` (기존 파일 소폭 변경)
`_read_confluence_summary()`/`_confluence_context_text()`를
`read_confluence_summary()`/`confluence_context_text()`로 공개 함수화(내부
로직 변경 없음) — job_market.py가 재사용하기 위함. 내부 호출부도 함께 갱신.

### `pages/job_market.py` (신규) + `app.py`
새 탭 "JOB Market"(`/job-market`) 추가. 화면 구성: 모드 전환(과제 단위/
개인별 검색, RadioItems) → 종료 예정 과제 선택(부서 드롭다운 선택 시
과제 드롭다운이 그 부서로 좁혀지는 cascading, `jm-project-dept` →
`jm-project-select`) 또는 개인별 검색어 입력 → 제외 부서/제외 과제(각각
독립적인 다중 선택 드롭다운, 전체 목록 대상) → 검색 버튼 → 명단 테이블 +
사람별 추천 카드(과제명·소속·A/B 점수 배지·사유, 0~3개 또는 "데이터
없음"/"근거 없음" 안내).

**검증**: `services/job_market.py`는 project_confl_address.csv(대괄호 태그
포함/미포함 혼재)·project_expertise_analysis.json·연구원 보유 전문성
분석.json 픽스처 + `fit.cached_embed`/`llm_client.call_llm` 모킹으로
후보 풀 구성(제외 집합 계산, A/B 둘 다 없는 과제 자동 제외, 대괄호 태그
중복 제거)과 과제 단위/개인별 검색 전체 흐름을 확인. `pages/job_market.py`는
Playwright로 실제 앱 기동 후: 네비게이션 탭 노출, 모드 전환 UI 토글,
부서→과제 cascading 드롭다운이 실제로 좁혀지는지, 제외 드롭다운 2개가
서로 독립적으로 전체 목록을 보여주는지, 검색 버튼 클릭 시(임베딩 서버
없는 개발 환경이라 "후보 과제 0건"으로 정상적으로 우아하게 처리됨 — 크래시
없음) 결과 영역이 렌더링되는지, 필수 입력 누락 시 경고 알럿이 뜨는지 확인.
기존 페이지(jd-reconciliation)에서도 동일하게 발생하는 무관한 콘솔 에러
(`ERR_TUNNEL_CONNECTION_FAILED`, 샌드박스 프록시 환경 이슈)를 제외하면
콘솔 에러 없음. 테스트 중 만든 픽스처 파일은 전부 삭제하고 원상 복구.

## 완료: 엑셀 프로필 다운로드 — 중복 인물 제거 + 과제수행이력 최신순 정렬

1. `components/nl_query_bar.py`의 `_selected_researcher_ids()` — 한 질문의
   결과 테이블에 같은 연구원이 여러 행(과제/논문/특허 등 항목별 한 행씩)으로
   나올 수 있어, 그중 여러 행을 선택하면 같은 researcher_id가 중복으로
   담겨 "선택 N명" 표시가 실제 인원수보다 부풀려지고 엑셀에도 같은 사람의
   프로필이 여러 번 나오는 문제가 있었다. 처음 나온 순서를 유지하며
   중복을 제거하도록 수정 — 이 함수가 "선택 N명" 라벨과 엑셀 다운로드
   둘 다의 유일한 소스라 한 곳만 고치면 둘 다 해결됨.
2. `services/researcher_profile_export.py`의 `_col_tasks()`(엑셀 "과제수행이력"
   컬럼) — `start_date` 오름차순 정렬을 `reverse=True`로 바꿔 최근 이력이
   상단에 오도록 수정.

## 완료: JOB Market — 종료 예정 과제 복수 선택 지원

"종료 예정 과제" 선택을 단일 선택에서 복수 선택으로 확장(제외 과제
섹션과 동일하게 부서/과제 드롭다운 모두 `multi=True`).

- `services/job_market.py`: `list_projects(department)`가 department를
  문자열 1개 또는 리스트 모두 받도록 일반화. `run_project_search()`가
  `project_name: str` 대신 `project_names: list`를 받아 선택한 과제 전체의
  배정 인원을 합친다(중복 인원은 한 번만). 제외 집합에는 선택한 과제
  전체를 넣는다 — 함께 종료되는 과제끼리 서로 재추천되지 않도록(과제 A와
  B가 같이 끝나면, A 소속이었던 사람에게 B를 추천하지 않음). 결과 dict의
  키도 `project_name` → `project_names`(리스트)로 변경.
- `pages/job_market.py`: 두 드롭다운에 `multi=True` 추가, `_run()` 콜백이
  리스트를 받아 그대로 전달, 결과 상단 알럿에 "선택한 과제(A, B)를
  기준으로..." 문구 추가.

검증: `list_projects()`에 부서 리스트를 넘겨 여러 부서의 과제가 모두
나오는지, `run_project_search(['ORG01','ORG02'], ...)`가 두 과제의 인원을
합친 명단(중복 없음)을 만들고 두 과제 모두 후보에서 제외하는지 픽스처로
확인. Playwright로 실제 화면에서 부서 2개 → 과제 2개를 순서대로 다중
선택해 cascading 옵션이 정확히 좁혀지는지, 검색 결과 상단에 선택한 과제
둘 다 표시되는지 확인.

## 완료: JOB Market — 검색 이력, 부서→과제 제외 드롭다운 cascading, 개인별 검색 버그 수정

1. **검색 이력**: `jd_reconciliation.py`와 동일한 패턴(`save_history`/
   `list_history`/`load_history`, `HISTORY_DIR = data/processed/job_market/`)을
   `services/job_market.py`에 추가. `run_project_search()`/`run_individual_search()`
   성공 시(에러 아닐 때만) 자동 저장. 화면에는 검색 결과 아래 "검색 이력"
   테이블(실행일시/구분/대상/인원/후보 과제/보기)을 추가, "보기" 클릭 시
   그 이력의 결과를 다시 렌더링(jd_reconciliation의 이력 보기 버튼과 동일한
   pattern-matching 콜백 구조).
2. **제외 과제 드롭다운도 부서 선택 시 좁혀지도록**: `jm-exclude-dept` 선택값을
   `jm-exclude-project`의 옵션 필터링에도 쓰도록 변경("종료 예정 과제"
   섹션과 동일한 cascading). 단, 실제 제외 계산(`_expand_excluded_projects`)의
   "부서 제외 + 과제 제외는 독립적으로 합쳐진다" 로직 자체는 그대로 — 여기서
   바뀐 건 드롭다운에 "보여주는 옵션"만이다.
3. **개인별 검색이 아무 결과도 안 보이던 버그**: `run_project_search()`는
   사람별 추천 계산(`recommend_for_researcher`)을 `llm_client.run_concurrent()`로
   감싸서 실행하기 때문에, 그 안에서 예상 못한 예외(예: 캐시에 차원이 다른
   임베딩이 섞여 있는 경우 등)가 나도 안전하게 잡아 "처리 중 오류" 노트로
   보여준다. 그런데 `run_individual_search()`는 같은 함수를 **직접** 호출하고
   있어서 이 안전망이 없었다 — 그런 예외가 나면 Dash 콜백 자체가 죽어서
   화면에 "아무 결과도 안 나오는" 것처럼 보였다(개인별 검색만 실패하고
   과제 단위 검색은 정상이었던 이유). `run_individual_search()`도
   `run_concurrent()`에 태워(1건이라도) 호출하도록 바꿔 과제 단위 검색과
   동일한 안전망을 갖도록 통일.

검증: `save_history`/`list_history`/`load_history`를 과제 단위·개인별 검색
둘 다로 픽스처 테스트. `recommend_for_researcher`를 몽키패치로 예외를
던지게 만들어 `run_individual_search()`가 예외를 그대로 전파하지 않고
"처리 중 오류: ..." 노트가 담긴 정상적인 결과 dict를 반환하는지 확인.
`jm.list_projects(department)`가 부서로 옵션을 좁히는지 확인. Playwright로
실제 화면에서 검색 이력 테이블이 채워지고 "보기" 버튼이 과거 결과를
다시 렌더링하는지, 제외 과제 드롭다운이 부서 선택 시 실제로 좁혀지는지,
개인별 검색이 정상적으로 결과를 보여주는지 모두 재확인.

## 완료: JOB Market — 검색 콜백 전체를 감싸는 최종 안전망 추가

이전에 `run_individual_search()` 내부의 사람별 추천 계산 단계만
`run_concurrent()`로 감싸 예외 안전망을 갖췄는데도, "개인별 검색에서
이름/사번을 넣고 검색해도 응답 자체가 없다"는 재현이 계속 보고됨 — 이
개발 샌드박스의 샘플 데이터로는 재현되지 않아, 실데이터 환경에만 있는
조건(예: 명단 구성/후보 조회 단계에서 나는 예외 등, run_concurrent
바깥의 코드)이 원인일 가능성이 높다고 보고 근본 원인 대신 증상 자체를
근본적으로 막기로 했다.

`pages/job_market.py`의 `_run()` 콜백 전체(모드 분기 + `jm.run_project_search`/
`jm.run_individual_search` 호출)를 `try/except Exception`으로 감싸, 어떤
원인의 예외든 "검색 중 오류가 발생했습니다: ..."라는 눈에 보이는 알럿으로
바뀌도록 했다 — Dash는 콜백 안에서 처리 안 된 예외가 나면(운영
모드 `debug=False`) 해당 콜백의 Output이 아예 갱신되지 않아, 사용자
입장에서는 "버튼을 눌러도 화면에 아무 반응이 없는" 것처럼 보인다. 이
최종 안전망으로 최소한 항상 뭔가는 화면에 뜨게 만들었다 — 이후 실제
알럿 메시지를 통해 정확한 원인을 알 수 있게 됨.

검증: `jm.run_individual_search`를 몽키패치로 임의 예외를 던지게 만들어
`_run()`이 예외를 삼키지 않고 `dbc.Alert(danger)`를 반환하는지 확인.
정상 동작(과제 단위/개인별 검색, 이력, cascading 드롭다운)은 Playwright로
재확인해 회귀 없음을 확인.

## 완료: JOB Market — 개인별 검색에서 Enter 키가 아무 반응이 없던 진짜 원인

이전 두 번의 시도(run_concurrent 안전망, 콜백 전체 try/except)로도
"개인별 검색에서 이름/사번을 넣어도 응답이 없다"가 재현된다는 보고가
계속돼, Playwright로 실제 사용자가 할 법한 다른 조작 패턴을 하나씩
테스트해 봤다 — 검색창에 이름을 입력하고 **Enter 키**를 누르는 경우
(버튼을 따로 클릭하지 않고)를 재현하자 실제로 화면에 아무 변화가 없는
것을 확인했다: `_run()` 콜백이 `Input('jm-run-btn', 'n_clicks')`만
듣고 있어서, Enter는 `dcc.Input`의 `n_submit` 값만 올릴 뿐 어떤
콜백도 트리거하지 않았다. 이전의 안전망들은 전부 콜백이 "실행된 이후"
발생하는 예외를 잡는 것들이라, 콜백 자체가 트리거되지 않는 이 케이스는
전혀 손대지 못하고 있었다.

`pages/job_market.py`의 `_run()` 콜백에
`Input('jm-individual-query', 'n_submit')`을 추가해 Enter로도 검색이
실행되도록 했다(`n_clicks`가 0이어도 `n_submit`으로 트리거될 수 있어야
하므로 `if not n_clicks: return ...` 가드도 제거 — `prevent_initial_call=True`가
이미 최초 로드 시 오발동을 막아 준다).

검증: Playwright로 검색창에 이름을 입력한 뒤 버튼 클릭 없이 Enter만
눌러 정상적으로 결과가 렌더링되는지 확인(수정 전엔 빈 화면, 수정 후엔
정상 결과). 기존 버튼 클릭 경로, 과제 단위 복수 선택 검색도 회귀
없음을 재확인.

## 완료: JOB Market — 개인별 검색을 3단계(검색→선택→검색 실행) 흐름으로 재설계

사용자 요청: 개인별 검색을 하나의 텍스트 입력으로 즉시 실행하는 대신,
1) 검색창에 이름/사번을 검색하면 대상자 후보가 나와서 고를 수 있고(다시
검색해서 복수 대상자를 계속 추가 가능), 2) 제외 부서/과제 선택, 3) "검색"
버튼으로 선택된 한 명 또는 여러 명 전체의 결과를 한 번에 보여주는 3단계
흐름으로 바꿔 달라는 것.

**`services/job_market.py`**:
- 신규 `search_researchers(query)` — 검색창용. 기존 `_resolve_researcher_query()`
  (정확 일치 우선, 없으면 부분 일치)를 그대로 재사용하되, 동명이인이어도
  에러 내지 않고 전부(최대 `MAX_SEARCH_RESULTS`=20건) 반환해 화면에서
  고르게 한다.
- `run_individual_search()` 시그니처를 `researcher_query: str`(단일 텍스트,
  내부에서 동명이인이면 에러) → `researcher_ids: list`(화면에서 이미 확정한
  1명 이상)로 변경. 사람마다 "현재 속한 과제" 제외 조건이 다를 수 있어
  후보 풀도 사람별로 계산하되, 같은 소속(정규화된 org_code)인 사람끼리는
  풀을 재사용해 임베딩 반복 계산을 피한다. 나머지(LLM 최종 판정)는
  `run_project_search()`와 동일하게 `run_concurrent()`로 동시 처리.
- `_history_label()`이 개인별 검색 결과가 이제 여러 명일 수 있음을 반영
  (1명이면 "이름(사번)", 여러 명이면 "이름1, 이름2 외 N명").

**`pages/job_market.py`**:
- 개인별 검색 영역을 검색창+"찾기" 버튼(Enter로도 검색) → 후보 목록(각
  후보에 "추가" 버튼) → "선택된 대상자" 칩 목록(각 칩에 "×" 제거 버튼) 구조로
  재구성. `dcc.Store`(`jm-individual-candidates-store`: 마지막 검색 결과,
  `jm-individual-selected-store`: 누적된 선택 목록)로 상태 관리.
- 새 콜백 3개: `_search_candidates`(검색 버튼/Enter → 후보 렌더링),
  `_update_selected`(패턴 매칭 — "추가"/"×" 버튼 클릭에 따라 선택 목록에
  더하거나 뺌, 중복 추가는 무시), `_render_selected`(선택 목록 렌더링).
- 최종 "검색" 버튼(`_run`)은 이제 `jm-individual-selected-store`에서
  researcher_id 목록을 뽑아 `run_individual_search(researcher_ids, ...)`를
  호출 — 1명이든 여러 명이든 동일한 경로.

검증: `search_researchers`가 동명이인/부분일치를 전부 반환하는지,
`run_individual_search`가 서로 다른 소속의 여러 사람을 한 번에 처리하고
입력에 중복 researcher_id가 있어도 한 번만 처리하는지 픽스처로 확인.
Playwright로 실제 화면에서 "정재원" 검색→추가, "오지아" 검색→추가로
두 명을 누적한 뒤 최종 검색을 누르면 두 사람 모두의 결과가 한 번에
나오는 것, 칩의 "×"로 제거가 되는 것, 과제 단위 검색(복수 선택)/이력/
제외 드롭다운 cascading에 회귀가 없는 것을 확인.
