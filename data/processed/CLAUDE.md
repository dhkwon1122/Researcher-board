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
   생성 — 원본 데이터를 요약/판단/구조화한 결과): `연구원 보유 전문성 분석.json`,
   `project_expertise_analysis.json`, `project_fit_by_project.json`,
   `project_fit_by_researcher.json`, `project_researcher_fit.html`,
   `researcher_similarity.json`, `researcher_pair_judgment.json`(쌍 판정 캐시),
   `journal_authority.json`(캐시), `strength_taxonomy*.json`(표준화 작업, 아래 참고),
   `embedding_cache.json`(BGE-M3 벡터 캐시, 텍스트 해시 키). 전체 LLM 프롬프트
   목록·원문은 세션 산출물로 사용자에게 전달된 `LLM_프롬프트_전체_목록.md` 참고
   (이 파일 자체는 저장소에 커밋돼 있지 않음 — 필요하면 재생성 가능).
   **"연구원 보유 전문성 분석.html"/"researcher_similarity.html"/
   "project_expertise_analysis.html"는 더 이상 이 디렉터리에 "현재본"으로
   저장되지 않는다** — 앞 둘은 `pages/researcher_similarity_map.py`가
   `pipeline/process_researcher_expertise.py`·`process_researcher_similarity.py`의
   `build_html()`을 화면 진입 시 그때그때 호출해 렌더링하고, 마지막
   하나(`project_expertise_analysis.html`, 앱 화면이 아니라 앱 밖 공유용)는
   `pipeline/process_project_expertise.py --email=...`로 그때그때 만들어 메일로만
   보낸다. 셋 다 실행 시각이 찍힌 스냅샷만 `data/processed/result/`(권한 잠금
   대상)에 남는다. 아래 "2026-08-19" 항목들 참고.

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

## 완료: JOB Market — 참여 가능한 과제가 없는 사람에게도 근거 표시

사용자 요청: 참여 가능한 과제를 찾지 못한 사람도 그냥 "없음"으로 끝내지
말고, "그나마 가장 가까운 과제는 이건데, 이것도 전문성이 이러이러해서
다르다" 식으로 근거를 보여 달라는 것.

**`services/job_market.py`**:
- `_RECOMMEND_SYSTEM_PROMPT`에 `closest_non_match` 출력 필드 추가 —
  `recommendations`가 빈 리스트면(뚜렷이 맞는 과제가 없으면) 그나마 가장
  가까운 후보 하나와 "왜 이것도 충분히 맞지 않는지" 사유를 담게 하고,
  `recommendations`에 1개 이상 있으면 반드시 `null`로 두게 지시. 추가
  LLM 호출 없이 기존 1회 호출의 출력 형식만 확장(구조화 출력 강제 원칙
  유지).
- `_judge_recommendations()`가 `(recommendations, closest_non_match)`
  튜플을 반환하도록 변경. `closest_non_match`도 `recommendations`와
  동일하게 "shortlist(임베딩 상위 후보)에 실제로 있던 과제명인지" 검증해
  할루시네이션이면 버림(신규 `_attach()` 헬퍼로 두 경로가 같은 검증 로직
  공유).
- `recommend_for_researcher()`의 반환 dict에 `closest_non_match` 필드
  추가(정상 케이스는 값 또는 None, "전문성 데이터 없음"/"후보 과제 없음"/
  "임베딩 실패"처럼 애초에 비교 자체를 못 한 케이스는 None — 비교할
  근거가 없으므로 억지로 만들지 않음).

**`pages/job_market.py`**: `recommendations`가 비어 있고 `closest_non_match`가
있으면, 실제 추천과는 시각적으로 구분되는(회색 배경 박스) "참여 가능한
과제를 찾지 못했습니다 + 그나마 가장 가까운 과제: OO(A/B 점수 배지) + 왜
안 맞는지 사유(이탤릭)" 블록을 보여준다. `closest_non_match`도 없으면
(비교 자체가 불가능했던 경우) 기존처럼 note 문구만 표시.

검증: (1) 추천 0건 + closest_non_match 있음 → 정상 표시, (2) LLM이
후보 목록에 없는 과제명을 closest_non_match로 냈을 때(할루시네이션) →
버려지고 None, (3) 실제 추천이 1건 이상 있을 때 → closest_non_match를
LLM이 실수로 채워도 무시하고 None으로 정규화 — 세 시나리오 모두 픽스처로
확인. `_render_result()`가 이 새 필드를 포함한 결과를 크래시 없이
렌더링하는지, 기존 개인별 검색(검색→추가→검색 실행) 흐름과 과제 단위
검색에 회귀가 없는지 Playwright로 재확인.

## 완료: JOB Market — 검색 결과 상단에 재배치 요약 지표 + 재배치 가능자 우선 정렬

사용자 요청: 검색 결과 상단에 "총 N명 중 M명 재배치 가능 예상(재배치율
X%), 대상 과제 K개" 같은 요약 지표를 보여주고, 재배치 가능한 사람은
위쪽에, 어려운 사람은 아래쪽에 정렬해 달라는 것.

**`pages/job_market.py`**:
- 신규 `_summary_stats(results)` — `results` dict(사람별 추천 결과)에서
  결정적으로 계산(추가 LLM 호출 없음): 대상 인원(`len(results)`),
  재배치 가능 인원(`recommendations`가 1개 이상인 사람 수), 재배치율(%),
  대상 과제 수(모든 사람의 `recommendations`에 등장한 `project_name`의
  distinct 합집합 — 여러 명이 같은 과제로 추천돼도 1개로 집계).
- 신규 `_summary_bar(results)` — 위 지표 3개를 상단에 타일 형태로 표시.
- `_render_result()`가 `results.items()`를 그대로 순회하던 것을,
  "추천 1개 이상 있음"을 우선 기준으로 `sorted()`(안정 정렬)해 재배치
  가능한 사람이 먼저 나오고, 그 안에서는 원래 순서(명단 순서)가 유지되게
  했다 — 재배치 어려운 사람(빈 추천, closest_non_match만 있거나 note만
  있는 경우)은 자동으로 하단에 모인다.
- history에서 과거 결과를 "보기"로 다시 열 때도 `_render_result()`를
  그대로 재사용하므로 저장된 이력에도 동일하게 요약 지표/정렬이 적용된다
  (지표를 report 저장 시점이 아니라 렌더링 시점에 매번 계산하므로, 이미
  저장된 옛 이력에도 별도 마이그레이션 없이 바로 적용됨).

검증: 4명(재배치 가능 2명 - 서로 다른 과제, 데이터 없음 1명,
closest_non_match만 있는 1명) 픽스처로 `_summary_stats`가 "총 4명 중
2명(50%), 대상 과제 2개"를 정확히 계산하는지, 정렬 결과가 재배치 가능
2명이 먼저(원래 순서 유지) 오고 나머지가 뒤따르는지 확인. Playwright로
실제 화면에서 요약 바가 렌더링되는지(개발 샌드박스는 임베딩/LLM 서버가
없어 0명/0%/0개로 나오지만 렌더링 자체와 계산 로직은 정상), 기존 흐름에
회귀가 없는지 재확인.

## 완료: 과제 직무/대상자 검증 — 현인원/채용 목표 인원수 혼동 수정 + 업로드 드래그앤드롭

사용자 요청 요약: 직무기술서에서 "'27년 채용 대상자 수"를 현재
인원수(현인원)로 잘못 읽어오는 버그. 원하는 동작은 (1) "현재
배정되어 있는 인원수"만 headcount로 읽고, (2) 채용 계획/목표 인원수는
버리지 말고 참고용으로 같이 보여달라는 것. 확인 결과 표(현인원 컬럼)와
서술형("현재 N명") 둘 다 현재 인원을 나타내며, 표를 우선하되 서술형과
비교(불일치 시 안내)하는 기존 `merge_roles()` 설계를 그대로 살리면
됨 — docx/이를 변환한 pdf 모두 동일하게 재현되어 원인이 포맷별 코드가
아니라 공용 추출 프롬프트에 있음을 확인.

**`services/jd_reconciliation.py`**:
- `_ROLE_EXTRACTION_SYSTEM_PROMPT`을 재작성 — "인원수 구분" 섹션을
  추가해 `headcount`("현재" 시점 실배정 인원 — 표의 "현인원"/"현원"/
  "현재 인원" 컬럼, 서술형의 "현재 N명")와 `hiring_target`(미래 채용
  계획/목표, 예: "'27년 채용 대상자 수" — "이건 headcount가
  아닙니다"라고 명시)을 뚜렷이 분리해서 추출하도록 지시. Output
  JSON에 `hiring_target` 필드 추가.
- `_extract_roles()` — 파싱 결과에 `hiring_target`(문자열, 숫자가
  아니어도 원문 표현 그대로 허용) 필드 추가.
- `merge_roles()` — `hiring_target`을 표/서술형 병합의 세 갈래
  전부(표+서술형 모두 있음/표만/서술형만)에서 함께 이어 감. 표+서술형
  모두 있을 때는 `t['hiring_target'] or n['hiring_target']`로 표를
  우선하되 표에 없으면 서술형 값을 채택. headcount 불일치 안내 로직은
  기존 그대로 유지(변경 없음).
- `build_report()` — 각 `role_rows` 항목에 `hiring_target` 필드 추가.

**`pages/jd_reconciliation.py`** `_role_card()`: `hiring_target`이
있을 때만 "채용 목표(참고용, 비교 대상 아님): ..." 문구를 회색
이탤릭체로, 문서 인원/실제 매칭 비교 줄과 분리된 별도 줄로 표시(비교
대상인 `document_count`/`matched_count`/`diff`와 시각적으로 섞이지
않도록).

**업로드 드래그앤드롭**: `dcc.Upload`는 원래부터 드래그앤드롭을
기본 지원하므로 기능 추가가 아니라 발견성(어포던스) 개선만 진행.
`jd-doc-upload`에 점선 테두리(`border: 2px dashed`), 업로드 아이콘,
"여기로 파일을 끌어다 놓거나 클릭해서 업로드" 안내 문구를 추가하고,
`style_active`/`style_reject`로 드래그 중/거부 시 테두리·배경색이
바뀌도록 설정. `assets/custom.css`에 `.jd-upload-dropzone:hover`
스타일 추가.

검증: `merge_roles()`/`build_report()`를 표 headcount=3 + 서술형
"현재 0명" + 표 hiring_target 픽스처로 직접 호출해 표 headcount가
채택되고 hiring_target이 role_rows까지 그대로 전달되는지 확인.
`_extract_roles()`를 `call_llm`을 모킹해 JSON 응답에서
`hiring_target`이 올바르게 파싱되는지 확인. `_role_card()`를 직접
렌더링해 `hiring_target`이 있을 때는 참고용 문구가, 없을 때는 문구
자체가 렌더링되지 않는지 확인. Playwright로 업로드 영역에 점선
테두리·아이콘·안내 문구가 실제 화면에 렌더링되는지, 콘솔 에러가
없는지 확인.

## 완료: JOB Market — 결과 카드에 연구원 본인의 보유 전문성 추가 표시

사용자 요청: 검색 결과가 매칭된 과제에 대한 설명만 보여줘서 신뢰성이
떨어지니, 그 연구원이 실제로 어떤 전문성을 갖고 있는지도 추천 사유와
함께 보여달라는 것.

**`services/job_market.py`** `recommend_for_researcher()`: 이미
내부에서 `expertise_profiles.get(researcher_id)`로 읽고 있던 프로필
원본을 반환값에 `'profile'` 키로 추가(조기 반환하는 4개 분기 — 데이터
없음/후보 없음/임베딩 실패/정상 — 전부에 포함, 데이터가 없을 때만
`None`). 추가 LLM 호출이나 임베딩 계산 없이 이미 로드해 둔 값을 그대로
얹기만 하므로 성능에 영향 없음.

**`pages/job_market.py`**: `components.detail_tabs.llm_summary_block`
(researcher_profile.py의 "전문성 요약(LLM)"과 동일한 컴포넌트 —
강점 분야/키워드는 배지로, 주요 역할·책임/전문지식 및 역량은 불릿
목록으로 렌더링)을 그대로 재사용해, 신규 `_profile_block(profile)`을
만들고 `_person_card()`에서 사람 이름/부서 줄과 추천 결과 사이에
"보유 전문성" 섹션으로 삽입. 프로필이 없으면 `llm_summary_block(None)`이
알아서 "분석 데이터 없음"을 보여주므로 별도 분기 불필요. history에
저장된 report에도 `profile`이 함께 저장되므로, 과거 이력을 "보기"로
다시 열 때도 `_render_result()`가 그대로 재사용돼 동일하게 표시된다
(저장 당시 `profile`이 없던 옛 이력은 `.get('profile')`이 `None`을
반환해 "분석 데이터 없음"으로 안전하게 처리).

검증: `_person_card()`를 프로필 있음/없음 두 픽스처로 직접 렌더링해
각각 "보유 전문성" 섹션에 강점 분야/키워드가 포함되는지, 프로필이
없을 때 "분석 데이터 없음"으로 대체되는지 확인. Playwright로 JOB
Market 페이지가 콘솔 에러 없이 로드되는지 확인.

## 완료: process_researcher_expertise.py / process_researcher_similarity.py max_tokens 상향

사용자 보고: JOB Market에서 쓸 데이터를 준비하려고 이 두 파이프라인을
돌리면 `[LLM 경고] content가 비어 있어 reasoning_content로 대체 사용
(finish_reason=length)`가 종종 뜬다는 것. 원인은 사내 LLM(thinkingcap)이
추론형 모델이라 최종 답변 전 사고 과정에도 토큰을 쓰는데, 요청
`max_tokens`(자동으로 `LLM2_MAX_TOKENS_MULTIPLIER`, 기본 3배가 곱해짐)를
사고 과정만으로 다 써버리면 `content`가 비어 응답이 잘리기 때문 —
`reasoning_content`로 대체는 되지만 그 안의 텍스트는 JSON 형식이 아닐
수 있어 이후 파싱이 실패하고, 그러면 캐시에 값이 안 남아 다음 실행 때
다시 시도돼야 한다.

자체 서버 운영 중이라 비용 부담이 없으므로 두 호출의 `max_tokens`를
상향:
- `process_researcher_expertise.py` `_analyze_researcher()`: 4000 ->
  6000(배수 적용 시 12000 -> 18000). 사람마다 과제/논문/특허 이력
  길이 편차가 커서 사고 과정도 그만큼 길어질 수 있음.
- `process_researcher_similarity.py` `_judge_pair()`: 1500 ->
  2500(배수 적용 시 4500 -> 7500).

검증: `ast.parse`로 두 파일 컴파일 확인. 실제 완화 효과는 사내 LLM
서버에 접근 가능한 환경에서 파이프라인을 재실행해 경고 빈도로
확인해야 함(이 개발 샌드박스에는 `llm_config.py`가 없어 재현 불가).

## 완료: LLM content-비어있음(finish_reason=length) 경고 발생 횟수 집계

사용자 요청: 위 max_tokens 상향으로 완전히 없앨 수는 없으니, 모듈을
실행했을 때 그 경고가 몇 번 발생했는지 결과에 표시해달라는 것.

**`pipeline/llm_client.py`**: 스레드 안전한 모듈 전역 카운터
`_truncation_count` 추가(`_stats_lock`으로 보호 — call_llm()이
`run_concurrent()`로 여러 스레드에서 동시에 호출되므로). `content`가
비어 `reasoning_content`로 대체하거나(그마저 없어 빈 문자열을
반환하거나) 하는 두 경고 분기 모두에서 `_record_truncation()`으로
증가. `get_truncation_count()`/`reset_truncation_count()`를 공개
함수로 노출 — reset은 배치 스크립트가 자기 실행분만 집계하도록
`process()` 시작 시 호출한다(이 모듈을 계속 import해 쓰는 장기 실행
서버가 아니라 스크립트 1회 실행 = 1번의 집계 단위이므로 이걸로 충분).

**`pipeline/researcher_fit.py`**: `llm_client`에서 두 함수를 추가로
import해 그대로 재노출 — `process_researcher_similarity.py`가 기존
`fit.call_llm`/`fit.run_concurrent`처럼 `fit.` 경유로 쓸 수 있게
(직접 `llm_client`를 import하지 않는 기존 관례 유지).

**`process_researcher_expertise.py`**: `process()` 시작에서
`reset_truncation_count()`, `연구원 보유 전문성 분석.json` 저장 로그
직후 `get_truncation_count()`가 0보다 크면 "[알림] LLM 응답 content가
비어(주로 finish_reason=length) 대체 처리된 횟수: N회" 출력(0이면
출력 안 함 — 정상 실행 로그에 잡음 추가하지 않음). 이 함수 안에서
`journal_authority.update_authority()`도 호출되므로(같은
`llm_client` 전역 카운터를 공유), 저널 조회 중 발생한 경고도 함께
집계된다.

**`process_researcher_similarity.py`**: `process()` 시작에서
`fit.reset_truncation_count()`, `researcher_similarity.html` 저장
로그 직후 동일한 형식으로 출력.

검증: `requests.post`를 모킹해 content가 비고 finish_reason=length인
응답을 반환하도록 하고 `call_llm()`을 호출 — 카운터가 1 증가하는지,
성공 응답(content 있음)에서는 증가하지 않는지, `reset_truncation_count()`
호출 후 0으로 돌아가는지 확인. `researcher_fit.py`를 통해서도 같은
카운터 함수에 접근되는지 확인. 4개 파일 모두 `ast.parse` 컴파일
확인(사내 LLM 서버가 없는 이 샌드박스에서는 실제 파이프라인 재실행으로
로그 출력까지는 확인 불가).

## 완료: "연구원 목록" → "연구원 명단" 리네이밍 + 컬럼/필터/검색·엑셀 다운로드 재구성

사용자 요청 4건: (1) 탭 이름 변경 + 컬럼에 과제(org_code) 추가(부서~직급
사이)/리더십·TOEIC 제거/최종학위→학력(최종)/전공 추가(학력~평가 사이)
(2) 필터에 과제 추가 + 부서→과제 캐스케이딩 (3) 필터 우측에 검색
아이콘 — 눌러야 필터 적용 (4) 검색 아이콘 옆 엑셀 아이콘 — 필터 대상
프로필 다운로드. 사전 확인 4문항에 대한 사용자 답변: 과제 필터는 이
페이지 자체 데이터(researchers.csv)로만 구성, 엑셀은
`researcher_profile_export.build_profile_workbook()` 재사용, 다운로드
범위는 "지금 화면에 실제로 보이는 행", 필터 초기화 시 테이블도 전체
목록으로 복귀.

**`pages/researcher_list.py`**:
- `dash.register_page`의 name/title과 페이지 H5 제목을 "연구원
  명단"으로 변경(`app.py`의 nav 링크 라벨도 동일하게 변경).
- `_build_summary_df()`: 리더십(`lea`)/TOEIC(`cert`) 관련 읽기·계산
  블록과 `_LEA_DIMS`를 전부 제거(컬럼이 없어지면 죽은 코드가 되므로).
  `과제` 컬럼을 `researchers.csv`의 `org_code`에서 추가. 기존
  "최종학위" 계산 블록에서 최고 학위 행을 그대로 재사용해 `학력(최종)`
  (학위명만)과 `전공`(그 행의 `major`)을 분리해서 담음. 최종 컬럼
  순서: 이름/부서/과제/직급/성별/학력(최종)/전공/'24~'26평가/인센티브/
  논문(전체)/논문(3년)/평균IF/특허(출원)/특허(등록)/수상.
- 신규 `_project_options(department=None)`: `researchers.csv`만
  읽어(무거운 `_build_summary_df()` 전체 재계산 없이) 부서 선택 시 그
  부서 소속 연구원들의 org_code만 남기는 캐스케이딩 옵션을 만든다 —
  JOB Market이 쓰는 `project_confl_address.csv` 카탈로그와는 별개(이
  페이지의 '부서' 표기가 그쪽 dep_name과 일치한다는 보장이 없어 자기
  완결적으로 둠, 사용자 확정 (a)).
- 필터 카드에 `과제` 드롭다운 추가, 그 옆에 검색(`bi-search`)/엑셀
  (`bi-file-earmark-excel`) 아이콘 버튼을 `dbc.ButtonGroup`으로 배치.
  `dcc.Download(id='researcher-list-excel-download')` 추가.
- DataTable의 `data`를 더 이상 `researcher_id`를 드롭하지 않고 그대로
  둔다(`columns` 목록에는 여전히 안 넣어 화면엔 안 보임) — 이러면
  `derived_virtual_data`(네이티브 필터/정렬 반영된 실제 표시 행)에도
  `researcher_id`가 숨은 필드로 남아, 엑셀 다운로드와 행 클릭 이동
  콜백이 이름으로 역조회할 필요 없이 바로 꺼내 쓸 수 있다(동명이인
  버그도 부수적으로 해결).
- 콜백 재구성: `update_project_options`(부서→과제 캐스케이딩),
  `update_table`은 드롭다운을 전부 `State`로 바꾸고 `list-search-btn`/
  `clear-filters-btn`의 `n_clicks`만 `Input`으로 받아 `dash.ctx.triggered_id`로
  분기(초기화 버튼이면 필터값과 무관하게 항상 전체 목록 반환),
  `clear_filters`는 드롭다운 5개 값만 비움(필터 5개로 늘어 Output도
  5개로 확장), 신규 `download_excel`(엑셀 버튼 클릭 시
  `derived_virtual_data`에서 `researcher_id`를 모아
  `build_profile_workbook()` 호출 후 `dcc.send_bytes`),
  `navigate_to_profile`은 `derived_virtual_data`를 `Input`에서
  `State`로 바꾸고(행 클릭 시에만 반응하도록) 이름 재조회 대신 숨은
  `researcher_id` 필드를 직접 사용하도록 단순화.

검증: `_build_summary_df()`/`_project_options()`를 직접 호출해 컬럼
구성과 부서→과제 캐스케이딩 결과 확인. Playwright로 실제 화면에서
(1) nav 라벨/제목 변경 (2) 헤더에 과제/학력(최종)/전공 존재, 리더십/
TOEIC 없음 (3) 부서 선택 시 과제 옵션이 좁혀짐 (4) 드롭다운만 바꿔서는
표가 안 바뀌다가 검색 버튼을 눌러야 바뀜 (5) 필터 초기화 시 표가 전체
목록으로 복귀 (6) 엑셀 다운로드 버튼 클릭 시 실제 파일 다운로드 발생
(7) 행 클릭 시 `/researcher-profile?id=...`로 정상 이동 — 을 모두
확인. 필터 드롭다운들이 화면에서 세로로 쌓여 보이는 현상은 이
샌드박스의 프록시가 Bootstrap CDN을 차단(403)해 그리드 CSS 자체가
로드되지 않는 환경 한정 아티팩트로 확인(기존 JOB Market 페이지도
동일하게 재현됨 — `col-md-*` 클래스 자체는 정상 적용되어 있어 실제
배포 환경에서는 문제 없음).

## 완료: 연구원 명단/엑셀 다운로드에 "직책"(team_refer.csv assignment_name) 추가

사용자 요청 2건: (1) 연구원 명단 컬럼에 직책 추가(직급~성별 사이,
team_refer.csv의 assignment_name 매핑, 없으면 "-") (2) 프로필 엑셀
다운로드에도 CL/년차~과제수행이력 사이에 직책 추가. 확인 결과 2번은
`pages/researcher_list.py`가 아니라 공용 모듈
`services/researcher_profile_export.py`(`build_profile_workbook()`)의
`_COLUMNS`를 가리키는 것이었고, 이 모듈은 연구원 명단 탭의 엑셀
다운로드뿐 아니라 "보유 전문성" 탭 AI 검색 결과 엑셀 다운로드
(`components/nl_query_bar.py`)에도 공유되는 함수라 두 화면 모두에
반영되는 게 맞는지 확인 — 사용자가 "둘 다 적용되는게 맞다"고 확정.

`team_refer.csv`는 조직장급 9명(소장/본부장/PL/파트장)만 `researcher_id`
당 1행씩 등록돼 있고(중복 없음 확인) 나머지는 매핑이 없어 "-"로
표기된다.

**`pages/researcher_list.py`** `_build_summary_df()`: `team_refer`를
추가로 읽어 `researcher_id -> assignment_name` dict(`title_by_id`)를
만들고, rows 딕셔너리에 `직책` 키를 `직급`과 `성별` 사이에 추가
(`title_by_id.get(rid) or '-'`).

**`services/researcher_profile_export.py`**: `_load_tables()`/
`_researcher_row_context()`에 `team_refer` 추가, 신규
`_col_position_title(_rid, rows)`(`team_refer` 행이 있으면
`assignment_name`, 없으면 "-")를 `_COLUMNS`의 `'CL/년차'`와
`'과제수행이력'` 사이에 삽입.

검증: `_build_summary_df()`를 직접 호출해 직책 컬럼 값(PL/파트장/소장/
"-")과 컬럼 순서(직급→직책→성별) 확인. `build_profile_workbook()`으로
실제 xlsx를 만들어 openpyxl로 다시 열어 헤더 순서(CL/년차→직책→
과제수행이력)와 셀 값을 검증.

## 완료: AI 검색 답변/초기화 + 전문성 MAP 줌 버그 수정 + 옵시디언식 관계 그래프

사용자 요청 3건, 확인 문답으로 범위 확정:
1. AI 검색 결과에 "왜 이렇게 찾았는지" LLM 설명을 추가(표에 실제로 있는
   내용만 근거로, 새 판단/환각 금지 — 사용자 확정 "예").
2. 검색창/답변/명단을 한 번에 비우는 "초기화" 버튼 추가(검색어 텍스트도
   포함해 완전 초기화 — 사용자 확정).
3. 전문성 MAP에서 확대할 때 화면이 리셋되는 버그 수정 + UMAP 산점도를
   "옵시디언 방식"(힘-기반 노드-링크 그래프)으로도 볼 수 있게, 버튼/탭
   전환으로 두 방식을 다 유지(사용자 확정: `researcher_similarity.json`
   기준 엣지, 라이브러리 추가 OK, 완전 교체 아니라 토글).

**1) AI 검색 답변 — `services/nl_query.py`**: 기존 3개 intent
(find_researchers_by_expertise/find_similar_researchers/open_data_query)
는 그대로 두고, 공용 진입점 `answer_question()`에서 조회가 끝난 뒤
한 번 더 LLM을 호출해(`_generate_answer_summary()`) 결과를 설명하는
텍스트를 `result['answer']`에 담는다. 새 `_ANSWER_SYSTEM_PROMPT`가
"표에 실제로 있는 내용만 근거로 쓰고 새 사실을 만들어내지 말라"고 강하게
제약 — 이 모듈의 기존 원칙("LLM은 판단하지 않고 조회만")을 깨지 않으면서
"이미 나온 결과를 설명"하는 역할만 추가한 것. rows가 비었거나 intent가
error/unsupported면 answer를 생성하지 않는다(설명할 게 없으므로). 표
데이터는 최대 20행만 프롬프트에 담고(`_ANSWER_MAX_ROWS`), 나머지는
"총 N건 중 20건만 보여줬다"는 문구로 대체.

**2) 초기화 버튼 — `components/nl_query_bar.py`**: 입력창 옆에
"초기화" 버튼 추가. `_reset_query()` 콜백이 검색어(`nl-query-input`)와
5개 Store(`full-result`/`filters`/`sort`/`expanded`/`selected`)를 전부
빈 값으로 되돌린다. `_render_nl_query_store()`의 `if not full_result`
분기를 `dash.no_update` 대신 `None`(빈 children)을 반환하도록 고쳐서 —
안 그러면 초기화해도 화면에 이전 결과가 그대로 남는다. 결과 표 위에
`_answer_block()`으로 `full_result.get('answer')`를 눈에 띄게(파란
Alert) 표시.

**3-a) 줌 리셋 버그 — `pages/researcher_similarity_map.py`**: 원인은
Plotly 그래프에 `uirevision`이 없었던 것. 기존엔 `_toggle_small_tier_by_zoom`
콜백이 relayoutData에서 읽은 확대 범위를 매번 수동으로 다시 그려
리셋을 막고 있었는데, 빠르게 연속으로 확대하면 서버 왕복 지연으로
뒤늦게 도착한 relayoutData가 이미 더 확대된 화면을 예전 범위로 덮어써
순간적으로 "리셋되는 것처럼" 보이는 레이스컨디션이 있었다. 신규
`_uirevision_for(rid)`(검색 대상 rid가 바뀔 때만 값이 달라짐)를 초기
figure 생성 시 `uirevision`으로 설정 — Plotly가 uirevision이 같은 한
사용자의 현재 확대/이동을 새 figure prop보다 우선해서 유지해 준다(공식
권장 방식). `_toggle_small_tier_by_zoom`에서 수동 range 재적용 로직을
전부 제거(트레이스 visible/hoverinfo 토글만 남김). 반대로
`_highlight_search_result`(검색으로 특정 지점에 의도적으로
확대·포커스하는 콜백)는 `uirevision`을 `selected_rid` 기준으로
명시적으로 바꿔서, 그 "의도된" 확대가 이전 수동 확대 상태에 가려지지
않고 실제로 반영되게 했다.

**3-b) 옵시디언식 관계 그래프**: `requirements.txt`에
`dash-cytoscape>=1.0.2` 추가.
- **`services/similarity_map.py`** 신규 `build_similarity_graph_elements()`:
  `researcher_similarity.json`(이미 배치로 판정된 연구원↔연구원 유사도)을
  dash_cytoscape elements(노드=연구원, 엣지=유사도 쌍)로 변환. 각
  연구원의 top-K 목록은 방향성이 있어(A 목록에 B가 있어도 B 목록엔
  A가 없을 수 있음) A-B/B-A를 정렬된 튜플로 묶어 한 번만 엣지로 만들고
  (process_researcher_similarity.py의 `_pair_key()`와 동일한 발상),
  양쪽 score가 다르면 더 높은 쪽을 채택. 노드에는 부서별 팔레트
  인덱스를 클래스(`dept-N`)로 붙이고, `similarity_graph_department_classes()`가
  그 클래스에 맞는 cytoscape 스타일시트를 만든다.
- **`pages/researcher_similarity_map.py`**: 전문성 MAP 탭 상단에
  "UMAP 지도"/"관계 그래프" 버튼 토글(`_subview_toggle()`) 추가. 기존
  탭 콘텐츠를 `_umap_subview_content()`로 그대로 옮기고, 신규
  `_graph_subview_content()`가 `cyto.Cytoscape`(레이아웃 `cose` — 별도
  확장 없이 기본 제공되는 힘-기반 레이아웃, 옵시디언 그래프 뷰와 같은
  "떠다니는" 느낌)를 렌더링. 엣지 두께/색은 cytoscape 스타일시트의
  `mapData(score, ...)`와 판정 레벨(상/중/하)별 클래스로 표현. 노드
  클릭 시 UMAP 점 클릭과 동일하게 '연구원' 탭으로 이동하도록
  `_go_to_researcher_card_from_graph()` 콜백 추가(기존
  `_go_to_researcher_card`와 입력 컴포넌트만 다름). 서브뷰는 "전문성
  MAP" 탭을 벗어났다 돌아오면 항상 UMAP 기본값으로 리셋(이 화면의
  기존 관례와 동일).

검증: `_generate_answer_summary()`/`answer_question()`을 `call_llm`
모킹으로 직접 호출해 답변 생성/스킵 조건 확인. 초기화 버튼은 Playwright로
실제 화면에서 입력창·결과 영역이 모두 비는지 확인. 줌 버그/관계 그래프는
연구원 12명 분량의 임시 픽스처(`연구원 보유 전문성 분석.json`/
`embedding_cache.json`/`researcher_similarity.json` — 테스트 후
원본으로 복원, 이 파일들은 전부 `.gitignore` 대상이라 커밋에는 영향
없음)로 실제 서버를 띄워 Playwright로: uirevision 값 확인, 마우스 휠로
확대 후 xaxis range가 리셋되지 않고 유지되는지 확인, 토글로 관계
그래프 전환 시 노드 12개가 정상 렌더링되는지, 다시 UMAP으로 돌아오는지,
그래프 노드를 tap하면 '연구원' 탭으로 이동하는지(cytoscape 인스턴스에
직접 tap 이벤트를 발생시켜 확인 — cose 레이아웃이 매번 다른 좌표를
계산해 마우스 좌표 클릭은 재현성이 없었음) 확인. 콘솔 에러 없음.

## 완료: python app.py 단독 실행 시 연결 끊김 완화(threaded=True)

사용자 보고: `python app.py`로 띄워두면 종종 연결이 끊긴다는 것. 원인은
`app.run(host='0.0.0.0', port=port, debug=False)`에 `threaded=True`가
없어 Werkzeug 개발 서버가 기본값(싱글 스레드)으로 동작했기 때문 —
UMAP 계산(콜드 스타트 시 numba JIT 포함 최대 30초 가까이 걸림, 오늘
테스트 중 직접 확인), LLM 호출(최대 300초 타임아웃), 전문성 MAP의
0.55초 주기 깜빡임 폴링처럼 오래 걸리거나 잦은 요청 하나가 서버
전체를 붙잡아 다른 요청이 밀리다 타임아웃 나는 구조였다.

**개인 데스크탑에서 소수 인원 베타테스트하는 용도**로 무엇이 적절한지
확인 — gunicorn(이미 `server = app.server`로 진입점은 준비돼 있음)은
Windows에서 아예 동작하지 않고(fork 기반) 이 규모엔 멀티 워커 관리가
과함, waitress는 Windows도 되지만 새 의존성이 필요함. 결론:
`app.run(..., threaded=True)` — 의존성 추가나 OS 제약 없이
`python app.py` 그대로 쓰면서 동시 요청을 스레드로 처리하게 하는 게
이 용도엔 충분하다고 판단, 사용자 동의로 적용.

**`app.py`**: `if __name__ == '__main__':` 블록의 `app.run()` 호출에
`threaded=True` 추가.

검증: `ast.parse` 컴파일 확인, 서버 재기동 후 정상 구동 확인. 동시
요청이 실제로 안 막히는지는 페이지 최초 GET(SPA 껍데기만 반환, 가벼움)
2개를 동시에 보내는 걸로는 유의미하게 검증되지 않았다(둘 다 즉시
응답) — 실제 무거운 연산은 페이지 로드 후 클라이언트가 보내는
`_dash-update-component` 콜백 요청에서 일어나는데, 그 요청을 재현하려면
콜백별 정확한 JSON payload가 필요해 이번엔 별도 부하테스트까지는
하지 않았다. `threaded=True`는 Flask/Werkzeug의 표준 옵션이라 동작
자체는 문서화된 대로 신뢰할 수 있지만, 완전한 동시성 재현 테스트는
못 했다는 점을 사용자에게 그대로 전달함.

## 완료: 관리자/유저 구분 없이 '조직별 비교'/'과제 직무/대상자 검증' 임시 숨김

사용자 요청: 관리자/유저를 구분할 수 있으면 두 기능(조직별 비교, 과제
직무/대상자 검증)을 유저에게만 숨기고, 구분이 어려우면 일단 전체
숨겼다가 나중에 보완해서 다시 열고 싶다는 것. 코드 전체를 확인한 결과
로그인/세션/권한 체계가 전혀 없어(auth/login/session 관련 코드 0건)
"관리자/유저 구분" 자체가 불가능한 상태 — 사용자가 제시한 두 번째
조건(전체 숨김)을 적용.

**`pages/org_comparison.py`**: `path='/'`(이 페이지가 원래 앱의 루트
경로)는 그대로 두고, 최상단에 `_FEATURE_HIDDEN = True` 플래그 추가.
`layout()`이 플래그가 켜져 있으면 실제 데이터 조회 없이
`dcc.Location(href='/researcher-profile', ...)`을 반환해 루트 진입 시
'연구원 프로필' 탭으로 클라이언트 사이드 리다이렉트한다. (참고: 처음엔
`dash.register_page(..., redirect_from=['/'])`를 다른 페이지에 걸어
루트를 넘기려 했으나, Dash가 루트를 프레임워크 자체 인덱스 라우트로
이미 예약해 둬서 Flask 라우트 충돌로 서버가 아예 기동하지 않았다 —
그래서 각 페이지가 자기 자신을 리다이렉트하는 방식으로 처리.)

**`pages/jd_reconciliation.py`**: 마찬가지로 `_FEATURE_HIDDEN = True`
추가, `layout()`이 플래그가 켜져 있으면 실제 업로드/검증 UI 대신
"이 기능은 현재 준비 중입니다." 안내만 보여준다(URL을 직접 알고
들어와도 기능 자체는 동작하지 않음).

**`app.py`**: 네비게이션 바에서 '조직별 비교'/'과제 직무/대상자 검증'
`dbc.NavItem`을 제거(발견 경로 차단). 재오픈 방법: 두 페이지 파일의
`_FEATURE_HIDDEN`을 `False`로 바꾸고, 이 커밋에서 지운 두 `dbc.NavItem`
블록을 git으로 복원하면 된다.

검증: Playwright로 실제 서버에서 (1) `/` 진입 시
`/researcher-profile`로 리다이렉트되는지 (2) 네비게이션 바에 4개
링크(연구원 프로필/보유 전문성/연구원 명단/JOB Market)만 남았는지
(3) `/jd-reconciliation`을 URL로 직접 열어도 "준비 중" 안내만 뜨고
실제 폼은 안 보이는지 확인.

## 완료: 좌측 상단 "의견 제출하기" 버튼 + 누적 CSV 저장

사용자 요청: 관리자/유저 구분 대신, 좌측 상단 "연구원 대시보드" 옆에
밝은 색 버튼으로 "기능 관련 수정/추가/보완/기타 의견 제출하기"를
추가해 베타테스터 의견을 받고 싶다는 것. 확인 문답으로 확정된 사항:
저장 위치는 `data/processed/` 하위(다른 기능들의 이력 저장 위치와
동일한 관례), 제출마다 새 파일이 아니라 **파일 하나에 누적**, 작성자는
**선택 입력**, 파일명은 사용자가 재확인한 표기 그대로 `request_fucntion`
(오타로 보이지만 사용자가 명시적으로 확정).

**형식은 CSV로 추천·채택**: 제출일시/구분/작성자/내용처럼 여러 항목을
구조적으로 담아야 하고, 이 프로젝트 전반에서 이미 엑셀을 검토 도구로
쓰고 있어 나중에 엑셀로 열어 정렬·필터링하며 보기 편하다. txt는 여러
줄짜리 의견이 여러 건 쌓이면 항목 구분이 애매해질 수 있어 제외.

**`services/feedback.py`**(신규): `FEEDBACK_DIR = data/processed/feedback`,
`FEEDBACK_PATH = .../request_fucntion.csv`. `submit_feedback(category,
message, author='')` — 카테고리가 4개(수정/추가/보완/기타) 밖이면
"기타"로 폴백, 내용이 비어 있으면 `ValueError`(호출부가 그대로 화면에
안내). `csv.DictWriter`로 파일이 없으면 헤더부터 쓰고, 있으면 한 줄
추가(append) — 매번 전체를 다시 쓰는 `services/comments.py` 방식과
달리 로그성 데이터라 append가 더 알맞다고 판단. `app.py`가
`threaded=True`라 여러 사용자가 동시에 제출할 수 있어, 프로세스 내
`threading.Lock()`으로 파일 쓰기가 서로 섞이지 않게 함(멀티프로세스
운영은 아직 아니라서 파일 락까지는 필요 없다고 판단).

**`components/feedback_modal.py`**(신규, `nl_query_bar.py`와 동일한
패턴 — app.py가 `dash.Dash()` 생성 후 명시적으로 import해야 모듈
콜백이 등록됨): `render()`가 버튼 + `dbc.Modal`(구분 라디오/내용
Textarea/작성자 선택 Input)을 반환. 콜백 하나가 열기/취소/제출 3개
버튼을 `dash.ctx.triggered_id`로 분기 — 열 때 필드 초기화, 취소 시
닫기, 제출 시 내용 비어있으면 경고, 성공하면 모달은 열어둔 채 필드만
비우고 초록색 성공 메시지 표시(제출 확인을 사용자가 보게 하려고 자동
닫기 대신 이렇게 함).

**버튼 색상 관련 이슈 발견·수정**: 처음엔 `dbc.Button`을 색 지정 없이
(기본값 `color='primary'`) 만들고 인라인 `style`로 배경색을 주황으로
덮어썼는데, 실제로는 계속 이 앱의 기본 파란색으로 보였다 — 원인은
`assets/custom.css`의 `.btn-primary { background-color: ... !important;
}` 규칙이 인라인 style보다 우선 적용되기 때문. `!important`가 없는
Bootstrap 기본 `color='warning'`(밝은 노랑/주황 계열)로 바꿔 이 충돌을
피하고, 텍스트 색·굵기만 인라인 style로 남겼다.

**`app.py`**: `feedback_modal` import 추가(nl_query_bar와 같은 줄),
네비게이션 바 상단 Row에서 `연구원 대시보드` 브랜드 타이틀 바로 옆
Col로 버튼 배치(버튼 자체에 `className='ms-3'`로 간격).

검증: `submit_feedback()`을 직접 호출해 CSV 헤더/여러 줄 메시지(개행
포함) 왕복, 빈 내용 시 `ValueError`, 잘못된 카테고리 폴백 확인.
Playwright로 실제 서버에서 버튼 클릭 → 모달 오픈 → 빈 제출 시 경고 →
정상 제출 시 성공 메시지 → 취소로 닫힘까지 전체 흐름 확인, 실제로
`request_fucntion.csv`에 제출한 내용이 그대로 기록됐는지 확인. 버튼
배경색 자체가 브라우저에서 노란색으로 보이는지는 이 샌드박스의
Bootstrap CDN 차단(기존에 여러 번 확인된 프록시 아티팩트) 때문에
직접 확인은 못 했지만, DOM에 `btn-warning` 클래스가 정확히 붙고
`custom.css`에 이를 덮어쓰는 규칙이 없음을 확인해 실제 배포
환경에서는 정상적으로 밝은 노랑으로 보일 것으로 판단.

## 완료: 엑셀 다운로드에 "보유 전문성"(LLM) 선택 컬럼 추가 + 보유 전문성 탭 기본값 변경

사용자 요청 두 가지: (1) AI 검색/연구원 명단 엑셀 다운로드에 LLM이
산출한 "연구원 보유 전문성 분석.json" 내용까지 받을 수 있게 하되,
선택(옵트인) 가능하도록. (2) "보유 전문성" 페이지 진입 시 첫 화면을
현재의 "전문성 MAP"에서 "연구원" 탭으로 변경. 확인 문답으로 확정된
사항: 전문성 4개 필드(강점 분야/강점 키워드/주요 역할·책임/전문지식 및
역량) 전부 포함, 체크박스는 **기본 해제(미포함) 상태**, 리포트 카드의
"📍 유사맵" 아이콘이 여는 `?highlight_researcher=...` 딥링크는 기존처럼
"전문성 MAP" 탭으로 강제 랜딩하는 것을 그대로 유지(새 기본값은 일반
진입에만 적용).

**`services/researcher_profile_export.py`**: `build_profile_workbook()`은
`nl_query_bar.py`(AI 검색)와 `researcher_list.py`(연구원 명단) 두 곳에서만
쓰이는 공용 함수라, 여기 하나만 고치면 두 화면 모두에 반영된다.
- `_load_tables()`에 `'expertise_profiles': data_store.read_expertise_profiles()`
  추가(다른 테이블과 달리 DataFrame이 아니라 `researcher_id -> dict`).
- `_researcher_row_context()`에 `'expertise_profile': tables['expertise_profiles'].get(researcher_id)`
  추가.
- `_expertise_field(field)` 신규 — 필드 하나(strength_fields 등)를 한
  셀에 줄바꿈으로 나열하는 컬럼 함수를 만드는 팩토리. 처음엔 4개 필드를
  `_col_expertise()` 하나로 합쳐 한 셀에 넣었으나, "4개 항목을 컬럼으로
  나눠 달라(보유전문성(강점 분야), 보유전문성(강점 키워드) 형식)"는
  후속 요청으로 `_EXPERTISE_COLUMNS`(4개 (헤더, 함수) 튜플 리스트 —
  `components/detail_tabs.py`의 `llm_summary_block()`과 동일한 필드/순서)로
  분리.
- `build_profile_workbook(researcher_ids, include_expertise=False)` —
  `include_expertise=True`일 때만 `_COLUMNS`의 로컬 사본에
  `_EXPERTISE_COLUMNS` 4개(각 너비 26)를 통째로 덧붙인다(모듈 상수
  `_COLUMNS` 자체는 건드리지 않음).
- 겸사겸사 발견한 기존 버그 수정: `widths` 리스트가 11개뿐이라
  `_COLUMNS`(이번 세션에 `직책`이 추가되며 12개가 됨)와 개수가 안 맞아
  마지막 컬럼(핵심이력)에 명시적 너비가 적용되지 않고 있었음 — `직책`
  칸에 너비 10을 추가해 `_COLUMN_WIDTHS`(12개)로 상수화.

**`components/nl_query_bar.py`**: 엑셀 버튼 옆에 `dbc.Checklist`(스위치형,
id `nl-query-excel-expertise-check`, 기본값 `[]`=미포함) 추가, 버튼과
같은 `_update_excel_button` 콜백에서 결과가 사람 데이터일 때만 같이
보이도록(`style` 출력 하나 추가) 동기화. `_download_excel` 콜백에
`State('nl-query-excel-expertise-check', 'value')`를 추가해
`include_expertise='include' in (value or [])`로 변환해 전달.

**`pages/researcher_list.py`**: 엑셀 버튼이 있는 `dbc.ButtonGroup` 아래
같은 컬럼(md=2)에 동일한 스위치형 체크박스(id
`list-excel-expertise-check`, 기본 미포함) 추가. `download_excel` 콜백에
`State`로 추가해 동일하게 `include_expertise`로 변환 후
`build_profile_workbook()`에 전달.

**`pages/researcher_similarity_map.py`**: `layout()`의 기본 진입 탭을
`highlight_researcher` 유무로 분기 — 없으면 `'researcher'`(신규 기본값),
있으면 기존처럼 `'map'`. `expertise-tab-content`의 초기 `children`도
탭 클릭 콜백(`_render_expertise_tab`)이 생성하는 것과 동일한 내용이
되도록 함께 분기(`researcher`면 `_iframe_tab('researcher')`, `map`이면
기존 `_map_tab_content(...)`) — 그렇지 않으면 활성 탭 표시와 실제 렌더된
내용이 어긋난다.

검증: (1) `_col_expertise()`를 목(mock) 프로필로 직접 호출해 4개 필드
레이블·순서·불릿 형식 확인, 프로필 없을 때 `'-'` 확인. (2)
`_load_tables()`를 목 데이터로 몬키패치해 `build_profile_workbook()`을
`include_expertise=True/False` 양쪽으로 실행 — 헤더 개수(12/13)·순서,
"보유 전문성" 셀 내용, 컬럼 너비(마지막 40) openpyxl로 열어서 확인.
(3) `nl_query_bar.render()`를 직접 호출해 새 체크박스 컴포넌트가
레이아웃 트리에 포함되는지 확인. (4)
`pages/researcher_similarity_map.layout()`을 `highlight_researcher` 유무
양쪽으로 직접 호출해 `active_tab`이 각각 `'researcher'`/`'map'`으로
갈리고, 초기 콘텐츠가 탭 전환 콜백과 같은 종류(iframe/지도)로 렌더되는지
확인(이 세션 컨테이너에는 `data/processed/`에 실제 파이프라인 산출물이
없어 iframe 쪽은 "리포트가 없습니다" 안내로 정상 폴백되는 것까지 확인 —
실제 데이터가 있는 환경에서는 그 자리에 리포트가 렌더된다). Playwright
브라우저 구동 테스트는 이번 세션 컨테이너에 `data/processed/`가
비어 있어(파이프라인 미실행) 실질적인 화면 검증이 어려워 생략 —
위 함수 단위 검증으로 로직을 대신 확인했다.

### 후속: "보유기술"(tech_ownership.csv) 컬럼 추가

연구원 프로필 화면(`components/detail_tabs.py`의 `owned_expertise_block()`
우측 "보유기술" 표 — `_tech_ownership_table()`, `tech_ownership.csv`의
`tech_1~5`/`lv_1~5`/`portion_1~5`)을 엑셀에도 넣어 달라는 요청. 이번
것은 LLM 산출물이 아니라 `핵심이력`/`학력` 등과 같은 성격의 원천 데이터라,
앞서 만든 "보유 전문성 포함" 체크박스(LLM 4필드 전용)와 묶지 않고
`_COLUMNS`에 **항상 포함**되는 일반 컬럼으로 추가했다(직책/과제수행이력
옆에 있는 핵심이력 바로 뒤, 헤더 "보유기술").

- `_load_tables()`/`_researcher_row_context()`에 `tech_ownership`
  (`data_store.read_processed('tech_ownership')`) 추가.
- `_col_tech_ownership(_rid, rows)` 신규 — 화면의 `_tech_ownership_table()`과
  동일하게 5개 슬롯(`tech_i`/`lv_i`/`portion_i`)을 돌며 이름이 있는
  슬롯만 `"전문분야 (Lv N, 보유율 M%)"` 형태로 줄바꿈 나열, 슬롯이
  하나도 없으면 `'-'`.
- `_COLUMNS`에 `('보유기술', _col_tech_ownership)`을 `핵심이력` 다음에
  추가(기본 컬럼이 12개→13개가 되며 `_COLUMN_WIDTHS`에도 너비 30 추가).

검증: `_load_tables()`를 목 데이터(2개 슬롯만 채운 tech_ownership 행)로
몬키패치해 `build_profile_workbook()`을 `include_expertise=True/False`
양쪽으로 실행 — 헤더 개수(13/17)·순서, "보유기술" 셀에 두 슬롯이
줄바꿈으로 정확히 나열되고 빈 슬롯은 건너뛰는지, 컬럼 너비까지 openpyxl로
확인.

### 후속: "특허 실적"/"논문 실적" 선택 컬럼 추가

"특허/논문도 엑셀에 선택적으로 다운받을 수 있게 해줘" 요청. 특허/논문은
연구원마다 여러 건이 쌓이는 실적 데이터라 항상 켜두면 셀이 매우 길어질
수 있어, 보유 전문성과 같은 옵트인(기본 해제) 방식을 그대로 따르되
"특허 포함"/"논문 포함"을 별도 체크박스로 분리했다(하나로 묶으면
특허만 필요하거나 논문만 필요한 경우를 못 고르게 되므로).

**`services/researcher_profile_export.py`**:
- `components.timeline_data`에서 `dedupe_patents`/`is_registered`를
  가져와 재사용 — 화면(`patents_tab()`)과 동일하게 국가별로 중복
  출원된 같은 특허(`application_id` 동일)를 한 행으로 합친다(등록국이
  하나라도 있으면 상태를 "등록"으로, 국가는 콤마로 병합).
- `_df_for(df, researcher_id)` 신규(`_rows_for()`의 DataFrame 버전) —
  `dedupe_patents()`가 DataFrame을 받아야 해서 특허만 리스트가 아니라
  필터링된 DataFrame 그대로 컨텍스트에 넣는다.
- `_load_tables()`/`_researcher_row_context()`에 `patents`(DataFrame,
  `patents_df` 키로 저장)·`publications`(리스트) 추가.
- `_col_patents(_rid, rows)` 신규 — dedupe 후 출원일 내림차순으로
  `"출원일 : 발명명칭 (상태, 대표발명자, 지분율%, 등급(전략출원 등))"`을
  한 셀에 줄바꿈 나열.
- `_col_publications(_rid, rows)` 신규 — `pub_date`(없으면 `pub_year`)
  내림차순으로 `"발표일 : 제목 (게재처, 순위/총수, 기여도%, 교신)"`을
  한 셀에 줄바꿈 나열.
- `_PATENT_COLUMNS`/`_PUBLICATION_COLUMNS`(각각 컬럼 1개)를
  `_EXPERTISE_COLUMNS`와 같은 패턴으로 정의.
- `build_profile_workbook(researcher_ids, include_expertise=False,
  include_patents=False, include_publications=False)` — 세 플래그가
  각각 독립적으로 해당 옵트인 컬럼 그룹을 이 순서(특허 → 논문 → 전문성)로
  덧붙인다 — 전문성 그룹을 맨 뒤에 고정한 이유는 아래 후속 참고.

**`components/nl_query_bar.py`/`pages/researcher_list.py`**: 기존
"보유 전문성 포함" 단일 체크박스를 3개 옵션짜리 `dbc.Checklist`(값
`expertise`/`patents`/`publications`, 전부 기본 해제)로 확장 —
id를 `*-excel-expertise-check`에서 `*-excel-options-check`로 변경(아직
릴리즈되지 않은 최근 기능이라 하위호환 부담 없음). 각 다운로드 콜백은
선택된 값 리스트에서 `'expertise'/'patents'/'publications'`가 있는지
판별해 `build_profile_workbook()`의 세 플래그로 그대로 전달.

검증: `_load_tables()`를 목 데이터(같은 `application_id`로 국가만
다른 특허 2건 + 다른 특허 1건, 논문 1건)로 몬키패치해
`build_profile_workbook(include_patents=True, include_publications=True)`
실행 — 헤더에 "특허 실적"/"논문 실적" 추가, 특허 셀에서 두 국가 출원이
한 줄로 합쳐지고(등록국 우선으로 상태 "등록") 서로 다른 특허는 별도
줄로 유지되는지, 논문 셀 형식(게재처/순위/기여도/교신) 확인. 세 플래그
모두 기본값(False)일 때 기존 13개 기본 컬럼만 나오는지도 함께 확인.
`nl_query_bar.render()`를 직접 호출해 새 체크리스트(3옵션)가 레이아웃에
포함되는지 확인.

### 후속: 보유 전문성 컬럼을 항상 맨 마지막으로 고정

"보유 전문성은 객관적인 내용이 아니므로(부서장/본인 컨펌 X) 엑셀의
가장 마지막 컬럼에 반영되도록 해줘" 요청 — 특허/논문(원천 실적 데이터)과
달리 보유 전문성은 LLM이 추정한 값이라 신뢰도 성격이 달라, 어떤 옵트인
조합을 선택해도 항상 맨 끝에 오도록 `build_profile_workbook()`의
추가 순서를 특허 → 논문 → 전문성으로 바꿨다(이전엔 전문성 → 특허 → 논문
순이라 셋 다 선택하면 전문성이 중간에 끼었음). 검증: 세 플래그를 모두
`True`로 `build_profile_workbook()`을 실행해 헤더 마지막 4개가 정확히
`보유전문성(강점 분야/강점 키워드/주요 역할·책임/전문지식 및 역량)`
순서로 오는지 openpyxl로 확인.

## 완료: JOB Market 검색 결과 엑셀 다운로드(사번 1열, 결과 2열)

"JOB market에서 검색한 결과를 엑셀로 다운로드 받을 수 있게 해줘.
재배치가 가능한 연구원의 사번을 첫번째 컬럼, 결과를 두번째 컬럼에
반영" 요청. "재배치가 가능한"이라는 표현대로 추천이 1건 이상인
사람만 포함하고(추천 0건인 사람은 행 자체를 뺌), 딱 2개 컬럼(사번/결과)
구성으로 만들었다 — 화면에 있는 사진/전문성 요약 카드 등은 엑셀에
옮기지 않고, 화면의 추천 한 줄(`_recommendation_row` — 과제명/부서/A·B
점수/사유)만 텍스트로 압축해 담았다.

**`services/job_market.py`**: `build_result_workbook(result)` 신규 —
`run_project_search()`/`run_individual_search()`/`load_history()`가
반환하는 report(`roster`, `results` 등)를 그대로 받는다. `roster` 순서를
따라 `results[rid]['recommendations']`가 있는 사람만 골라, 추천마다
`"N. 과제명 (부서명) - A: xx%, B: xx%"` + (있으면) `"   사유: ..."` 두 줄을
만들고 여러 추천은 빈 줄로 이어붙여 한 셀에 담는다(A/B 점수가 없는
쪽은 "데이터없음"). `researcher_profile_export.py`와 같은 스타일(바탕체
11pt, 전체 테두리, 헤더 볼드, 줄바꿈 셀)로 새 워크북을 직접 만든다(대상
데이터 구조가 완전히 달라 그 모듈 함수는 재사용하지 않음). openpyxl/io
임포트 추가. `result_default_filename()`도 추가(`JOB_Market_결과_YYYYMMDDHHMM.xlsx`).

**`pages/job_market.py`**: 검색 결과 영역(`dcc.Loading(html.Div(id='jm-result'))`)
바로 아래에 엑셀 다운로드 버튼(`jm-excel-btn`, 기본 숨김) + `dcc.Download`
추가, 결과 원본을 담아두는 `dcc.Store(id='jm-result-store')` 신규 —
검색(`_run`)과 이력 보기(`_view_history`) 콜백 둘 다 `_render_result()`로
화면을 그릴 때 같은 원본 `result`를 이 스토어에도 함께 저장한다(에러
결과는 `None`으로 비움). `_update_excel_button()` 콜백이 스토어 변화를
지켜보다 재배치 가능한 사람이 1명이라도 있을 때만 버튼을 보이게/눌리게
하고, `_download_excel()`이 그 스토어 값을 그대로
`build_result_workbook()`에 넘긴다.

검증: `build_result_workbook()`을 목 결과(3명 중 2명만 추천 있음, 그중
한 명은 추천 2건에 점수 없는 필드/빈 사유 섞음)로 직접 호출해 —
추천 없는 사람이 행에서 빠지는지, 사번이 roster 순서 그대로 1열에
오는지, 2열 줄바꿈/번호/사유 서식과 "데이터없음" 폴백이 맞는지 openpyxl로
확인. `pages.job_market.layout()`을 직접 호출해 `jm-excel-btn`/
`jm-excel-download`/`jm-result-store`가 레이아웃에 포함되는지 확인.
Playwright 브라우저 테스트는 이번 세션 컨테이너에 `data/processed/`가
비어 있어(LLM 호출까지 필요한 실제 검색 자체가 불가능) 생략 — 위 함수
단위 검증으로 로직을 대신 확인했다.

## 완료: 보유 전문성 "연구원"/"연구원↔연구원" 탭을 조직도 클릭식 상세보기로 전환

"보유 전문성 탭의 연구원과 연구원↔연구원 탭에서 모든 연구원 정보가 카드
형태로 쭉 나열되어있는데, 조직도 상에서 클릭하면 그때 해당 연구원의
정보가 보이도록 수정해줘" 요청. 이 두 탭은 `pages/researcher_similarity_map.py`가
정적 HTML 리포트(`연구원 보유 전문성 분석.html`/`researcher_similarity.html`,
각각 `pipeline/process_researcher_expertise.py`/`process_researcher_similarity.py`가
생성)를 iframe(srcDoc)으로 그대로 띄우는 구조이고, 좌측 사이드바 조직도는
이미 있었지만(`team_refer.csv` 기반, `rd_specialist_markdown.build_org_tree()`)
클릭 시 "그 사람 카드로 스크롤"만 할 뿐 본문엔 항상 전체 연구원 카드가
나열돼 있었다 — 그래서 스크롤 없이 원하는 사람을 찾기 번거로웠다.

**`pipeline/rd_specialist_markdown.py`**(3개 콘솔형 리포트의 공용 인프라 —
과제 전문성/strength 표준화/임베딩 설명 리포트도 같은 `console_page()`를
쓰므로, 영향 범위를 연구원/연구원↔연구원 두 리포트로만 좁히기 위해
옵트인 플래그로 구현):
- `console_page(title, sidebar_html, body_html, detail_view=False)` —
  `detail_view=True`면 `<body class="detail-view">`를 붙이고, 본문 맨 앞에
  안내 문구(`.detail-placeholder`, "◀ 왼쪽 조직도에서 연구원을 선택하면
  정보가 표시됩니다.")를 넣는다. 기본값 False라 다른 3개 리포트는 기존
  동작 그대로.
- `CONSOLE_STYLE`에 규칙 추가: `body.detail-view .content` 안의
  `.card`/`.dept-heading`/`.org-heading`을 기본 `display:none`(카드가
  `.sim-sections` 같은 중첩 래퍼 안에 있어도 맞도록 자손 선택자 사용),
  `.card.detail-active`만 `display:block`. `.detail-placeholder`는
  `detail-view`가 아닐 때는 항상 숨김.
- `_CONSOLE_SCRIPT`의 기존 `a[href^="#"]` 클릭 핸들러(원래 스크롤만 하던
  곳)에 `document.body.classList.contains('detail-view')`일 때의 분기를
  추가 — 클릭한 카드에만 `.detail-active`를 옮겨 붙이고(기존 활성 카드는
  제거) 안내 문구를 숨긴다. 조직도 검색(`org-search-input`)이나
  드래그 리사이즈 등 나머지 인터랙션은 그대로.

**`pipeline/process_researcher_expertise.py`/`process_researcher_similarity.py`**:
각각의 `console_page(...)` 호출에 `detail_view=True`만 추가.

**`pages/researcher_similarity_map.py`의 `_iframe_tab()`**: UMAP 점 클릭이나
관계 그래프 노드 클릭으로 "연구원" 탭으로 넘어올 때(`scroll_to` 인자)
주입하는 스크립트가 기존엔 `el.scrollIntoView()`만 호출했는데, detail-view
아래에서는 그 카드가 `.detail-active`가 아니라서 숨겨진 채로 스크롤만
되어 화면엔 아무것도 안 보이는 회귀가 생길 뻔했다 — 사이드바 클릭
핸들러와 동일한 로직(다른 카드의 `.detail-active` 제거 → 대상 카드에
추가 → 안내 문구 숨김)을 이 주입 스크립트에도 그대로 추가해 미리 잡았다.

검증: `rd_specialist_markdown` 함수들로 카드 2개짜리 목(mock) 리포트를
직접 만들어(`console_page(..., detail_view=True)`) 로컬 HTML로 저장한 뒤
Playwright(Chromium)로 열어 — 초기 상태에서 카드 2개·부서 헤딩 모두
숨겨지고 안내 문구만 보이는지, 조직도에서 첫 번째 사람을 클릭하면 그
사람 카드만 보이고 안내 문구가 사라지는지, 이어서 두 번째 사람을
클릭하면 첫 번째 카드는 다시 숨고 두 번째 카드로 바뀌는지 확인. 별도로
`researcher_similarity_map._iframe_tab('researcher', scroll_to='r-002')`가
만드는 주입 스크립트를 같은 목 리포트에 적용해 Playwright로 열어보고,
로드 즉시(클릭 없이) 목표 카드가 `.detail-active`로 바로 보이는지도
확인. 이번 세션 컨테이너엔 실제 파이프라인 산출물이 없어 진짜
`연구원 보유 전문성 분석.html`/`researcher_similarity.html`로는 확인하지
못했지만, 두 리포트 모두 같은 `rd_specialist_markdown` 함수와 카드 DOM
구조(`class="card" id="r-{사번}"`)를 공유하므로 위 검증이 그대로
적용된다.

## 완료: 연구원/연구원↔연구원 탭 — 프로필 이동 아이콘 + 엑셀 다운로드 + 표시 개수/검색 개선

한 메시지로 들어온 5개 요청. 1·3·4·5는 범위가 명확해 바로 구현했고,
2(부서 단위 엑셀 다운로드)는 UI 위치/부서 트리 기준/유사 연구원 명단
범위 3가지가 설계에 직접 영향을 줘 `AskUserQuestion`으로 확인 후 구현—
셋 다 추천안(①탭 바깥 별도 패널 ②조직도(team_refer.csv) 트리 ③저장된
전체 목록)으로 확정됐다.

**1) 카드에 "연구원 프로필로 이동" 아이콘 추가** (`pipeline/rd_specialist_markdown.py`):
- `profile_link_html(researcher_id)` 신규 — `map_link_html()`과 동일한
  `.map-link` 스타일, `/researcher-profile?id={rid}` + `target="_top"`으로
  이동(researcher_profile.py의 `layout(id=...)`이 그대로 받아 그 사람을
  선택해 보여주는 기존 동작 재사용).
- `.card-top` 안에서 두 아이콘(프로필/전문성 MAP)이 항상 한 덩어리로
  오른쪽에 붙도록 `<div class="card-icons">{profile_link_html}{map_link_html}</div>`로
  묶었다 — 기존엔 `.map-link` 자체에 `margin-left:auto`가 있어 아이콘이
  하나뿐일 때만 맞는 방식이었으므로, `margin-left:auto`를 `.card-icons`
  래퍼로 옮기고 개별 `.map-link`에서는 뺐다.
- `pipeline/process_researcher_expertise.py`(`_researcher_card_html`)와
  `pipeline/process_researcher_similarity.py`(카드 헤더) 둘 다 이 래퍼로
  교체.

**3) 유사 연구원 리스트 행에도 프로필 이동 아이콘** (`process_researcher_similarity.py`):
`profile_icon_link_html(researcher_id)` 신규(아이콘만, 텍스트 없는 소형
버전 — 표 행처럼 좁은 공간용) — `_match_row_html()`의 이름 옆에 붙였다.

**4) 유사 연구원 표시 개수 기본값 3명**: `count_toggle`의 라디오 버튼
`checked` 속성을 `count-5`에서 `count-3`으로 옮겼다(CSS `:checked ~`
형제 선택자 기반이라 이 한 줄만 바꾸면 됨 — JS 불필요).

**5) 연구원 개별 프로필 이름 검색에 부서명 추가**(`pages/researcher_profile.py`
`_load_selector_data()`의 `_opt()`): 라벨을
`"이름 [부서]  (사번) — 직급"` 형태로 바꿔 동명이인을 부서로 구분할 수
있게 했다.

**2) 보유 전문성 + 유사 연구원 명단 엑셀 다운로드(개인별/부서 단위)**:
- `services/similarity_map.py`에 조직도 유틸 추가 —
  `pipeline.rd_specialist_markdown.build_org_tree`/`read_team_refer`를
  그대로 가져와(`pipeline`이 실제 파이썬 패키지라 `services/job_market.py`의
  sys.path 트릭 없이 바로 import 가능) `org_tree_options()`(들여쓰기로
  평탄화한 부서 드롭다운 옵션, value=dep_id), `researchers_under_departments
  (dep_ids, include_children)`(선택 부서(들)의 org_code + include_children면
  하위 부서 org_code까지 모아 researchers.csv와 매칭), `individual_search_options()`
  ("이름 [부서] (사번)" 형식, researcher_profile.py와 동일 표기)를 만들었다.
- `services/researcher_profile_export.py`에 `expertise_field_lines(profile,
  field)` 공개 함수 추가 — 기존 `_expertise_field()`(`_researcher_row_context()`
  전제)의 내부 로직을 분리해, profile dict만 있는 호출부(이번 신규 기능)도
  같은 서식(강점 분야/키워드/역할·책임/역량 4필드)을 재사용할 수 있게 했다.
- `services/similarity_map.py`에 `build_expertise_similarity_workbook
  (researcher_ids)` 신규 — 컬럼: 사번/성명/부서/보유전문성 4개(위 함수 재사용)/
  유사 연구원 명단(researcher_similarity.json의 `similar` 리스트 **전체**를
  "이름(부서) - 유사도% [판정]" 줄로, 화면의 3/5/10 표시개수 제한과 무관).
  `researcher_ids` 중복은 순서를 유지하며 제거. `researcher_profile_export.py`
  스타일(바탕체 11pt, 테두리, 헤더 볼드, 줄바꿈 셀)을 그대로 따름.
- `pages/researcher_similarity_map.py`: 탭(`dcc.Loading(...expertise-tab-content)`)
  아래 `_download_panel()`을 상시 배치하고, `expertise-tabs.active_tab`을
  구독하는 콜백으로 "전문성 MAP" 탭에서는 숨긴다(요청이 "연구원,
  연구원↔연구원 탭에서"로 한정했으므로). 패널 안: `dbc.RadioItems`로
  "개인별 검색"/"부서 선택(조직도)" 모드 전환(다른 모드의 입력 행은 숨김),
  개인별은 `dcc.Dropdown(multi=True)` + `individual_search_options()`,
  부서는 `dcc.Dropdown(multi=True)` + `org_tree_options()` + "하위부서
  포함" 스위치(기본 켬). 다운로드 콜백은 선택 검증(미선택/매칭 없음 시
  빨간 안내 문구) 후 `build_expertise_similarity_workbook()` 호출.

검증: `services/similarity_map.py`의 새 함수들을 `read_team_refer`/
`read_processed`/`read_expertise_profiles`/`read_similar_researchers`를
목(mock) 데이터로 몬키패치해 직접 호출 — 3단 조직도(루트+하위 2개)에서
`include_children=False`면 루트 소속 1명만, `True`면 하위 부서 포함
3명 전부 나오는지, 개별 하위부서만 선택하면 그 부서 소속만 나오는지,
개인별 검색 옵션 라벨에 부서가 포함되는지 확인. `build_expertise_similarity_workbook()`은
중복 ID 제거, 프로필 없는 사람은 4개 필드 전부 "-", 유사 연구원 점수가
없을 때 "데이터없음" 폴백, 유사 연구원이 명단에 없는(이름 매핑 안 되는)
경우 사번 그대로 표시되는지까지 openpyxl로 열어 확인. 프로필/전문성MAP
아이콘은 `rd_specialist_markdown` 함수로 만든 목 카드 HTML을 Playwright로
열어 두 아이콘의 텍스트·href가 정확한지, `.card-icons`로 오른쪽에 나란히
붙는지(스크린샷) 확인. `pages/researcher_similarity_map.layout()`을 직접
호출해 다운로드 패널의 모든 컴포넌트 id가 레이아웃에 포함되는지 확인.
이번 세션 컨테이너엔 실제 파이프라인 산출물(HTML 리포트)이 없어 진짜
브라우저로 전체 흐름(조직도 선택 → 다운로드 클릭 → 파일 저장)을 끝까지
확인하지는 못했다 — 화면에 반영하려면 `process_researcher_expertise.py`/
`process_researcher_similarity.py`를 다시 실행해 두 HTML을 재생성해야
한다(직전 완료 항목과 동일한 제약).

## 완료: 엑셀 다운로드에 "직무"/"직무이력" 선택 컬럼 추가

"AI검색, 연구원 명단 엑셀 다운로드 시 직무(researchers.csv의
job_function), 직무이력(job_profile.csv)을 선택적으로 다운받을 수
있도록 해줘" 요청. 특허/논문과 같은 성격(LLM 산출물이 아닌 원천 데이터)
이지만, 사용자가 명시적으로 "선택적으로"라고 했고 서로 다른 두 출처
(researchers.csv 단일 값 vs job_profile.csv 이력)라 특허/논문처럼
독립적인 체크박스 2개("직무 포함"/"직무이력 포함")로 추가했다.

**`services/researcher_profile_export.py`**: `build_profile_workbook()`
공용 함수라 여기 한 곳만 고치면 AI 검색/연구원 명단 다운로드 둘 다 반영.
- `components.timeline_data.job_points()`(이미 있던 job_profile.csv wide
  포맷 파서 — researcher_profile.py 타임라인이 쓰는 것과 동일 로직) 재사용.
- `_load_tables()`/`_researcher_row_context()`에 `job_profile`
  (DataFrame, `job_profile_df` 키 — `_df_for()`로 필터링, dedupe_patents
  처럼 DataFrame 그대로 필요) 추가.
- `_col_job_function(_rid, rows)` 신규 — `researcher.job_function` 값
  그대로(단일 값이라 다른 컬럼처럼 목록 서식 불필요).
- `_col_job_profile(_rid, rows)` 신규 — `job_points()`로 슬롯을 푼 뒤
  시작일 내림차순 정렬, `"직무명('YY ~ 'YY/현재)"`를 과제수행이력과 동일한
  표기 규칙으로 줄바꿈 나열.
- `_JOB_FUNCTION_COLUMNS`/`_JOB_PROFILE_COLUMNS`(각 컬럼 1개)를 기존
  `_PATENT_COLUMNS`/`_PUBLICATION_COLUMNS`와 같은 패턴으로 추가.
- `build_profile_workbook()`에 `include_job_function=False`/
  `include_job_profile=False` 파라미터 추가, 특허 → 논문 → 직무 → 직무이력
  → (항상 마지막) 보유 전문성 순으로 옵트인 컬럼을 붙인다.

**`components/nl_query_bar.py`/`pages/researcher_list.py`**: 기존
3옵션(보유 전문성/특허/논문) 체크리스트에 "직무 포함"/"직무이력 포함"
2개를 추가(총 5옵션, 전부 기본 해제). 두 다운로드 콜백 모두
`'job_function'/'job_profile' in excel_options`를 새 파라미터로 그대로
전달.

검증: `_load_tables()`를 목 데이터(job_function='SW개발', job_profile.csv
2개 슬롯 — 하나는 종료일 있음, 하나는 진행중)로 몬키패치해
`build_profile_workbook(include_job_function=True, include_job_profile=True)`
실행 — 헤더에 "직무"/"직무이력" 추가, "직무" 셀 값, "직무이력" 셀이
최신(진행중) 항목부터 내림차순으로 두 줄 나열되고 진행중 항목은 "현재"로
표기되는지 openpyxl로 확인. 플래그 전부 기본값(False)일 때 기존 13개
기본 컬럼만 나오는 것도 함께 확인. `nl_query_bar.render()`로 새
체크리스트 5개 옵션이 레이아웃에 포함되는지 확인.

## 완료: evaluations.csv를 long → wide로 재구성 + 상/하반기업적 추가 + 3월 기준 회계연도

"evaluations.csv 생성 로직 설명해줘(확인 후 수정예정)"로 시작해, 여러 차례
문답으로 확정된 대규모 스키마 변경. 기존엔 `researcher_id, year, grade,
score`(long, 연봉등급만) 였는데, 다음으로 바뀌었다:

**확정된 요구사항**:
1. **researcher_id당 1행(wide)**, 연봉등급 3개년 + 상/하반기업적(EM/ES/MT)
   3개년 컬럼(`{연도}_salary_grade`, `{연도}_first_half_grade`,
   `{연도}_second_half_grade`) — 점수(score) 컬럼은 없음(연봉등급도
   상/하반기업적도 점수 환산 안 함 — 다운스트림에서 원래 안 쓰이던 값이라
   완전히 제거).
2. **연도 기준을 "매년 3월 시작 회계연도"로 통일**: 오늘이 3월 이후면
   FY=올해, 1~2월이면 FY=작년. 연봉등급 3개년=[FY,FY-1,FY-2], 상/하반기업적
   3개년=[FY-1,FY-2,FY-3](그 해 연봉등급이 전년도 업적 평가를 반영하므로
   항상 연봉등급 연도-1). 기존에 논의했던 "원본에 해당 연도 컬럼이
   있는지로 분기"하는 방식은 전부 이 날짜 기반 계산으로 대체됐다(더 이상
   원본 파일 컬럼 존재 여부를 보지 않음 — 특정 연도 컬럼이 원본에 없으면
   그 컬럼만 비워둘 뿐, 3개년 범위 자체는 안 바뀜).
3. **연구원 개별 프로필 표(`evaluation_incentive_block`)**: 연도 열마다
   그 해 연봉등급과 (그 해-1) 상/하반기업적을 합쳐 한 셀로 표시.
4. **엑셀 다운로드("평가" 컬럼)**: 2줄 — 1줄: 연봉등급 3개년 슬래시("다/다/다"),
   2줄: 상/하반기업적 3개년 쌍을 괄호로 묶어 콤마 나열("(MT/MT, MT/MT, MT/MT)").
5. **합성 표기 규칙**(문답으로 8가지 조합 전부 확정):
   - 연봉등급 있음 → `"{연봉등급}({있는 반기만 슬래시로 이어붙임})"`,
     반기 둘 다 없으면 괄호 없이 연봉등급만("다").
   - 연봉등급 없음 → 반기 두 자리를 항상 `"{첫자리 or '-'}/{둘째자리 or '-'}"`로
     (예: `-/MT`, `MT/-`, `-/-`) — 있는 것만 골라 보여주는 위 규칙과 달리
     이쪽은 자리를 항상 유지한다(사용자가 초안의 "MT" 단독 표기를
     "-/MT"로 직접 수정하며 확정).
   - 이 규칙을 프로필 표/엑셀 다운로드 양쪽에 동일하게 적용.
6. 색상은 기존 `GRADE_COLOR`(가~마 5색) 그대로 — 합성 문자열이 돼도
   앞의 연봉등급 부분 기준으로 계속 색칠.
7. `pages/researcher_list.py`의 하드코딩된 `"'24평가"/"'25평가"/"'26평가"`
   3개 컬럼도 동적 연도로 전환.

**`services/evaluations.py`**(신규) — 위 로직의 단일 출처. 파이프라인과
3곳의 화면/엑셀 소비처가 전부 이 모듈 하나만 보고 계산하게 해서, 한쪽만
고치고 다른 쪽을 깜빡하는 사고를 막는다.
- `current_fiscal_year(today=None)` — 3월 기준 회계연도 계산.
- `evaluation_years(today=None)` — `(연봉등급 3개년, 업적 3개년)`, 둘 다
  내림차순.
- `salary_grade_column(year)`/`first_half_column(year)`/`second_half_column(year)`
  — 컬럼명 생성기(오타 방지, 한 곳에서만 포맷 정의).
- `format_half_pair(first, second)` — "{first or '-'}/{second or '-'}".
- `format_evaluation_cell(salary, first, second)` — 위 6가지 조합 규칙을
  구현한 합성 함수. `SALARY_GRADES`(가나다라마)/`HALF_GRADES`(EM/ES/MT)
  튜플도 여기서 export.

**`pipeline/process_tp_evaluation.py`**: 기존 `GRADE_COLS`(연도 3개
하드코딩)/`GRADE_TO_SCORE`(점수 매핑) 상수를 걷어내고, `evaluation_years()`로
얻은 6개 연도(연봉등급 3 + 업적 3)에 대해 원본 컬럼(`"{연도} 연봉등급"`,
`"{연도} 상반기업적"`, `"{연도} 하반기업적"`)을 하나씩 읽어 유효값(가~마 /
EM·ES·MT)만 남기고 `researcher_id`당 1행짜리 `result` DataFrame에
컬럼으로 직접 붙인다(예전처럼 연도별로 melt해서 세로로 쌓지 않음). 원본에
특정 연도 컬럼이 없으면 그 컬럼만 빈 문자열로 두고 WARN, 유효하지 않은
값(오타 등)도 그 셀만 비우고 WARN — 나머지는 그대로 저장. 이름/성별/
생년월일 추출(1번 섹션)은 이번 변경과 무관해 그대로 둠.

**`services/researcher_profile_export.py`**: `_col_evaluation()`을
wide 컬럼(`evaluations.salary_grade_column()` 등)을 읽어
`format_half_pair()`로 조립하는 2줄(`\n` 하나) 문자열로 재작성. 헤더
`"평가('24~'26)"`도 하드코딩을 걷어내고 모듈 임포트 시점에
`_EVAL_SALARY_YEARS`(evaluation_years() 결과)로 동적 생성(`_EVAL_HEADER`)
— 회계연도가 바뀌는 건 1년에 한 번뿐이라 매 요청마다 재계산할 필요 없이
프로세스 기동 시 한 번이면 충분(이 앱의 다른 "현재 시점 기준" 값들과
동일한 전제). 평가 컬럼 너비도 12→22로 넓힘(2줄째 반기 표기가 더 길어져서).

**`components/profile_sections.py`**: `evaluation_incentive_block()`의
`_grade()`(단순 조회)를 `_eval_cell()`(연봉등급 + 전년도 반기 조회 →
`format_evaluation_cell()`로 합성, `(색상용 연봉등급, 표시 문자열)` 튜플
반환)로 교체. `_grade_td()`는 색상은 첫 번째 값(연봉등급)으로, 텍스트는
두 번째 값(합성 문자열)으로 렌더링하도록 시그니처 변경. 문자열이 길어져
폰트 크기를 0.9rem→0.8rem으로 살짝 줄임. NaN-as-string("nan"/"None")
정리용 `_clean_grade()` 헬퍼 추가(evaluations.csv를 `read_processed()`로
읽으면 빈 셀이 파이썬 float NaN이 되고, 이걸 다시 문자열화하면 "nan"이
되는 이 프로젝트 공통 패턴 — 다른 CSV들의 `_s()` 계열 헬퍼와 동일 목적).

**`pages/researcher_profile.py`**: `years = [CURRENT_YEAR-2, CURRENT_YEAR-1,
CURRENT_YEAR]`(달력연도)를 `sorted(evaluation_years()[0])`(회계연도, 3월
기준)로 교체 — 안 그러면 1~2월엔 화면이 찾는 연도와 evaluations.csv에
실제로 있는 컬럼이 어긋난다. 나이 계산 등에 쓰는 `CURRENT_YEAR` 자체는
달력연도 그대로 유지(이번 요청과 무관).

**`pages/researcher_list.py`**: 모듈 상단에 `_EVAL_SALARY_YEARS`(오름차순)/
`_EVAL_GRADE_COLUMNS`(`"'24평가"` 형태, 동적)를 계산해두고, `_grade()`
조회 로직과 `_GRADE_STYLES`(조건부 배경색) 둘 다 이 동적 목록을 쓰도록
교체. 이 표는 "직급/직무" 같은 정량 지표 나열이 목적이라, 프로필/엑셀과
달리 상/하반기업적을 합성하지 않고 연봉등급만 표시(사용자 확인: 하드코딩
연도만 동적으로 바꾸면 됨, 서식 자체는 그대로).

**`services/data_labels.py`**: 없어진 `grade`/`score`(evaluations.csv)
고정 라벨 항목을 지우고, `label_for()`에 `{연도}_salary_grade` 등 동적
평가 컬럼명을 정규식으로 인식해 `"2026 연봉등급"`처럼 라벨링하는 분기
추가(AI 검색 결과 테이블 헤더용).

**알려진 미반영 항목**: `pages/org_comparison.py`(조직별 비교, 이미
`_FEATURE_HIDDEN=True`로 항상 리다이렉트되는 죽은 코드)도 옛 long 포맷
(`eva['year']`)을 그대로 쓰고 있어 이번 변경으로 논리상 깨졌다. 지금은
도달 불가능한 코드라 당장 영향은 없지만, 나중에 이 기능을 다시 켠다면
`pages/researcher_list.py`와 같은 방식으로 같이 고쳐야 한다.

검증: `services/evaluations.py`의 회계연도 계산을 2026-01/2026-03/
2026-08/2027-01/2027-03 등 여러 날짜로 직접 호출해 3월 경계가 정확히
지켜지는지, `format_evaluation_cell()`을 8가지 조합 전부 표로 돌려
확정된 표기와 정확히 일치하는지 확인. `pipeline/process_tp_evaluation.py`를
목(mock) T&P DataFrame(정상값/빈값/잘못된 값 섞음)으로 직접 실행해
evaluations.csv가 wide로 정확히 저장되는지, 유효하지 않은 값만 선택적으로
빈 칸 처리되는지 raw CSV 파일까지 열어 확인. `_col_evaluation()`/
`evaluation_incentive_block()` 둘 다 목 데이터로 직접 호출해 8가지 조합
전부(둘 다 있음/연봉등급만/반기만/전부 없음 등) 기대한 문자열·색상이
나오는지 확인. `pages/researcher_list.py`의 `_build_summary_df()`를
목 데이터로 실행해 동적 연도 컬럼명·조건부 스타일 규칙(15개 = 5등급×3년)이
올바르게 생성되는지 확인. 관련 5개 파일 전부 `ast.parse`로 구문 확인,
`pages.researcher_list`/`pages.researcher_profile`를 Dash 앱 컨텍스트에서
직접 import해 모듈 로드 자체가 깨지지 않는지 확인. 이번 세션 컨테이너엔
실제 T&P 원본 파일이 없어 진짜 파이프라인 재실행·브라우저 확인은
못 했다 — 화면에 반영하려면 `python pipeline/process_tp_evaluation.py`
(또는 전체 파이프라인)를 다시 실행해 evaluations.csv를 재생성해야 한다.

## 완료: JOB Market 추천 결과의 A/B 유사도 의미를 안내 아이콘으로 표기

"job market 결과에서 A 유사도 B 유사도가 뭘 의미하는거였지? 아이콘에
어떤 의미인지 표기해줘" — 기존엔 결과 상단 Alert 문구에만 짧게("A: 과제
분석 기반, B: 배정 인력 전문성 기반") 적혀 있어 눈에 잘 안 띄었다.
`services/job_market.py` 모듈 docstring에 있던 A/B 정의(A=과제 자체의
분석 문서 임베딩과 비교, B=그 과제에 배정된 사람 중 가장 가까운 1명과
비교)를 그대로 옮겨, "추천 결과" 제목 옆에 hover 안내 아이콘(ⓘ)을
추가했다 — `components/detail_tabs.py`의 등급/Lv 안내 아이콘과 동일한
hover 패턴(다만 이미지 대신 텍스트 툴팁).

**`pages/job_market.py`**: `_score_info_icon()` 신규 — `bi-info-circle`
아이콘 + `dbc.Tooltip`(A/B 각각 한 줄 설명 + "데이터 없음일 때" 안내).
`_render_result()`의 "추천 결과" `html.H6` 옆에 붙였다(추천 목록 전체에
한 번만 — 등급/Lv 안내 아이콘처럼 반복되는 배지마다가 아니라 섹션당
하나로 충분).

검증: `_render_result()`를 목 결과로 직접 호출해 아이콘 id/Tooltip
target이 일치하는지, 툴팁 내용에 A/B 설명 문구가 정확히 들어가는지 확인.

## 완료: 연구원 개별 프로필 검색에 과제명 추가 + 최근 검색 이력

"1. 연구원 개별 프로필에서 연구원 검색 시 기존 부서명에서 과제명도
추가해줘. 2. 연구원 검색 시 내가 검색했었던 연구원 이력이 남아있어서
다시 찾아볼 수 있게해줘" 요청.

**1) 검색 라벨에 과제명(org_code) 추가**(`pages/researcher_profile.py`
`_load_selector_data()`의 `_opt()`): 기존 `"이름 [부서]  (사번) — 직급"`을
`"이름 [부서 · 과제]  (사번) — 직급"`으로 — 부서/과제 둘 다 비어있지
않은 것만 `·`로 이어 대괄호 안에 넣는다(둘 다 없으면 대괄호 자체 생략).

**2) 최근 검색 이력**: 로그인 체계가 없어(이 프로젝트 공통 제약) 서버에
"누구의" 이력인지 구분할 방법이 없다 — 대신 `dcc.Store(id='researcher-
search-history', storage_type='local')`로 **브라우저 localStorage**에
남겨, 같은 브라우저로 새로고침/재방문해도 이어서 보이게 했다("나" =
이 브라우저 하나로 구분).
- `_record_search_history()` — `researcher-select` 값이 바뀔 때마다(직접
  검색이든 이력 칩 클릭이든) 그 사람을 이력 맨 앞으로 올린다. 이미 있던
  항목은 지우고 다시 넣어 중복 없이 최신순 유지, 최대 8개(`_HISTORY_LIMIT`)
  만 보관.
- `_render_history_chips()` — 선택 카드 하단에 "최근 검색" 칩(`dbc.Badge`,
  패턴매칭 id `{'type':'researcher-history-chip','rid':...}`)으로 렌더링,
  비어 있으면 안내 문구.
- `_select_from_history()` — 칩을 누르면 그 사람의 부서로 `dept-select`도
  같이 옮긴 뒤 `researcher-select` 값을 설정한다 — 부서를 안 맞추면
  현재 부서 필터에 그 사람이 없어 선택이 무시될 수 있어서(`layout()`의
  `id=` 딥링크가 처음부터 default_dept/default_rid를 함께 계산해 두는 것과
  동일한 이유). `Output('researcher-select', 'value', allow_duplicate=True)`
  — 이미 `filter_by_dept` 콜백이 같은 Output을 갖고 있어 중복 허용 필요.

검증: `_load_selector_data()`로 라벨에 "부서 · 과제"가 올바르게 붙는지
확인. `_record_search_history()`를 연속 호출해(A선택→B선택→A재선택)
최신순·중복제거가 맞는지, `_render_history_chips()`가 그 목록으로 올바른
배지(텍스트/패턴매칭 id)를 만드는지 확인. `layout()`을 직접 호출해
`researcher-search-history`/`researcher-history-chips` 컴포넌트가
레이아웃에 포함되는지 확인. `_select_from_history()`는 `dash.ctx.
triggered_id`를 쓰는 함수라 테스트 스크립트에서 직접 호출하면 컨텍스트
오류가 나는 게 정상(이 앱의 다른 패턴매칭 id 콜백들과 동일한 제약) —
로직 자체는 소스 리뷰로 확인.

## 완료: JOB Market "제외" 부서 선택이 결과에 영향을 주지 않도록 수정

이전 턴에서 "부서를 선택하면 그 부서의 모든 과제가 제외되는 게 맞냐"고
확인을 요청하셨고(전체 42개 과제 중 5개 과제짜리 부서를 제외하면 37개로
줄어드는 걸 관찰) — 코드를 다시 확인해 그게 `_expand_excluded_projects()`
가 부서를 그 부서 소속 과제 전체로 펼쳐 제외 집합에 합치기 때문이라고
설명했다. 이번 요청은 그 동작을 **원치 않는 것으로 확정** — "부서는
단순히 과제를 선택하기 위한 캐스캐이딩 역할만 하고, 실제 제외/검토는
과제 단위에서만 선택하게, 부서는 결과에 아무 영향이 없도록" 수정.

**`services/job_market.py`**: `_expand_excluded_projects(excluded_departments,
excluded_org_codes, all_rows)`(부서→과제 펼치기 로직)를 완전히 제거하고,
`_normalize_excluded_projects(excluded_org_codes)`(과제명 정규화만 하는
한 줄짜리 함수)로 교체. `run_project_search()`/`run_individual_search()`
시그니처에서 `excluded_departments` 파라미터 자체를 삭제(부서 값이
함수에 전달될 통로 자체를 없애 "결과에 영향 없음"을 구조적으로 보장) —
이제 두 함수 다 `excluded_org_codes`(제외할 과제 목록)만 받는다. 이
파라미터를 위해서만 읽던 `project_confl_address.csv`/`_dedup_candidate_rows()`
호출도 두 함수에서 같이 제거(불필요해짐).

**`pages/job_market.py`**: `_run()` 콜백에서 `State('jm-exclude-dept',
'value')`를 제거하고 `jm.run_project_search()`/`run_individual_search()`
호출에서 `excluded_depts` 인자를 뺐다. `jm-exclude-dept` 드롭다운
자체는 그대로 남겨뒀다 — `_update_exclude_project_options()`가 이미
그 값으로 "제외할 과제" 드롭다운의 옵션만 좁혀 보여주는 순수 캐스케이딩
용도로만 쓰고 있어서(결과 계산에는 관여하지 않음), 과제를 부서별로
빠르게 찾는 용도로는 계속 유용하다. 다만 오해의 소지가 있어 placeholder
문구를 "제외할 부서(복수 선택)" → "부서로 좁혀 찾기(선택, 결과엔 영향
없음)"로 바꾸고, 섹션 제목 아래에 "실제로 제외되는 건 아래 '제외할
과제'에서 고른 과제뿐입니다" 안내 문구를 추가했다. 스테일해진 주석
("_expand_excluded_projects — 부서 제외와 개별 과제 제외는 계속
독립적으로 합쳐진다")도 새 동작에 맞게 수정.

검증: `_normalize_excluded_projects()`가 과제명만 정규화하는지 확인.
사용자가 관찰한 시나리오(전체 42개 프로젝트, 그중 5개가 특정 부서 소속)를
목 DataFrame으로 재현해 — 부서를 제외 집합에 전혀 넣지 않고도(새 함수
시그니처 자체가 부서를 받지 않으므로 구조적으로 불가능) 42개가 그대로
후보로 남는지 확인. `run_project_search`/`run_individual_search`의
`inspect.signature()`로 `excluded_departments` 파라미터가 완전히
사라졌는지 확인. `pages.job_market.layout()`을 직접 호출해
`jm-exclude-dept`/`jm-exclude-project` 두 컴포넌트가 여전히 레이아웃에
있는지(드롭다운 자체는 유지) 확인.

## 완료: JOB Market 추천에 "반드시 배치해야 한다면" 강제 후보 1~3개 추가

"재배치 결과를 지금과 같이 유지하되, 재배치가 불가능한 과제를 제외하고
반드시 나머지 과제 중 배치해야 한다고 가정했을 때 1~3개를 반드시 고른
값도 함께 보여달라" 요청. 문답으로 확정: (1) 기존 LLM 호출 하나를
그대로 재사용하되 출력 형식만 확장(별도 LLM 호출 추가 안 함), (2) 최소
1개는 반드시 나와야 함(후보가 있는 한), (3) 재배치 가능 여부
통계/엑셀 다운로드 기준은 그대로 `recommendations`만 보고, 이번 추가는
**화면에만 보이는 참고 정보**, (4) 기존 추천/근접 후보 블록 아래에
경고색으로 구분해서 표시.

**`services/job_market.py`**:
- `_RECOMMEND_SYSTEM_PROMPT`에 5번 규칙 추가 — `recommendations`/
  `closest_non_match` 판단과 완전히 별개로, "무조건 후보 중 하나로
  재배치해야 한다"고 가정했을 때 그나마 최선인 과제를 `must_place`에
  반드시 1~3개(빈 리스트 금지) 담게 지시. 같은 프롬프트/같은 LLM 호출
  안에서 세 번째 필드로만 추가돼 호출 횟수는 그대로.
- `_fallback_must_place(shortlist)` 신규 — LLM이 규칙을 안 지켰거나(빈
  `must_place`) 호출/파싱 자체가 실패해도, 후보(shortlist)가 하나라도
  있으면 임베딩 유사도 1순위를 그대로 `must_place`에 채워 넣는 안전망.
  "1개는 꼭 반드시" 요구를 LLM 순응 여부와 무관하게 코드 레벨에서 보장.
- `_judge_recommendations()` 반환값이 2-tuple → 3-tuple(`recommendations,
  closest_non_match, must_place`)로 확장, 모든 실패 경로(raw 없음/JSON
  파싱 실패/must_place 누락)에서 `_fallback_must_place()`를 적용.
  `shortlist`가 애초에 비어 있으면(후보 자체가 없음) `must_place`도
  `[]`(강제할 대상 자체가 없으므로 예외).
- `recommend_for_researcher()`가 `must_place`를 반환 dict에 추가(그 외
  실패 경로 — 프로필/후보 풀 없음, 임베딩 실패 — 는 전부 `[]`).

**`pages/job_market.py`**: `_must_place_block(must_place)` 신규 —
`bi-exclamation-triangle-fill` 아이콘 + "반드시 배치해야 한다면" 제목의
경고색(`bg-warning bg-opacity-10 border-warning`) 박스로 1~3개를
나열(과제명/부서/A·B 배지/사유, 기존 추천 행과 같은 정보 밀도).
`must_place`가 비어 있으면 `None`을 반환해 아예 렌더링되지 않는다(후보
자체가 없는 극단적 케이스). `_person_card()`의 기존 추천/근접 후보
블록(`body`) 아래에 이 블록을 추가 — 기존 표시 로직은 전혀 안 건드림
(요청대로 "지금과 같이 유지"). `_summary_stats()`/`build_result_workbook()`
등 재배치 가능 통계·엑셀 다운로드 기준은 이번 변경에서 손대지 않음
(여전히 `recommendations` 기준).

검증: `_judge_recommendations()`를 4가지 시나리오(LLM이 정상적으로 둘 다
줌 / recommendations는 비었지만 must_place도 깜빡함 / LLM 호출 자체가
실패(raw=None) / 애초에 shortlist가 비어 있음)로 직접 호출해 각각
기대한 대로 동작하는지 확인 — 특히 2·3번 케이스에서 폴백이 정확히
임베딩 1순위로 채워지는지, 4번은 강제할 대상이 없어 `[]`로 남는지 확인.
`_person_card()`를 목 결과로 렌더링해 경고 박스가 올바른 항목 수·문구로
나오는지, `must_place`가 빈 리스트일 때는 그 블록 자체가 안 나오는지
(`None` 반환) 확인.

### 후속: "반드시 배치해야 한다면"을 엑셀 별도 컬럼으로 추가

"반드시 배치해야 한다면 결과를 엑셀에만 추가를 해줄 수 있을까?(별도의
컬럼으로)" — 엑셀 행 범위를 바꿀지(`AskUserQuestion`) 확인: 지금은
`recommendations`가 있는(재배치 가능한) 사람만 엑셀에 포함되는데,
"재배치 불가 인원도 포함(추천)"으로 확정 — must_place는 애초에 재배치가
어려운 사람을 위해 만든 값이라, 그 사람들이 빠지면 의미가 없다는 이유.

**`services/job_market.py`**: `_format_picks(picks)` 신규 — 기존
`build_result_workbook()` 안에 있던 "N. 과제명 (부서) - A/B%\n   사유:
..." 줄바꿈 조합 로직을 뽑아낸 공용 함수(결과/반드시 배치해야 한다면
두 컬럼이 똑같은 모양의 데이터를 받으므로 재사용). `build_result_workbook()`
을 3컬럼(사번/결과/반드시 배치해야 한다면)으로 확장하고, 행 포함 조건을
`recommendations 있음` → `recommendations 또는 must_place 중 하나라도
있음`으로 넓혔다 — `recommendations`가 없는 사람은 "결과" 셀만 `'-'`로
비워두고 "반드시 배치해야 한다면" 셀은 채운다. `openpyxl.utils.
get_column_letter` 임포트 추가(컬럼이 3개로 늘어 너비 지정에 필요).

검증: 3명(추천+강제배치 둘 다 있음 / 추천은 없고 강제배치만 있음 / 둘 다
없음) 목 데이터로 `build_result_workbook()`을 실행해 — 헤더 3개,
"추천은 없고 강제배치만 있음"인 사람이 이제 엑셀에 포함되고 "결과" 셀이
`'-'`인지, "둘 다 없음"인 사람은 여전히 제외되는지 openpyxl로 확인.

## 완료: 프로필 엑셀 "평가" 컬럼 둘째 줄 — 연봉등급 있을 때 빈 반기 자리 표시 안 함

"엑셀 다운로드 시 평가 컬럼에서 표시 로직을 변경해줘. 연봉등급이 있고
상반기 연봉등급이 없을 때는 표시를 하지 말아줘" — 예시: `가/나/나` +
`(-/EM, -/ES, -/ES)` → `가/나/나` + `(EM, ES, ES)`.

기존엔 둘째 줄(반기 쌍)을 `evaluations.format_half_pair()`로 만들었는데,
이 함수는 그 해 연봉등급 유무와 무관하게 항상 두 자리를 다 보여주고
빈 자리는 `'-'`로 채우는 규칙(연봉등급이 아예 없을 때를 위한 규칙 —
이전에 사용자가 "MT" 단독 표기를 "-/MT"로 직접 고쳐 확정한 바로 그
규칙)이었다. 그런데 둘째 줄은 첫째 줄(연봉등급)과 별개로 계산돼서,
연봉등급이 있는 해에도 반기 하나가 비면 똑같이 `-/EM`처럼 나왔던 것 —
연구원 개별 프로필 화면(`format_evaluation_cell()`)은 애초에 연봉등급이
있을 때 "있는 반기만 이어붙이는" 규칙이라 이 문제가 없었고, 엑셀만
어긋나 있었다.

**`services/evaluations.py`**: `format_half_display(salary_grade,
first_half, second_half)` 신규 — `format_evaluation_cell()`과 같은
판단이지만 연봉등급 부분은 이미 첫째 줄에 있으므로 괄호 안에 들어갈
반기 부분만 반환한다. 연봉등급이 있으면 있는 반기만 이어붙이고(둘 다
없으면 `'-'` 하나만), 연봉등급이 없으면 기존 `format_half_pair()`
그대로(빈 자리 `-` 유지 — 이 경우는 이번 요청 범위 밖이라 안 건드림).

**`services/researcher_profile_export.py`**: `_col_evaluation()`의
둘째 줄 조합에서 `format_half_pair()` 대신 `format_half_display()`를
쓰도록 교체 — 각 반기 연도(y)에 대응하는 연봉등급 연도(y+1)의 값을
같이 넘겨준다(`evaluations.salary_grade_column(y + 1)`).

검증: `format_half_display()`를 8가지 조합으로 직접 호출해 연봉등급
있을 때(반기 하나만 있음/둘 다 있음/둘 다 없음)와 없을 때(기존 대시
유지) 전부 기대값과 일치하는지 확인. 사용자가 준 예시를 그대로
`build_profile_workbook()`으로 재현해 `가/나/나\n(EM, ES, ES)`가 정확히
나오는지 확인. 연봉등급이 없는 해가 섞인 경우(`-/나/가\n(-/MT, ES, -)`)
로도 확인해, "연봉등급 없을 때는 대시 유지" 기존 규칙이 그대로
살아있는지 함께 검증.

## 완료: position 영문 라벨 한글화 + 보유 전문성 시니어/주니어 분류를 CL/년차 기준으로 변경 + 임원 제외

두 가지 요청. (1) `researchers.csv`의 `position`(원본 CL 컬럼) 값 중 영문
임원 표기를 한글로 통일. (2) "연구원 ↔ 연구원" 유사도 리포트의 시니어/
주니어 구분을 기존 "근속 5년" 기준에서 "CL/년차" 기준으로 바꾸고, 임원은
유사 연구원 매칭 대상에서 완전히 제외.

**1) `pipeline/process_researchers.py`**: `POSITION_LABEL_MAP` 신규 —
`{'Corporate VP': '상무', 'Corporate President': '사장', 'Senior Advisor':
'고문', 'Corporate EVP': '부사장'}`(그 외 값, 예: CL1~CL6은 원본 그대로).
`position` 필드를 만들 때 이 맵으로 치환(매핑에 없으면 원본 그대로 폴백).

**2) 시니어/주니어 분류 기준 변경**:
- **`services/researcher_profile_export.py`**: 기존 `_col_position_year()`
  (엑셀 "CL/년차" 컬럼, 예: "CL3-5")의 "년차" 계산 부분을 `position_years
  (promotion_date)`라는 공개 함수로 분리했다 — 승격기준일 기준 회계연도
  계산(`_next_promotion_ref_date`, 2027-03-01 시작 매년 3월 기준일)은
  이미 있던 로직 그대로, 재사용 가능하게 이름만 붙여 뺀 것(동작 변경
  없음, `_col_position_year()`는 이 함수를 호출하도록 리팩터링).
- **`pipeline/process_researcher_similarity.py`**: `_tenure_level()`을
  `hire_date` 기반(근속 5년 미만/이상)에서 `position`(CL)/`promotion_date`
  기반으로 전면 교체 — "CL3-5 이상이면 시니어, CL3-4 이하면 주니어"라는
  확정 문구를 CL 레벨 전체로 일반화해, **CL3 미만은 항상 Junior, CL3
  초과는 항상 Senior, 정확히 CL3일 때만** `position_years()`로 계산한
  년차가 5 이상이면 Senior·미만이면 Junior로 갈리게 했다(이 CL3 이외
  레벨에 대한 일반화는 사용자가 명시하지 않아 합리적으로 추정한 부분 —
  다르게 원하시면 `_CL_SENIOR_THRESHOLD_LEVEL`/`_cl_level()` 판단부만
  고치면 됨). `_cl_level(position)` 신규 — `"CL3"` → `3`처럼 CL 접두사 +
  숫자 형태만 파싱하고, 임원 직책처럼 그 형태가 아니면 `None`(미분류).
  `build_tenure_map()`도 `hire_date` 컬럼 대신 `position`/`promotion_date`
  컬럼을 읽도록 교체. `datetime`/`date` 임포트가 더 이상 안 쓰여서 제거.
- 임원 제외: `_EXCLUDED_POSITIONS = {'상무','사장','고문','부사장','Master'}`
  신규. `process()`에서 `연구원 보유 전문성 분석.json`을 읽은 직후
  `researchers.csv`의 `position`으로 이 집합에 속하는 사람을 `profiles`
  에서 아예 걸러낸다 — 이후 임베딩/LLM 판정/결과 저장 전 과정에서 그
  사람은 존재하지 않는 것처럼 처리되어, **자기 카드도 안 생기고 다른
  누구의 유사 연구원 후보로도 뽑히지 않는다**("연구원 보유 전문성 분석"
  자체(process_researcher_expertise.py)는 건드리지 않아 그 사람의
  개인 프로필 페이지는 그대로 남음 — 요청이 "유사 연구원을 찾을 때"로
  한정했으므로).
- 관련 docstring(모듈 헤더의 "3단계" 설명, `compute_similarity()`/
  `attach_tenure_levels()` 주석, HTML 사이드바 태그라인 "근속 시니어
  우선" → "CL 시니어 우선")도 새 기준에 맞게 업데이트.

검증: `process_researchers.process()`를 목 원본 데이터(CL 컬럼에
"Corporate VP"/"CL3" 섞음)로 실행해 `researchers.csv`에 "상무"/"CL3"로
정확히 저장되는지 확인. `_cl_level()`을 여러 입력(CL1~CL6/임원 직책/빈
값/이상한 형식)으로 확인. `_tenure_level()`을 6가지 경계 케이스(CL2,
CL4, CL3+5년이상, CL3+5년미만, CL3+승격일없음, 비CL직책)로 직접 호출해
전부 기대값과 일치하는지 확인. `build_tenure_map()`을 목 DataFrame으로
확인. `process()` 전체를 LLM/임베딩 관련 함수는 스텁으로 바꾼 채
실행해서 — 임원 1명이 로그에 찍히며 `profiles`에서 실제로 제외되고
(`compute_similarity`에 넘어가는 목록에 안 보임), `tenure_map`은
그 사람도 포함해 계산되지만(단순 조회용이라 무해) 최종 결과에는
영향이 없는지 확인. 관련 3개 파일 전부 `ast.parse` 구문 확인,
`process_researcher_similarity` 모듈을 실제로 import해(services 쪽
연쇄 임포트 포함) 깨지지 않는지 확인. 이번 세션 컨테이너엔 실제
원본 데이터/파이프라인 산출물이 없어, 실제 재실행·브라우저 확인은
못 했다 — 화면에 반영하려면 `python pipeline/process_researchers.py`와
`python pipeline/process_researcher_similarity.py`(또는 전체 파이프라인)
를 다시 실행해야 한다.

## 완료: 과제 이력의 과제명을 참여 당시 실제 이름으로 보정(the_task_name)

"tasks.csv의 과제 이력이 과거 참여 당시 이름이 아니라 현재(최신) 과제명으로
표시되는 문제" — 예: 지금은 2DM인 과제가 예전엔 GRAPH였는데, 과거 참여
기간도 전부 "2DM"으로 나옴(tasks.csv 원본 자체가 과제코드 기준 "현재
이름"을 내려주는 원천 시스템 특성). 문답으로 확정된 해결책은 tasks.csv
행을 개명 시점 기준으로 **여러 구간으로 쪼개는** 것 — 처음 제안(컬럼 하나
추가, 1행=1값)보다 큰 변경으로, 사용자가 직접 예시를 만들어 확정:
GROTH(2019-02-01 기록)/GRAPH(2020-06-01 기록)/2DM(2023-01-01 기록) 이력이
있고 참여기간이 2019-06-01~2023-02-01이면 → GROTH(2019-06-01~2020-05-31),
GRAPH(2020-06-01~2022-12-31), 2DM(2023-01-01~2023-02-01) 3구간으로 분리.
매핑 실패/이력 없음/참여 시작 이전 이력 없음은 전부 원본 task_name 그대로
폴백(정보 유실 방지, 확정). 반영 범위는 과제 이력이 보이는 모든 곳
(타임라인 막대·과제 표·엑셀 다운로드) 전부.

**핵심 아이디어**: `tasks_information.csv`(process_task_information.py)는
이미 "task_code가 같아도 task_name이 다르면(개명) 별도 행으로 보존"하고
`task_name` 기준 중복 제거가 되어 있어(1개 task_name = 1개 task_code
보장), 이 파일이 곧 "이 과제코드가 시간에 따라 어떻게 불렸는지"의
이력 데이터베이스 역할을 한다. 파이프라인 순서도 이미
`process_task_information.py`(5번)가 `process_tasks.py`(9-6번)보다
먼저 실행되므로, 순서를 바꿀 필요 없이 `process_tasks.py`가 그 결과물을
그대로 읽어 쓰면 된다.

**`pipeline/process_tasks.py`**: 기존 `_merge_consecutive_periods()`(연속
참여기간 병합, 안 건드림) 직후에 새 단계 `_apply_name_history()`를 추가.
- `_read_tasks_information()` — `tasks_information.csv`를 읽되 없으면
  빈 DataFrame(그래프 폴백 트리거).
- `_name_to_code_map(tasks_info_df)` — `task_name → task_code`
  (`components/timeline_data.py`의 기존 `task_code_map()`과 같은 로직,
  pipeline 스크립트는 관례상 `components/`를 안 끌어써서 여기 별도로
  작게 구현).
- `_code_to_history_map(tasks_info_df)` — `task_code → [(write_date,
  task_name), ...]`(write_date 오름차순 정렬, write_date/task_name 둘 다
  있는 행만).
- `_split_by_name_history(task_name, start, end, name_to_code,
  code_history)` — 핵심 로직. 참여 종료일 이후에 생긴 개명은 무관하므로
  제외하고, "참여 시작 시점에 이미 있던 가장 최근 이름"부터 시작해서
  그 이후 각 write_date를 구간 경계로 삼아 쪼갠다(경계 사이는 "다음
  경계 write_date - 1일"까지). 시작 시점보다 이전 이력이 아예 없으면
  그 구간(시작일 ~ 첫 기록 직전)은 원본 task_name으로 채운다(사용자 확정
  폴백 규칙을 부분 구간에도 적용 — 명시적으로 물어보진 않았지만 "모르면
  원본 그대로"의 자연스러운 연장으로 판단, 다르게 원하시면 이 함수의
  `start_name` 계산부만 고치면 됨).
- `_apply_name_history(df)` — tasks.csv의 각 행을 위 함수로 쪼개
  `task_code`/`the_task_name` 컬럼이 추가된(그리고 개명 이력이 있으면
  행 수가 늘어난) 새 DataFrame을 만든다. `researcher_id`/`task_name`
  (원본)/`input_rate`는 쪼개진 모든 구간에 그대로 복제.
- `process()`에 이 단계를 연결하고, 행 수가 늘어나면 로그로 알림.

**반영 3곳**(전부 `the_task_name`이 있으면 그걸, 없으면(구버전 CSV/매핑
실패) 원본 `task_name`으로 폴백):
- `components/timeline_data.py`의 `task_points()`(타임라인 스파인 막대).
- `components/profile_sections.py`의 `tasks_block()`(과제 이력 표) — 이
  참에 재사용을 위해 `_clean_grade()`(평가 셀 NaN 정리용으로 이전에
  만든 헬퍼)를 `_clean_str()`로 이름만 일반화(동작 변경 없음, 4곳 모두
  치환).
- `services/researcher_profile_export.py`의 `_col_tasks()`(엑셀 과제수행이력).

검증: `_split_by_name_history()`를 사용자 예시 그대로 호출해 3구간
경계(2020-05-31/2020-06-01, 2022-12-31/2023-01-01 등 하루 단위 경계)가
정확히 일치하는지 확인. 추가로 5가지 경계 케이스(참여 시작이 전체 이력보다
이름/진행중(end 없음)/개명 없음(단일 구간)/task_name 매핑 실패/start_date
자체 없음)를 직접 호출해 전부 기대한 폴백대로 동작하는지 확인.
`_apply_name_history()`를 2명(한 명은 개명 있음 → 3행, 한 명은 개명
없음 → 1행) 목 DataFrame으로 확인. `process()` 전체를 raw 소스 +
`tasks_information.csv` 둘 다 목 데이터로 몬키패치해 실행 → 저장된
tasks.csv가 정확히 3행으로 쪼개지는지 확인. `tasks_information.csv`가
아예 없는 상태로도 `process()`를 실행해 에러 없이 `the_task_name=
task_name` 그대로(행 수 안 늘어남) 폴백하는지 확인. 쪼개진 3행짜리
결과를 `task_points()`/`tasks_block()`/`_col_tasks()` 세 곳 모두에
직접 통과시켜 GROTH/GRAPH/2DM이 각자의 기간으로 정확히 나오는지, 옛날
형식(the_task_name 컬럼 자체가 없는) 데이터도 원본 task_name으로
문제없이 표시되는지 확인. 이번 세션 컨테이너엔 실제 원본 데이터가 없어
`python pipeline/process_tasks.py`(tasks_information.csv가 먼저 있어야
함) 실제 재실행·브라우저 확인은 못 했다.

## 완료(1단계: 데이터 레이어): 전량 덮어쓰기 → 업서트(upsert) 전환 + data/updates 폴더 신설 + researchers.csv 시점(valid_year/valid_month)·is_current·researchers_history.csv

지금까지 파이프라인은 매 실행마다 `data/processed/*.csv`를 통째로 새로
써서, 예를 들어 이번 달 `인력현황.xlsx`에 없는 사람(다른 사업부로 전배 등)은
다음 실행부터 그냥 사라졌다. 실 데이터 운영(주기적 파일 교체/적재)을
시작하는 시점이라, "같은 사람은 최신 값으로 교체하되, 이번 파일에 없는
사람은 삭제하지 않고 보존"하는 업서트 방식으로 데이터 레이어 전체를
바꿨다. 두 가지 요청을 하나의 설계로 묶어 처리했다:

1. **데이터 적재를 업서트로 전환** — `data/raw/`는 그대로 두고, 별도
   `data/updates/` 폴더에 최신 파일(raw와 동일 파일명)을 넣으면 그 파일이
   가진 사람/이벤트만 기존 `data/processed/*.csv`에 업서트되고, 나머지는
   보존된다. 이력형(1인 N행) 테이블은 자연키(natural key) 추천을 요청받아
   테이블별로 정했다(아래 "자연키 등록부" 참고).
2. **`researchers.csv`에 시점(연/월) 도입** — `인력현황.xlsx`의
   `인원실적년도`/`인원실적월`을 `valid_year`(YYYY)/`valid_month`(MM)로
   저장하고, `(researcher_id, valid_year, valid_month)`가 같으면 교체,
   다르면 누적하는 히스토리를 별도로 쌓는다. 전배로 최신 파일에서 빠진
   사람은 "최신월과 다른 시점에 머물러 있음"으로 자동 판별한다
   (`is_current`).

설계 갈림길: `researchers.csv` 자체를 다건화(1인 N행, 이력 전체)할지,
아니면 "현재상태"와 "이력"을 분리할지 상의했고, **분리하는 쪽으로
확정**했다 — `researchers.csv`를 읽는 화면(연구원 명단/보유 전문성
조직도/JOB Market/유사 매칭/AI 검색/엑셀 다운로드/전문성 분석 파이프라인
전부)이 여전히 "1인 1행"을 가정하고 있어, 다건화하면 그 전부를 고쳐야
하기 때문. 대신:

- **`researchers.csv`(기존 유지, 1인 1행 "현재상태")** — `researcher_id`
  키로 업서트: 새 파일에 있으면 행 전체 교체, 없으면 이전 행 그대로 보존.
  병합 뒤 파일 전체에서 `(valid_year, valid_month)`의 최댓값(=가장 최근
  인원실적월)을 구해 각 행에 `is_current`(Y/N)를 다시 계산해 채운다 — 그
  행이 최신월과 같으면 `Y`(현재 소속), 다르면(더 과거에 머물러 있으면)
  `N`(현재 미소속 — 전배·퇴사를 구분하진 못하지만 "지금 우리 조직 소속이
  아님"은 알 수 있다). valid_year/valid_month가 비어있는 행(구버전 데이터,
  또는 원본에 해당 컬럼이 없는 경우)은 판단 근거가 없어 항상 `Y`.
- **`researchers_history.csv`(신규)** — `(researcher_id, valid_year,
  valid_month)` 키로 계속 누적(같은 키는 교체, 다른 키는 새 행, 절대
  삭제 없음). "누적기준"(한 번이라도 등록된 적 있는 전체 인원, 월별
  스냅샷) 검색 전용이며, 이 파일이 생겨도 기존 화면은 전혀 영향받지
  않는다.

**`pipeline/merge_utils.py`(신규)** — 공용 업서트 유틸리티.
- `upsert_merge(existing, new, keys)`: keys가 일치하는 행은 new 값으로
  완전 교체, existing에만 있는 키는 보존, new에만 있는 키는 추가. new
  안에서 키가 중복되면 마지막 행 채택. new가 0행이면 existing을
  보존하되(진짜 없는 게 없으면), existing마저 없으면(최초 실행) new의
  컬럼 구조라도 살려 반환 — 안 그러면 헤더 없는 빈 CSV가 만들어지는
  버그가 있었다(초기 구현에서 발견해 수정, 아래 검증 참고).
- `group_replace_merge(existing, new, group_keys)`: group_keys가 일치하는
  기존 행들을 통째로 지우고 new로 교체 — 행 안에 개별 식별자가 없는
  테이블(평가자 1인 1행인 `leadership_comments.csv`) 전용.
- `write_merged(out_path, new, keys, group_replace=False)`: 기존 CSV
  읽기 → 병합 → 저장까지 한 번에 처리하는 편의 함수. 각 `process_*.py`의
  `result.to_csv(...)` 한 줄을 이걸로 바꾸면 된다.
- `TABLE_KEYS`/`GROUP_REPLACE_KEYS`: 테이블별 자연키 등록부(한 곳에서
  관리, 아래 표).

**자연키 등록부(`TABLE_KEYS`)**:

| 테이블 | 자연키 | 비고 |
|---|---|---|
| researchers | researcher_id | 1인 1행 "현재상태" |
| researchers_history | researcher_id, valid_year, valid_month | 신규, 월별 스냅샷 누적 |
| evaluations / tech_ownership / job_profile / work_objective | researcher_id | 1인 1행(wide) |
| hr_orders | researcher_id, order_date, order_name | |
| tasks | researcher_id, task_name, start_date | the_task_name 분리 후에도 구간별 start_date가 달라 키 유지됨 |
| patents | application_id, researcher_id | 특허 1건에 발명자 여러 명 = 여러 행 |
| publications | researcher_id, title, pub_date | |
| awards | researcher_id, award_date, award_name | |
| nurturing | researcher_id, start_date, category | |
| core_technology | researcher_id, tech_field, tech_name | 1인당 여러 핵심기술 가능(1인1행 아님, 코드로 확인) |
| education | researcher_id, degree | 학사/석사/박사 각 1건 |
| incentive_selection | researcher_id, year | |
| leadership | researcher_id, year, evaluator_group | |
| comments | researcher_id, year, commenter_type | |
| tasks_information | task_name | 기존 `_dedupe_by_name()`과 동일 기준 |
| project_confl_address | dep_name, project_name | |
| technology_transfer / transfers / certifications / succession | (raw 컬럼 기준 추정 키) | 전용 처리기 없이 `_raw` 폴백만 지원 — 아래 참고 |
| leadership_comments | researcher_id, year, evaluator_group (그룹 단위 교체) | 평가자 개별 식별자가 없어 GROUP_REPLACE_KEYS 사용 |

**수정한 처리기(17개, 전부 동일 패턴)**: `process()`에 `raw_dir: str =
RAW_DIR` 매개변수를 추가(기본은 기존과 동일한 `data/raw`, `data/updates`를
넘기면 그 폴더만 읽음)하고, 마지막 `result.to_csv(out_path, ...)`를
`merge_utils.write_merged(out_path, result, TABLE_KEYS['테이블명'])`로
교체했다 — `process_researchers`, `process_tp_evaluation`(evaluations),
`process_patents`, `process_personnel_orders`(hr_orders),
`process_nurturing`, `process_task_information`(tasks_information),
`process_awards`, `process_education`, `process_leadership`(leadership +
leadership_comments, 후자는 group_replace), `process_incentive`
(incentive_selection), `process_tech_ownership`, `process_job_profile`,
`process_work_objective`, `process_publications`, `process_tasks`,
`process_comments`(comments), `process_project_confl`
(project_confl_address). `SOURCE`/`OUTPUT`처럼 모듈 로드 시점에 `RAW_DIR`을
써서 경로를 고정해버리던 3개 파일(`process_publications`/`process_tasks`
는 `SOURCE_FILE` 상수 + 함수 안에서 `os.path.join(raw_dir, ...)`으로,
`process_work_objective`는 `_read_year_file()`에 `raw_dir` 인자를 추가로
전달하도록)도 함께 고쳤다. 더 이상 안 쓰는 `import csv`(각자 자기 CSV를
직접 쓰던 줄이 `write_merged` 호출로 바뀌며 필요 없어짐)도 제거.

**`pipeline/run_pipeline.py`**: `_run_with_fallback()`(전용 처리기 실패 시
`{table}_raw` 폴백)와 맨 끝 `TABLES` 루프(전용 처리기 자체가 없는
technology_transfer/transfers/certifications/succession, raw 컬럼을
그대로 쓰는 4개)도 `TABLE_KEYS`에 키가 등록돼 있고 실제 컬럼에 그 키가
있으면 업서트, 없으면(raw 스키마가 예상과 다르면) 기존처럼 전체 교체로
안전하게 폴백하도록 고쳤다. 이 4개는 전용 컬럼 매핑이 없어 raw 파일
컬럼명이 곧 출력 컬럼명이라는 전제로 키를 추정해뒀다(실제 raw 파일이
준비되면 확인 필요).

**`pipeline/process_researchers.py`**: 위 공통 패턴에 더해 valid_year/
valid_month 추출(`COL_VALID_YEAR='인원실적년도'`, `COL_VALID_MONTH=
'인원실적월'`, 각각 4자리/2자리 문자열로 정규화), `_compute_is_current()`
(병합된 전체 파일에서 최신 (valid_year, valid_month)를 구해 `is_current`
재계산), `researchers_history.csv` 누적 저장(같은 `process()` 호출
안에서 researchers.csv 저장 직후 이어서 실행)을 추가했다.

**`pipeline/paths.py`**: `UPDATES_DIR = data/updates` 신규.

**`pipeline/run_update.py`(신규)**: `data/updates/`에 있는 파일명을 보고
해당하는 처리기만 `raw_dir=UPDATES_DIR`로 실행하는 진입점. `data/raw/`는
전혀 읽지도 쓰지도 않는다. 폴더가 비어있거나 예상 파일명과 다르면 안내만
출력하고 끝난다(부분 업데이트 지원 — 이번엔 인력현황만 왔으면 그 파일
하나만 넣고 돌리면 됨).

**검증**: `merge_utils.upsert_merge`/`group_replace_merge`를 목
DataFrame으로 직접 호출해 교체/보존/추가/그룹교체 동작 확인. 실제 xlsx
2개(2026-06 스냅샷 3명, 2026-07 스냅샷에서 1명 전배로 빠지고 1명 CL
변경·1명 신규입사)를 만들어 `process_researchers.process()`를
`data/raw` 대신 임시 폴더로 연달아 실행 — 전배자가 `researchers.csv`에
`is_current='N'`으로 마지막 상태 그대로 남고(삭제 안 됨), 나머지는
`Y`로 정확히 갈리는지, `researchers_history.csv`가 두 시점 스냅샷을
누락 없이 누적하는지(이영희의 CL4→CL5 두 행 모두 보존), 같은 파일을
다시 실행해도 히스토리가 중복 누적되지 않는지(멱등성) 확인. 수정한 17개
처리기 전부 `py_compile` 통과 + 존재하지 않는 폴더로 `process(raw_dir=...)`
직접 호출해 예외 없이 `[SKIP]`으로 정상 종료하는지 일괄 확인.
`run_pipeline.py`/`run_update.py`를 실제로 실행해(원본 파일 없는 이
컨테이너 환경 기준) 에러 없이 끝까지 도는지 확인하던 중, `new`가 0행이지만
컬럼은 있는 경우(예: comments_raw.xlsx도 없고 leadership_comments.csv도
없어 `process_comments`의 `out_df`가 0행인 상황) `upsert_merge`가
`existing`(파일이 아예 없으면 컬럼도 없는 빈 DataFrame)을 그대로
반환해버려 헤더 없는 빈 CSV가 만들어지는 버그를 실제로 재현·확인하고
수정(`len(new) == 0`일 때 `existing`이 비어있으면 `new`를 반환하도록)
— 수정 후 재실행해 `comments.csv`가 정상 헤더로 저장되는지 재확인.
이번 세션 컨테이너에는 실제 원본 xlsx가 없어(`data/raw/`가 통째로
없음), 위 검증은 모두 임시로 만든 목/합성 데이터 기준이다.

**아직 안 한 것(2단계, 다음 작업)**: 연구원 프로필/명단/보유 전문성
조직도/AI 유사 연구원 매칭/AI 검색 5개 화면에 "현재기준 ↔ 누적기준"
토글을 화면별로 독립 배치(사용자 확정)하는 UI 작업 — JOB Market은
후보군 계산을 항상 현재기준으로 고정하고 토글 자체를 넣지 않기로
확정했다. 보유 전문성 조직도는 누적기준일 때 조직도 트리 탐색 대신
이름/사번 검색만 허용하기로 확정. 이 화면 작업은 아직 시작 전이다.

## 2026-08-13: 보유 전문성 요약카드 정리 / 전문성 MAP 숨김 / 연구원 명단 필터 모달화

사용자가 "보유 전문성" 탭(연구원/연구원↔연구원) 요약 카드 스크린샷을 보내며
5가지를 요청: ① 요약카드를 "마지막 갱신" 1개만 남기기(긴 직사각형으로) ②
"전문성 MAP" 탭 숨김(보여주기엔 좋으나 기능상 의미 없음) ③ 연구원 명단
메인 화면 필터를 부서/과제만 남기고 나머지는 별도 모달로 분리 ④
"학력(최종)"을 "학력"으로 표기 변경 ⑤ "연구원"/"연구원 ↔ 연구원" 리포트의
프로필 아이콘 클릭 시 새 창으로도 열 수 있게.

**① 요약카드 축소(`pipeline/process_researcher_expertise.py`,
`pipeline/process_researcher_similarity.py`)**: 두 파일의 `stat_row_html([...])`
호출을 각각 `mmd.coverage_stat(...)`/`(resp_count, ...)`/`(domain_skill_count, ...)`
등 3~4개 항목에서 `mmd.generated_at_stat()` 1개만 남기도록 축소. `.stat-row`가
`grid-template-columns: repeat(auto-fit, minmax(150px,1fr))`라 카드가 1개면
자동으로 전체 폭을 채워 "긴 직사각형"이 되므로 CSS 변경은 불필요했다(Playwright로
독립 HTML 프리뷰 렌더링해 확인). 더 이상 쓰이지 않게 된 `total`/`high_conf`/
`flagged`/`resp_count`/`domain_skill_count` 지역변수도 함께 제거.
`mmd.coverage_stat()` 함수 자체는 다른 리포트(`process_project_expertise.py`
등)가 쓸 수 있어 그대로 둠.

**② 전문성 MAP 탭 숨김(`pages/researcher_similarity_map.py`)**:
`pages/org_comparison.py`/`pages/jd_reconciliation.py`와 동일한
`_FEATURE_HIDDEN` 관례를 이 페이지의 탭 단위로 적용 — `_MAP_TAB_HIDDEN = True`
플래그를 추가해 `layout()`의 `dbc.Tabs` children에서 '전문성 MAP' 탭을
제외하고, `highlight_researcher` URL 쿼리로 진입해도(옛 '📍 전문성 MAP'
아이콘이 쓰던 경로) 더 이상 `map` 탭으로 랜딩하지 않고 '연구원' 탭 기본
진입으로 처리. `_map_tab_content()`/`_umap_subview_content()` 등 실제
구현 코드는 전부 남겨둬 재오픈 시 플래그만 `False`로 바꾸면 된다.

같이 처리해야 했던 부분: "연구원"/"연구원 ↔ 연구원" 리포트 카드 우측 상단의
'📍 전문성 MAP' 아이콘(`pipeline/rd_specialist_markdown.py`의
`map_link_html()`)이 숨겨진 탭으로 이어지는 죽은 링크가 되므로,
`process_researcher_expertise.py`/`process_researcher_similarity.py`의
`card-icons`에서 `mmd.map_link_html(rid)` 호출을 제거(프로필 아이콘만 남김).
`map_link_html()` 함수 자체는 나중에 재오픈할 경우를 위해 그대로 둠.
`pipeline/process_project_expertise.py`가 쓰는 `_personnel_html()`의 유사한
배지 링크는 그 리포트(`project_expertise_analysis.html`) 자체가 어느
`pages/*.py`에서도 임베드되지 않는(앱에서 도달 불가능한) 산출물이라 이번
작업 범위에서 제외 — 그대로 둠.

**③ 연구원 명단 필터 모달화(`pages/researcher_list.py`)**: 메인 화면
드롭다운 행에는 부서/과제만 남기고, 직급/학력/인센티브 드롭다운을 제거한
뒤 그 자리에 '필터' 버튼(`open-filter-btn`)을 추가. 버튼을 누르면 여는
`dbc.Modal`(`filter-modal`)에 직급/직책/성별/학력/전공/재직상태 6개
드롭다운을 배치(`필터 초기화`/`적용` 버튼 포함). 재직상태는
`_build_summary_df()`에 새 컬럼(`researchers.csv`의 `employment_status`
그대로)을 추가해야 필터 대상이 됐다. 직책 드롭다운(`filter-title`)도
새로 추가(기존엔 표에만 표시되고 필터는 없었음).

판단해서 명확히 표시해 둘 부분 두 가지(사용자 지시 원문에 모호함이
있어 임의로 정한 것):
- 사용자가 나열한 모달 필터 목록에 "과제"가 포함돼 있었지만, 같은 문장에서
  "부서, 과제를 남겨두고"라고도 했다 — 과제를 메인 화면과 모달에 중복
  배치하지 않고 메인 화면에만 남겼다(모달에는 과제 없음).
- "인센티브"는 메인 화면 제외 대상으로만 언급됐고, 모달의 필터 목록
  7종(과제/직급/직책/성별/학력/전공/재직상태)에도 포함되지 않아 문자
  그대로는 인센티브 필터 자체가 없어진다 — 그대로 따라 인센티브 필터를
  완전히 제거했다. 되살리고 싶다면 모달에 `filter-incentive` 드롭다운을
  다시 추가하면 된다(엑셀 다운로드의 "인센티브" 관련 데이터 자체는
  안 건드림 — `_build_summary_df()`의 `인센티브` 컬럼은 표에 그대로
  남아있고 표 자체 네이티브 필터로는 여전히 걸러진다).

**필터링에 안 걸리는 나머지 컬럼(사용자 요청 "나머지 컬럼이 뭐가 있는지
확인" 답변)**: `_build_summary_df()`가 만드는 컬럼 중 부서/과제(메인) +
직급/직책/성별/학력/전공/재직상태(모달) 8개를 뺀 나머지 — `이름`(식별자,
필터 대상이 아님), 평가등급 열(`'24평가`/`'25평가`/`'26평가` 등 연도별,
`_EVAL_GRADE_COLUMNS`), `인센티브`(위 사유로 필터는 제거, 컬럼은 유지),
`논문(전체)`/`논문(3년)`/`평균IF`, `특허(출원)`/`특허(등록)`, `수상`. 이
컬럼들은 드롭다운 필터는 없지만 `dash_table`의 네이티브 컬럼 필터 행으로는
계속 걸러진다.

**④ 학력(최종) → 학력**: `pages/researcher_list.py` 전체(행 딕셔너리 키,
`_filter_options()` 호출, 모달 라벨, `update_table()` 필터링 로직)에서
`'학력(최종)'`을 `'학력'`으로 일괄 변경. 다른 파일에는 이 문자열이 코드로
쓰인 곳이 없었다(grep 확인).

**⑤ 프로필 아이콘 새 창 열기(`pipeline/rd_specialist_markdown.py`)**:
`profile_link_html()`(카드 상단, 텍스트 있는 버전)과
`profile_icon_link_html()`(유사 연구원 표 행, 아이콘만) 둘 다 기존
`target="_top"`(iframe 밖 최상위 대시보드로 이동) 링크에 더해
`target="_blank"`(새 창/탭으로 프로필만 열기) 링크(↗)를 나란히 추가.
`.map-link`/`.row-icon-link`는 이미 여러 개 아이콘이 자연스럽게 나란히
붙는 CSS라 추가 스타일 변경 없이 바로 적용됨.

**검증**: `py_compile`로 수정한 5개 파일 전부 문법 확인. 이 컨테이너에는
`data/raw`/실제 인력현황 데이터가 없어(`researchers.csv`조차 없음)
파이프라인을 실제로 재실행해 정적 리포트를 새로 만들 수는 없었다 — 대신
(1) `mmd.stat_row_html([mmd.generated_at_stat()])` + `mmd.profile_link_html()`
를 실제 `CONSOLE_STYLE`과 함께 독립 HTML로 렌더링해 Playwright 스크린샷으로
"긴 직사각형" 카드와 프로필/새창 아이콘 두 개가 나란히 보이는지 직접 확인,
(2) `python3 app.py`를 백그라운드로 띄우고 Playwright로 `/researcher-list`
(필터 버튼 클릭 → 모달에 직급/직책/성별/학력/전공/재직상태 6개 드롭다운 확인 →
적용 버튼으로 모달 닫힘 확인, 메인 화면엔 부서/과제만 남고 '학력(최종)' 문자열
없음 확인)와 `/researcher-similarity-map`(`#expertise-tabs`에 '연구원'/
'연구원 ↔ 연구원' 2개만 남고 '전문성 MAP' 없음 확인)을 직접 조작해 확인했다.
이 환경은 `dbc.themes.BOOTSTRAP` CDN을 못 받아와(네트워크 제한) 스크린샷의
시각 스타일 자체는 깨져 보이지만(Bootstrap CSS 미적용), DOM 구조·라벨·
필터 필드·탭 구성 등 기능적 정확성은 위 방법으로 모두 확인됨.

## 2026-08-13 (2): 보유 전문성 정적 리포트 다크모드 제거

사용자 보고: "보유 전문성" 탭의 연구원/연구원↔연구원(조직도 사이드바 +
연구원 전문성 카드)이 다크모드에 가깝게 어둡게 보임 — 항상 밝게 고정해
달라는 요청.

원인: `pipeline/rd_specialist_markdown.py`의 `CONSOLE_STYLE`(정적 리포트
공용 CSS)에 `@media (prefers-color-scheme: dark)` 분기가 있어, 사용자의
OS/브라우저가 다크모드면 리포트 색상 토큰이 자동으로 어둡게 바뀌었다.
정작 이 리포트를 iframe으로 담는 대시보드 셸(`app.py`,
`dbc.themes.BOOTSTRAP`)은 다크모드를 지원하지 않고 항상 밝은 테마라,
시스템이 다크모드인 사용자만 리포트가 나머지 화면과 어긋나 어둡게 보이는
불일치였다.

수정: `CONSOLE_STYLE`에서 `@media (prefers-color-scheme: dark) { :root {...} }`
블록 전체를 삭제 — `:root`의 라이트 토큰만 남아 시스템 설정과 무관하게
항상 밝게 렌더링된다. "연구원 보유 전문성 분석.html"/"researcher_similarity.html"
등 이 스타일을 공유하는 모든 리포트에 함께 적용됨(별도 CSS 없음).

검증: Playwright 브라우저를 `color_scheme='dark'`로 에뮬레이트하고 사이드바
조직도 + 카드가 포함된 독립 HTML을 렌더링해 스크린샷 — 다크 에뮬레이션
상태에서도 배경/카드/조직도가 모두 밝게 유지되는 것을 확인.

## 2026-08-19: "보유 전문성" 정적 HTML 리포트를 온디맨드 렌더링으로 전환

사용자 문제 제기: "연구원 보유 전문성 분석.html"/"researcher_similarity.html"이
`data/processed/`(운영 서버)에 완성된 리포트 그대로 저장돼 있으면, 화면에만
적용되는 역할 기반 접근 제어(`services/auth.py`)를 거치지 않고 서버 계정을 가진
누구나 파일을 직접 열어 원데이터를 볼 수 있는 구멍이 된다 — DB 이관을 마친 지금
이 두 파일도 "필요할 때만 뽑아내는" 방식으로 바꾸는 게 안전하지 않겠냐는 질문.

검토: `pipeline/process_researcher_expertise.py`/`process_researcher_similarity.py`의
`_build_html()`이 순수 함수(파일 I/O 없음, `results`/`researchers_df`(+similarity는
`profile_by_id`)만으로 HTML 문자열을 만듦)임을 확인 — 파일을 안 거치고 화면에서
직접 호출해도 되는 구조였다. 캐싱이 꼭 필요한지 사용자가 "속도상 유리하면 잠긴
캐싱 폴더도 고려" 조건부로 확인해줘서, 별도 벤치마크 스크립트로 실제 조직 규모보다
넉넉한 1500명(유사도는 인당 10건 매칭) 합성 데이터를 만들어 `build_html()` 호출
시간을 측정: 연구원 리포트 평균 32ms, 연구원↔연구원 리포트 평균 185~225ms(둘 다
탭을 열 때 1회만 계산됨). 캐싱 없이도 충분히 빨라 별도 잠금 캐싱 폴더는 만들지
않기로 함.

수정:
- `_build_html()` → `build_html()`로 공개(두 파일 모두 내부 호출부 1곳씩이라
  이름 변경만으로 안전하게 공개 가능했음).
- 두 파이프라인 스크립트 모두 `data/processed/{파일명}.html`(현재본)을 더 이상
  쓰지 않음 — `result_archive.archive_copy()`로 실행 시각이 찍힌 스냅샷만
  `data/processed/result/`(기존 권한 잠금 대상, `scripts/secure_data_permissions.sh`)에
  남긴다. `process_researcher_expertise.py`의 `_write_html()`은 `_archive_html()`로
  이름을 바꿔 이 역할만 하도록 정리(`render_html()`/`--html-only` CLI는 그대로 두되,
  이제는 "화면 갱신"이 아니라 "아카이브 스냅샷 재생성" 용도임을 docstring에 명시).
- `pages/researcher_similarity_map.py`: `_iframe_tab()`이 더 이상
  `data/processed/*.html` 파일을 읽지 않고, 새 `_render_report_html()`이
  `services/data_store.read_expertise_profiles()`/`read_similar_researchers()`/
  `read_processed('researchers')`(DB 우선/파일 폴백, 이미 있던 패턴)로 읽은 데이터를
  `pipeline.process_researcher_expertise.build_html()`/
  `pipeline.process_researcher_similarity.build_html()`에 바로 넘겨 렌더링한다.
  데이터가 없으면(파이프라인 미실행) 기존과 동일하게 안내 Alert. `_REPORT_FILES`
  (report_key → 파일명 dict)는 `_REPORT_TABS`(탭 키 튜플)로 대체 — 이제 파일명이
  필요 없어졌기 때문.

검증: 이 환경에 실제 인력현황 데이터가 없어(`researchers.csv`조차 없음) 5명 규모
합성 픽스처(researchers.csv + 두 JSON)를 `data/processed/`에 임시로 써넣고
`pages.researcher_similarity_map._render_report_html()`을 더미 `dash.Dash` 앱
컨텍스트에서 직접 호출 — 연구원/연구원↔연구원 두 리포트 모두 정상 렌더링되고
합성 데이터의 이름 문자열이 결과 HTML에 포함되는지 확인 후 픽스처 삭제(둘 다
`.gitignore`의 `data/processed/*` 대상이라 커밋되지도 않음). 벤치마크 스크립트는
저장소 밖 스크래치 경로에서 실행.

## 2026-08-19 (2): "과제 전문성 분석" 리포트도 파일로 안 남기고 메일 발송으로 전환

앞 항목("보유 전문성" 정적 HTML → 온디맨드 렌더링)에 이어, 3번째 JSONB 이관
대상인 `project_expertise_analysis`에 대한 사용자 질문: "db에 추가한 jsonb
3개 파일 내용으로 별도의 html없이 모든 화면 렌더링이 가능한 상태인 거지?"

확인 결과: JSON 쪽(`services/jd_reconciliation.py`, `services/job_market.py`)은
원래부터 `data_store.read_project_expertise_analysis()`(DB 우선/파일 폴백)로
JSON만 읽어 화면을 그려서, 애초에 HTML을 거친 적이 없었다. 다만
`pipeline/process_project_expertise.py`가 `project_expertise_analysis.html`을
`data/processed/`에 여전히 저장하고 있었는데, 이건 앱 화면이 읽는 파일이
아니라 그 자체 docstring에 적힌 대로 "앱 밖으로 공유하는 독립적인 정적
페이지"였다 — 즉 대상은 다르지만(화면용이 아니라 배포용) 서버 파일시스템에
누구나 열어볼 수 있는 완성본을 남긴다는 점에서 같은 보안 문제가 남아 있었다.

사용자 결정: "앱 밖에서 쓸 일이 있다면 해당 html을 만들어서 메일로 보내는
형식으로 하고, 파일로 남기지는 않는 게 좋겠어."

수정:
- `pipeline/mailer.py`(신규): SMTP가 아니라 사내 메일 발송 REST API를
  호출한다(사용자가 실제 사내 API 호출부 예시를 직접 제공 —
  `requests.post(url, headers=header, data=json.dumps(payload),
  proxies=proxy, verify=false)`, URL에 `?userId=` 쿼리 파라미터 필요).
  `.env`의 `MAIL_API_URL`/`MAIL_TOKEN`/`MAIL_SYSTEM_ID`/`MAIL_FROM`(전부
  필수) + `MAIL_USER_ID`(기본값 `people.sait`, `.env`에 있으면 덮어씀)로
  `send_html_email(to, subject, html_body)` 제공. payload는
  `{subject, contents, contentType:"html", docSecuType:"PERSONAL",
  sender:{emailAddress}, recipients:[{emailAddress, recipientType:"TO"}]}`,
  headers는 `Authorization: Bearer {MAIL_TOKEN}` + `System-ID` + JSON
  Content-Type(전부 사용자가 지정한 실제 스키마 그대로). `verify=False`와
  프록시 미사용(`{"http": None, "https": None}`)은 이 API 전용으로 코드에
  고정 — 사내 루트 CA가 공인 신뢰 체인에 없어 검증이 실패하기 때문(사용자가
  "이 API만 verify=False로, 제공한 코드 그대로"라고 명시적으로 확인—
  다른 외부 호출(LLM2/Confluence 등)에는 영향 없음). 미설정/발송 실패는
  `MailError`.
- `pipeline/process_project_expertise.py`: `_build_html()` → `build_html()`
  공개(다른 두 리포트와 동일 패턴). `process()`는 더 이상
  `project_expertise_analysis.html`을 파일로 저장하지 않고(JSON/
  project_personnel.csv는 그대로), `result_archive.archive_copy()`로 실행
  이력 스냅샷만 남긴다. 신규 `email_report(recipients)`는 이미 저장된 분석
  결과(DB 우선/파일 폴백, `data_store.read_project_expertise_analysis()`)로
  Confluence/LLM 재분석 없이 리포트를 다시 만들어 메일만 보낸다 — CLI는
  `python pipeline/process_project_expertise.py --email=a@x.com,b@y.com`.
- `.env.example`/`docker-compose.yml`에 `MAIL_*` 섹션 추가.
  `pipeline/run_pipeline.py`의 출력 설명도 함께 갱신.

검증: `requests.post`를 페이크 함수로 몽키패치해 실제 네트워크 호출 없이
(1) `MAIL_API_URL`/`MAIL_TOKEN`/`MAIL_SYSTEM_ID`/`MAIL_FROM` 미설정 시
`MailError` 발생, (2) 정상 설정 시 요청 URL·쿼리(`userId`)·헤더
(`Authorization`/`System-ID`)·payload(제목/본문/발신자/수신자 목록)·
`proxies`/`verify`가 사용자가 지정한 스키마와 정확히 일치하는지, (3)
`MAIL_USER_ID`를 `.env`로 덮어쓸 수 있는지 확인.
`process_project_expertise.email_report()`는 (1) 데이터 없을 때 안내 후
`False` 반환, (2) 5건 규모 합성 픽스처(project_expertise_analysis.json +
project_confl_address.csv)를 `data/processed/`에 임시로 써넣고 실행해
전송될 payload의 `contents`(HTML)에 과제명/인력 이름이 실제로 포함되는지
확인 후 픽스처 삭제(둘 다 `.gitignore`의 `data/processed/*` 대상이라 커밋
대상 아님).

## 2026-08-19 (3): 온디맨드 렌더링 후 조직도가 평면 부서 목록으로 퇴화하는 버그 수정

사용자 보고: "보유 전문성 화면에서 왼쪽에 노출되던 화면이 부서-과제-연구원으로
열리고 닫히는 조직도 형태로 보여졌었는데 지금은 부서 아래에 연구원 명단이
평면으로 열거되는 형식이야." — 앞선 "온디맨드 렌더링 전환"(위 2026-08-19
항목) 이후 생긴 회귀.

원인: `pipeline/process_researcher_expertise.py`/`process_researcher_similarity.py`의
`build_html()`은 좌측 사이드바 조직도를
`mmd.build_org_tree(mmd.read_team_refer(OUT_DIR))`로 만드는데,
`read_team_refer()`가 `data/processed/team_refer.csv`를 파일로만 직접
읽었다(DB 폴백 없음) — `team_refer`는 `load_to_db.py`의 `TABLES`에 애초에
없어서 DB로 이관된 적이 없었기 때문. 예전에는 이 리포트가 파이프라인
CLI(데이터 파일 전체에 접근 가능한 환경)에서 한 번 만들어져 완성된 정적
HTML로 저장됐으므로 문제가 없었지만, 이제는 실행 중인 앱 프로세스가 화면
진입 시마다 `build_html()`을 직접 호출한다 — 앱 서버 쪽에
`team_refer.csv`가 없으면(DB 위주로 배포된 환경이라면 있을 이유가 없음)
`read_team_refer()`가 빈 리스트를 반환해 `org_tree`가 falsy가 되고,
조용히 부서만 있는 평면 목록으로 폴백해버렸다(크래시 없이 그냥 다르게
보임 — 원인 파악이 어려운 종류의 회귀).

수정:
- `pipeline/load_to_db.py`: `TABLES`에 `team_refer` 추가 — DB로도 이관되게 함.
- `pipeline/rd_specialist_markdown.py`의 `read_team_refer()`: DB(`services.
  data_store.read_processed('team_refer')`)를 먼저 시도하고, 실패/빈 결과일
  때만 기존처럼 `out_dir/team_refer.csv`를 직접 읽는다.

**부수 버그(수정 과정에서 발견)**: `read_processed()`는 `researcher_id`
컬럼만 명시적으로 문자열화하고, DB 미설정 상태로 CSV를 직접 읽을 때는
`researcher_id`가 아닌 다른 컬럼의 빈 셀을 `.fillna('')`하지 않는다 —
즉 pandas가 빈 셀을 float NaN으로 남긴다. `team_refer.csv`는 최상위
조직(upper_dep_id가 원래 비어 있음, 예외가 아니라 정상 케이스)이 있어
이 NaN이 자주 나오는데, `build_org_tree()`가 `row.get('upper_dep_id')`에
바로 `.strip()`을 호출해서(`NaN or ''` → NaN, NaN은 참으로 취급돼 `or`가
안 걸러줌) `AttributeError: 'float' object has no attribute 'strip'`로
크래시했다. `read_team_refer()`에서 `read_processed()` 결과에
`.fillna('')`를 한 번 더 적용해 해결.

검증: 실제 로컬 PostgreSQL 16으로 (1) CSV 전용(DB 미설정) 폴백 경로 —
최상위 노드의 빈 upper_dep_id로 크래시 재현 후 수정 확인, (2) DB 경로 —
`team_refer.csv`를 디스크에서 완전히 지운 뒤(배포 환경에서 이 파일이
없는 상황 재현) DB만으로 2단 조직도(플랫폼A → 과제1팀)가 정확히
복원되는지, (3) 파일도 DB도 없을 때 빈 리스트를 반환하는지 확인. 마지막
으로 `pages.researcher_similarity_map._render_report_html('researcher')`를
직접 호출해 두 경로 모두 결과 HTML에 `org-tree` 클래스와 실제 조직명
("과제1팀")이 포함되는지(평면 폴백이 아닌지) 확인.

## 2026-08-20: 개별 연구원 전문성 메일 발송 + 프로필 링크 404 수정

**프로필 링크 404**: 사용자 보고 — "보유 전문성 화면에서 프로필 버튼 클릭하면
404 error가 떠". 원인: `pages/researcher_profile.py`의 `dash.register_page()`
경로가 과거 어느 시점에 `/researcher-profile` → `/`로 바뀌었는데(git log로
확인), `pipeline/rd_specialist_markdown.py`의 `profile_link_html()`/
`profile_icon_link_html()`과 `pages/researcher_similarity_map.py`의 누적기준
카드 3곳이 옛 경로(`/researcher-profile?id=...`)를 그대로 쓰고 있었다 —
모두 `/?id=...`로 수정(쿼리 파라미터 이름 `id`는 그대로, 경로만 교정).

**개별 연구원 전문성 메일 발송**: 사용자 요청 — "과제 전문성 분석 리포트
보다는 개별 연구원 전문성에 대해 조회된 내용을 메일로 보내는 기능을
만들어줘." 확인 질문으로 범위 확정: (1) 위치 = "보유 전문성" 탭의 개별
카드마다, (2) 권한 = 그 프로필을 조회할 수 있는 사람 누구나(admin 게이트
없음 — 이미 화면에서 조회 가능한 정보라서), (3) 내용 = 보유 전문성 +
유사 연구원 매칭 결과 둘 다.

수정:
- `pipeline/process_researcher_expertise.py`: `_researcher_card_html()` →
  `researcher_card_html()` 공개(anchor 기본값 ''), card-icons에
  `mmd.mail_link_html(rid)` 추가.
- `pipeline/process_researcher_similarity.py`: 카드 렌더링 로직을
  `researcher_match_card_html()`로 추출·공개(기존 build_html() 루프는 이제
  이 함수를 호출), card-icons에 `mmd.mail_link_html(rid)` 추가.
- `pipeline/rd_specialist_markdown.py`: `mail_link_html(researcher_id)`
  신규(정적 리포트는 iframe 안이라 콜백을 못 붙이므로, profile_link_html()과
  동일하게 target="_top" 이동 — `/researcher-similarity-map?mail_rid=...`로
  최상위 대시보드를 이동시키면 그 화면이 메일 발송 모달을 연다).
  `mail_page(title, body_html)` 신규 — console_page()와 같은 CONSOLE_STYLE을
  재사용하되 조직도 사이드바·JS 없는 단순 셸(이메일 본문용).
- `services/similarity_map.py`: `build_researcher_mail_html(rid)` 신규 —
  `read_expertise_profiles()`/`read_similar_researchers()`(DB 우선/파일
  폴백)로 한 사람의 보유 전문성 카드 + 유사 연구원 매칭 카드 2장만 뽑아
  `mail_page()`로 감싼다. 데이터 없으면 None.
- `pages/researcher_similarity_map.py`: `layout()`에 `mail_rid` URL 쿼리
  파라미터 추가(있으면 발송 모달을 처음부터 연 채로 진입). 신규
  `_mail_researcher_modal()`(수신자 입력 + 발송 버튼, 권한 게이트 없음).
  "누적기준" 검색 결과 카드(`_render_cumulative_result()`)에도 같은 모달을
  여는 '메일로 보내기' 버튼 추가(이쪽은 이미 Dash 컴포넌트 트리 안이라
  패턴매칭 콜백으로 곧바로 모달을 염 — target="_top" 이동 불필요). 발송
  콜백은 `pipeline.mailer.send_html_email()`을 직접 호출(과제 전문성 리포트
  메일 기능과 달리 `process_project_expertise.py`를 거치지 않으므로, 그
  파일의 bare-import MailError와 dotted-import MailError가 서로 다른
  클래스가 되는 문제(위 8/19 항목 참고)는 여기선 애초에 해당 없음 — 항상
  `pipeline.mailer`에서 `MailError`와 `send_html_email`을 같이 가져옴).

검증: 5명 미만 규모 합성 픽스처(researchers.csv + 두 JSON)로 (1)
`build_researcher_mail_html()`이 대상자 이름/유사 연구원 이름을 포함한
HTML을 만드는지, 데이터 없는 사번엔 None을 반환하는지 (2) 정적 리포트
HTML(연구원/연구원↔연구원 둘 다)에 `mail_rid=` 링크와 수정된 `/?id=`
프로필 링크가 포함되는지 (3) `layout(mail_rid=...)`가 모달을 열어 둔 채로
반환되는지 (4) 발송 콜백을 직접 호출해 수신자 미입력/대상자 없음/데이터
없음/실제(모킹 아닌) 메일 API 미설정 시 `MailError`/`requests.post`만
모킹한 성공 경로 5가지 모두 확인 (5) 누적기준 카드에 올바른 rid를 담은
패턴매칭 버튼이 포함되는지 확인. 픽스처는 모두 `.gitignore`의
`data/processed/*` 대상이라 커밋되지 않음.

## 2026-08-20 (2): 수신자 미입력 시 본인에게 발송 + MAIL_TIMEOUT 설정 가능

사용자 요청: "메일 발송할 때 메일 주소를 입력 없이 발송하면 로그인한
본인에게 발송되도록 해줘. 수신인 주소를 로그인 ID@samsung.com 으로
설정하도록 하면 돼." (겸사겸사 실제 발송 테스트 중 timeout error 보고.)

수정:
- `services/auth.py`: `current_user_mail_default()` 신규 —
  `get_current_user()['user_id']` + `@samsung.com`(로그인 세션 없으면 빈
  문자열). 리포트 메일(`pages/admin.py`)과 개별 연구원 메일
  (`pages/researcher_similarity_map.py`) 양쪽 발송 콜백이 공유.
- 두 발송 콜백 모두: 수신자 입력이 비어 있으면 이 기본값을 쓰고, 로그인
  세션조차 없으면(이론상 발생 안 함 — 두 화면 다 로그인 필요) 기존처럼
  "수신자 이메일을 입력하세요" 경고로 폴백. 입력 placeholder와 발송 성공
  알림(실제 수신자 주소 표시)도 함께 갱신.
- `pipeline/mailer.py`: `MAIL_TIMEOUT`(초, 기본 30) 환경변수 추가 — 하드코딩된
  `timeout=30`을 대체. 타임아웃 보고에 대해 사내망 API 응답이 느릴 가능성을
  감안해 값을 조정할 수 있게 함(이 세션 자체는 사내망 밖이라 원인을 직접
  재현/진단할 수 없어, 조정 가능한 손잡이만 제공). `.env.example`/
  `docker-compose.yml`에도 반영.

검증: Flask 세션을 `test_request_context()`로 실제 로그인 상태를 흉내 내
(1) 두 발송 콜백 모두 수신자 공백 시 `{user_id}@samsung.com`으로 실제
발송되는지(payload의 recipients 확인) (2) 세션 없을 때 기존 경고로
폴백하는지 확인. `MAIL_TIMEOUT` 환경변수가 `requests.post()`에 실제로
전달되는지 몽키패치로 확인.

## 2026-08-20 (3): MAIL_API_URL을 base URL로, /mails/send 경로는 코드가 붙이도록 수정

사용자 확인: "보낼 때는 Base URL 뒤에 /mails/send?userId=... 이렇게 붙여야
해." — `.env.example`에 예시로 적어 둔 `MAIL_API_URL=.../api/v1/mail/send`가
실제 엔드포인트 경로와 달랐다(추정으로 채워 넣은 값이라 확인이 필요했음).

수정: `pipeline/mailer.py`가 `MAIL_API_URL`을 base URL로 받아 그 뒤에
`/mails/send?userId=...`를 직접 이어붙이도록 변경(`base_url.rstrip('/')`로
끝에 슬래시가 있어도/없어도 동일하게 동작). `.env.example`의 예시값과
설명도 base URL만 넣으면 된다는 것으로 갱신.

검증: base URL에 슬래시가 있는 경우/없는 경우 둘 다
`{base}/mails/send?userId=...` 형태로 정확히 만들어지는지 몽키패치로
확인. 과제 전문성 분석 리포트 메일 발송 경로 전체(email_report() →
mailer.send_html_email())를 실행해 최종 요청 URL이 올바른지 재확인.

## 2026-08-20 (4): 메일 본문에서 프로필/메일 발송 링크 제거

사용자 보고: "메일이 잘 온다. 그런데 메일 내에 프로필과 메일 보내기
링크가 포함되어 있어. 그건 빼주는 게 좋겠음."

원인: 카드 렌더러(`researcher_card_html()`/`researcher_match_card_html()`/
`project_card_html()`/`_personnel_html()`/`_match_row_html()`)가 항상
`mmd.profile_link_html()`/`mmd.mail_link_html()`/전문성 MAP 링크를 붙였는데,
이 링크들은 전부 `target="_top"` + 상대경로(`/?id=...`, `/researcher-
similarity-map?...`)라 앱의 iframe/최상위 문서 안에서만 의미가 있다 —
메일 클라이언트에서 열면 깨진 링크가 된다.

수정: 위 5개 렌더러 전부에 `include_links: bool = True` 파라미터를 추가해
false면 링크 없이(사번 텍스트만 남기거나 아이콘 자체를 생략) 렌더링하도록
바꿨다. 메일 경로만 `include_links=False`로 호출:
- `services/similarity_map.py`의 `build_researcher_mail_html()`(개별
  연구원 메일)
- `pipeline/process_project_expertise.py`의 `email_report()`(과제 전문성
  분석 리포트 메일)
라이브 앱이 읽는 `build_html()` 경로(iframe 리포트)는 인자를 안 넘겨
기존처럼 링크가 그대로 나온다.

검증: (1) `build_researcher_mail_html()` 결과에 실제 `<a class="map-link">`/
`<a class="row-icon-link">` 앵커나 `href="/?id="`/`href="/researcher-
similarity-map`가 전혀 없는지(카드 내용·이름은 그대로 남아 있는지) (2)
`email_report()`의 전송 payload에 `highlight_researcher` 링크가 없고
사번 텍스트만 남는지 (3) 라이브 앱의 `_render_report_html()`은 여전히
`mail_rid=`/`/?id=` 링크를 포함하는지(회귀 아님) 확인. 첫 시도에서
`'map-link' not in html_out` 같은 단순 문자열 검사가 실패했는데, 이는
버그가 아니라 재사용 중인 CONSOLE_STYLE 안의 `.map-link` CSS 클래스 정의
자체가 문자열로 걸린 것(실제 `<a>` 태그는 없음) — 검증을 `href=`/`<a
class=` 단위로 다시 짜서 확인했다.

## 2026-08-20 (5): 개별 프로필 카드(A4 인쇄 내용) PDF 첨부 메일 발송

사용자 요청: "개인별 프로필 카드(A4 인쇄되는 내용을 pdf로 저장)도 메일에
첨부해 발송할 수 있는 기능을 만들어 줄 수 있어?" 확인 질문으로 두 가지
결정: (1) 메일 API가 실제로 첨부파일을 지원하며, 사용자가 실제 호출
코드(`requests.post(url, data=[('mail', (None, json.dumps(payload)))],
files=[('attachments', fileobj), ...])`)를 그대로 제공 (2) PDF는 헤드리스
브라우저(Playwright)로 화면과 100% 동일하게 만들기로 함(경량 HTML→PDF
라이브러리 대신 — Docker 이미지가 커지는 대신 인쇄 결과와 완전히 같음).

**PDF 생성**: `pages/researcher_profile.py`의 "프로필 인쇄 (A4)"는 원래
브라우저 안에서만 동작(`window.print()` + 논문/특허 표를 실제 렌더링
높이로 재서 페이지 예산에 맞게 자르는 동적 JS)했는데, 서버 쪽에서도 같은
결과를 얻어야 해서:
- 그 준비 로직(A4 `@page` 오버라이드 + 표 실측 자르기)을 `assets/
  profile_print.js`의 `window.__prepareProfilePrint()`로 추출(Dash가
  `assets/`의 .js를 모든 페이지에 자동으로 실어줌) — 버튼 클릭 콜백은 이
  함수를 부른 뒤 그대로 `window.print()`까지 이어간다(동작 100% 동일,
  단순 리팩터링).
- `services/profile_pdf.py`(신규): 헤드리스 Chromium이 앱 자기 자신에게
  `http://127.0.0.1:{PORT}/?id=...`로 재접속해(같은 컨테이너 안 서버사이드
  렌더링 패턴) `window.__prepareProfilePrint()`만 호출(`window.print()`는
  호출 안 함 — 헤드리스에서 의미 없고 afterprint 정리 타이밍과 경쟁할
  위험만 있음)한 뒤 `page.pdf(prefer_css_page_size=True)`로 캡처. 앱이
  로그인을 요구하므로(`app.py`의 `require_login`), 호출부(현재 로그인된
  사용자의 Flask `session` 쿠키)가 그 쿠키 값을 그대로 넘겨 헤드리스
  브라우저 컨텍스트에 심는다 — 서버사이드 세션 저장소 없이 서명된
  쿠키만으로 인증하므로 같은 프로세스(같은 SECRET_KEY)가 그대로 검증.

**메일 첨부**: `pipeline/mailer.py`의 `send_html_email()`에
`attachments: list[tuple[str, bytes]] | None` 파라미터 추가 — 있으면
JSON 단일 바디 대신 멀티파트로 전환(`data=[('mail', (None,
json.dumps(payload)))]` + `files=[('attachments', (name, content)), ...]`,
Content-Type 헤더는 requests가 boundary와 함께 자동 설정하도록 직접
지정한 `application/json` 값을 빼야 함). 첨부 없을 때(기존 두 메일
기능)는 완전히 동일하게 동작.

**UI**: `pages/researcher_profile.py`의 "프로필 인쇄 (A4)" 버튼 옆에
"메일로 보내기 (PDF 첨부)" 버튼 + 모달 추가. 수신자 비워두면 본인
(`current_user_mail_default()`, 앞서 만든 다른 메일 기능과 동일 원칙)에게
발송. 별도 권한 게이트 없음(이미 이 화면에서 조회 가능한 정보).

**인프라**: `requirements.txt`에 `playwright` 추가, `Dockerfile`에
`playwright install --with-deps chromium` 단계 추가(+300MB 안팎, Chromium
바이너리를 사내 프록시로 내려받아야 해서 사내망에서 막혀 있으면 이
단계에서 빌드가 실패할 수 있음 — 그 경우 PDF 첨부 기능만 비활성 상태로
두고 나머지는 그대로 배포 가능, Dockerfile 주석 참고).

검증: `pipeline/generate_sample_data.py`로 실제 50명 샘플 데이터를 만들고,
`python3 app.py`로 앱을 실제로 띄운 뒤(포트 8765) HTTP 로그인으로 진짜
세션 쿠키를 발급받아 — (1) `services/profile_pdf.render_profile_pdf()`를
직접 호출해 2페이지짜리 실제 PDF(사진/기본정보/학력/평가/전문성 1페이지
+ 논문·특허 상세 표 2페이지)가 만들어지는지 Read 도구로 PDF 내용까지
확인 (2) `pages.researcher_profile._send_profile_mail()` 콜백을 실제 Flask
세션 컨텍스트(쿠키를 진짜 SECRET_KEY로 디코딩)에서 호출해 수신자
공백→본인 발송 기본값, PDF 첨부, `requests.post`(모킹) 호출 시
멀티파트 형태가 사용자가 준 스키마와 정확히 일치하는지 확인 (3) 실제
Playwright 브라우저로 "메일로 보내기" 버튼을 클릭해 모달이 실제로 열리고
입력 필드가 반응하는지 확인. 첫 시도에서 `wait_for_selector`가 기본값
(visible)으로 대기해 `.profile-print-only`(화면에서 항상 display:none)를
영원히 못 찾고 타임아웃난 버그를 발견해 `state='attached'`로 수정.

## 2026-08-20 (6): Playwright 브라우저 설치 실패해도 전체 빌드는 계속되도록 수정

사용자 보고: "docker compose하는 과정에서 fail이 뜨네" —
`playwright install --with-deps chromium`(exit code 1)에서 빌드 자체가
멈춤. 미리 안내한 그대로(위 2026-08-20 (5) 항목의 Dockerfile 주석) 사내망이
Playwright의 Chromium 다운로드 호스트(Microsoft CDN — pip이 쓰는
repository.samsungds.net과는 다른 별도 외부 호스트)를 막고 있을 가능성이
높다.

수정: `RUN ... playwright install --with-deps chromium` 뒤에
`|| echo "..."`를 붙여, 이 단계가 실패해도 Dockerfile 전체가 실패하지
않고 계속 진행되게 했다 — PDF 첨부 메일 기능만 "PDF 생성 실패"로
비활성화된 채, 나머지 모든 기능(개별/과제 리포트 메일 발송 포함, PDF
첨부만 못 함)은 정상 빌드·배포된다. 근본 해결(사내망에서 Chromium
다운로드 호스트 허용, 또는 PLAYWRIGHT_DOWNLOAD_HOST로 사내 미러 지정)은
네트워크 담당자 확인이 필요해 사용자에게 맡김.

검증: 이 샌드박스에는 docker 데몬이 없어 실제 빌드 재현은 불가 — Dockerfile
문법(RUN 안 셸 `||` 체인)만 직접 검토. 데몬 접근이 되면
`docker compose build --progress=plain`으로 실제 실패 로그를 받아 근본
원인(프록시 차단/apt 문제 등)을 추가로 진단하기로 함.

## 2026-08-20 (7): Playwright 브라우저 설치 시 Node.js TLS 인증서 오류 수정

사용자 보고: "Error: unable to verify the first certificate; if the root
CA is installed locally, try running Node.js with --use-system-ca" —
`playwright install --with-deps chromium`이 빌드를 막지는 않게 됐지만
(위 (6) 항목), 실제 실패 원인이 드러남.

원인: `playwright install`은 내부적으로 Node.js로 브라우저 바이너리를
내려받는데, Node는 Python `requests`(REQUESTS_CA_BUNDLE 환경변수로 이미
사내 루트 CA를 신뢰하도록 설정돼 있음)와 달리 OS 인증서 저장소를 자동으로
쓰지 않는다. 사내망 프록시가 TLS를 가로채는(MITM) 환경이라 Node가 그
프록시의 인증서 체인을 검증하지 못해 실패했다.

수정: `playwright install` 실행 시 `NODE_EXTRA_CA_CERTS=/etc/ssl/certs/
ca-certificates.crt`(Dockerfile이 이미 만들어 둔, 사내 루트 CA가 병합된
동일한 시스템 번들)를 함께 넘겨 Node도 그 인증서를 신뢰하도록 했다. 그래도
실패하면(네트워크 자체가 막혀 있는 경우) 여전히 `|| echo`로 전체 빌드는
계속된다.

검증: 이 샌드박스에는 docker 데몬이 없어 실제 빌드 재현은 불가 —
Dockerfile 문법만 검토. 사용자 환경에서 재빌드로 확인 필요.

## 2026-08-20 (8): NODE_EXTRA_CA_CERTS로도 안 돼 NODE_TLS_REJECT_UNAUTHORIZED=0 추가

사용자 보고: NODE_EXTRA_CA_CERTS(위 (7) 항목) 적용 후 재빌드해도 "동일하게
에러가 나". 재검토 결과, NODE_EXTRA_CA_CERTS는 이 이미지가 사내 루트 CA를
실제로 신뢰 저장소에 갖고 있을 때만 효과가 있는데 — Dockerfile의 CA 등록
단계는 `certs/`에 사용자가 실제로 인증서 파일을 넣어야만 동작하는
옵션(opt-in) 단계이고, 그 뒤에 실행되는 pip install은 `--trusted-host`로
검증 자체를 건너뛰고 있어서 이 이미지가 사내 CA를 실제로 갖고 있는지 여태
검증된 적이 없었다는 걸 깨달음. 즉 `certs/`가 비어 있는 채로 빌드됐다면
NODE_EXTRA_CA_CERTS가 가리키는 번들에도 사내 루트 CA가 없어 그대로
실패한다.

수정: pip의 `--trusted-host`와 같은 원칙으로, `playwright install`에
`NODE_TLS_REJECT_UNAUTHORIZED=0`을 최종 폴백으로 추가 — TLS 인증서 체인
검증 자체를 건너뛴다. 공개 오픈소스 브라우저 바이너리를 받는 이 빌드
단계 하나에만 적용되고(런타임 앱 요청에는 전혀 영향 없음), NODE_EXTRA_CA_CERTS는
그대로 남겨 인증서가 있는 환경에서는 정석대로 검증되도록 유지.

검증: 이 세션에는 docker 데몬이 없어 실제 재빌드는 사용자 환경에서 확인
필요.

## 2026-08-20 (9): 연구원 프로필 카드(A4 인쇄/PDF) UI 폭 6건 수정

Docker 빌드 성공 확인 후 사용자가 연구원 프로필 카드 화면을 보고 6가지를
요청: (1) "보유 전문성 · 보유 기술 · 전문성 요약(LLM)" 박스 제목 제거,
(2) "과제 수행 / 인사 발령 이력" 박스 제목을 "과제 수행 / 인사 발령
이력(최근 10건)"으로 단순화, (3) 양성이력·시상이력이 없을 때 "없음"
문구 대신 빈 칸으로, (4) 보유기술 표의 Lv·보유율 열 가운데 정렬,
(5) 핵심기술 이름이 길어 줄바꿈될 때 이어지는 줄이 등급 배지(B급/A급)
아래로 오지 않고 기술명 시작 위치에 맞춰 들여써지게, (6) 사진을
`data/photo/` 폴더(원본 다운로드 전용, 용량이 커서 `data/raw`와 분리)에서도
읽어오게.

수정 — 모두 pages/researcher_profile.py의 인쇄/PDF 경로(_print_profile_
content)와 그 하위 컴포넌트에 한정, 화면(라이브) 쪽은 그대로 둠(사용자
요청이 "인쇄되는 내용"인 프로필 카드에 한정됐다고 판단):
- `_print_box(None, ...)`로 (1) 제목 생략(_print_box는 title이 falsy면
  제목 div 자체를 안 만듦), (2) 제목 문자열만 교체.
- `components/profile_sections.py`의 `nurturing_block()`/`award_block()`에
  `show_empty_message: bool = True` 파라미터 추가 — False면 빈 이력일 때
  "양성 이력 없음"/"시상 이력 없음" div 대신 None을 반환(→ 렌더 안 됨).
  화면 쪽 호출부(update_profile 콜백)는 그대로 True(기존 동작 유지),
  인쇄 쪽만 False로 호출.
- `components/detail_tabs.py`의 `_tech_ownership_table()` Lv/보유율
  `<Td>`·`<Th>`에 Bootstrap `.text-center` 클래스와 별개로 인라인
  `style={'textAlign': 'center'}`도 함께 줌 — 이 세션에서 반복 확인된
  대로(부트스트랩 CDN이 이 샌드박스에서 막혀 있던 것과 같은 이유로 사내
  운영 컨테이너/헤드리스 PDF 캡처 환경에서도 CDN을 못 받아올 가능성을
  배제 못해, 인쇄/PDF에 중요한 스타일은 유틸리티 클래스만 믿지 않고
  인라인 style로 이중 보장).
- `_core_technology_table()`의 등급 배지+기술명 칸을 flex 레이아웃
  (`d-flex align-items-center`) 대신 CSS hanging indent로 교체:
  `style={'paddingLeft': '44px', 'textIndent': '-44px'}`인 컨테이너 안에
  배지(pill)와 `marginLeft: 6px`인 기술명 span을 나란히 둠. text-indent
  음수값은 첫 줄만 왼쪽으로 당기고(배지가 들어갈 자리), 줄바꿈된 이후
  줄들은 padding-left(44px)를 그대로 받아 기술명 시작 위치에 맞춰
  들여써진다 — 사용자가 그림으로 보여준 "B급 무슨무슨 / (들여쓰기)무슨
  기술" 형태.
- `services/data_store.py`에 `PHOTO_DIR = data/photo` 상수 추가.
  `components/profile_sections.py`의 `load_photo_src()` 탐색 순서를
  `(PHOTO_DIR, assets/photos, RAW_DIR)`로, `app.py`의 `/photo/<rid>`
  라우트(serve_photo)도 동일하게 PHOTO_DIR을 assets/photos보다 먼저
  찾도록 수정 — 둘 다 같은 순서를 유지해야 load_photo_src()가 반환한
  URL이 실제로 서빙된다. `.gitignore`에 `data/photo/`를 `data/raw/`와
  같은 방식으로 추가(원본 사진 파일이 형상관리에 절대 올라가지 않게).

검증: `pipeline/generate_sample_data.py`로 실제 샘플 데이터(연구원 50명)
생성 후 실제 서버 기동 + 실제 로그인(세션 쿠키 획득) + 실제 Playwright
헤드리스로 프로필 인쇄 화면 렌더 확인.
- (1)(2): 렌더된 HTML에 옛 제목 문자열이 없고 새 제목만 있음을 문자열
  검사로 확인.
- (3): awards.csv가 샘플 데이터에서 빈 데이터(0행)로 생성된 것을 이용,
  렌더된 HTML에 "시상 이력 없음" 문자열이 없음을 확인.
- (4): 렌더된 HTML에 Lv/보유율 `<td>`가 `text-align: center` 인라인
  style을 실제로 갖고 있음을 확인.
- (5): core_technology.csv에 두 줄로 줄바꿈될 만큼 긴 핵심기술명을 넣어
  실제로 렌더 후 스크린샷으로 육안 확인 — 줄바꿈된 두 번째 줄이 "B급"
  배지 아래가 아니라 기술명 시작 위치에 맞춰 들여써짐을 확인.
- (6): `data/photo/00000001.png` 테스트 파일을 두고 `/photo/00000001`
  라우트를 직접 호출해 정확히 그 파일이 그대로 서빙됨을 바이트 단위로
  확인(cmp 일치).
- 테스트에 쓴 샘플 데이터·테스트 사진·테스트 계정은 모두 삭제해 원상
  복구(`data/processed/CLAUDE.md`는 보존).

## 2026-08-20 (10): 핵심기술 등급 배지(S급 등) 하얗게 사라지는 버그 수정

사용자 보고: "핵심기술 화면에서 S급 글자가 하얗게 되어서 녹색 동그라미
왼쪽에 위치하고 있는 상태야. 기술 분야 이름이 긴 경우 흰색 글씨 위로
겹쳐서 보이기도 해" — 위 (9)번 항목에서 핵심기술 줄바꿈 hanging indent를
`padding-left: 44px; text-indent: -44px`로 구현했는데, 이게 화면·인쇄본
양쪽 다 실제로 망가뜨리고 있었음.

원인: 등급 배지(`_pill()`)가 `display: inline-block`인데, 첫 줄 맨 앞
요소가 inline-block일 때 음수 text-indent를 주면 브라우저가 그 박스를
단순히 왼쪽으로 옮기는 게 아니라 배지 자신의 렌더링 폭 자체를 잘라낸다
(격리된 재현 HTML로 실측: 의도한 폭 ~44px짜리 배지가 실제로는 20px로
잘려 렌더링됨). 그 결과 "B급"/"S급" 글자가 담긴 왼쪽 부분이 통째로
잘려나가 안 보이고, 초록 배경의 오른쪽 둥근 끝부분만 작은 원처럼 남아
보였다 — 사용자가 본 "하얗게 사라진 글자 + 녹색 동그라미"가 바로 이
현상. 기술분야(field) 열 이름이 길면 그 열의 텍스트가 오른쪽으로 더
늘어나 이 잘린 배지 자리와 시각적으로 겹쳐 보인 것.

수정: `text-indent` 대신 `display: table` / `table-cell` 두 칸(배지 칸 —
`whiteSpace: nowrap`, 텍스트 칸 — `width: 100%`)으로 배치. 각 칸이
독립된 박스라 배지가 잘리는 문제가 없고, 텍스트 칸에서 줄바꿈이 일어나도
그 칸의 폭(배지 칸 오른쪽부터 시작) 안에서만 줄바꿈되므로 요청했던
hanging indent 효과(줄바꿈된 다음 줄이 배지 아래가 아니라 기술명 시작
위치에 맞춰짐)는 그대로 유지된다.

검증: 격리된 HTML(테이블 마크업만 동일하게 재현)로 먼저 버그를
재현(배지 폭 20px로 잘림 확인 — `bounding_box()`로 실측) → table-cell
방식으로 교체 후 재현 HTML에서 정상 렌더링 확인 → 실제 앱에 적용 후
`pipeline/generate_sample_data.py`로 샘플 데이터 생성, core_technology.csv에
긴 기술분야명("반도체시스템연구소 소재개발팀")과 두 줄로 줄바꿈될 만큼
긴 핵심기술명을 넣어 실제 서버 기동 + 로그인 + Playwright로 (a) 화면
쪽(`owned_expertise_block(stacked=False)`, 라이브 프로필 탭)과 (b)
인쇄/PDF 쪽(`stacked=True`) 양쪽 모두 스크린샷으로 "B급" 배지가 완전한
채로 보이고, 줄바꿈된 둘째 줄이 기술명 시작 위치에 맞춰 들여써짐을 육안
확인. 테스트 데이터·서버·계정은 모두 정리.

## 2026-08-20 (11): 사진 확장자가 대문자(.JPG)면 서빙 안 되는 버그 수정

사용자 보고: "사진 확장자가 JPG 대문자인 경우 사진을 못 띄우는 것 같아".

원인: `app.py`의 `/photo/<rid>` 라우트(`serve_photo()`)가 `data/photo/`와
`assets/photos/`를 찾을 때는 `os.path.join(base_dir, f'{r}.{ext}')` +
`os.path.isfile()`로 소문자 확장자(`_IMG_EXTS = ('png','jpg','jpeg')`)
경로를 직접 만들어 확인했다 — 리눅스(운영 컨테이너)는 파일시스템이
대소문자를 구분하므로 실제 파일이 `00000001.JPG`면 `00000001.jpg` 경로는
존재하지 않는 것으로 처리돼 404가 났다. 반면 `RAW_DIR` 폴백 분기와
`components/profile_sections.py`의 `load_photo_src()`(사진 URL이 있는지
먼저 판단하는 쪽)는 애초에 `os.listdir()`로 디렉토리 목록을 읽어 소문자로
비교하는 대소문자 무관 방식이었다 — 그래서 `load_photo_src()`는 사진이
있다고 판단해 `/photo/{rid}` URL을 내려주는데, 정작 그 URL을 실제로
서빙하는 `serve_photo()`는 대문자 확장자를 못 찾아 404가 나는 불일치가
있었다.

수정: `serve_photo()`의 `PHOTO_DIR`/`assets/photos`/`RAW_DIR` 세 디렉토리
모두 `os.listdir()` + 소문자 비교 방식으로 통일 — `load_photo_src()`가
찾은 대로 실제로 서빙되도록 했다.

검증: `data/photo/00000001.JPG`(대문자 확장자) 테스트 파일을 두고 실제
서버 기동 + 로그인 + `/photo/00000001` 라우트를 직접 호출해 수정 전
404였던 것이 수정 후 200(`image/jpeg`, 파일 그대로)으로 바뀜을 확인.
테스트 데이터·서버·계정은 모두 정리.

## 2026-08-20 (12): AI 검색을 연구원 명단 화면 전용으로 제한 + 조직별 비교 메뉴 숨김

사용자 요청: "AI검색이 모든 메뉴에서 보이게 표시되고 있는데, 이걸 연구원
명단 화면에서만 표시되게 해줘. 그리고 조직별 비교 라는 메뉴는 현재는
사용하지 않을 거라 없애주었으면 해."

### AI 검색(자연어 질문 바)을 연구원 명단 화면 전용으로

`app.py`의 `nl_query_bar.render()`는 `dash.page_container` 밖(네비게이션
바로 아래)에 전 화면 공통으로 고정 배치돼 있어서 모든 메뉴에서 항상
보였다. `nl_query_bar`와 그 아래 구분선(`html.Hr`)을 `id='nl-query-bar-
wrapper'`인 Div로 감싸고, `_pages_location.pathname`을 Input으로 받는
콜백(`_toggle_nl_query_bar`, `_navbar-user`를 갱신하는 기존
`refresh_navbar_user`와 같은 패턴)이 경로가 `/researcher-list`(연구원
명단)일 때만 `style={}`(보임), 그 외에는 `{'display': 'none'}`을
돌려주도록 했다. 컴포넌트를 아예 안 그리는 대신 CSS로 숨기는 방식이라
다른 화면으로 옮겨도 입력하던 질문/규칙 설정 상태가 유지된다.

### 조직별 비교 메뉴 숨김

이 저장소에는 이미 "당장 안 쓰는 화면을 완전히 지우지 않고 숨겨두는"
확립된 관례가 있다 — `pages/jd_reconciliation.py`의 `_FEATURE_HIDDEN`
플래그(위쪽 커밋 로그, 재오픈 방법 기록). 동일한 패턴을
`pages/org_comparison.py`에도 적용: `register_page()` 바로 아래에
`_FEATURE_HIDDEN = True`를 추가하고, `layout()` 맨 앞에서 이 플래그가
True면 실제 조직별 비교 화면 대신 `dbc.Alert('이 기능은 현재 준비
중입니다.', ...)`만 반환하도록 했다(페이지 구현 코드 자체는 전부 그대로
남겨둠). `app.py` 네비게이션 바에서 '조직별 비교' `dbc.NavItem`을
제거했다(발견 경로 차단 — URL을 직접 입력해 들어가도 준비중 안내만
보임).

재오픈 방법: `pages/org_comparison.py`의 `_FEATURE_HIDDEN`을 `False`로
바꾸고, 이 커밋에서 지운 `dbc.NavItem`(app.py, 'JOB Market' 바로 위)을
되살리면 된다.

검증: 샘플 데이터 생성 후 실제 서버 기동 + 로그인 + Playwright로
(1) 네비게이션 바 링크 목록에 '조직별 비교'가 없음, (2) `/`(연구원
프로필)·`/researcher-similarity-map`(보유 전문성)에서는 AI 검색
wrapper의 `display: none`, `/researcher-list`(연구원 명단)에서는
`display: block`, (3) `/org-comparison` URL로 직접 이동해도 "이 기능은
현재 준비 중입니다." 안내만 보이고 기존 조직별 비교 콘텐츠("조직별 우수
연구원 비교")는 렌더되지 않음을 각각 확인. 테스트 데이터·서버·계정은
모두 정리.

## 2026-08-20 (13): 연구원 명단 화면 평가등급 색상이 홀수행에서 무시되는 버그 수정

사용자 보고: "연구원 명단 화면에서 평가에 색깔이 입혀지는데 아무런 규칙이
없어 보여."

원인: `pages/researcher_list.py`의 `style_data_conditional`이
`grade_styles(평가등급별 배경색, 열 지정) + [줄무늬(row_index: 'odd'),
활성 셀(state: 'active')]` 순서였다. Dash DataTable은 뒤에 오는 규칙이
같은 셀의 같은 속성을 나중에 덮어쓰는데(먼저 매치돼도 이후 규칙이 우선),
줄무늬 규칙은 열 지정 없이 모든 셀에 적용되는 규칙이라 `grade_styles`
뒤에 오면서 홀수행에서는 등급별 배경색을 전부 무채색 줄무늬 색(#f9fbfd)
으로 덮어버렸다. 그 결과 짝수행은 가/나/다/라/마 등급별 배경색이 정상,
홀수행은 등급과 무관하게 항상 같은 옅은 파란회색이라 — 사용자 입장에서
훑어보면 절반은 등급대로 색이 붙고 절반은 안 붙어 "규칙이 없어 보이는"
상태였다.

수정: 리스트 순서를 바꿔 줄무늬/활성 셀 규칙을 먼저, 열 지정된
`grade_styles`를 나중에 두어 등급 색이 항상 줄무늬 배경 위에 최종
적용되게 했다.

검증: `salary_grade_column()`이 기대하는 실제 와이드 포맷
(`2024_salary_grade` 등)으로 테스트용 `evaluations.csv`를 만들어(연구원
12명에 가/나/다/라/마 5개 등급을 순환 배정) 실제 서버 기동 + 로그인 +
Playwright로 각 평가등급 셀의 실제 렌더링 배경색(`getComputedStyle`)을
읽어, 수정 전에는 홀수행(0-index 기준 1,3,5...)에서 등급과 무관하게 항상
`rgb(249,251,253)`이던 것이 수정 후에는 12개 행 전부 등급별로 정확한
색(가=연두, 나=하늘, 다=노랑, 라=주황, 마=빨강)으로 바뀜을 확인. 평가등급
열이 아닌 '이름' 열은 수정 후에도 홀짝 줄무늬가 그대로 유지됨을 함께
확인(부작용 없음). 테스트 데이터·서버·계정은 모두 정리.

참고: `pipeline/generate_sample_data.py`가 만드는 `evaluations.csv`는
`researcher_id/year/grade/score`의 롱포맷인데, `services/evaluations.py`
의 `salary_grade_column()`은 `{year}_salary_grade` 와이드 컬럼을
기대한다(`pipeline/process_tp_evaluation.py`가 실제로 만드는 포맷) — 샘플
데이터로는 연구원 명단의 평가등급 열이 전부 "-"로만 보인다. 이번 버그와는
무관한 별개 사항이라 이번 수정 범위에는 포함하지 않았다.

## 2026-08-20 (14): AI 검색과 연구원 명단 테이블을 하나로 통합 + 필수 컬럼 축소

사용자 요청: "AI 검색과 아래의 연구원 명단으로 표현되는 테이블 내용이 거의
겹치는 듯하네. 창이 두개라 헷갈리기도 하고... 아래 노출되는 테이블의
필수 컬럼을 좀 줄이고, AI검색의 결과에 따라 동적으로 추가 컬럼이
구성되도록 바꿀 수 있을까?"

AskUserQuestion으로 3가지 확정: (1) 완전 통합 — 명단 자체가 AI 검색
결과로 바뀌는 방식(AI 검색 전용 별도 결과표는 없앰), (2) 필수(항상 노출)
컬럼은 사번/이름/부서/과제/직급/직책/재직상태/Knox ID로 우선 시작, (3) AI
답변 문장은 명단 위에 계속 표시.

### 아키텍처 변경

`components/nl_query_bar.py`는 원래 app.py 최상위 레이아웃(모든 탭 공용)에
떠 있으면서, 자기 자신의 결과를 별도의 표(정렬/필터 드롭다운·체크박스·
엑셀 다운로드까지 갖춘, `pages/researcher_list.py`의 명단 테이블과
거의 동일한 기능을 중복 구현한)로 렌더링했다 — 이게 "창이 두 개" 문제의
원인. 직전 커밋(2026-08-20 (12))에서 이미 AI 검색을 `/researcher-list`
화면 전용으로 제한해뒀던 터라, 이번엔 아예 컴포넌트 자체를
`pages/researcher_list.py` 안으로 옮겨 심고, app.py에서 관련 마운트/
`_toggle_nl_query_bar` 콜백/`nl_query_bar` import를 모두 제거했다.

`components/nl_query_bar.py`는 611줄 → 약 200줄로 대폭 축소:
- 남긴 것: 질문 입력창(질문하기/초기화 버튼), "규칙 설정" 패널, AI 답변
  문장/오류 안내(`nl-query-note`), 결과를 담는 `nl-query-full-result`
  Store.
- 뺀 것: 자체 결과 표 렌더링(`_render_table_body`), 정렬/필터 드롭다운과
  그 콜백들(`_set_sort`/`_set_filters`/`_reset_sort`/`_reset_filters`),
  행 체크박스·전체선택(`_sync_selected`/`_toggle_selectall`), "전체 N건
  보기" 펼치기, 자체 엑셀 다운로드(`_update_excel_button`/
  `_download_excel`) — 전부 명단 테이블이 이미 갖고 있던 기능이라 중복
  이었다.
- 검색 기준(최신/누적) 라디오도 자체적으로 갖지 않고, 같은 화면의
  `list-search-mode`(명단 필터 카드에 이미 있던 라디오)를 State로 공유
  하도록 통일 — 화면에 "검색 기준" 선택지가 두 벌 있던 것도 없앴다.

### 필수 컬럼 축소 + AI 검색 결과의 동적 컬럼 병합

`pages/researcher_list.py`:
- `_build_summary_df()`에 `Knox ID`(researchers.knox_id) 컬럼 추가.
- `_ESSENTIAL_COLUMNS`(사번/이름/부서/과제/직급/직책/재직상태/Knox ID) —
  AI 검색 없이도 항상 노출. 사번은 라벨만 "사번"으로 보여주고 데이터 키는
  `researcher_id` 그대로 둬서(행 클릭 프로필 이동/엑셀 다운로드/일괄
  인쇄가 전부 이 키로 연구원을 식별) 기존 로직을 건드리지 않았다.
  나머지(평가등급/인센티브/논문/특허/수상/성별/학력/전공)는 기본적으로
  숨긴다.
- `_OPTIONAL_FILTER_COLUMNS`(성별/학력/전공) — 상세 필터 모달에서 값을
  고르면(="그 기준으로 비교하고 싶다"는 뜻으로 보고) 그 컬럼도 함께
  보여준다. 직급/직책/재직상태는 이미 필수라 제외.
- `_merge_ai_result(base_df, ai_result)` — AI 검색 결과(columns/labels/
  rows, researcher_id 포함)를 명단 기본 정보와 합친다. researcher_id로
  기본 명단과 매칭해 essential 컬럼 값은 명단 쪽 것을 쓰고, AI 결과에만
  있는 나머지 컬럼(강점 분야/유사도 점수/근거 등, `_AI_SKIP_COLUMNS =
  {researcher_id, name, department}`만 제외)을 그대로 이어붙인다. 같은
  연구원이 여러 행(과제/논문별 등)으로 나오면 처음 나온 값만 쓰고,
  기본 명단에 없는 사람(권한 필터/현재 소속 기준 등으로 제외된 경우)은
  건너뛴다. researcher_id가 없는 결과(집계/통계성 답변)면 빈 DataFrame을
  반환 — 표는 비고 AI 답변 문장만으로 안내한다.
- `update_table` 콜백에 `Input('nl-query-full-result', 'data')` 추가.
  이 Store가 트리거면(AI 검색 실행/초기화) 기존 부서/과제/직급/직책/성별/
  학력/전공/재직상태 드롭다운 필터는 적용하지 않고(질문 자체가 이미 그
  필터 역할) `_merge_ai_result()` 결과로 명단을 통째로 바꾼다. 결과가
  없거나 초기화되면 필수 컬럼만으로 전체 목록에 복귀한다.

### 검증

실제 서버 기동 + 로그인 + Playwright, 그리고 `services.nl_query.
answer_question`을 모듈 속성 몽키패치로 가짜 결과(로봇 제어 전문가 2명,
강점 분야/키워드/매칭 키워드 수 컬럼 포함)로 바꿔치기해 LLM 키 없이도
실제 콜백 체인 전체(입력 → nl_query_bar 콜백 → Store → 명단 테이블 콜백)를
검증:
- 초기 로드 시 명단 컬럼이 정확히 사번/이름/부서/과제/직급/직책/재직상태/
  Knox ID 8개인지 확인.
- AI 검색 실행 후: (a) 명단이 검색된 2명으로만 줄어듦, (b) 강점 분야/
  키워드/매칭 키워드 수 3개 컬럼이 추가로 붙고 값이 정확함, (c) 명단
  위에 AI 답변 문장("로봇 제어 전문가 찾아줘" 관련 전문가는 총 2명입니다)
  이 표시됨을 확인.
- 초기화 버튼 클릭 후: 컬럼이 필수 8개로, 행이 전체 30건(첫 페이지)으로,
  입력창/답변 영역이 모두 비워짐을 확인.
- 병합된(AI 검색 결과) 테이블에서도 행 클릭 → 프로필 이동(`/?id=...`),
  엑셀 다운로드가 정상 동작함을 확인(둘 다 `researcher_id`를 데이터 키로
  쓰는 기존 로직 그대로라 문제 없음).
- `_build_columns()`/`_merge_ai_result()`를 직접 호출해 상세 필터
  선택(`optional_ids`) 컬럼 노출, 기본 명단에 없는 연구원 제외,
  researcher_id 없는 결과(집계성 질문) 처리 등 경계 케이스를 별도 확인.
- 테스트 데이터·서버·계정은 모두 정리.

## 2026-08-20 (15): 프로필 일괄 인쇄, 인원 많으면 진행률 표시 + 브라우저 응답 없음 방지

사용자 요청: "pool에 대한 개별카드를 인쇄할 때 인원이 많으면 브라우저에서
timeout이 되는 경우가 있어. 준비되는 중에 Progress bar를 보여주던지...
대기 시간을 좀 가시화해주면 좋겠어."

원인: `assets/profile_print.js`의 `window.__prepareProfilePrint()`(인쇄
직전 논문·특허 표를 페이지 예산에 맞게 자동으로 잘라내는 로직)가
`.print-page-block`(일괄 인쇄에서는 인원 1명당 1개)마다
`getBoundingClientRect()`로 강제 리플로우를 일으키는 `while` 루프를
동기적으로 돌았다. 인원이 적으면(개별 프로필 1명 = 블록 1개) 순식간에
끝나 문제가 없었지만, 일괄 인쇄로 인원이 수십~수백 명이면 이 전체가 한
번의 동기 호출로 메인 스레드를 오래(체감상 초 단위) 막아, 크롬이 "페이지
응답 없음"을 띄운다 — 사용자에게는 이게 "타임아웃"처럼 보인다. 진행률
표시(Progress bar)를 단순히 얹어도, 이 블로킹 루프가 도는 동안은
브라우저가 화면을 다시 그릴 수조차 없어 진행률이 실제로 보이지 않는다 —
그래서 "진행률을 보여달라"는 요청을 제대로 들어주려면 이 루프 자체를
비동기로 바꿔야 했다.

수정 — `assets/profile_print.js`:
- 블록별 처리(`fitBlock`)를 그대로 두되, 전체를 `forEach` 동기 순회 대신
  블록 하나 끝날 때마다 `setTimeout(fn, 0)`으로 메인 스레드에 제어권을
  돌려주는 재귀 체인으로 바꿔 `Promise`를 반환하게 했다 — 브라우저가
  "응답 없음"으로 판단하지 않고, 그 사이 진행률 콜백(`onProgress(done,
  total)`)도 실제로 화면에 반영된다.
- `window.__prepareProfilePrint`를 재진입 방지 래퍼로 감쌌다: 이미 실행
  중일 때 또 호출되면(아래 "부수 발견" 참고) 처음부터 다시 돌지 않고
  진행 중인 같은 Promise를 재사용하고 새 `onProgress`만 그 위에 얹는다.

수정 — `pages/researcher_profile.py`의 인쇄 버튼 clientside_callback:
- `async function`으로 바꿔 `window.__prepareProfilePrint(onProgress)`가
  끝날 때까지 기다린 뒤에야(아직 자르기가 안 끝난 상태로 인쇄되는 걸
  막기 위해) `window.print()`를 부르도록 했다.
- 새 오버레이(`_print_progress_overlay()`, 화면 우측 상단 고정, Bootstrap
  클래스 대신 인라인 style — 이 화면의 다른 인쇄 관련 요소들과 같은 이유로
  CDN 로드 실패에도 항상 동작해야 함)에 "인쇄 준비 중… (N / 총원)"과 진행
  막대를 실시간으로 그린다. 개별 프로필 인쇄는 블록이 1개뿐이라 거의
  즉시 끝나 오버레이가 스쳐 지나가듯만 보인다.
- `window.__profilePrintInProgress` 플래그로 콜백 자체도 재진입을 막는다.

부수 발견(원인 조사 중 확인, 이번 수정 범위에 포함): 인쇄 버튼을 한 번
클릭해도 이 clientside_callback이 두 번 발생하는 현상이 있었다 — 수정
전(순수 동기) 코드에서도 똑같이 재현됨을 확인해 이번에 새로 생긴 문제가
아니라 이 프로젝트의 Dash 클릭 처리에 원래 있던 동작으로 보인다(정확한
근본 원인은 못 찾음 — Dash 자체의 클라이언트 사이드 콜백 디스패치
동작으로 추정). 기존 동기 버전에서는 두 번째 호출이 똑같은 계산을 한 번
더 하고 `window.print()`를 한 번 더 부르는 정도라 눈에 띄지 않았지만,
이번 진행률 표시에서는 그대로 두면 진행 막대가 중간에 처음으로 되돌아가
보이는 문제가 생겨, 위 두 재진입 방지 장치(JS 쪽 in-flight Promise 공유 +
콜백 쪽 진행 중 플래그)로 실제 측정 작업과 `window.print()` 호출 모두
정확히 한 번만 일어나게 막았다.

검증: 실제 서버 기동 + 로그인 + Playwright, 샘플 데이터 15/50명 규모로
`/?ids=...` 일괄 인쇄 화면 테스트.
- `window.print`를 스텁으로 바꿔 실제 인쇄 대화상자 없이 확인: 클릭 후
  오버레이가 "인쇄 준비 중… (N / 15)"로 진행률을 실시간으로 갱신하다가
  완료 시 사라짐(스크린샷으로 시각 확인).
- 블록별 `getBoundingClientRect()` 호출 횟수를 계측해 실제 리플로우
  작업이 정확히 블록 수(15)만큼, 즉 한 번만 수행됨을 확인 — 위 "부수
  발견" 이중 호출에도 불구하고 재진입 방지가 정상 동작함을 검증.
  `window.print()` 호출 횟수도 정확히 1회임을 확인.
- 개별 프로필(블록 1개) 인쇄에서는 오버레이가 스쳐 지나가듯 사라지고
  깨끗하게 종료됨을 확인(부작용 없음).
- `services/profile_pdf.py`(헤드리스 브라우저 기반 PDF 첨부 메일 발송)가
  `page.evaluate()`로 이제 Promise를 반환하는 `__prepareProfilePrint()`를
  호출해도(Playwright가 Promise를 자동으로 기다림) 정상적으로 PDF가
  생성됨을 실제 호출로 확인(샌드박스 전용 Playwright 브라우저 경로
  오버라이드로 테스트, 프로덕션 코드에는 없음).
- `python3 -m py_compile`/`node -c`로 컴파일·구문 확인.
- 테스트 데이터·서버·계정은 모두 정리.

## 2026-08-21 (16): 개별 카드(A4 1페이지) 손그림 양식 재배치 + 1페이지 초과 방지

사용자가 손그림 와이어프레임과 함께 6가지를 요청: (1) 인물 코멘트 박스
제거, (2) 평가·인센티브 이력을 사진+이름 박스 아래로, (3) 양성·시상
이력을 논문·특허 요약과 한 박스로, (4) 우측 상단 박스는 핵심기술·보유기술,
(5) 전문성 요약 박스를 전체 폭으로, (6) 과제 수행/인사 발령 이력 건수를
줄여 1페이지를 넘어가지 않게. 근본 동기: "개별 카드 인쇄를 할 때 첫장이
자꾸 1Page를 넘어가는 경우가 없었으면 해."

### 레이아웃 변경 (`pages/researcher_profile.py`의 `_print_profile_content()`)

- `header_row`를 3열로 재구성: ① 사진 박스(이름/직급연차 캡션은
  `photo_block()`이 이미 포함 + 그 아래 `print_eval_content` 붙임) / ②
  기본정보 표(사번~Knox ID) / ③ 학력 + 핵심기술·보유기술을 합친 새 박스.
  기존에 사진 옆에 있던 "평가·인센티브(+양성/시상)" 박스와, 사진 아래
  따로 있던 "학력" 박스를 없애고 위 구조로 재배치했다.
- `components/profile_sections.py`의 `evaluation_incentive_summary_text()`
  — 평가 줄이 인센티브 줄보다 먼저 오도록 순서를 바꿨다(사용자 예시:
  "나(ES)/다(MT)/다(MT)" 다음 줄에 "-/-/C"가 오는 형태 — 기존엔 인센티브가
  먼저였음).
- 논문·특허 실적 요약 + 양성 이력 + 시상 이력을 `history_box` 하나로
  합쳤다(기존엔 논문·특허가 별도 박스, 양성·시상은 평가·인센티브와 같은
  박스에 있었음).
- `capability_box`(핵심기술·보유기술 1 : 전문성 요약 2 비율의 2단 박스)를
  없애고, 핵심기술·보유기술은 위 ③ 박스로, 전문성 요약(LLM)은
  `expertise_summary_box`로 분리해 전체 폭을 쓰게 했다. 더는 안 쓰는
  `_print_box_cols()` 헬퍼(2단 배치 전용)도 함께 지웠다.
- "인물 코멘트" 박스를 인쇄 콘텐츠에서 완전히 뺐다 — 화면 쪽 "인물 코멘트
  (부서장 · 부서원)" 탭은 그대로 둔다(사용자 요청이 인쇄본 한정이라고
  판단). 이에 따라 `_print_profile_content()`/`_build_print_block()`
  시그니처에서 `comments_content`/`show_comments`를 제거했다(화면 탭용
  `comments_content`는 `update_profile()` 안에서 별도로 그대로 계산됨 —
  인쇄 경로로 넘기지 않을 뿐).
- `_TASK_HR_RECENT_LIMIT`을 10 → 6으로 줄이고, 박스 제목("과제 수행 /
  인사 발령 이력(최근 N건)")도 하드코딩 숫자 대신 이 상수를 참조하게
  고쳤다(이전엔 제목 문자열이 "10건"으로 고정돼 있어 실제 표시 건수와
  달라질 수 있었음).

### 발견한 버그: 사진 박스가 중첩 리스트라 페이지 전체가 무한 재렌더링

새 사진 박스를 만들면서 `html.Div([photo_block(...), html.Div(eval)])`
형태로 짰는데, `photo_block()`은 컴포넌트 "리스트"를 그대로 반환하는
함수라(이 파일의 `llm_summary_block()` 사용부에도 동일한 경고 주석이
있음) 이게 다른 리스트 안에 그대로 들어가면 중첩 리스트가 되어 Dash가
그 서브트리를 렌더링하지 못한다. 콘솔에 "Minified React error #31"이
찍히면서, 어째서인지 이 렌더링 실패가 페이지 전체를 도돌이표처럼 만들어
`_pages_content`/`update_profile`/`leadership-chart` 등 초기 로드 때 도는
콜백 전체가 300~700ms 간격으로 영원히 반복 실행되는 현상으로 이어졌다
(브라우저 개발자도구 없이 화면만 보면 그냥 "가끔 사진이 안 보이나?"
정도로만 보일 수 있어 놓치기 쉬움 — Playwright로 `#profile-print-content`
의 자식 수를 짧은 간격으로 반복 측정해 0/1을 오가는 것을 보고 잡아냈다).
수정: `photo_block(...)`을 `html.Div(photo_block(...))`로 한 번 더 감싸
평평하게 만들었다.

### 검증

실제 서버 기동 + 로그인 + Playwright, 샘플 데이터 + 직접 만든 평가등급
(와이드 포맷)/핵심기술/보유기술 테스트 데이터로 확인.
- 위 무한 재렌더링 버그: 수정 전엔 3초 안에 dash-update-component 요청이
  끊임없이(초당 여러 건) 발생하고 `#profile-print-content` 자식 수가
  0/1을 오갔던 것이, 수정 후엔 페이지 로드 시 딱 한 번의 정상 콜백
  캐스케이드(6건)만 발생하고 안정됨을 확인.
- 6가지 배치 요청 모두 스크린샷으로 손그림 양식과 대조해 확인(사진박스
  아래 평가·인센티브, 학력+핵심기술+보유기술 박스, 논문·특허+양성·시상
  통합 박스, 전문성 요약 전체 폭, 인물 코멘트 없음).
- 1페이지 높이 예산 검증: `#profile-print-content`에서 2페이지(논문·특허
  상세, `.print-page-block`)가 시작되는 지점까지의 실제 렌더링 높이를
  A4 인쇄 예산(`assets/profile_print.js`와 동일 계산, 약 937px)과 비교.
  기본 테스트 데이터(과제 4건)는 736px, 과제 이력을 14건으로 늘려 6건
  제한이 실제로 걸리게 한 경우 784~849px(제한값 10건일 때 vs 6건일 때
  비교) — 항상 예산 안에 여유 있게 들어옴을 확인. 부서명·학력 학교명을
  일부러 아주 길게(줄바꿈되도록) 바꿔도 여유(약 150px)가 남음을 추가
  확인.
- 병합(bulk) 인쇄(`/?ids=...`, 3명)에서도 콘솔 에러 없이
  `.print-page-block`이 인원 수만큼 정확히 생성됨을 확인(무한 재렌더링
  버그가 이 경로에도 있었을 것이므로 함께 검증).
- 화면(라이브) 쪽 "인물 코멘트 (부서장 · 부서원)" 탭은 그대로 남아있음을
  확인(인쇄본에서만 제거).
- `python3 -m py_compile`로 컴파일 확인.
- 테스트 데이터·서버·계정은 모두 정리(테스트용으로 건드린 researchers/
  education/tasks.csv도 재생성으로 원복).

## 2026-08-21 (17): 개별 카드 인쇄 후속 조정 3건 — 평가·인센티브 표기 간소화, 학력 위치, 논문·특허 박스 폭

바로 앞 (16)번 재배치 이후 사용자가 3가지 후속 조정을 요청:

1. "사진 아래에는 평가 인센티브 이력이라는 제목도 빼고, '평가'와
   '인센티브' 라는 구분자도 빼고 내용만 표기를 해줘. 가운데 정렬로. ...
   권한이 없는 사람의 경우 그냥 자물쇠 표시만 해줘."
2. "학력 사항을 Knox ID 아래로 옮기는 게 좋겠어."
3. "예전 학력 박스 배치처럼 논문,특허, 시상, 양성 이력이 표기된 박스의
   폭을 우상단의 핵심기술, 보유기술 박스와 병렬 배치 가능한 정도로
   줄여줘."

### 수정

- `components/profile_sections.py`의 `evaluation_incentive_summary_text()`
  — "평가 · 인센티브 이력 ('24~'26)" 제목 줄과 "평가"/"인센티브" 라벨을
  모두 빼고, 값 두 줄(평가 먼저, 인센티브 다음 — 위 (16)번에서 이미
  확정된 순서)만 가운데 정렬로 반환한다. 더는 안 쓰는 `year_range`
  계산도 함께 제거.
- `pages/researcher_profile.py`의 `_locked_block()`에 `icon_only: bool`
  파라미터 추가 — `True`면 안내 문구 없이 자물쇠 아이콘만 가운데 정렬로
  반환한다(다른 잠금 자리는 기존처럼 문구 포함 그대로 유지 — 이 함수를
  쓰는 다른 2곳에는 영향 없음). 사진 박스 아래 평가·인센티브 자리의
  권한 없음 처리를 `_locked_block('평가 · 인센티브 이력')`에서
  `_locked_block(icon_only=True)`로 교체.
- `_print_profile_content()`: 학력을 우측 상단 박스(핵심기술·보유기술과
  같이 있던 곳)에서 빼서, 기본정보 표(사번~Knox ID) 바로 아래 `info_col`
  안으로 옮겼다. 우측 상단 박스(`right_box`)는 이제 핵심기술·보유기술만
  남는다.
- `history_box`(논문·특허 요약 + 양성·시상 이력)를 감싸는 `html.Div`에
  `style={'width': 'calc((100% - 190px - 12px) / 2)'}`를 줘서, 폭을
  `header_row`의 핵심기술·보유기술 열(사진 190px 고정 폭과 여백 12px을
  뺀 나머지를 반으로 나눈 값 — 사번~Knox ID 열과 정확히 같은 계산)과
  같은 폭으로 줄였다. 전체 폭 대신 왼쪽 정렬로 좁게 표시되어, 오른쪽에
  핵심기술·보유기술 박스와 나란히 놓을 수 있는 정도의 폭이 된다(사용자
  표현 "병렬 배치 가능한 정도로").

### 검증

실제 서버 기동 + 로그인 + Playwright, (16)번과 동일한 테스트 데이터로 확인.
- 평가등급 권한이 있는 사용자(team_lead): 사진 박스 아래에 제목·라벨
  없이 "나/가/다"(평가) 다음 줄에 "-/-/최우수"(인센티브)만 가운데
  정렬로 표시됨을 스크린샷 확대로 확인.
- 평가등급 권한이 없는 사용자(talent_dev)로 별도 계정을 만들어 확인 —
  사진 박스 아래에 렌더된 실제 DOM이 정확히
  `<div class="text-center"><i class="bi bi-lock-fill text-secondary">
  </i></div>` 하나뿐이고 안내 문구가 전혀 없음을 확인(이 샌드박스는
  Bootstrap Icons 폰트를 CDN에서 못 받아와 아이콘 자체가 시각적으로는
  안 보이지만, 이 세션에서 반복 확인된 사내망 특유의 제약이라 실제
  운영 환경에서는 정상 렌더링됨 — data/processed/CLAUDE.md의 기존
  기록 참고).
- 학력이 Knox ID 아래(기본정보 열)에 표시되고, 우측 상단 박스에는
  핵심기술·보유기술만 남음을 스크린샷으로 확인.
- 논문·특허+양성·시상 박스가 전체 폭 대신 좁은 폭(우측 박스와 비슷한
  너비)으로, 왼쪽 정렬로 표시됨을 스크린샷으로 확인.
- 1페이지 높이: 667px(예산 약 937px) — 학력 이동·박스 축소로 오히려
  더 여유가 생김.
- 페이지 로드 시 dash-update-component 요청이 정상적으로 한 번만
  발생(무한 재렌더링 없음), 콘솔 에러 없음을 확인(직전 (16)번에서 고친
  버그가 이번 수정으로 재발하지 않았는지 재확인 차원).
- `python3 -m py_compile`로 컴파일 확인.
- 테스트 데이터·서버·계정(추가로 만든 권한 없음 테스트 계정 포함) 모두
  정리.

## 2026-08-21 (18): 개별 카드 논문·특허+양성·시상 박스 폭 재조정 — 핵심기술·보유기술 박스만큼만 빼기

바로 앞 (17)번에서 논문·특허+양성·시상 박스(`history_box`) 폭을 우측
핵심기술·보유기술 박스와 "같은" 폭(header_row의 flex:1 열 하나 너비, 즉
전체의 절반 가까이)으로 줄였는데, 사용자 피드백: "논문 시상 양성 이력
박스의 폭은 너무 줄였어. 전체 폭에서 핵심기술, 보유기술 폭을 뺀 정도로
줄이고 사진 박스 아래에 바로 아래에 위치하게끔 해주면 돼." — 즉 "우측
박스와 같은 폭"이 아니라 "전체 폭에서 우측 박스 폭만 뺀 나머지"(사진
190px + 여백 12px + info_col 폭, 대략 전체의 58%)로 다시 넓혀야 했다.
위치(사진 박스 바로 아래, header_row 다음 첫 블록)는 (17)번에서 이미
그렇게 돼 있어 변경 불필요 — 폭 계산식만 수정.

**`pages/researcher_profile.py`**: `history_box`의
`style={'width': 'calc((100% - 190px - 12px) / 2)'}`(header_row의
flex:1 열 하나와 같은 폭)를
`style={'width': 'calc(100% - (100% - 190px - 12px) / 2)'}`(전체 폭에서
그 flex:1 열 하나를 뺀 나머지)로 변경 — 같은 계산식에서 반대쪽 값을
취하는 것뿐이라 `calc()` 식도 그 차로 구성했다. 위 박스 설명 주석과
`_print_profile_content()` docstring의 손그림 양식 설명("논문·특허+
양성·시상(좁은 폭)")도 새 폭 기준("핵심기술·보유기술 박스를 뺀 나머지
폭")에 맞게 함께 수정.

**검증**: 실제 서버 기동 + 로그인(team_lead 역할) + Playwright, 과제
이력을 14건으로 부풀려 6건 제한이 실제로 걸리게 하고 부서명·학력
학교명을 길게(줄바꿈되도록) 바꾼 스트레스 테스트 데이터로 확인.
- `getBoundingClientRect()`로 직접 측정: `history_box` 너비 741px(전체
  폭 1280px 기준) — 기대값(`content_width - (content_width - 190 - 12)
  / 2`) ≈ 744px와 일치(우측 박스 524px + 여백만큼 빠진 나머지). 이전
  (17)번 폭(약 370px, 우측 박스와 동일)보다 뚜렷이 넓어짐을 확인.
  `left: 0`으로 왼쪽 정렬 유지(사진 박스와 같은 시작선).
- `history_box`가 header_row(사진+기본정보+핵심기술·보유기술) 바로
  다음 첫 블록으로 배치되어(정보 흐름상 "사진 박스 바로 아래") 위치
  변경이 필요 없었음을 top 좌표로 재확인.
- 무한 재렌더링 회귀 없음: 페이지 로드 후 3초간
  `_dash-update-component` 요청 0건, `#profile-print-content`의 자식
  수가 6회 연속 측정에서 항상 1로 안정((16)번에서 고친 photo_block()
  중첩 리스트 버그가 이번 폭 변경으로는 건드려지지 않았음을 재확인 —
  이 함수가 그 버그의 근원이라 회귀 여부를 특히 주의 깊게 재확인).
- 콘솔 에러 없음.
- 1페이지 높이: 684.6px(예산 약 937px) — 박스가 넓어졌지만 내용
  자체(논문/특허 요약 2줄 + 양성/시상 각 항목)는 그대로라 줄바꿈이
  오히려 줄어 여유가 유지됨(이전 좁은 폭 667px보다 살짝 늘었지만 여전히
  budget 안에 충분히 들어옴).
- 스크린샷으로 육안 확인: 논문·특허+양성·시상 박스가 화면 왼쪽 절반
  이상(핵심기술·보유기술 박스 시작 지점 직전까지)을 채우는 넓은 박스로
  표시됨.
- `python3 -m py_compile`로 컴파일 확인.
- 테스트 데이터·서버·계정 모두 정리.

## 2026-08-21 (19): 논문·특허+양성·시상 박스가 핵심기술·보유기술 박스 높이를 기다리지 않고 사진 박스 바로 아래에서 시작하도록 구조 변경

바로 앞 (18)번에서 폭은 고쳤지만 사용자 피드백: "여전히 사진 박스 바로
밑에 안 붙어. 핵심기술 보유기술 박스가 끝나는 지점에서 시작되지 않고
사진 박스 아래에서 시작되게 해줘." — 폭이 아니라 **위치**(수직 시작
지점)가 문제였다.

**원인**: `header_row`가 `[photo_box(190px), info_col, right_box]`
3열을 한 flex row로 두고, `history_box`(논문·특허+양성·시상)를 그
`header_row` 다음의 새 블록으로 이어붙이는 구조였다. flex row의 높이는
"가장 키가 큰 열" 기준으로 정해지므로, `history_box`의 시작 위치도
사진+기본정보(왼쪽)가 아니라 3열 중 가장 긴 열(핵심기술·보유기술
표 — 항목이 많으면 꽤 길어질 수 있음) 기준으로 밀려 내려갔다. 폭은
(18)번에서 이미 "핵심기술·보유기술 박스를 뺀 나머지"로 맞춰 놨지만,
수직 위치는 여전히 그 박스의 높이에 종속돼 있었던 것 — 별개의
문제였다.

**수정**(`pages/researcher_profile.py`의 `_print_profile_content()`):
`[사진+기본정보(학력 포함)]` 열과 `history_box`를 `left_column`이라는
하나의 세로 묶음으로 감싸, `right_box`(핵심기술·보유기술)와 나란한
**독립된 열**로 재배치했다.

```python
left_column = html.Div([
    html.Div([
        html.Div(photo_box, style={'flex': '0 0 190px'}),
        info_col,
    ], style={'display': 'flex', 'alignItems': 'flex-start', 'marginBottom': '10px'}),
    history_box,
], style={'width': 'calc(100% - (100% - 190px - 12px) / 2)', 'minWidth': '0'})

header_row = html.Div([
    left_column,
    html.Div(right_box, style={'width': 'calc((100% - 190px - 12px) / 2)', 'minWidth': '0'}),
], style={'display': 'flex', 'alignItems': 'flex-start', 'marginBottom': '10px'})
```

이제 `history_box`의 시작 y좌표는 `left_column`(사진+기본정보) 높이만의
함수이고, `right_box`의 높이와 완전히 무관하다 — `right_box`가 더
길어도 `history_box`는 기다리지 않고, 오히려 `right_box`가 계속
이어지는 동안(같은 y 범위) `history_box`가 왼쪽에서 먼저 끝나는
"마감형" 2열 레이아웃이 된다. 폭 계산식(`calc(100% - (100% - 190px -
12px) / 2)`)은 (18)번에서 이미 확정된 값 그대로 재사용 — 이번은 위치만
바꾸는 것이라 폭은 건드리지 않았다. `history_box` 자체는 더 이상
`html.Div(style={'width': ...})`로 감쌀 필요가 없어져(부모
`left_column`이 폭을 이미 정함) `_print_box(...)`를 직접 반환하도록
단순화했고, `_print_profile_content()` docstring도 이 2열 구조를
설명하도록 갱신했다.

**검증**: 실제 서버 기동 + 로그인(team_lead) + Playwright, (18)번과
동일한 스트레스 테스트 데이터(과제 14건, 긴 부서명/학교명)에 이번엔
핵심기술을 10건(기존 2건 + 8건 추가, 각 항목명도 길게)으로 늘려
`right_box`를 의도적으로 `left_column`보다 훨씬 길게 만든 뒤 확인.
- 1차(핵심기술 2건, `right_box`가 `left_column`보다 짧음): `history_box`
  top=290.1px, `photo_box` bottom=240.0px, `right_box` bottom=276.0px —
  이 경우도 `history_box`가 `right_box`보다 먼저 시작함을 확인
  (290.1 > 276.0이지만 근소, `info_col`의 학력 3줄이 `photo_box`보다
  길어 `left_column` 높이가 이미 `right_box`와 비슷했던 경우).
- 2차(핵심기술 10건으로 인위적으로 `right_box`를 훨씬 길게):
  `right_box` bottom이 275.97px → 493.72px로 크게 늘었는데도
  `history_box` top은 정확히 290.125px로 **완전히 동일**(소수점까지
  일치) — `right_box`의 높이 변화가 `history_box` 위치에 전혀 영향을
  주지 않음을 수치로 확인. 스크린샷으로도 핵심기술 표가 10줄로 길게
  이어지는 동안 왼쪽의 논문·특허+양성·시상 박스는 훨씬 짧게 먼저
  끝나 있는(전문성 요약(LLM) 박스가 그 아래, header_row 전체가 끝난
  뒤에만 시작하는) 것을 육안 확인.
- 무한 재렌더링 회귀 없음: `_dash-update-component` 요청 0건,
  `#profile-print-content` 자식 수 6회 연속 측정에서 항상 1로 안정.
- 콘솔 에러 없음.
- 1페이지 높이: 핵심기술 10건 스트레스 테스트에서 773.3px(예산 약
  937px) — 여전히 여유 있게 들어옴.
- `python3 -m py_compile`로 컴파일 확인.
- 테스트 데이터·서버·계정 모두 정리(추가했던 핵심기술 8건 포함).

## 2026-08-21 (20): 개별 카드 "학력" 제목 제거 + 사진 20% 확대(대신 사진 박스 폭 축소)

사용자 요청 2건: "1. 학력이라는 글자는 없어도 되겠어. 2. 사진이 지금보다
20% 정도 커져서 사진 박스가 조금 더 길어져서 학력 아래 란까지 닿게끔
해줘. 대신 폭은 지금보다 좀 더 줄어드는 게 낫겠어"

**1) "학력" 제목 제거** (`pages/researcher_profile.py`의
`_print_profile_content()`): `info_col`에서 `html.Div('학력', ...)`
라벨 줄을 지우고 `education_block(...)`만 남겼다(기본정보 표와 구분되게
`marginTop: '8px'`만 유지). Knox ID 아래 학력 내용(박사/석사/학사)이
제목 없이 바로 이어져 보인다.

**2) 사진 20% 확대 + 사진 박스 폭 축소**:
- `components/profile_sections.py`의 `photo_block()`에
  `img_max_height: int = 200` 파라미터 추가 — 사진 `<img>`의
  `maxHeight`를 하드코딩 대신 이 값으로 받는다. 기본값 200은 화면(라이브)
  탭 호출부(`pages/researcher_profile.py`의 `update_profile()`, 인자
  안 넘김)와 동일해 화면 쪽은 변경 없음.
- `pages/researcher_profile.py`의 인쇄 전용 호출부만
  `img_max_height=240`(200 → 20% 증가)으로 넘긴다.
- 신규 모듈 상수 `_PHOTO_BOX_WIDTH_PX = 160`(기존 190px에서 축소) —
  `photo_box`의 `width`/`flex` 기준값과, `header_row`의 `left_column`/
  `right_box` 폭 계산(`calc()`) 3곳이 전부 이 상수 하나를 참조하도록
  통일해(f-string으로 조립) 사진 폭을 나중에 또 바꿔도 좌우 정렬이
  어긋나지 않게 했다.
- **막혀 있던 진짜 원인**: `img_max_height`만 올려서는 효과가 없었다 —
  `assets/custom.css`의 `@media print { img { max-height: 65px
  !important; } }`(다른 인쇄 화면들을 위한 전역 규칙으로 추정, 이번
  세션 이전부터 있던 기존 규칙)가 인쇄 시 모든 `<img>`를 65px로 강제
  캡핑하고 있어서, 인라인 style의 240px 값이 완전히 무시되고 있었다
  (특이도는 낮지만 `!important`라 인라인 style을 이겼다 — Playwright로
  실측해 65px 그대로인 것을 보고 발견). 이 전역 규칙 자체는 다른 인쇄
  대상에 영향을 줄 수 있어 건드리지 않고, `.profile-print-only
  .print-section img { max-height: 240px !important; }`(2클래스+1요소,
  전역 `img`(요소 1개)보다 선택자 특이도가 높아 `!important`끼리도
  이긴다)를 프로필 카드 사진에만 추가로 얹어 해결했다.

**검증**: 실제 서버 기동 + 로그인(team_lead) + Playwright, 이전 (18)/(19)번과
동일한 스트레스 테스트 데이터(과제 14건, 긴 부서명)로 확인.
- `edu_label_found`(DOM에서 정확히 "학력" 텍스트만 있는 리프 요소 검색)
  = False로 라벨이 실제로 사라졌음을 확인, 학력 내용(박사/석사/학사
  3줄)은 그대로 보임을 스크린샷으로 확인.
- `photo_box` 렌더링 폭이 208px(기존 190+padding+border) → 178px
  (160+padding+border)로 축소됨을 실측 확인.
- **샌드박스 샘플 사진의 한계**: 이 저장소의 샘플 사진 생성기
  (`pipeline/generate_sample_data.py`의 `_make_png_bytes`)가 만드는
  파일은 원본 자체가 80×80px 정사각형 단색 PNG라, `width:auto;
  height:auto`(원본보다 확대하지 않음) 특성상 실측 렌더 크기가 절대
  80px를 넘지 못한다 — 위 CSS 캡 수정 전에는 65×65px(구 65px 캡에
  걸림), 수정 후에는 80×80px(원본 그대로, 새 240px 캡에는 안 걸림)로
  올라 사진 박스 bottom이 240.0px → 255.0px로 늘고 학력 열(info_col)
  bottom(272.9px)과의 간격이 32.9px → 17.9px로 줄어드는 것까지는
  확인했지만, 원본이 80px뿐이라 "학력 아래 란까지 완전히 닿음"까지는
  이 샌드박스 샘플로는 재현되지 않는다(운영 환경의 실제 증명사진은
  해상도가 훨씬 크므로 이 한계에 해당하지 않을 것으로 예상).
  → **추가로 실측 검증**: 3:4 비율(300×400px)의 합성 인물사진을
  `data/photo/00000001.png`에 임시로 넣어(테스트 후 삭제) 같은 화면을
  다시 렌더링 — 이번엔 이미지가 폭 기준으로 160×213px까지 커지며
  (240px 캡에 걸리지 않음) 사진 박스 bottom이 388.4px까지 늘어나
  학력 열(272.9px)을 오히려 넘어서는 것을 확인 — 캡 해제 + 폭 축소
  메커니즘 자체가 의도대로 동작하고, 실제 증명사진 비율에서는 "학력
  아래 란까지 닿는" 요청을 충분히 만족시킬 수 있음을 확인했다(정확히
  얼마나 닿을지는 실제 사진 비율에 따라 달라지는 부분이라 픽셀 단위로
  못박을 수는 없음).
- 무한 재렌더링 회귀 없음: `_dash-update-component` 요청 0건,
  `#profile-print-content` 자식 수 6회 연속 측정에서 항상 1로 안정.
- 콘솔 에러 없음.
- 1페이지 높이: 기본 샘플 사진 기준 681.6px, 3:4 합성 사진(과도하게
  커진 케이스) 기준 797.0px — 둘 다 예산(약 937px) 안에 들어옴.
- `python3 -m py_compile`로 컴파일 확인.
- 테스트 데이터·서버·계정, 임시 3:4 합성 사진(`data/photo/`) 모두 정리.

## 2026-08-21 (21): 개별 카드 사진 박스 15% 축소(직전 확대가 과했다는 피드백)

바로 앞 (20)번에서 사진을 20% 키웠는데 사용자 피드백: "사진이 너무
길어졌어. 사진이 포함된 박스의 길이와 폭이 15% 정도 줄어들면 좋겠어."
— 20% 확대가 과했으니 폭·높이 모두 15%씩 줄여 원래보다 약간만 큰
수준으로 되돌려 달라는 것.

**수정**(둘 다 (20)번에서 만든 값에 0.85를 곱해 산출 — 새 계산이 아니라
같은 상수/파라미터의 값만 조정):
- `pages/researcher_profile.py`: `_PHOTO_BOX_WIDTH_PX`를 160 → 136
  (160×0.85)으로 축소. `header_row`의 `left_column`/`right_box` 폭
  계산(calc)이 전부 이 상수를 참조하므로 이 한 줄만 바꾸면 좌우 정렬은
  자동으로 유지된다.
- 인쇄 전용 `photo_block(..., img_max_height=240)` 호출부의 값을
  204(240×0.85)로 축소. 화면(라이브) 탭 호출부는 인자를 안 넘겨 여전히
  200 그대로(변경 없음).
- `assets/custom.css`의 `.profile-print-only .print-section img {
  max-height: 240px !important; }`(직전 커밋에서 전역 65px 캡을
  덮어쓰려고 추가한 규칙)도 204px로 함께 낮춰 Python 쪽 값과 어긋나지
  않게 했다.

**검증**: 실제 서버 기동 + 로그인(team_lead) + Playwright, 이전과 동일한
스트레스 테스트 데이터로 확인. (20)번 검증 때와 마찬가지로 이 저장소의
기본 샘플 사진은 80×80px 정사각형 placeholder라 240/204 어느 캡을
둬도 원본 크기(80px)보다 못 커서 캡 값 변화 자체는 이 샘플로는
드러나지 않는다 — 3:4 비율(300×400px)의 합성 인물사진을
`data/photo/00000001.png`에 임시로 넣어(테스트 후 삭제) 실측:
- 이미지 렌더 크기: 160×213px((20)번 값) → 136×181px(이번 값) — 폭·높이
  모두 정확히 15.0% 감소(컨테이너 폭에 의해 가로로 제한되는 케이스라
  `_PHOTO_BOX_WIDTH_PX` 축소가 그대로 이미지 크기에 비례 반영됨).
- `photo_box` 렌더링 폭(테두리·패딩 포함): 178px → 154px.
- `photo_box` 높이(사진+캡션+평가·인센티브 텍스트 전체): 336.9px →
  304.9px(약 9.5% 감소 — 사진 자체는 정확히 15% 줄었지만, 캡션·평가
  텍스트 줄은 고정 크기라 전체 박스 높이 감소율은 사진 단독보다는
  작다. 사용자가 지적한 "사진이 너무 길어짐"의 핵심 원인인 사진
  자체는 요청대로 15% 줄었다).
- 기본 샘플 사진(80×80px)으로도 회귀 확인: `edu_label_found=False`
  (학력 제목 계속 없음), `photo_box` 폭 178px→154px로 축소 확인,
  무한 재렌더링 회귀 없음(`_dash-update-component` 요청 0건,
  `#profile-print-content` 자식 수 6회 연속 1로 안정), 콘솔 에러 없음,
  1페이지 높이 681.6px(예산 약 937px)로 여유 있게 들어옴.
- `python3 -m py_compile`로 컴파일 확인.
- 테스트 데이터·서버·계정, 임시 3:4 합성 사진(`data/photo/`) 모두 정리.

## 2026-08-21 (22): 개별 카드 직급연차↔평가 줄 간격 축소 + 핵심기술/보유기술 구분선 제거

사용자 요청 2건: "직급년차와 평가 사이의 줄 간격이 더 클 필요가 없어.
핵심기술과 보유기술 사이에 있는 줄도 지워도 돼."

**1) 직급연차↔평가·인센티브 줄 간격 축소**(`pages/researcher_profile.py`):
사진 박스 안에서 `photo_block()`이 만드는 마지막 캡션 줄(직급연차,
예: "수석연구원-18(18.0년)")과 그 아래 `print_eval_content`(평가·
인센티브 두 줄) 사이의 `marginTop`을 8px → 2px로 줄였다. 이 8px는
photo_block()이 만드는 다른 줄 사이 간격(캡션끼리는 기본 줄간격만,
명시적 마진 없음)보다 확연히 크게 벌어져 보이던 원인이었다 — 2px로
줄이자 실측 줄 간격(다음 요소 top - 이전 요소 bottom)이 name↔직급연차
줄 간격(약 12.0px, 텍스트 자체의 줄간격만으로 생기는 값)과 거의
같은 12.5px가 되어, 유독 크게 벌어져 보이던 문제가 해소됐다(다른 줄
간격 대비 도드라지지 않게 됨).

**2) 핵심기술↔보유기술 구분선 제거**(`components/detail_tabs.py`의
`owned_expertise_block()`): `stacked=True`(A4 인쇄본 전용 — 화면
`stacked=False`는 좌우 배치라 border-start로 계속 구분되므로 영향
없음) 분기에서 보유기술 블록에 걸려 있던
`style={'borderTop': '1px solid #e8e8ed'}`를 제거하고, 그 선 위 여백용
이던 `pt-3`도 함께 뺐다(`mt-3`만 남김 — 핵심기술/보유기술 사이 여백
자체는 유지, 선만 삭제).

**검증**: 실제 서버 기동 + 로그인(team_lead) + Playwright, 이전과 동일한
스트레스 테스트 데이터로 확인.
- 사진 박스 안 `<p>` 요소(name/직급연차)와 평가·인센티브 wrapper의
  실제 렌더링 위치를 `getBoundingClientRect()`로 측정 — 직급연차↔평가
  간격이 12.5px(marginTop 2px + 텍스트 자체 줄간격)로, name↔직급연차
  간격(12.0px)과 비슷한 수준까지 줄어든 것을 확인(기존 8px marginTop
  때는 약 18.5px로 확연히 더 컸을 것으로 역산됨 — marginTop 차이(6px)
  만큼 정확히 줄어든 것으로 계산 검증).
  - 검증 스크립트 버그 하나 발견·수정: 처음엔 `.print-section`
    선택자가 사진 박스뿐 아니라 `_print_box()`가 만드는 다른 모든
    인쇄 박스(핵심기술 박스 포함, 같은 클래스를 공유)에도 매칭돼
    엉뚱한 값을 측정했다 — `<img>`를 포함한 `.print-section`만
    골라내도록 좁혀서 해결.
- "보유기술" 텍스트에서 조상으로 올라가며 `computed borderTopColor`가
  제거 대상 색(#e8e8ed)인 요소를 찾는 검사 → `None`(찾지 못함)으로
  구분선이 실제로 사라졌음을 확인(외곽 `_print_box` 자체 테두리(#1d1d1f,
  전체 4면)는 무관하므로 색으로 구분).
  - 이것도 검증 스크립트 버그 하나 발견·수정: 처음엔 `borderTopWidth`만
    보고 있어서 바깥 `_print_box`의 4면 테두리(위쪽 변도 borderTopWidth
    1px로 잡힘)를 오탐지했다 — 색상까지 함께 비교하도록 좁혀서 해결.
- 스크린샷으로 육안 확인: 사진 캡션 아래 평가·인센티브 텍스트가
  더 촘촘하게 붙어 보이고, 핵심기술 표와 보유기술 표 사이에 가로줄이
  없어졌음을 확인.
- 무한 재렌더링 회귀 없음: `_dash-update-component` 요청 0건,
  `#profile-print-content` 자식 수 6회 연속 측정에서 항상 1로 안정.
- 콘솔 에러 없음.
- 1페이지 높이: 681.6px(예산 약 937px) — 여유 있게 들어옴.
- `python3 -m py_compile`로 컴파일 확인.
- 테스트 데이터·서버·계정 모두 정리.

## 2026-08-21 (23): 핵심기술/보유기술 표 헤더 제거 + 사진·기본정보·핵심기술 박스를 테두리 하나로 통합

사용자 요청: "핵심기술, 보유기술 표에는 Header가 필요 없을 것 같아. 핵심기술은
(A급)00000000 분야 > 0000000000 기술 이렇게 표현하고, 보유기술은 그냥 내용에
해당되는 row만 바로 보이게 표시하면 되겠어. 그리고 사진 박스, 사번 박스,
핵심기술보유기술 박스를 하나의 큰 박스 안에 넣고 사진박스와 핵심기술 박스를
감싼 테두리는 없애줘."

**1) 표 헤더 제거 + 핵심기술 표기 형식 변경** (`components/detail_tabs.py`):
- `_core_technology_table(core_df, *, compact=False)` — `compact=True`면 2열
  표(기술분야/핵심기술 헤더 포함) 대신 "(등급)분야 > 기술명" 한 줄짜리 텍스트를
  항목마다 나열한다(예: "(B급)반도체 소재 > 차세대 저전력 반도체 소재 및
  공정 최적화 기술 개발"). 등급이 없으면 "(-)"로 표시. 화면(라이브) 탭은
  `compact` 인자를 안 넘겨 기존 표 그대로.
- `_tech_ownership_table(tech_row, *, show_index=True, no_header=False)` —
  `no_header=True`면 `html.Thead(...)`(구분/전문분야/Lv/보유율)를 아예 안 만들고
  `html.Tbody(rows)`만 반환한다(표 구조·3열 정렬은 유지, 헤더 행만 제거).
- `owned_expertise_block(..., compact: bool = False)` 신규 파라미터 — 위 두
  함수에 각각 `compact`/`no_header`로 전달. "핵심기술"/"보유기술" 섹션 제목
  (`_PANEL_TITLE_STYLE` 텍스트) 자체는 요청 범위 밖이라 그대로 유지 — 표
  내부 열 헤더만 없앤 것.
- `pages/researcher_profile.py`의 인쇄 전용 호출부만 `compact=True` 추가
  (화면 탭은 그대로).

**2) 사진·기본정보·핵심기술/보유기술 박스를 테두리 하나로 통합**
(`pages/researcher_profile.py`의 `_print_profile_content()`): 직전까지는
`photo_box`(자체 테두리)/`right_box`(`_print_box`로 만들어 자체 테두리)가
각자 따로 박스였는데, 사용자 요청대로 photo_box/tech_box(옛 right_box)의
자체 테두리(`border`/`borderRadius`)를 빼고, 그 대신 [photo_box, info_col,
tech_box] 셋을 한 flex row로 묶은 `combined_box`에 테두리(`_PRINT_BOX_BORDER`,
borderRadius, padding)를 딱 하나만 준다.

이 변경으로 이전 (19)번 항목에서 만든 "history_box가 tech_box(구
right_box)의 높이를 기다리지 않고 사진 박스 바로 아래에서 시작하게 하는"
`left_column`(독립 열) 구조는 더 이상 쓰지 않는다 — 이번 요청이 photo_box/
info_col/tech_box 3개를 명시적으로 "하나의 큰 박스"로 합치라는 것이었고
history_box는 그 언급에서 빠져 있어서, history_box를 그 안에 끼워 넣지
않고(요청 범위 밖) `combined_box` 바로 다음 블록으로 되돌렸다. 그 결과
history_box의 시작 위치는 다시 `combined_box` 전체 높이(= photo+info 쪽과
tech_box 쪽 중 더 큰 쪽) 기준으로 정해진다 — 다만 이제는 tech_box가 더
길어도 photo_box처럼 "별도 테두리 박스가 일찍 끝나고 그 안에 어색한 빈
공간이 남는" 시각적 문제가 없다(테두리 자체가 하나로 합쳐져 있어 빈 공간이
아니라 "같은 박스 안에서 오른쪽 칸이 더 길다"는 자연스러운 모양이 되므로).
`_photo_w`/`_PHOTO_BOX_WIDTH_PX` 등 폭 계산 상수·calc 식은 그대로 재사용
(값 자체는 안 바뀜, `combined_box`/`history_box` 조립부가 참조하도록 주석·
변수명만 정리).

**검증**: 실제 서버 기동 + 로그인(team_lead) + Playwright, 이전과 동일한
스트레스 테스트 데이터(과제 14건, 긴 부서명)로 확인.
- `<th>` 전체 목록에서 기술분야/핵심기술/구분/전문분야/Lv/보유율이 전부
  사라지고, 무관한 페이지2 논문 상세 표 헤더(연도/제목/게재처 등)만 남는
  것을 확인.
- 본문 텍스트에 정규식(`\([A-Z가-힣0-9\-]*급\).+>`)으로 "(등급)분야 >
  기술명" 형식 줄이 실제로 존재하는지 확인.
- 사진 `<img>`에서 조상으로 올라가며 테두리 있는 요소를 전부 수집 —
  기존엔 photo_box 자체 테두리 1개가 먼저 걸렸을 텐데, 이번엔 정확히
  1개(combined_box, 전체 폭 1280px)만 발견됨을 확인. "핵심기술" 텍스트
  에서도 동일하게 조상 테두리를 수집해 역시 정확히 1개(같은 combined_box,
  같은 top/bottom/width)만 발견 — 사진과 핵심기술이 물리적으로 동일한
  하나의 테두리 박스 안에 있음을 좌표까지 일치시켜 확인.
- 스크린샷으로 육안 확인: 사진·기본정보·핵심기술/보유기술이 테두리 하나
  안에 나란히 배치되고, 핵심기술이 "(B급)반도체 소재 > 차세대 저전력
  반도체 소재 및 공정 최적화 기술 개발" 형식으로, 보유기술이 헤더 없이
  3개 행(반도체 소재 분석/박막 공정/품질 관리, Lv·보유율)만 표시됨을 확인.
- 핵심기술 10건(원래 2건 + 8건 추가)으로 인위적으로 늘려 combined_box를
  더 길게(높이 243.4px→298.8px) 만든 스트레스 테스트에서도 여전히 테두리
  1개로 유지되고, 1페이지 높이가 749.0px(예산 약 937px)로 여유 있게
  들어옴을 확인.
- 무한 재렌더링 회귀 없음: `_dash-update-component` 요청 0건,
  `#profile-print-content` 자식 수 6회 연속 측정에서 항상 1로 안정.
- 콘솔 에러 없음.
- `python3 -m py_compile`로 컴파일 확인.
- 테스트 데이터(스트레스 테스트용 핵심기술 8건 추가분 포함)·서버·계정
  모두 정리.

## 2026-08-21 (24): 논문·특허 실적 박스 전체 폭으로 확대 + 박스 테두리 완화 + combined_box 내부 옅은 회색 구분선

사용자 요청: "논문 특허 실적 박스는 전체 폭을 사용하도록 넓혀줘. 박스
테두리가 너무 진하지 않게 짙은 회색 정도로 표현되게 해주고, 아까 합친
사진, 사번, 핵심기술 박스들은 사이에 옅은 회색으로 세로 줄을 그어서 살짝
구분감이 들게끔 보여지면 좋겠어."

**`pages/researcher_profile.py`**:
- `_PRINT_BOX_BORDER`를 `'1px solid #1d1d1f'`(거의 검정) → `'1px solid
  #555555'`(짙은 회색)로 완화. 이 상수를 `_print_box()`/`combined_box`가
  공유하므로 인쇄본의 모든 테두리 박스(combined_box, history_box,
  expertise_summary_box, task_hr_box, 논문·특허 상세 페이지 박스)에 한
  번에 반영된다.
- 신규 상수 `_PRINT_BOX_DIVIDER = '1px solid #ddd'`(옅은 회색) — combined_box
  내부에서 개별 테두리를 없앤 자리에 살짝 구분감만 주는 용도. `info_col`
  (사번 박스)에 `borderLeft: _PRINT_BOX_DIVIDER` 추가(기존 `paddingLeft:
  '12px'`는 그대로 둬 photo_box와의 간격 유지, 그 경계에 선이 그어짐).
  `tech_box`를 감싸는 wrapper div에도 동일하게 `borderLeft:
  _PRINT_BOX_DIVIDER` + `paddingLeft: '10px'` 추가(info_col과의 경계).
- `history_box`(논문·특허 실적 요약 + 양성·시상 이력)의 폭을 좁게 고정하던
  `style={'width': f'calc(100% - (100% - {_photo_w} - 12px) / 2)'}`를
  제거 — `_print_box()`가 이미 100% 폭으로 렌더링하므로 불필요한 wrapper
  `html.Div`(width 스타일 지정용으로만 있던 것)도 함께 없애고
  `_print_box(...)`의 반환값을 그대로 `history_box`로 쓰도록 단순화.

**검증**: 실제 서버 기동 + 로그인(team_lead) + Playwright, 이전과 동일한
스트레스 테스트 데이터(과제 14건, 긴 부서명)로 확인.
- `history_box`("논문 실적" 텍스트에서 조상 중 `borderTopWidth`가 있는
  가장 가까운 요소로 탐지) 폭이 정확히 `#profile-print-content`의 전체
  폭(1280px)과 같아짐을 확인(직전엔 폭이 좁게 제한돼 있었음).
- `history_box`/`combined_box`(둘 다 `_print_box`/직접 스타일로 만든
  실제 박스 테두리, `borderTopWidth`로 탐지해 `borderLeft`만 있는
  구분선과 구분) 둘 다 테두리 색이 `rgb(85, 85, 85)`(#555555)로 바뀐
  것을 확인 — 검증 스크립트가 처음엔 `borderWidth`(전체 축약형) 기준으로
  탐지해 `borderLeft`만 있는 구분선을 잘못 테두리로 오탐지하는 버그가
  있었는데, `borderTopWidth`(상단 변 기준, 구분선은 상단이 없음)로
  좁혀서 해결.
- `info_col`(Knox ID를 포함한 사번 박스)과 `tech_box` wrapper 둘 다에서
  `borderLeftColor`가 `rgb(221, 221, 221)`(#dddddd, 옅은 회색), 폭
  1px인 구분선이 실제로 존재함을 확인.
- `combined_box`만 잘라(clip) 스크린샷으로 육안 확인 — 사진 박스와
  사번 박스 사이, 사번 박스와 핵심기술/보유기술 박스 사이에 옅은 회색
  세로 구분선이 선명하게 보이고, 전체 박스 테두리는 예전보다 확연히
  옅어진 회색으로 보임을 확인.
- 무한 재렌더링 회귀 없음: `_dash-update-component` 요청 0건,
  `#profile-print-content` 자식 수 6회 연속 측정에서 항상 1로 안정.
- 콘솔 에러 없음.
- 1페이지 높이: 693.6px(예산 약 937px) — 논문·특허 실적 박스가 넓어져
  내용 줄바꿈이 줄어든 덕에 직전(19)~(23)번 대비 오히려 여유가 비슷하거나
  나음.
- `python3 -m py_compile`로 컴파일 확인.
- 테스트 데이터·서버·계정 모두 정리.

## 2026-08-21 (25): 보유기술 Lv/% 열 최소화 + 핵심기술 등급 원형 아이콘 복원 + 구분선 전체 높이 + 사진 10% 추가 축소 + 인쇄 배경색 제거

사용자 요청 4건: "1. 보유기술 표시하는 표에서 Lv과 %가 표시되는 공간을
최소화해줘. Lv0, 100% 정도의 글자만 들어갈 수 있으면 되니 다른 공간은
보유기술명을 표시하는 데 쓸 수 있게 해줘. 핵심기술 등급은 기존처럼
강조될 수 있게 색깔 있는 동그라미에 하얀 글씨로 표현되게 해주면 좋겠어.
아이콘 같은 형태로. 2. 박스 안에 옅은 세로줄은 박스 최상단에서 최하단까지
다 그어지게 해줘. 내용이 끝나는 데서 끝나지 않도록. 3. 사진 크기를 10%정도만
줄였으면 좋겠어. 사진 부분이 제일 길게 내려 오고 있네. 4. Page 배경색으로
옅은 회색이 사용되고 있는데 이걸 제외하면 좋겠어."

**1) 보유기술 Lv/% 열 최소화**(`components/detail_tabs.py`의
`_tech_ownership_table()`): 헤더가 없으면(`no_header=True`, 인쇄 전용)
`<Th> width`로 열 폭을 정할 수 없어(헤더 자체가 없으므로) `<colgroup>`을
새로 도입 — 전문분야(보유기술명) 열은 `html.Col()`(폭 미지정, 나머지 폭을
그대로 흡수), Lv 열은 `28px`, 보유율 열은 `36px`로 고정. 헤더가 없으면
숫자만 봐서는 "Lv"인지 알 수 없어(사용자 예시 "Lv0") 값 자체에 "Lv"
접두사를 붙인다(`no_header=True`일 때만 `f'Lv{lv}'`, 화면 표는 헤더가
있으니 그대로 숫자만).

**핵심기술 등급 → 원형 아이콘**: `components/detail_tabs.py`에 신규
`_grade_circle(grade, size=18)` — 기존 `_pill()`(둥근 사각형, "B급"처럼
여러 글자)과 달리 정사각형(18×18px)에 `borderRadius: '50%'`로 진짜
원을 만들고, 배경은 기존 `_GRADE_PILL_COLOR`(#3f8f57, 초록) 그대로
재사용, 글자는 "급" 없이 등급 한 글자만("B", "A" 등, 아이콘 크기에
맞춤) 하얀 글씨로 담는다. `_core_technology_table(compact=True)`가
전에 만들던 "(등급)분야 > 기술명" 텍스트 접두사 대신 이 원형 아이콘 +
"분야 > 기술명" 텍스트를 flex row(`alignItems: 'flex-start'`)로
배치 — 기술명이 길어 줄바꿈돼도 텍스트 자체가 별도 flex 아이템 박스라
줄바꿈된 다음 줄이 아이콘 아래가 아니라 텍스트 시작 위치에 맞춰
자동으로 들여써진다(이전 세션에 표-셀 방식으로 해결했던 것과 동일한
원리를 flexbox로 재현 — 별도 트릭 불필요).

**2) 구분선 전체 높이**(`pages/researcher_profile.py`): `combined_box`의
`alignItems`를 `'flex-start'` → `'stretch'`로 변경 — flex-start였을
때는 각 열(사진/기본정보/핵심기술)이 자기 내용 높이만큼만 차지해서,
`info_col`/`tech_box` wrapper에 걸어둔 옅은 회색 `borderLeft` 구분선이
그 열의 내용이 짧으면 박스 중간에서 끊겨 보였다. `stretch`로 바꾸면
세 열 모두 가장 긴 열의 높이까지 늘어나(짧은 열은 빈 여백이 생기지만
테두리 안쪽이라 시각적으로 문제 없음) 구분선이 박스 padding 안쪽
전체(최상단~최하단)를 관통한다.

**3) 사진 10% 추가 축소**: `_PHOTO_BOX_WIDTH_PX`(136→122, 136*0.9=
122.4→122)와 인쇄 전용 `photo_block(img_max_height=...)` 호출값
(204→184, 204*0.9=183.6→184), `assets/custom.css`의 대응 override
(204px→184px) 셋을 함께 낮췄다 — "사진 부분이 combined_box 안에서
제일 길게 내려온다"는 피드백에 따른 것.

**4) 인쇄 페이지 배경색 제거**(`assets/custom.css`): 화면용 body 배경색
(`--gs-bg: #f5f5f7`, 옅은 회색)이 `@media print` 안의
`* { print-color-adjust: exact }`(원래는 뱃지 등 의도된 배경색을
인쇄에 살리려는 규칙) 때문에 인쇄 시에도 그대로 찍히고 있었다 —
`@media print` 블록에 `body { background-color: #fff !important; }`를
추가해 인쇄 페이지는 항상 흰 배경이 되도록 했다(이 규칙은
연구원 프로필 카드 전용이 아니라 전체 인쇄 경로에 공통 적용 — 다른
인쇄 화면에도 옅은 회색이 찍히는 문제가 있었다면 함께 해결됨).

**검증**: 실제 서버 기동 + 로그인(team_lead) + Playwright, 이전과 동일한
스트레스 테스트 데이터로 확인.
- `getComputedStyle(document.body).backgroundColor` — 화면 모드에서는
  `rgb(245, 245, 247)`(옅은 회색, 정상), `page.emulate_media('print')`
  적용 후에는 `rgb(255, 255, 255)`(흰색)로 정확히 바뀌는 것을 확인.
- 핵심기술 항목에서 `borderRadius: '50%'`이고 18×18px인 `<span>`을
  탐지 — 텍스트 "B", 글자색 `rgb(255,255,255)`(흰색), 배경색
  `rgb(63,143,87)`(#3f8f57, 기존 등급 색과 동일)로 정확히 렌더링됨을
  확인.
- 보유기술 표에서 "LvN" 형식 텍스트(`Lv1`/`Lv2`/`Lv3`)가 실제로 표시됨을
  정규식으로 확인, Lv `<td>` 실측 폭 28px·보유율 `<td>` 실측 폭 36px로
  `<colgroup>` 지정값과 정확히 일치함을 확인(첫 검증 시 페이지2의 무관한
  "기여도" % 셀을 잘못 집어 77px로 나온 스크립트 버그를 발견·수정 —
  "첫 매치만 채택"으로 좁혀 해결).
- 구분선 높이: `combined_box` 자체 높이(top~bottom)와 `info_col`/
  `tech_box` wrapper의 `borderLeft` 구분선 높이를 비교 — 구분선이
  `combined_box`의 padding(10px) 안쪽 콘텐츠 영역 전체(위아래 각
  ~11px만 padding으로 남고 나머지는 전부 선으로 채워짐)를 관통함을
  확인(이전 `flex-start`였다면 내용이 짧은 열에서 선이 중간에 끊겼을
  구간).
- 사진 크기 축소: 이 저장소의 기본 샘플 사진(80×80px 정사각형
  placeholder)은 원본 자체가 새 184px 캡보다도 작아 캡 값 변화가
  드러나지 않는 한계가 있어(이전 라운드부터 반복 확인된 사실) 3:4
  비율(300×400px)의 합성 인물사진을 `data/photo/00000001.png`에
  임시로 넣어(테스트 후 삭제) 실측 — 이미지 렌더 크기가 136×181px
  ((24)번 이전 값 기준) → 122×163px로 폭·높이 모두 정확히 10.0%~10.1%
  감소함을 확인.
- 스크린샷으로 combined_box만 잘라(clip) 육안 확인 — 원형 등급 아이콘,
  좁은 Lv/% 열, 박스 전체를 관통하는 구분선, 축소된 사진을 모두 확인.
  전체 페이지 스크린샷에서도 콘텐츠 상자 바깥 여백이 흰색으로 바뀐 것을
  확인(이전 스크린샷들과 대비되는 옅은 회색 → 흰색 전환).
- 무한 재렌더링 회귀 없음: `_dash-update-component` 요청 0건,
  `#profile-print-content` 자식 수 6회 연속 측정에서 항상 1로 안정.
- 콘솔 에러 없음.
- 1페이지 높이: 기본 샘플 사진 기준 693.6px, 3:4 합성 사진(크게 렌더된
  케이스) 기준 765.6px — 둘 다 예산(약 937px) 안에 여유 있게 들어옴.
- `python3 -m py_compile`로 컴파일 확인.
- 테스트 데이터·서버·계정, 임시 3:4 합성 사진(`data/photo/`) 모두 정리.

## 2026-08-21 (26): 보유기술 표 "LvLv3" 중복 표기 버그 수정

사용자 보고: "보유 기술 표기하는 표에 LvLv3 이렇게 표시가 되네. 그냥 Lv3
으로만 표시되게 바꿔 줘." — 직전 (25)번에서 헤더 없는 보유기술 표에
"Lv" 접두사를 추가했는데(`f'Lv{lv}'`), 원본 `tech_ownership.csv`의
레벨(N) 값 자체가 이미 "Lv3"처럼 접두사를 포함해 들어오는 경우가 있어
(원천 엑셀 셀 표기가 텍스트 그대로 보존됨 —
`pipeline/process_tech_ownership.py`의 `_clean_num(val)`은 숫자 변환에
성공할 때만 정리하고, "Lv3"처럼 숫자로 안 읽히는 값은 원문 그대로
통과시킨다) "LvLv3"로 중복돼 버렸다. 이 저장소 샘플 데이터 생성기
(`pipeline/generate_sample_data.py`)는 항상 순수 숫자만 만들어서 이
세션의 기존 테스트로는 재현되지 않았던 문제.

**수정**(`components/detail_tabs.py`의 `_tech_ownership_table()`):
`no_header`(인쇄 전용) 분기에서 접두사를 무조건 붙이지 않고, 값이 이미
"Lv"로 시작하면(대소문자 무관, `lv.upper().startswith('LV')`) 그대로
두고, 아니면(순수 숫자) "Lv"를 붙이도록 idempotent하게 고쳤다.

**검증**: 실제 서버 기동 + 로그인(team_lead) + Playwright. 이번엔 버그를
실제로 재현하기 위해 `tech_ownership.csv`의 `lv_1`을 수동으로 `"Lv3"`
(원천 표기가 이미 접두사 포함인 경우 재현), `lv_2`를 `"2"`(순수 숫자,
기존 케이스)로 만든 뒤 확인 — 인쇄 콘텐츠 텍스트에서 정규식(`Lv\S*`)으로
찾은 값이 `['Lv3', 'Lv2', 'Lv3']`로 셋 다 정상(중복 없음), 문자열
전체에 `'LvLv'`가 전혀 없음을 확인. 스크린샷으로도 "반도체 소재 분석
Lv3 30%"/"박막 공정 Lv2 40%"/"품질 관리 Lv3 50%"가 깨끗하게 표시됨을
육안 확인. `python3 -m py_compile`로 컴파일 확인. 테스트 데이터(수동
수정한 lv_1/lv_2 포함)·서버·계정 모두 정리.

## 2026-08-21 (27): 과제/인사발령 이력 표시 건수 확대 + 소제목 박스 강조 + Strength Field/Keyword 힘 빼기

사용자 요청 2건: "1. 과제 수행 / 인사 발령 이력은 아래에 공간이 많은데
표시가 많이 안 되는 것 같아. 2. 전체 카드 그림 안에서 Strengh Field와
Strength Keyword가 너무 강조되어 보이는 것 같아. 핵심기술, 보유기술,
논문 실적, 특허 실적, 양성 이력, 시상 이력, 전문성 요약(LLM), 과제
수행/인사 발령 이력 이 키워드들이 네모 박스 같은 정도로 감싸져서
중제목 정도의 느낌으로 보여지면 좋겠어. Strength, Field, Strength
Keyword는 좀 더 힘을 빼줘."

**1) 과제/인사발령 이력 표시 건수 확대**: `_TASK_HR_RECENT_LIMIT`을
6 → 12로 올렸다. 6은 원래 10이었다가 "1페이지를 넘어가지 않게"라는
요청으로 줄인 값인데, 그 뒤 여러 라운드(사진 10% 추가 축소, photo/
사번/핵심기술 박스 통합, 보유기술 표 Lv/% 열 최소화, 논문·특허 박스
전체 폭화 등)를 거치며 1페이지 여유 공간이 크게 늘어, 실측해보니
limit=6일 때 페이지 예산(약 937px) 대비 190px이나 남아 있었다(사용자가
지적한 "공간은 많은데 표시가 적다"는 정확한 원인). limit=12로
올려 실측한 결과 페이지 높이 843.2px, 여유 93.5px — 여전히 안전한
버퍼를 남기면서 표시 건수를 2배로 늘렸다.

**2) 소제목 박스 강조**: `components/detail_tabs.py`에 신규
`print_sub_heading(text)` + `_PRINT_SUB_HEADING_STYLE`(옅은 회색
배경 #eef0f3 + 옅은 테두리 #d5d8dc + 둥근 모서리 + padding, 굵은 글씨
— "네모 박스로 감싸져 중제목 느낌") 추가, A4 인쇄본 전용(화면 탭에는
안 씀). 적용 지점:
- `owned_expertise_block(compact=True)`의 "핵심기술"/"보유기술" 제목
  (`compact=True`일 때만 — 화면 stacked=False는 기존 스타일 그대로).
- `pages/researcher_profile.py`의 `_print_box(title, ...)` — 인쇄본
  전용 함수라 title이 있으면 무조건 `print_sub_heading()`으로 감싸도록
  바꿨다. 이 함수를 쓰는 `task_hr_box`("과제 수행 / 인사 발령
  이력(최근 N건)")뿐 아니라 페이지2의 논문·특허 상세 표 제목(`_print_
  pub_patent_detail_page()`가 같은 `_print_box()`를 재사용)에도 자동
  적용돼 일관된 스타일이 됨(부수 효과지만 요청 취지에 부합해 그대로 둠).
- `_print_publication_summary()`/`_print_patent_summary()`: 기존엔
  "논문 실적 12건 ..."처럼 라벨과 집계가 한 문장에 섞여 있었는데,
  라벨("논문 실적"/"특허 실적")을 떼어내 함수는 집계 내용만("12건 ...")
  반환하고, 호출부(history_box 조립부)에서 `print_sub_heading('논문
  실적')`/`print_sub_heading('특허 실적')`을 앞에 붙이는 구조로 바꿨다
  — 양성 이력/시상 이력과 같은 방식으로 통일.
- "양성 이력"/"시상 이력"/"전문성 요약(LLM)" 라벨도 기존
  `className='small fw-semibold text-muted ...'`(민무늬 텍스트)에서
  `print_sub_heading()`으로 교체.

**3) Strength Field/Keyword 힘 빼기**: `llm_summary_block()`에
`deemphasize_strength: bool = False` 파라미터 추가(인쇄 전용 —
화면 탭 호출부는 인자를 안 넘겨 기존 그대로). `True`일 때 Strength
Field/Keywords를 `dbc.Badge`(dark/secondary 색 배지) 대신 옅은 회색
콤마 나열 텍스트로 바꾼다 — 다른 섹션 제목이 네모 박스로 더 강조된
것과 반대로 이쪽은 덜 튀도록. `pages/researcher_profile.py`의
`expertise_summary_box` 조립부에서 `llm_summary_block(...,
deemphasize_strength=True)`로 호출.

**검증**: 실제 서버 기동 + 로그인(team_lead) + Playwright, 이전과
동일한 스트레스 테스트 데이터(과제 14건, 긴 부서명)로 확인.
- 배경색 `rgb(238, 240, 243)`(#eef0f3)을 가진 요소를 전부 찾아 텍스트를
  모아보니 정확히 `['핵심기술', '보유기술', '논문 실적', '특허 실적',
  '양성 이력', '시상 이력', '전문성 요약(LLM)', '과제 수행 / 인사
  발령 이력(최근 12건)', ...(페이지2 상세 표 제목 2개)]`로 요청한
  8개 라벨이 전부 박스로 감싸졌음을 확인.
- `rgb(33, 37, 41)`(dark 배지)/`rgb(108, 117, 125)`(secondary 배지)
  배경을 가진 요소가 전혀 없음을 확인(Strength Field/Keywords 배지가
  사라졌음).
- 별도로 `연구원 보유 전문성 분석.json`에 실제 strength_fields/
  strength_keywords/domain_knowledge_skill이 있는 픽스처를 임시로
  넣어(테스트 후 삭제) `전문성 요약(LLM)` 박스만 잘라 스크린샷 —
  제목은 굵은 네모 박스, "Strength Field"/"Strength Keywords"는 얇은
  회색 라벨+콤마 텍스트로 확연히 톤다운되고 "전문지식 및 역량"(변경
  대상 아님)은 기존 스타일 그대로임을 육안 확인.
- 과제/인사발령 이력: limit=12로 12건이 실제로 나열되고 "외 2건 더"
  안내가 남는 것을 확인. 가장 오래된 표시 대상(2012년) 과제명을 일부러
  20자 이상의 긴 이름으로 바꿔 줄바꿈 여부까지 스트레스 테스트 —
  전체 폭 박스라 한 줄에 들어가 줄바꿈 없이 렌더링됨을 확인(페이지
  높이 수치도 짧은 이름일 때와 완전히 동일해 줄바꿈이 없었음을
  재확인).
- 무한 재렌더링 회귀 없음: `_dash-update-component` 요청 0건,
  `#profile-print-content` 자식 수 6회 연속 측정에서 항상 1로 안정.
- 콘솔 에러 없음.
- 1페이지 높이: 843.2px(예산 약 937px) — limit=12에 긴 과제명
  스트레스 테스트까지 포함한 수치, 93.5px 여유.
- `python3 -m py_compile`로 컴파일 확인.
- 테스트 데이터(긴 과제명 3건, 임시 전문성 분석 JSON 픽스처 포함)·
  서버·계정 모두 정리.

## 2026-08-21 (28): 기본 인적 정보 소제목 추가 + Strength Field/Keyword/전문지식 및 역량 소제목 통일 + disc 목록 → 사각 마커 목록

사용자 요청 3건: "1. 사번 박스 위에도 기본 인적 정보 라고 아까 만든 박스
스타일로 중제목을 달아주면 좋겠어. 2. Strength Field, Strength Keyword도
어느 정도는 디자인적 요소가 있으면 좋겠어. 그리고 Strength Field,
Keyword, 전문지식 및 역량은 소제목 형태로 통일감 있게 표현해줘. 3.
전문지식 및 역량이랑 과제 수행 / 인사 발령 이력 열거할 때 disc 형태로
list가 만들어지는 건 너무 밋밋해."

**1) "기본 인적 정보" 소제목**: `pages/researcher_profile.py`의
`info_col`(사번~Knox ID 표 + 학력) 맨 위에
`html.Div(print_sub_heading('기본 인적 정보'), className='mb-2')`를
추가했다 — combined_box 안 다른 두 열(tech_box는 `owned_expertise_block`이
이미 "핵심기술" 소제목을 달고 있음)과 대칭을 이룬다. `mb-2`는 tech_box
쪽 `owned_expertise_block`의 `left_title`(핵심기술 제목)이 쓰는 값과
맞춰, 정보 표 첫 행과 핵심기술 표 첫 행이 같은 높이에서 시작하도록
했다.

**2) Strength Field/Strength Keywords/전문지식 및 역량 소제목 통일**:
`components/detail_tabs.py`의 `llm_summary_block()`에서
`deemphasize_strength=True`(A4 인쇄 전용) 분기의 라벨 3개
("Strength Field"/"Strength Keywords"/"전문지식 및 역량")를 전부
기존 `print_sub_heading()`(다른 8개 섹션 제목과 같은 네모 박스 스타일)로
바꿨다. 별도 "축소판" 스타일을 새로 만들지 않고 기존 `print_sub_heading()`
그대로 재사용한 것은 "소제목 형태로 통일감 있게"라는 요청을 가장 직접적
으로 만족시키는 선택이며(1번 요청도 "아까 만든 박스 스타일로"라고
명시), 라벨 자체가 곧 사용자가 원한 "디자인적 요소"가 된다. 다만
Strength Field/Keywords의 *내용*(값 나열)은 이전 라운드((27)번, "너무
강조되어 보인다... 힘을 빼줘")에서 색깔 배지를 옅은 회색 콤마 텍스트로
바꾼 상태를 그대로 유지했다 — 이번 요청은 "라벨에 디자인 요소를
더해달라"는 것이지 값 배지를 부활시켜 달라는 것이 아니라고 판단(절충).
전문지식 및 역량은 원래도 `deemphasize_strength`와 무관하게 항상 표시
되던 라벨이라, 인쇄 전용(deemphasize_strength=True)일 때만
`print_sub_heading()`으로, 화면(라이브) 탭(`deemphasize_strength=False`,
기존 인자 없이 호출)은 기존 `text-muted fw-semibold` 스타일 그대로
남겼다 — 화면 탭 스타일은 이번 요청 범위 밖.

**3) disc 목록 → 사각 마커 목록**: `components/detail_tabs.py`에 신규
`bullet_list(items, *, class_name='small')` 헬퍼 추가 — 기본 `<ul>`의
브라우저 disc 마커 대신 5×5px 사각 마커(`_LIST_MARKER_COLOR = '#8e8e93'`)
+ `display:flex`/`alignItems:flex-start`로 하나하나를 행으로 그린다.
`_core_technology_table(compact=True)`가 이미 쓰던 "아이콘 + flex 행"
구조를 그대로 재사용한 것 — 줄바꿈된 다음 줄도 마커가 아니라 텍스트
시작 위치에 맞춰 들여써지는(hanging indent) 효과가 덤으로 따라온다(기존
`<ul class="ps-3">`는 이 정렬을 신경 쓰지 않았음). 적용 지점 2곳(사용자가
지목한 바로 그 두 목록):
- `llm_summary_block()`의 전문지식 및 역량(domain_skill) 목록 —
  `html.Ul(...)` → `bullet_list(domain_skill)`. 화면/인쇄 양쪽 호출부
  모두에 적용(이 목록 자체는 `deemphasize_strength`와 무관하게 항상 같은
  구조라, 인쇄 전용으로 분기할 이유가 없음 — 오히려 화면 탭의 disc도
  같이 개선되는 효과).
- `pages/researcher_profile.py`의 `_print_task_hr_timeline()` — 과제
  수행/인사 발령 이력 목록. `html.Ul(...)` → `bullet_list([e['text']
  for e in entries])`. 인쇄 전용 함수라 여기서는 사실상 인쇄본에만
  영향.
- 같은 함수의 주요 역할·책임(responsibilities) 목록도 같은 헬퍼로
  통일했다(사용자가 직접 지목하지는 않았지만, `domain_skill`과 바로
  옆에서 같은 `<ul class="ps-3">` 패턴을 쓰던 목록이라 남겨두면 오히려
  통일감이 깨짐 — 다만 `include_responsibilities=False`인 인쇄본에는
  어차피 안 보이고, 화면(라이브) 탭에만 영향).
- 양성 이력(`nurturing_block()`)의 `<ul>`은 이번 요청 대상이 아니라
  손대지 않았다(검증 스크립트로 실제 남아 있음을 확인 — 의도적으로
  그대로 둔 것).

**검증**: 실제 서버 기동(`generate_sample_data.py`로 50명 샘플 생성 후
core_technology.csv/tech_ownership.csv/hr_orders.csv를 직접 구성,
tasks.csv를 14건으로 부풀리고 부서명·학교명을 길게 바꾸는 기존
스트레스 테스트에 더해, 이번엔 `연구원 보유 전문성 분석.json`에
strength_fields/strength_keywords/domain_knowledge_skill이 모두 채워진
실제 프로필 픽스처와 hr_orders.csv 5건까지 같이 넣어 "실제 데이터가
꽉 찬" 케이스로 검증) + 로그인(team_lead, `services.auth.create_user()`로
직접 계정 생성) + Playwright.
- 배경색 `rgb(238, 240, 243)` 요소 텍스트를 문서 순서대로 모아보니
  `['기본 인적 정보', '핵심기술', '보유기술', '논문 실적', '특허 실적',
  '양성 이력', '시상 이력', '전문성 요약(LLM)', 'Strength Field',
  'Strength Keywords', '전문지식 및 역량', '과제 수행 / 인사 발령
  이력(최근 12건)', ...(페이지2 상세 표 제목 2개)]` — 요청한 3개
  라벨(기본 인적 정보/Strength Field/Strength Keywords/전문지식 및
  역량, 총 4개 항목)이 모두 소제목 박스로 통일된 것을 확인.
- `rgb(33, 37, 41)`(dark 배지)/`rgb(108, 117, 125)`(secondary 배지)
  배경 요소 없음을 재확인(Strength Field/Keywords 값은 여전히 배지가
  아니라 텍스트임을 유지).
- `#profile-print-content` 안에 남은 `<ul>`이 정확히 1개(양성 이력)뿐임을
  확인 — 전문지식 및 역량/과제 수행·인사 발령 이력의 `<ul>`은 모두
  사라지고 5×5px 사각 마커(`width:5px;height:5px`인 `<span>`) 15개로
  대체됨을 확인.
- 무한 재렌더링 회귀 없음: `_dash-update-component` 요청 0건,
  `#profile-print-content` 자식 수 6회 연속 측정에서 항상 1로 안정.
- 콘솔 에러 없음.
- **1페이지 높이 예산 관련 발견(이번 라운드가 만든 문제는 아님, 정직하게
  기록)**: "실제 데이터가 꽉 찬" 위 픽스처(전문성 분석 프로필 + hr_orders
  포함)로 측정하니 1페이지 높이 1009.9px(예산 약 937px, 73px 초과).
  같은 픽스처로 이번 3가지 변경 *이전* 코드(git stash로 되돌려 재측정)를
  재보니 이미 984.7px(48px 초과)였다 — 즉 (27)번 라운드가 `_TASK_HR_
  RECENT_LIMIT=12`를 "93.5px 여유"로 검증할 때 썼던 스트레스 테스트에는
  실제로는 `연구원 보유 전문성 분석.json`(Strength Field/Keywords/
  전문지식 및 역량 텍스트)과 `hr_orders.csv` 데이터가 포함돼 있지
  않았던 것으로 보인다(둘 다 없으면, 이번 픽스처에서도 870.4px로 66px
  여유 있게 들어옴 — 직접 재확인). 이번 3가지 변경이 추가로 얹은 높이는
  25.2px(984.7→1009.9, "기본 인적 정보" 소제목 1개 + Strength 라벨 3개
  박스화)뿐으로, 73px 초과 중 대부분(48px)은 이번 라운드 이전부터
  이미 있던 상태다. 실제 headless Chromium으로 PDF까지 뽑아
  (`page.pdf()`) 페이지 수를 세어보니(PDF 내부 `/Type /Page` 오브젝트
  개수) 3페이지로 나옴을 확인 — `task_hr_box`가 `breakable=True`(개별
  테두리 박스가 페이지 중간에서 잘리지 않게 막는 `print-section` 클래스를
  일부러 빼둔 상태, (18)~(19)번 이후 유지)라 내용 뒤쪽이 2페이지로
  자연스럽게 흘러넘치고, `_print_pub_patent_detail_page()`는
  `breakBefore:'page'`로 항상 새 페이지에서 시작하므로 상세 표는
  3페이지에서 시작 — 레이아웃이 깨지거나(글자가 겹치거나 잘리는 등)
  잘못 렌더링되는 것은 아니고, 원래 "1페이지 논문·특허 상세는 항상
  2페이지"이던 것이 데이터가 아주 많은 연구원에 한해 3페이지로 늘어나는
  정도다. 이번 요청 3건과는 무관한 사전 조건이라 `_TASK_HR_RECENT_LIMIT`
  등은 건드리지 않았고, 다음에 페이지 수 관련 요청이 오면 이 수치(전문성
  분석 데이터가 있는 연구원 기준 실제 여유가 음수)를 참고할 것.
- `python3 -m py_compile`로 컴파일 확인.
- 테스트 데이터(core_technology.csv/tech_ownership.csv/hr_orders.csv
  직접 구성, tasks.csv 14건, 전문성 분석 JSON 픽스처, 계정)·서버 모두
  정리.

## 2026-08-21 (29): 전문성 요약(LLM) 제목 제거 + Strength Field 줄에 "(by AI)" 표기 + 전문지식 및 역량 마커 제거 + 과제/인사발령 이력 표 형태로 개편

사용자 요청 3건: "1. 전문성 요약(LLM) 이라는 제목은 없어도 되겠고, Strenth
Field 라고 표시되는 줄의 오른쪽 끝에 (by AI)이라고 옅은 회색으로 써주면
좋겠어. 2. 전문지식 및 역량의 내용은 목록 아이콘 없이 약간 들여쓰기만
된 상태로 나열되게 해줘. 3. 과제 수행 / 인사발령 이력은 기간 / 날짜 |
발령 내용 | 조직명 이런 식으로 정리되게 해줘. 과제 수행인 경우에는 발령
내용에 과제 Assign 이라고 넣으면 될 것 같아."

**1) "전문성 요약(LLM)" 제목 제거 + "(by AI)" 표기**:
`pages/researcher_profile.py`의 `expertise_summary_box` 조립부에서
`html.Div(print_sub_heading('전문성 요약(LLM)'), className='mb-1')` 줄을
그냥 삭제했다. 대신 `components/detail_tabs.py`의 `llm_summary_block()`
에서 `deemphasize_strength=True`(인쇄 전용) 분기의 "Strength Field"
소제목 박스를 `justify-content-between`로 같은 줄 오른쪽 끝에
`html.Span('(by AI)', className='text-muted', style={'fontSize':
'0.68rem'})`를 배치하는 flex 행으로 바꿨다 — 제목을 없애면서도 이 블록이
LLM(AI) 생성 결과라는 정보 자체는 잃지 않도록. 화면(라이브) 탭은
`deemphasize_strength`를 안 넘겨 영향 없음(그쪽은 자체 "전문성
요약(LLM)" `<P>` 제목을 따로 갖고 있음, `update_profile()` 콜백 쪽).

**2) 전문지식 및 역량 마커 제거**: `components/detail_tabs.py`에 신규
`plain_indent_list(items, *, class_name='small')` 헬퍼 추가 — (28)번의
`bullet_list()`(사각 마커 + hanging indent)에서 마커용 `<span>`만 뺀
버전, `marginLeft: 10px`로 살짝 들여쓰기만 한다. `llm_summary_block()`의
전문지식 및 역량 목록을 `bullet_list(domain_skill)` →
`plain_indent_list(domain_skill)`로 교체(화면/인쇄 양쪽 공통 — 이 목록은
`deemphasize_strength`와 무관하게 항상 같은 구조). 주요 역할·책임
(responsibilities) 목록은 그대로 `bullet_list()`(사각 마커) 유지 —
이번 요청은 전문지식 및 역량만 지목했음.

**3) 과제/인사발령 이력 표 형태 개편**: `pages/researcher_profile.py`의
`_print_task_hr_timeline()`을 (27)~(28)번의 한 줄짜리 텍스트 목록에서
3열 표(`dbc.Table`, `기간/날짜`·`발령 내용`·`조직명` 헤더, `<colgroup>`
으로 17%/14%/나머지 폭 고정)로 바꿨다. 과제 수행 이력은 발령 내용 칸에
"과제 Assign"(사용자가 준 문구 그대로, 번역·의역하지 않음)을 넣고,
과제명 자체는 조직명 칸에 넣었다 — 인사 발령의 조직명(부서, "어디에
배정됐는지")과 "무엇에 배정됐는지"라는 성격이 같다고 보고 같은 칸을
재사용한 것(사용자가 3열만 지정했고 과제명을 따로 넣을 4번째 칸은
없었으므로). 인사 발령 이력의 조직명 칸에는 기존처럼 부서/직급/직책
(order_dep/order_cl/order_assignment)을 ' / '로 이어 붙인 값을 그대로
넣었다(이전엔 발령명 뒤 괄호 안에 있던 것을 조직명 칸으로 옮긴 것뿐,
정보 손실 없음). `bullet_list()`를 더 이상 이 함수에서 쓰지 않아
`pages/researcher_profile.py`의 import에서 `bullet_list`를 뺐다
(detail_tabs.py 안에서는 responsibilities 목록에 계속 쓰여 정의는
그대로 둠).

**검증**: 실제 서버 기동(`generate_sample_data.py` + core_technology.csv/
tech_ownership.csv/hr_orders.csv 직접 구성 + tasks.csv 14건 + 전문성
분석 JSON 픽스처, (28)번과 동일한 "실제 데이터가 꽉 찬" 스트레스
픽스처) + 로그인(team_lead) + Playwright.
- 배경색 `rgb(238, 240, 243)` 요소 텍스트 목록에서 `'전문성 요약(LLM)'`이
  사라졌음을 확인(나머지 소제목은 그대로).
- `(by AI)` 텍스트가 실제로 "Strength Field" 소제목과 같은 한 줄
  (`parentElement.textContent === 'Strength Field(by AI)'`)에 있음을
  확인. 색상은 `className='text-muted'`로 지정했는데, 이 샌드박스
  환경은 `cdn.jsdelivr.net`(Bootstrap CSS가 거기서 로드됨)에 네트워크
  접근이 안 돼 `getComputedStyle` 색상이 실제로는 검정(`rgb(0,0,0)`)으로
  측정된다(`--bs-secondary-color` CSS 변수가 빈 문자열) — `사번` 라벨
  등 기존에도 `text-muted`를 쓰던 다른 요소들도 이 환경에서는 전부
  똑같이 검정으로 측정되는 것으로 재확인했으므로, 이번에 새로 생긴
  문제가 아니라 이 테스트 환경의 네트워크 제약(운영 환경에서는 CDN이
  정상 로드되어 문제 없음)이다. `className`이 올바르게 붙어 있는지
  (DOM 구조·클래스명)로 검증을 대신했다.
- `#profile-print-content`의 전문지식 및 역량 목록에서 5×5px 사각
  마커(`<span>`)가 더 이상 하나도 없음을 확인(이전 (28)번의 15개 →
  responsibilities는 인쇄본에 애초에 안 보이므로 0개).
- 과제/인사발령 이력 표: `<th>` 텍스트가 정확히 `['기간/날짜', '발령
  내용', '조직명']`이고, 실제 데이터 행이
  `['2023-01 ~ 2023-06', '과제 Assign', '테스트과제13']`(과제)/
  `['2019-03-01', '전배', '반도체시스템연구소']`(인사발령) 형태로
  나오는 것을 확인. `<colgroup>` 폭이 실제 렌더링(17.0%/13.9%/68.6%,
  1254px 표 기준 212/174/860px)에 그대로 반영됨을 `getBoundingClientRect()`
  로 재확인.
- 무한 재렌더링 회귀 없음(`_dash-update-component` 0건, 자식 수 안정),
  콘솔 에러 없음.
- 1페이지 높이: 1024.9px(예산 약 937px, 88px 초과) — (28)번 항목에 기록한
  "실제 데이터가 꽉 찬 경우 이미 예산 초과" 사전 조건이 표 헤더 행 추가로
  15px 더 늘었을 뿐, 근본 원인(전문성 분석 데이터 존재 시)은 동일. 헤드리스
  PDF 페이지 수도 여전히 3페이지(`task_hr_box`가 `breakable=True`라 표
  뒷부분이 2페이지로 자연스럽게 흘러넘침) — PDF 페이지 개수(`/Type /Page`
  오브젝트 수)만 확인했고, 페이지 렌더링 도구가 없어 2페이지로 넘어간
  부분에서 `<thead>`가 실제로 반복되는지는 이번엔 육안으로는 확인하지
  못했다(표가 브라우저 기본 인쇄 동작으로 페이지에 걸쳐 나뉘어도 레이아웃
  깨짐·겹침은 없을 것으로 예상되지만, 이 부분은 검증 안 된 채로 남겨둠).
- `python3 -m py_compile`로 컴파일 확인.
- 테스트 데이터(core_technology.csv/tech_ownership.csv/hr_orders.csv
  직접 구성, tasks.csv 14건, 전문성 분석 JSON 픽스처, 계정)·서버 모두
  정리.

## 2026-08-21 (30): Strength Field/Keyword + 논문·특허·양성·시상 내용 들여쓰기 통일 + 과제/인사발령 이력 1페이지 동적 오토핏 + "by AI" 아이콘 배지

사용자 요청 4건: "1. Strength Field/Keyword 의 내용도 전문지식 및 역량이랑
동이랗게 들여쓰기 해줘. 2. 논문 실적, 특허 실정, 양성이력, 시상 이력의
내용도 동일하게 들여쓰기 해주면 돼. 3. 과제 수행, 인사 발령 이력의 내용은
페이지가 1페이지 안에 인쇄되도록 개수를 동적으로 조정해줘. 4. by AI라는
글씨는 괄호에 넣지 않고 아이콘 느낌으로 표현해줘. AI느낌이 나는 작은
픽토그램을 같이 넣어도 좋아."

**1)+2) 내용 들여쓰기 통일**: (29)번에서 전문지식 및 역량에 적용한
"마커 없이 marginLeft:10px만" 스타일을 나머지 항목에도 넓혔다.
- `llm_summary_block()`(`components/detail_tabs.py`): Strength Field/
  Strength Keywords 콤마 나열 텍스트 div에 `'marginLeft': '10px'` 추가.
- `_print_publication_summary()`/`_print_patent_summary()`
  (`pages/researcher_profile.py`): 반환하는 `html.Div`에 같은
  `marginLeft: 10px` 추가(둘 다 애초에 한 줄짜리 텍스트라 마커 자체가
  없었음 — 들여쓰기만 더하면 됨).
- `nurturing_block()`/`award_block()`(`components/profile_sections.py`):
  신규 `plain_style: bool = False` 파라미터 추가 — `True`면 기존
  `<ul class="ps-3"><li>`(브라우저 기본 disc 마커) 대신
  `components/detail_tabs.py`의 `plain_indent_list()`와 같은 모양(마커
  없는 `<div>`, `marginLeft: 10px`)으로 렌더링한다. 화면(라이브) 탭
  호출부(`update_profile()`)는 이 인자를 안 넘겨 기존 그대로,
  `history_box` 조립부(인쇄 전용)만 `plain_style=True`로 호출하도록
  바꿨다. `award_block()`의 `single_line=True`(생략 부호 ellipsis) 옵션은
  `plain_style=True`와 함께 써도 그대로 유지되도록 `item_style`을 두
  분기 모두에 병합해 넣었다.
- `nurturing_block`/`award_block`이 반환하는 `<ul>` 자체가 없어지면서,
  `components/profile_sections.py`가 `components/detail_tabs.py`의
  `plain_indent_list`를 새로 import한다(순환 import 없음 — `detail_tabs.py`
  는 `profile_sections.py`를 참조하지 않음, 미리 확인).

**3) 과제/인사발령 이력 1페이지 동적 오토핏**: 그동안 `_TASK_HR_RECENT_
LIMIT`(고정 12건)으로 서버에서 미리 잘라 보여줬는데((27)~(29)번에서 실측
기반으로 이 값을 조정해왔음에도, (28)~(29)번에서 실제 전문성 분석 데이터가
있으면 이미 1페이지 예산을 넘긴다는 걸 확인한 바 있다), 이번엔 아예 고정
건수 자르기를 없애고 `pages/researcher_profile.py`의
`_print_publication_detail_table()`/`_print_patent_detail_table()`(페이지2
상세 표)가 이미 쓰던 실측 기반 클라이언트사이드 오토핏 패턴을 그대로
재사용했다.
- `_print_task_hr_timeline(task_df, hr_df, rid)`에서 `limit` 파라미터를
  없애고 항상 전체 행을 렌더링, 표에 `.print-autofit-table`/
  `.print-autofit-body`/`.print-autofit-note` 마커를 단다(페이지2 상세
  표와 완전히 같은 구조 — 스타일도 같은 `_PRINT_TABLE_TH_STYLE`/
  `_PRINT_TABLE_TD_STYLE`을 재사용해 `dbc.Table` 대신 raw `html.Table`로
  바꿈).
- 문제는 `assets/profile_print.js`의 오토핏 로직(`__runProfilePrintFit()`)
  이 `.print-page-block`(지금까지 페이지2 논문·특허 상세 블록에만 붙어
  있던 클래스) 단위로만 높이를 재고 잘랐다는 것 — 페이지1 콘텐츠는 이
  마커가 없어 오토핏 대상이 아니었다. `_print_profile_content()`가
  반환하던 페이지1 콘텐츠(제목~과제/인사발령 이력+출력일)를
  `page1_block = html.Div([...], className='print-page-block')`로 감싸는
  것만으로 해결했다 — `.print-page-block` 자체엔 CSS가 전혀 없어(강제
  페이지 나눔은 페이지2 블록의 인라인 `style={'breakBefore':'page'}`가
  하는 것이지 이 클래스가 하는 게 아님, 확인) JS 셀렉터 표시 용도뿐이라
  **JS 코드는 한 줄도 안 바꿔도** 범용 오토핏 로직이 페이지1의
  `.print-autofit-table`(과제/인사발령 표)도 자동으로 집어내 실측
  높이가 예산을 넘으면 뒤쪽(오래된) 행부터 순서대로 숨기고 "외 N건 더"를
  채운다. `services/profile_pdf.py`의
  `wait_for_selector('.print-page-block', state='attached')`는 "첫 매치
  대기"라 블록이 인당 1개→2개로 늘어도 영향 없음을 확인. 일괄 인쇄
  (`/?ids=...`)는 사람마다 이미 바깥에서 `style={'breakAfter':'page'}`로
  구분하고 있어(`build_bulk_print_content()`), 사람당 블록 수가 늘어난
  것과 무관하게 그대로 동작함을 실측으로 확인(아래 검증 참고).
- `_TASK_HR_RECENT_LIMIT` 상수와 관련 주석을 통째로 삭제. `task_hr_box`
  제목에서 고정 건수("최근 N건")도 뺐다 — 이제 몇 건이 보일지는 인쇄
  시점마다 달라지므로, 페이지2 상세 표 제목들이 건수를 안 적는 것과
  같은 방식(잘린 건수는 "외 N건 더"로만 안내)으로 통일.
- `task_hr_box`를 감싸던 `_print_box(..., breakable=True)`도
  `breakable=False`(기본값)로 되돌렸다 — 오토핏이 이제 항상 1페이지
  안에 들어오게 보장하므로, 페이지2 상세 표들과 똑같이
  `break-inside:avoid`(`.print-section`)로 보호해도 안전하고, 오히려
  측정 오차로 살짝 넘칠 경우 표 중간이 아니라 박스 전체가 다음 페이지로
  통째로 넘어가는 게 더 안전하다. `_print_box()` 자체의 `breakable`
  파라미터는 지금은 아무도 안 쓰지만(향후 필요할 수 있어) 그대로 남겨둠.

**4) "by AI" 아이콘 배지**: `components/detail_tabs.py`에 신규
`_AI_TAG_STYLE` + `_ai_tag()` 추가 — bootstrap-icons의 `bi-stars`(반짝임)
아이콘 + "by AI" 텍스트를 옅은 남색 계열(#eef1fb 배경/#dde2f5 테두리)
알약(pill) 배지에 담는다. `llm_summary_block()`의 Strength Field 줄에서
`html.Span('(by AI)', ...)`(괄호 텍스트)를 `_ai_tag()` 호출로 교체 —
텍스트 자체에 괄호 문자가 없다.

**검증**: 실제 서버 기동(`generate_sample_data.py` + core_technology.csv/
tech_ownership.csv/hr_orders.csv 직접 구성 + tasks.csv 14건 + 전문성
분석 JSON 픽스처 + awards.csv 2건 직접 추가 — (29)번까지는 awards.csv가
빈 데이터라 시상 이력 들여쓰기를 육안 확인 못 했었음, 이번에 보완) +
로그인(team_lead) + Playwright.
- Strength Field 값/논문 실적/특허 실적/양성 이력/시상 이력 텍스트 요소를
  각각 찾아 `getComputedStyle(...).marginLeft`가 모두 `'10px'`임을 확인.
- `#profile-print-content` 안에 `<ul>`이 0개임을 확인(이전 (28)~(29)번의
  양성/시상 이력 `<ul>`이 이번에 마지막으로 없어짐 — 논문 실적/특허
  실적/전문지식 및 역량/Strength Field·Keywords는 이미 `<ul>`이 아니었음).
- 본문 텍스트에 `(by AI)`(괄호 포함) 문자열이 없고, `by AI` 텍스트와
  `.bi-stars` 아이콘 요소가 존재함을 확인. 다만 이 샌드박스가
  `cdn.jsdelivr.net`(bootstrap-icons 폰트가 로드되는 곳)에 네트워크
  접근이 안 돼(이전 (29)번에서도 같은 이유로 `text-muted` 색상을 픽셀로
  확인 못 했던 것과 동일한 제약) 아이콘 글리프 자체가 실제로 화면에
  그려지는지는 스크린샷으로 확인 못 했다 — `bi-stars` 클래스가 올바르게
  붙어 있는지(DOM)로 검증을 대신했고, 운영 환경(CDN 접근 가능)에서는
  정상 렌더링될 것으로 예상.
- 과제/인사발령 이력 오토핏: 실제 데이터가 꽉 찬 픽스처(전문성 분석
  프로필 있음)에서 합계 19건 중 3건만 보이고 "외 16건 더"가 표시됨을
  확인, 보이는 3건이 정확히 최신순 상위 3건(2023/2022/2021)임을 각 행의
  `style.display`로 재확인(오래된 행부터 숨겨짐 — 의도대로 동작).
  전문성 분석 프로필을 뺀(더 여유 있는) 같은 픽스처로는 9건이 보임을
  확인해, 콘텐츠 양에 따라 실제로 "동적으로" 조정됨을 실증.
- 페이지 수: `.print-page-block` 개수가 정확히 2개(페이지1 콘텐츠 +
  페이지2 상세)이고, 페이지2 블록의 top이 페이지1 블록의 height와
  정확히 일치함을 확인 — (28)~(29)번에서 실제 데이터가 꽉 찬 경우 3페이지로
  넘치던 문제가 이번 오토핏 도입으로 해결됨(더 이상 페이지1 콘텐츠
  높이를 직접 실측해 예산과 비교할 필요 없이, 오토핏이 항상 예산
  이하로 맞춰준다 — 실측값 882.8px < 예산 936.7px).
  전문성 분석 프로필을 뺀 경우도 페이지1 높이 873.2px로 마찬가지 2페이지.
- 일괄 인쇄(`/?ids=00000001,00000002,00000003`)로 3명을 한 번에 인쇄해
  `.print-page-block`이 정확히 6개(인당 2개)이고, 각자의 페이지1
  제목("연구원 프로필")·페이지2 제목(이름+사번)이 모두 정상 출력되며
  콘솔 에러가 없음을 확인(뜬 에러 2건은 `net::ERR_TUNNEL_CONNECTION_
  FAILED` — 위와 같은 CDN 네트워크 제약, 앱 자체 에러 아님).
- 무한 재렌더링 회귀 없음(`_dash-update-component` 0건, 자식 수 안정),
  콘솔 에러 없음(단일 인쇄 기준).
- `python3 -m py_compile`로 컴파일 확인.
- 테스트 데이터(core_technology.csv/tech_ownership.csv/hr_orders.csv/
  awards.csv 직접 구성, tasks.csv 14건, 전문성 분석 JSON 픽스처, 계정)·
  서버 모두 정리.

## 2026-08-21 (31): 과제/인사발령 이력 오토핏 임계값 보정 — 페이지1 전용 안전 여백 도입 + (30)번 검증 방법 오류 정정

사용자 리포트: "아래에 공간이 있는데 발령 건수가 좀 적게 들어가는 듯해."

**원인**: (30)번에서 과제/인사발령 이력을 페이지2 상세 표와 같은
`.print-autofit-table`/`PAGE_HEIGHT_PX`(A4 전체 높이 − 80px 안전 여백,
약 936.69px) 로직에 태웠는데, 이 80px 안전 여백은 페이지2(표 위주,
제목 줄바꿈이 많은 콘텐츠)를 기준으로 잡힌 값이라 페이지1(사진/기본정보/
핵심기술 등 flex 레이아웃 위주 콘텐츠)에는 안 맞았다. Playwright로
직접 실측해보니, 페이지1 콘텐츠에서는 오프스크린 측정 기법(assets/
profile_print.js의 `__pp-measuring`, `position:fixed` 클론으로 잰다)이
실제 인쇄 결과보다 오히려 "더 크게"(반대 방향!) 나왔다 — 같은 픽스처에서
표시 행 수를 0/3/9/19로 바꿔가며 측정해도 (실제 DOM 높이 − 오프스크린
높이)가 항상 정확히 일정(부서명 긴 픽스처 −60.9px, 짧은 픽스처
−45.7px)했다. 페이지2용 80px 안전 여백을 그대로 적용하면 이미 여유가
있는 페이지1에 또 안전 여백을 얹는 격이라 필요 이상으로 적게(3건)만
보여주고 있었다.

**(30)번 검증 방법의 문제(정정)**: 처음에는 "오프스크린 ↔ DOM 실측
차이"만 보정해 임계값을 `A4 전체 높이 + 25px ≈ 1041.69px`로 올렸는데,
이 값으로 실제 `page.pdf(prefer_css_page_size=True)` 헤드리스 PDF를
뽑아보니 **3페이지로 넘쳤다** — "DOM 실측(print media) vs 실제 PDF
페이지 나눔 경계"에도 별도의 설명 안 되는 차이가 있었던 것(Playwright
`page.pdf()`의 페이지 분할 계산과 브라우저 print-media 레이아웃이
완전히 같지는 않은 것으로 추정, 원인 정확히 못 밝힘). 돌이켜보면
(30)번에서 "3페이지 초과 문제가 해결됨"이라고 적었던 근거는
`.print-page-block` DOM 요소 개수(=2, 페이지1/페이지2 마커일 뿐 실제
인쇄 페이지 수가 아님)와 `getBoundingClientRect()` 높이 vs 예산
비교였지, **실제 `page.pdf()`로 페이지 수를 직접 세어 재확인하지
않았다** — (28)/(29)번에서는 이 방식으로 직접 확인했었는데 (30)번에서
빠뜨린 것. 이번 라운드에서 이 실수를 발견하고 바로잡았다: 최종 값은
간접 추론이 아니라, `data-fit-height-px`(아래) 후보값을 여러 개 두고
매번 실제 `page.pdf()`를 뽑아 페이지 수를 세는 이분 탐색으로 구했다.

**수정**: `assets/profile_print.js`의 `fitBlock(block)`이
`block.getAttribute('data-fit-height-px')`가 있으면 공용 `PAGE_HEIGHT_PX`
대신 그 값을 쓰도록 변경(없으면 기존 그대로 — 페이지2 블록은 영향
없음). `pages/researcher_profile.py`에 신규 상수
`_PAGE1_FIT_HEIGHT_PX = 1000`(부서명이 긴 픽스처·짧은 픽스처 둘 다
A4 전체 높이(1016.69px) 근처에서 2→3페이지 경계가 있음을 확인하고,
그보다 확실히 낮은 안전한 값으로 선택 — 정확한 탐색 로그는 상수
정의부 주석 참고)을 추가하고, `page1_block = html.Div([...],
className='print-page-block', **{'data-fit-height-px':
str(_PAGE1_FIT_HEIGHT_PX)})`로 속성을 붙였다.

**검증**: 실제 서버 기동 + 로그인 + Playwright, 부서명이 긴
픽스처(전문성 분석 데이터 있음)와 짧은 픽스처(전문성 분석 데이터
없음) 둘 다로 확인.
- `data-fit-height-px` 후보값(850~1041.69px 사이 다수)마다 매번 실제
  `page.pdf(prefer_css_page_size=True)`를 뽑아 PDF 내부 `/Type /Page`
  오브젝트 개수를 세는 이분 탐색으로 안전한 값의 범위를 찾았다(긴
  픽스처: 1016.69px 이하는 전부 2페이지, 1020px부터 3페이지로 넘침.
  짧은 픽스처: 1010px 이하는 2페이지, 1016.69px부터 3페이지로 넘침
  — 두 픽스처 모두에 안전한 1000px을 최종 채택).
- 최종 값(1000px)으로 두 픽스처 모두 실제 PDF가 정확히 2페이지임을
  재확인. 표시 행 수는 긴 픽스처 6건(19건 중, "외 13건 더" — (30)번의
  3건에서 2배로 늘어남), 짧은 픽스처 13건(19건 중, "외 6건 더" — (30)번
  때는 이 픽스처를 아예 검증에 안 썼었음)으로, 콘텐츠 여유에 따라
  실제로 더 많이 보여주게 됐음을 확인.
- 무한 재렌더링 회귀 없음, 콘솔 에러 없음.
- `python3 -m py_compile`, `node --check assets/profile_print.js`로
  컴파일/문법 확인.
- 테스트 데이터(core_technology.csv/tech_ownership.csv/hr_orders.csv
  직접 구성, tasks.csv 14건, 전문성 분석 JSON 픽스처, 부서명 긴/짧은
  버전, 계정)·서버 모두 정리.

**교훈**: 클라이언트사이드 오토핏처럼 "실제 인쇄 파이프라인"이 최종
판정자인 기능은, 중간 단계 측정값(오프스크린 클론 높이, DOM
`getBoundingClientRect()`)이 서로 일치하더라도 실제 `page.pdf()`
페이지 수까지 반드시 다시 확인해야 한다 — 이번처럼 두 번째 단계
(DOM 실측 vs 실제 PDF)에서 또 다른 오차가 숨어 있을 수 있다.

## 2026-08-21 (32): BGE-M3 임베딩 서버를 docker-compose 서비스로 분리 (Job Market "임베딩 서버 연결 불가" 오류 대응)

배경: 지금까지는 `bge_server.py`(BGE-M3 임베딩 서버, `services/bge_server.py`)
를 Windows 호스트에서 직접(수동 또는 `pipeline/embed_server.py`의
`ensure_embed_server()` 자동 기동으로) 실행해왔는데, 배포 환경을 Linux
머신으로 옮기면서 이 서버를 어디서도 실행하지 않게 됐다 — Job Market
화면에서 "로컬 임베딩 서버에 연결할 수 없습니다" 오류가 뜨는 원인.
`docker-compose.yml`을 확인해보니 애초에 이 서버가 컨테이너 배포
경로에는 전혀 반영돼 있지 않았다: `app` 컨테이너(Dockerfile)는
`requirements.txt`만 설치해 `FlagEmbedding`/`torch`가 없고, `ensure_embed_server()`
는 오프라인 배치(`run_expertise.py`)에서만 호출돼 웹 앱 요청 경로
(Job Market 실시간 매칭, `services/job_market.py` → `pipeline/researcher_fit.py`
의 `cached_embed()` → `services/llm.py`의 `embed()`)에서는 아예 자동
기동되지 않는다 — 애초에 어떤 배포 시나리오에서도 라이브 앱이 BGE
서버를 스스로 띄워주지 않았고, Windows 호스트에서 수동으로 띄워온
것으로 이 구멍이 가려져 있었다.

**결정**: `ollama`(로컬 LLM, 기존에도 `profiles: ["llm"]`로 옵셔널
분리)와 같은 패턴으로 BGE-M3도 별도 docker-compose 서비스로 분리하기로
했다(사용자에게 "앱 컨테이너 안에 같이 넣기" 대안과 함께 트레이드오프
설명 후 확정) — `torch`/`FlagEmbedding`이 무거운 ML 의존성(수 GB)이라
앱 이미지에 얹으면 배포마다 재빌드가 커지고, 무엇보다 `gunicorn`
재시작(배포/장애/`docker compose restart`)마다 이미 로딩해둔 BGE-M3
모델까지 함께 죽어 재로딩(수십 초~수 분)이 필요해진다 — 별도의 오래
사는 컨테이너로 분리하면 앱을 몇 번 재배포해도 임베딩 서버는 계속
켜진 채로 재사용된다.

**변경**:
- 신규 `Dockerfile.embed`: `services/bge_server.py` + `requirements-embed.txt`
  만 담은 최소 이미지. 메인 `Dockerfile`과 같은 사내 CA/프록시 패턴을
  재사용. `EMBED_BASE_URL=http://0.0.0.0:7138`을 이미지 안에 고정해(기본값
  `localhost`는 컨테이너 자기 자신만 접근 가능해 다른 컨테이너에서 못
  붙는다) 어떤 배포에서도 항상 모든 인터페이스에 바인딩되게 했다.
  `TORCH_INDEX_URL` 빌드 인자(GPU용, 기본 빈 값=CPU 빌드)를 추가 — 값이
  있으면 `requirements-embed.txt` 설치 전에 그 인덱스에서 torch를 먼저
  설치해 CUDA 빌드가 자리 잡게 한다(PyPI 기본 CPU 빌드가 나중에 덮어쓰지
  않도록 순서가 중요).
- `docker-compose.yml`: 신규 `bge-embed` 서비스(`profiles: ["embed"]`,
  `ollama`와 동일하게 기본으로는 안 뜸). 모델 캐시용 `bge_hf_cache`
  볼륨(`/root/.cache/huggingface`)을 붙여 재기동해도 BGE-M3를 매번 다시
  받지 않게 했다. `app` 서비스 환경변수에 `EMBED_BASE_URL: ${EMBED_BASE_URL:-http://bge-embed:7138}`
  (도커 네트워크 안에서 서비스명으로 접근)/`EMBED_MODEL` 추가, `NO_PROXY`/
  `no_proxy` 목록에 `bge-embed` 추가(다른 내부 대상들과 같은 이유 — 런타임
  프록시가 컨테이너 간 트래픽을 가로채지 않게).
- `docker-compose.gpu.yml`: `bge-embed`에도 `ollama`와 같은 GPU 디바이스
  예약을 추가하되, 주석으로 명확히 구분했다 — `ollama`는 자체 CUDA
  감지 바이너리라 디바이스 노출만으로 충분하지만, `bge-embed`는 파이썬
  torch라 디바이스 노출만으로는 부족하고 `TORCH_INDEX_URL`로 실제
  CUDA 빌드 torch를 설치해야 GPU를 쓴다 — 오버레이에서 `build.args.TORCH_INDEX_URL`
  을 `https://download.pytorch.org/whl/cu121`로 지정해 이 부분까지
  실제로 동작하게 만들었다(단순히 디바이스만 노출해 놓고 "GPU 지원"이라고
  적으면 실제로는 CPU 빌드 torch가 GPU를 안 쓰는 상태로 오해를 살 수
  있어, 값이 없을 때의 함정을 주석에도 명시).
- `.env.example`의 BGE-M3 섹션 갱신 — `EMBED_BASE_URL`이 "앱이 어디서
  실행되는지"에 따라 값이 달라진다는 것(컨테이너+컨테이너 vs 로컬+컨테이너
  vs 컨테이너+호스트 조합별 예시)과, `docker compose --profile embed up -d
  bge-embed` 사용법을 명시.

**검증**: 이 세션(샌드박스)에는 docker 데몬이 없어(`docker version`은
클라이언트만 성공, 데몬 소켓 연결 실패) 실제 이미지 빌드/기동까지는
못 했다 — 대신:
- `python3 -c "import yaml; ..."`로 `docker-compose.yml`/`docker-compose.gpu.yml`
  둘 다 YAML 문법 오류 없음을 확인.
- `docker compose --profile embed config`로 실제 컴포즈 병합 결과를
  렌더링해, `app`의 `EMBED_BASE_URL`이 `http://bge-embed:7138`로,
  `bge-embed` 자신의 `EMBED_BASE_URL`이 `http://0.0.0.0:7138`로 서로
  다르게(의도대로) 나오는 것을 확인. 포트(7138)/볼륨(`bge_hf_cache`→
  `/root/.cache/huggingface`) 매핑도 의도대로 렌더링됨을 확인.
- `docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile
  embed config`로 GPU 오버레이가 `bge-embed`의 `build.args.TORCH_INDEX_URL`
  과 `deploy.resources.reservations.devices`를 올바르게 병합하는 것을
  확인.
- `Dockerfile.embed`의 두 `RUN` 블록을 셸 스크립트로 추출해 `bash -n`
  으로 문법 오류 없음을 확인(실제 `pip install`까지는 실행 안 함 —
  torch/FlagEmbedding 다운로드는 이 세션에서는 과함).
- **실기 빌드/기동/실제 임베딩 호출까지는 검증하지 못했다** — 사용자가
  실제 Linux 배포 환경에서 `docker compose --profile embed up -d bge-embed`
  로 띄운 뒤 Job Market 화면에서 직접 재현 확인이 필요하다.

## 2026-08-25 (33): 팀참조시트 전처리 개편 + "팀/리더 참조" 관리자 웹 CRUD 탭 신설

배경: 팀참조시트.xlsx의 컬럼 체계를 바꾸고(비공식소속부서명/구분/부서/
과제·파트 등 신규), 지금까지 파일 전량 덮어쓰기였던 team_refer.csv를
날짜 기반으로 누적하며, 최초 1회는 엑셀 업로드로 적재하되 이후에는
관리자 화면에서 웹으로 개별 조직 단위를 수시 수정할 수 있게 해달라는
요청. 기존 team_refer.csv는 실행할 때마다 전량 교체하는 구조라, 부분
수정을 전제로 한 웹 CRUD와 근본적으로 맞지 않았다(전체 재업로드가
아니면 "이번에 없으면 삭제"를 판단할 기준이 없음).

**결정 1 — 컬럼 재매핑**(`pipeline/process_team_refer.py`): 엑셀 헤더명 →
출력 컬럼명을 `비공식소속부서명→org_name_wd`(researchers.csv org_code
매칭키, 구 project_name), `구분→work_type`(신규, "R&D"만 전문성 분석
대상), `부서→dep_name`(신규, "연구원 명단" 부서 필터 표시 전용 — 조직도
트리 구조와는 무관한 평면 태그), `과제/파트→pjt_part_name`(조직도 트리
라벨 — 이제 이 값만 사용, 구 end_name/project_name 폴백 제거),
`조직코드→dep_code`(구 code3)로 바꿨다.

**결정 2 — 날짜 기반 누적, dep_id별 최신 판정**: 자연키를
`(dep_id, valid_year, valid_month, valid_day)`로 바꾸고 `pipeline/merge_utils.py`의
기존 upsert 인프라(TABLE_KEYS에 등록)로 계속 누적한다. "현재" 조직도는
researchers.csv의 is_current처럼 파일 전체 기준 최신 날짜 하나를 쓰지
않고, **dep_id별로 독립적으로 최신 날짜 행**을 고른다
(`rd_specialist_markdown._latest_current_rows()`, `read_team_refer()`가
호출부에 반환하기 전에 자동 적용) — 웹에서 조직 하나만 오늘 날짜로
저장해도 나머지 dep_id는 각자 마지막 저장 시점 값 그대로 정상 노출되게
하기 위함(파일 전체 기준이면 부분 수정이 나머지 전체를 "사라짐"으로
만들어버림). 삭제는 실제로 지우지 않고 `deleted='Y'` 표시가 붙은 새
날짜 행(톰스톤)으로 남긴다 — 이력은 보존하되 "현재" 판정에서는 제외.

**결정 3 — 전문성 분석 대상 필터 교체**: `전문성 분석 부서.xlsx`
(`process_analysis_dep.py`, department 화이트리스트)를 `work_type=="R&D"`
게이트로 완전히 대체하고 그 파일/모듈은 삭제했다(`process_researcher_expertise.py`
`_filter_eligible_researchers()`). org_code가 team_refer에 매핑되지 않은
연구원은 이제 R&D 여부를 판단할 근거가 없어 분석 대상에서 제외된다(이전
"매핑 실패해도 부서 화이트리스트만 통과하면 포함"과 달리 team_refer
매핑이 필수가 됨 — 사용자 확정).

**결정 4 — "연구원 명단" 부서/과제 필터**: 라벨은 team_refer의
dep_name/pjt_part_name(신규 `services/similarity_map.py` 헬퍼:
`department_filter_options`/`pjt_part_filter_options`)에서 가져오되, 실제
연구원 필터링은 여전히 org_code 매칭(`org_codes_for_dep_names`/
`org_codes_for_pjt_part_names`)으로 한다 — 라벨 문자열이 researchers.csv
표기와 다를 수 있어(기존 `_project_options()`가 지적했던 이유) 라벨로
직접 비교하지 않는다. "과제" 필터 라벨을 "과제/파트"로 변경.

**결정 5 — "팀/리더 참조" 관리자 웹 CRUD**(`pages/admin.py`,
`services/team_refer_store.py`): 관리자 화면을 `dbc.Tabs`로 재구성해
"사용자 관리" 옆에 신설. 컬럼은 엑셀 원본 헤더명을 그대로 쓰고
(`process_team_refer._COL_MAP` 재사용), `dash_table.DataTable`의
`row_deletable`로 행 삭제, "행 추가" 버튼으로 빈 행 추가. 저장 시
`dcc.DatePickerSingle`로 지정한 날짜(기본 오늘, 과거 소급 입력 가능)로
스탬프해 `team_refer.csv`에 반영하고, `team-refer-loaded-dep-ids` Store
(그리드를 처음 불러올 때의 부서ID 목록)와 저장 시점 그리드를 비교해
사라진 dep_id는 톰스톤으로 처리한다. `services/team_refer_store.py`가
CSV 반영과 함께 DB(`DATABASE_URL` 설정 시 `team_refer` 테이블, Postgres
`ON CONFLICT` upsert, `services/user_store.py`와 동일한 패턴 — DB 없으면
조용히 실패 반환하고 CSV 반영만으로 정상 동작)에도 반영한다. 저장할
때마다 `data/processed/team_leader_refer/팀_리더_참조_입력날짜(YYMMDD).xlsx`
로 그 시점 전체 스냅샷도 남긴다(파일명이 날짜까지만이라 같은 날 재저장은
덮어써 마지막 저장이 그날의 유효값이 됨 — 사용자 확정). 상위부서ID가
실제 존재하는 부서ID를 가리키지 않으면 저장은 진행하되 경고를 보여준다
(`build_org_tree()`가 이런 행을 조용히 최상위 조직으로 취급하므로).

**검증**:
- `rd_specialist_markdown._latest_current_rows()`/`build_org_tree()`/
  `org_tree_html()`에 합성 데이터로 부분수정(한 dep_id만 최신 재저장,
  다른 dep_id는 과거 날짜 그대로 생존)·삭제(톰스톤 제외) 시나리오 통과.
- `services/similarity_map.py`의 부서/과제·파트 옵션·매칭 헬퍼를 동일한
  합성 데이터로 별도 검증(캐스케이딩, org_code 집합 산출).
- `services/team_refer_store.py`의 `save_snapshot()`/`list_editable_rows()`/
  `export_snapshot_xlsx()`를 CSV 경로로 3회 연속 저장(신규→수정→삭제)
  시나리오로 직접 실행해, 누적 행 수·최신 판정·톰스톤·엑셀 스냅샷 파일명이
  전부 의도대로 나오는 것을 확인(DB는 이 세션에 DATABASE_URL이 없어
  `db_ok=False` 경로만 확인, 실제 Postgres upsert는 미검증).
- `pages/admin.py`를 `dash.Dash(use_pages=True)` 컨텍스트에서 실제로
  `layout()`/`_team_refer_tab()`을 렌더링해 컴포넌트 트리 구성 오류가
  없음을 확인, `team_refer_add_row`/`team_refer_save` 콜백 함수를 직접
  호출해(빈 부서ID 행 스킵, 로드된 dep_id 목록 갱신) 동작을 확인.
- 변경된 모든 파일 `py_compile` 통과.
- **미검증**: 실제 DB(Postgres) upsert 경로, 브라우저에서의 실제
  클릭·타이핑 조작(DataTable 인라인 편집/행 삭제 UI 자체), 로그인 세션을
  통한 관리자 권한 게이트의 실제 동작.

## 2026-08-26 (34): 원천 파일명 와일드카드 매칭 도입 + 헤더 행 재조정 + job_profile 2파일 병합 전처리

배경: 사내 시스템에서 원천 엑셀을 다운로드하면 파일명에 다운로드 시각이
찍혀 나와(예: "T&P 기본 인사 정보 2026-08-26 11_22 GMT+9.xlsx") 매번
이름이 달라진다 — `pipeline/sources.py`가 그동안 요구하던 고정 파일명
매칭(`인력현황.xlsx` 등)이 더는 맞지 않는다는 사용자 확인에 따라, 관련
6개 원천(인력현황/T&P/시상/학력/인사발령/직무이력)의 파일명을 와일드카드
패턴으로 바꾸고, 각 파일의 실제 헤더 행 위치도 함께(사내 리포트 상단에
안내문 행이 붙어 있어 예전보다 아래로 밀림) 재조정했다.

**결정 1 — 와일드카드 매칭 인프라**(신규 `pipeline/source_files.py`):
`find_matches()`/`find_latest()`가 `data/raw/`(또는 `data/updates/`)를
스캔해 패턴에 맞는 파일을 mtime 오름차순으로 찾는다. 여러 개가 동시에
매칭되면: 스냅샷성 파일(T&P/시상/학력/인사발령/직무이력)은 `find_latest()`로
가장 최근 수정된 파일 하나만 쓰고, 인력현황만 `find_matches()`로 매칭되는
파일을 전부 읽어 이어붙인다(아래 결정 2). `pipeline/sources.py`의 각
항목은 이제 (스테이징명, 패턴|패턴리스트, header_row, multi=False) 4-tuple이며,
패턴에 '*'가 없으면 기존과 동일하게 정확한 파일명만 찾는다.

**결정 2 — 인력현황(researchers)은 파일명이 아니라 내부 데이터로 현재/과거를
가린다**(사용자 확정: "YYYYMM 접두사는 크게 의미가 없다"): 다운로드 파일이
여러 개 동시에 있어도(`*That Month Headcount*.xlsx` / `*End of Month
Headcount*.xlsx`) `xlsx_to_raw_csv.py`가 stage 1에서 전부 읽어 그대로
이어붙이기만 하고(가공 없음 — stage 1의 기존 원칙 유지), 실제 "이 사람의
현재 소속"은 여전히 `process_researchers.py`가 각 행의 인원실적년도/
인원실적월(내부 컬럼)로 판단한다(기존 is_current 로직 그대로, 사용자가
이미 확정한 patterns). 다만 두 파일에 같은 researcher_id가 다른 기간으로
동시에 존재할 수 있게 되면서, 업서트 시 "새 배치 안에서 키가 중복되면
마지막 행 채택"(`merge_utils.upsert_merge`)이 파일명이 아니라 기간 순서를
따르도록 `result.sort_values(['researcher_id','valid_year','valid_month'])`로
정렬 기준을 변경(기존엔 researcher_id 단일 정렬이라 동순위 정렬이
불안정해 어느 파일이 이길지 보장이 없었음 — 실제 버그였을 수 있는 지점을
이번에 같이 정리).

**결정 3 — job_profile은 2개 원천을 병합한 새 파일을 읽는다**(신규
`pipeline/merge_job_profile_source.py`, `xlsx_to_raw_csv.py`가 매 실행
맨 앞에서 자동 호출): 구버전 이력 `임직원_직무이력('18.5월_이전).xlsx`
(직종/직군/주직무여부 삭제, "직무 프로필"→"직무" 개명)와 최신
`내 리포트 *.xlsx`(ID 컬럼 삭제)를 합친다. 안전을 위해 신규 파일(2번)의
컬럼명을 기준으로 구버전 데이터(1번)를 `reindex`해 맞춘(사용자 확정 —
컬럼이 이미 완전히 같더라도 방어적으로) 뒤, 신규 데이터 다음에 구버전을
이어붙이고 "사번" 오름차순 정렬. 원본을 덮어쓰지 않고 새 파일
"내 리포트 *_병합.xlsx"로 저장하며, 신규 파일의 앞쪽 안내 행(1~5행)을
그대로 보존해 병합 산출물도 "6번째 행이 헤더"를 유지한다(`sources.py`의
job_profile 헤더 행과 일치시키기 위함 — 이를 위해 `excel_reader.py`에
헤더 적용 없이 원본 행렬을 그대로 돌려주는 `read_xlsx_matrix()` 추가).
`find_latest(..., exclude='_병합')`로 이 스크립트 자신의 산출물을 다음
실행에서 다시 입력으로 집어먹지 않게 막는다.

**결정 4 — 헤더 행 재조정**(모두 사용자 지정값, 0-based로 환산):
인력현황 0→1, T&P 0→8, 시상 0→8, 임직원학력 0→9, 인사발령이력 0→1,
양성_인력_현황(파일명 불변) 0→1, job_profile(병합본) →5, 업무목표24/25/26
(파일명 불변) 0→2. 특허/과제정보/핵심기술/보유기술/개인별논문현황/
리더십진단/핵심이력 등 나머지는 그대로.

**결정 5 — 업무목표24/25/26의 "사번"→"부서장사번" 개명**: 소스 파일
자체에서(과거 부서장 사번 컬럼이 "사번"으로 잘못 표기돼 연구원 본인
식별용 "사번"(F열)과 혼동됐던 것을) 개명하기로 확정 — 개명 후에는 파일에
"사번"이라는 헤더가 F열 하나만 남으므로 `process_work_objective.py`의
`COL_ID = '사번'`은 코드 수정 없이 그대로 F열을 가리킨다. 2~3열 병합
셀 해제는 사용자가 실데이터로 직접 확인해 빈 값이 생기지 않는다고
확정했으므로 fill-down 등 별도 처리 코드는 추가하지 않았다(문제가 생기면
추후 대응).

**결정 6 — `data/updates/`(수시 업서트) 경로도 새 패턴을 인식**:
`pipeline/run_update.py`의 파일 존재 판정을 각 process 모듈이 export하는
`*_PATTERN`/`*_PATTERNS` 상수 기준 와일드카드 매칭으로 바꿨다(기존엔
정확한 파일명 문자열 비교라 이름이 바뀌면 그냥 무반응이었을 것).

**검증**:
- 변경된 모든 pipeline 파일 `py_compile` 통과.
- `source_files.find_matches`/`find_latest`를 합성 파일(동시에 여러 개
  매칭, `_병합` 제외 옵션 포함)로 직접 실행해 mtime 정렬·제외 동작 확인.
- `merge_job_profile_source.run()`을 openpyxl로 만든 합성 legacy/new
  파일(안내 행, 헤더 위치, 중복 사번, 컬럼 불일치 포함)로 직접 실행 —
  컬럼 삭제/개명/정렬/이어붙이기·안내 행 보존이 모두 의도대로 나오는 것을
  `pandas.read_excel(header=5)`로 재확인.
- **미검증(Windows+xlwings+실제 DRM 원본 없이는 불가)**: `xlsx_to_raw_csv.py`
  전체 실행(실제 회사 다운로드 파일로), `process_researchers.py`의 다중
  파일 업서트가 실제 DB/CSV 파이프라인 전체를 통과하는 end-to-end 시나리오.

## 2026-08-26 (35): 관리자 "데이터 업데이트" 탭 — 매니페스트 20개 파일 웹 업로드/실행 + DB 반영 버튼

배경: 지금까지 원천 엑셀 갱신은 Windows PC에서 로컬로 process_*.py를 직접
돌려야 했는데, 매니페스트 22개 중 리더십진단(원본 파일 있음에도 운영상
제외 확정)·comments_raw(원본 자체가 없음) 2개를 뺀 20개를 관리자 화면에서
직접 업로드→실행할 수 있게 해달라는 요청. 서버는 리눅스, 사용자는 Windows
브라우저로 접속(사용자 확정) — 즉 지금까지 전제였던 xlwings(Excel COM,
Windows 전용) DRM 해제를 서버에서 할 수 없어, **업로드 전 사용자가 자기
PC의 Excel에서 열어 "다른 이름으로 저장"으로 DRM을 해제한 사본을 올린다**는
전제로 설계했다(사용자 확정 — 대안으로 제시한 "실제 DRM 여부 테스트"/
"Windows 워커 별도 구축"은 채택 안 함). 서버는 평범한 xlsx만 받으므로
excel_reader.read_xlsx()의 기존 openpyxl 폴백(xlwings import 실패 시
자동 전환)이 그대로 쓰인다 — 이 폴백 자체는 이미 있던 코드라 변경 없음.

**결정 1 — 신규 `services/web_pipeline_runner.py`**: 20개 항목의 매니페스트
(키/라벨/pipeline 모듈명/업로드 안내문구/모드)를 갖고, `data/web_updates/<key>/`
폴더에 업로드 파일을 보관한다. 모드 3가지: 'exact'(정확한 파일명 하나 —
업로드 즉시 그 모듈이 기대하는 파일명으로 저장해, 사용자가 로컬 파일명을
다르게 저장해와도 실행이 실패하지 않게 함), 'wildcard'(원본 브라우저
파일명 그대로 보존 — 각 모듈의 raw_dir 오버라이드가 기존
pipeline/source_files.py 와일드카드 매칭으로 그대로 찾음, 2026-08-26(34)번
작업 재사용), 'dual'(직무이력 전용 — 사용자 확정: 구버전 이력(선택)/
"내 리포트"(필수) 두 파일을 각각 업로드, 실행 시 merge_job_profile_source.py
전처리를 먼저 돌린 뒤 process_job_profile.py 실행).

**결정 2 — 실행/실패 사유 캡처**: 각 process_*.py는 성공 여부만 bool로
반환하고 실패 사유는 print()로만 남기는 경우가 많아, 실행을
`contextlib.redirect_stdout`으로 감싸 캡처하고 마지막 [ERROR]/[SKIP]/[WARN]
줄을 실행결과 메시지로 쓴다(사용자 확정 — "실제 처리를 시도해서 에러
메시지를 보여주는 걸로 충분", 업로드 파일명 사전 검증은 하지 않음).
예외가 나면 예외 메시지 + 캡처된 로그를 합쳐 보여준다.

**결정 3 — 실행 로그는 CSV**(`data/processed/web_pipeline_runs.csv`,
사용자 확정 — DB 대신): 키당 1행(최종실행이력/실행결과)만 유지, 매 실행마다
덮어씀(이력 누적 아님 — 감사 목적이 아니라 "가장 최근 상태" 표시 목적).

**결정 4 — 동시 실행 방지 락은 파일 기반**(`data/web_updates/.lock.json`):
이 앱이 `gunicorn --workers 2`로 뜨므로(Dockerfile) 워커 프로세스 메모리상의
플래그로는 두 워커 간에 공유가 안 돼, 파일 락 + 30분 초과 시 죽은 락으로
간주하고 무시하는 방식을 썼다. "전체/선택 실행"과 "DB 반영"은 같은 락을
공유해 동시 진행을 막는다(둘 다 data/processed를 건드리므로).

**결정 5 — 백그라운드 스레드로 실행**(사용자 확정: "브라우저 탭을 꺼도
서버에서는 계속 돌게"): 버튼 클릭 콜백은 `threading.Thread(daemon=True)`를
시작만 시키고 즉시 반환하고, 화면은 `dcc.Interval`(3초)로 실행 로그/락
상태를 다시 읽어와 갱신한다 — 탭을 닫았다 다시 열어도 마지막 상태 그대로
보인다. "전체 업데이트"는 업로드된 파일이 있는 항목만 자동으로 골라
실행하고(사용자 확정 — 실패 방지), "선택 업데이트"는 체크된 항목 중
업로드가 없는 게 있으면 전체를 막고 어느 항목인지 안내한다.

**결정 6 — DB 반영 버튼**: 사용자 제안(raw→processed CSV 변환 후 Postgres
반영도 웹에서 하고 싶다)에 따라 기존 `pipeline/load_to_db.py`(순수 CSV→
Postgres, DRM/xlwings 무관이라 리눅스 서버에서 바로 실행 가능)를 그대로
재사용하는 별도 버튼을 추가했다. 테이블 단위가 아니라 등록된 전체
테이블을 매번 통째로 재적재하는 기존 스크립트의 방식을 그대로 따른다
(멱등적이라 자주 눌러도 안전).

**결정 7(부수 버그 수정) — `process_work_objective.py`**: 이번 기능으로
업무목표24/25/26을 웹에서 "따로" 갱신할 수 있게 되면서, 기존 코드가
이번 실행에 없는 연도의 출력 컬럼을 무조건 빈 문자열로 채우던 버그가
실제로 발동하게 됐다(예: 24만 새로 올리면 write_merged가 researcher_id
하나로 행 전체를 교체해 기존 25/26 값까지 지워버림). 이번 실행에 없는
연도는 기존 work_objective.csv에서 값을 찾아 이어붙이도록 수정(있으면
보존, 처음부터 없었으면 그대로 빈 값).

**결정 8 — 권한/탭 배치**: 관리자(`can('manage_users')`)만 접근 가능한
기존 /admin 페이지 안에 "데이터 업데이트" 탭을 추가(사용자 확정 —
"사용자 관리, 팀/리더 참조와 동일하게").

**결정 9 — 업로드 용량 상한 50MB**(사용자 확정): `MAX_UPLOAD_BYTES`
환경변수로 조절 가능(기본 50MB). Flask `MAX_CONTENT_LENGTH`(app.py)도
기존 10MB 기본값에서 70MB로 올렸다 — dcc.Upload가 base64로 인코딩해
보내(원본 대비 약 1.37배 부풀림) 50MB 파일이 요청 크기로는 그보다 커짐.

**검증**:
- `services/web_pipeline_runner.py`를 합성 데이터로 직접 실행: 업로드 없음/
  필수 컬럼 누락/정상 성공 3가지 경로 모두 실행결과 메시지가 의도대로
  나오는 것 확인(process_patents.py 기준). 파일 락 이중 획득 방지 확인.
  job_profile 'dual' 모드에서 legacy 파일 없이 new 파일만 올려도
  merge_job_profile_source.py 전처리 + process_job_profile.py가 정상
  연계되는 것을 실제 실행으로 확인. `start_run()`으로 백그라운드 스레드
  실행 후 락 해제·실행결과 반영까지 end-to-end 확인.
- `process_work_objective.py` 버그 수정을 합성 데이터(기존 3개년 값이 있는
  연구원에게 24년만 재실행)로 검증 — 24년만 갱신되고 25/26은 보존됨을 확인.
- `pages/admin.py`를 `dash.Dash(use_pages=True)` 컨텍스트에서 실제로
  `layout()`(빈 상태)과 `_data_update_table()`(업로드/실행결과가 채워진
  상태 포함)을 렌더링해 컴포넌트 트리 구성 오류가 없음을 확인.
- 변경된 모든 파일 `py_compile` 통과.
- **미검증**: 실제 브라우저에서의 드래그앤드롭 업로드, 두 gunicorn 워커
  프로세스에 걸친 실제 동시 클릭 시나리오, 실제 Postgres에 대한
  `load_to_db.load()` 실행(DATABASE_URL 없는 샌드박스라 "미설정" 분기만
  확인), 50MB에 가까운 실제 대용량 파일 업로드.

## 2026-08-26 (36): "데이터 업데이트" 탭에 사내 API 연동 확장 포인트(항목별 아이콘) 선반영

배경: 지금은 파일 업로드로 갱신하지만, 궁극적으로는 20개 항목 모두 사내
API에서 직접 데이터를 받는 게 최종 목표(사용자 확정) — 그때 화면을 다시
만들지 않고, 지금 미리 아이콘을 심어 두면 연동 시 바로 반영되게 해달라는
요청.

**결정 — `services/web_pipeline_runner.py`에 `register_api_fetch(key, fn)`
확장 포인트 추가**: MANIFEST 각 항목에 `api_fetch`(콜러블, 기본 None) 필드를
두고, `run_one(key, via_api=True)`가 이 훅이 있으면 먼저 호출해 받은
(파일명, bytes, slot) 목록을 `save_upload()`로 저장한 뒤 — **그 다음부터는
파일 업로드 실행과 완전히 동일한 경로**(같은 process_*.py 호출, 같은 락/
로그/폴링)를 탄다. 훅이 없으면(현재 전 항목) 그 자리에서 "아직 사내 API
연동이 준비되지 않았습니다" 실패로 기록하고 끝난다 — 화면·버튼은 이미
동작하되 실제 데이터만 없는 상태. 실제 연동 시 각 소스별로
`register_api_fetch('researchers', fetch_fn)` 한 줄만 호출하면(신규 모듈,
예: `services/hr_api_client.py`) 화면 변경 없이 그 항목의 아이콘이 바로
동작한다.

**화면(`pages/admin.py`)**: 각 행의 "구분" 셀에 작은 "API로 가져오기"/
"API 연동 예정" 버튼을 추가(`{'type':'du-api','key':...}` 패턴 매칭 id,
`data_update_run_via_api` 콜백 → `wpr.start_run_via_api([key])`). 안내
알림에도 이 아이콘이 아직 비활성 상태임을 명시.

**검증**: `register_api_fetch()` 등록 전/후 `run_one(key, via_api=True)`를
합성 데이터로 직접 실행 — 등록 전엔 명확한 "미연동" 실패 메시지, 등록
후엔 실제 process_patents.py까지 정상 실행되는 것을 확인. `pages/admin.py`
레이아웃 렌더링(아이콘 포함) 재확인. 변경 파일 `py_compile` 통과.

## 2026-08-26 (37): team_refer 부서ID(dep_id) 중복 진단 — CLI 경고 + 웹 저장 시 별도 창

배경: team_refer.csv 누적 시 원본(엑셀 또는 웹 그리드)의 행 수보다 저장된
행 수가 적은 문제를 사용자가 발견 — 원인 중 하나가 같은 부서ID가 같은
업로드/저장 배치 안에 중복되면(자연키가 (dep_id, valid_year, valid_month,
valid_day)라 한 번의 저장은 전부 같은 날짜라 dep_id만 같아도 충돌)
merge_utils.upsert_merge()가 "새 데이터 안에서 키 중복 시 마지막 행만
채택"해 조용히 사라지는 것. 사용자 요청: (1) python으로 실행할 때
진단되게, (2) 웹 CRUD 저장 시에는 별도 창(모달)으로 보여주게.

**결정 — 진단 로직을 `pipeline/process_team_refer.py`에 공용 함수로**:
`find_duplicate_dep_ids(result)`(build_rows_from_records() 결과에서 dep_id
기준 중복 그룹 탐지, 조직코드/과제파트/부서/상위부서ID/사번/성명까지
같이 반환해 원본에서 바로 찾을 수 있게 함)와, CLI용 콘솔 출력 헬퍼
`_print_duplicate_warning()`을 추가. `process()`(CLI 실행,
`python pipeline/process_team_refer.py`)가 저장 직전에 이걸 호출해
`[WARN]` 블록으로 어느 dep_id가 몇 번 중복됐고 각 행이 무엇인지 출력한다
(저장 자체는 계속 진행 — 기존 동작 유지, 알림만 추가).

**웹 저장 경로**: `services/team_refer_store.save_snapshot()`도 같은
`find_duplicate_dep_ids()`를 호출해 반환값에 `duplicate_dep_ids`를
추가했고, `pages/admin.py`의 `team_refer_save` 콜백이 이걸로 새
`dbc.Modal`(`team-refer-dupe-modal`)을 자동으로 열어(사용자 요청 —
"별도창") 중복된 부서ID별로 행 목록을 표로 보여준다. 인라인
저장결과 알림에도 "N건 중복" 요약을 같이 남겨 모달을 닫아도 다시 열어볼
필요가 있다는 걸 놓치지 않게 했다.

**검증**: `find_duplicate_dep_ids()`를 합성 데이터(부서ID 중복 2행 + 부서ID
공란 1행)로 직접 실행 — 공란 행은 기존처럼 필터링되고, 중복 행만 정확히
잡히는 것 확인, `_print_duplicate_warning()` 콘솔 출력도 확인. `save_snapshot()`
반환값에 `duplicate_dep_ids`가 올바르게 채워지는 것, `pages/admin.py`의
`_dupe_modal_body()`와 전체 admin 레이아웃(모달 포함) 렌더링 모두 오류
없이 되는 것을 Dash 컨텍스트에서 직접 확인. 변경 파일 `py_compile` 통과.
**미검증**: 실제 브라우저에서 모달이 열리고 닫히는 클릭 동작.

## 2026-08-26 (38): 명단/팀참조 테이블 UX 5건 — 표시 매핑, 가운데정렬+말줄임+호버, 필터 대소문자, 컬럼 리사이즈, AI검색 오류 메시지

배경: 사용자가 화면을 실제로 써보면서 나온 5가지 요청을 한 번에 반영.

**1) 연구원 명단 부서/과제 표시값을 team_refer 매핑으로 변경**(사용자 확정
— 매핑 없으면 원본 값 유지, 라벨만 "과제"→"과제/파트"): 확인해보니 지금까지
명단 표의 '부서'/'과제' 셀은 필터 드롭다운만 team_refer 기준이었고 실제
표시값은 researchers.csv의 원본 department/org_code 그대로였다(특히
'과제' 열은 사람이 읽는 라벨이 아니라 raw org_code 코드값이었음). 새
`services/similarity_map.org_code_label_maps()`(team_refer 한 번 순회로
org_code→dep_name/pjt_part_name dict 2개를 만듦 — 기존
`dep_name_for_org_code()`는 1건씩 매번 전체 스캔이라 명단 전체에 그대로
쓰면 느림)를 `pages/researcher_list.py._build_summary_df()`에 적용했다.
**중요한 부수 수정**: 부서/과제 드롭다운 필터가 내부적으로 "표의 '과제'
컬럼 값=org_code"라는 전제로 `display_df['과제'].isin(org_codes)`로
매칭하고 있었는데, '과제' 컬럼이 이제 라벨을 담게 되면서 이 전제가
깨진다 — 화면에는 안 보이는 내부 컬럼 `_org_code`를 새로 추가해 필터
매칭은 계속 `_org_code` 기준으로 하도록 고쳤다(안 고쳤으면 매핑된 모든
행이 부서/과제 필터에서 안 걸리는 회귀 버그가 났을 것). 엑셀 다운로드도
동일 기준으로 나가야 해서(사용자 확정) `services/researcher_profile_export.py`의
`_col_dept_task()`(엑셀의 '부서\n(과제)' 셀)도 같은 매핑을 쓰도록 고쳤다
— `build_profile_workbook()`이 배치당 한 번만 `org_code_label_maps()`를
호출해 `_researcher_row_context()`로 실어 보낸다(연구원 수만큼 반복 스캔
방지). `similarity_map`이 이미 `researcher_profile_export`를 임포트하므로
순환 임포트를 피하려고 지연 임포트로 가져왔다. AI 검색 결과에 붙는
7개 기본 컬럼(`researcher_profile_export.PERSON_BASE_COLUMNS`, Job
Market에서도 재사용)과 프로필 화면은 이번 범위에 포함하지 않음(사용자
요청 범위가 "명단 표 + 그 엑셀 다운로드"였음).

**2) 팀/리더 참조 + 연구원 명단 테이블 — 가운데 정렬 + 말줄임 + 호버**
(사용자 확정 — 안 들어가면 스크롤 남는 것도 허용): `pages/admin.py`의
team-refer-table에 없던 `textAlign: center`/`overflow: hidden`/
`textOverflow: ellipsis`를 추가하고 폰트·여백을 줄였다. 이미 있는
컬럼 드래그 리사이즈(`.column-header-name`의 CSS `resize`) 트릭과
안 부딪히도록 `maxWidth`를 강제하지 않고 `overflow`/`textOverflow`만
추가해, 사용자가 드래그로 넓힌 폭 기준으로 자연스럽게 말줄임되게 했다.
말줄임된 셀은 마우스 오버로 전체 내용을 볼 수 있게 `tooltip_data`를
추가했는데, 이 테이블은 행 추가/삭제/정렬/편집 콜백이 여러 개라 각자
손보는 대신 `data`를 지켜보는 새 콜백(`team_refer_sync_tooltip`) 하나로
어디서 바뀌든 자동으로 최신 상태를 유지하게 했다. `pages/researcher_list.py`
쪽도 동일하게 `tooltip_data`를 추가(`_build_tooltip_data()`, `update_table`
콜백의 5개 반환 지점 전부)했고, 컬럼 리사이즈 CSS 트릭도 그대로 이식했다.

**3) 연구원 명단 필터 행 — 항상 대소문자 무시 + 아이콘 제거 + 시각적 구분**
(사용자 확정 — 모두 반영): dash_table의 `filter_action='native'` 필터 행에
기본으로 붙는 "Aa" 대소문자 토글 아이콘의 실제 DOM(`.dash-filter--case`,
기본 상태가 "sensitive")을 직접 확인 후, 테이블 레벨 `filter_options=
{'case': 'insensitive', 'placeholder_text': '🔍 검색...'}`로 기본값 자체를
바꾸고, 그 토글 아이콘은 `css=[{'selector': '.dash-filter--case', 'rule':
'display: none;'}]`로 숨겼다(숨겨도 무시 동작 자체는 그대로 유지).
`style_filter`에 진한 배경(#eaf2fb)과 위/아래 테두리를 추가해 검색 가능한
행이라는 게 눈에 띄게 했다.

**4) AI 검색 LLM 오류 메시지 정확화**: `LLM2_API_URL` 미설정 시
`services/nl_query.py`가 "지금 요청이 많아 응답을 만들지 못했습니다.
잠시 후 다시 시도해주세요"라는, 실제로는 영구적인(재시도해도 절대 안
풀리는) 문제를 마치 일시적인 것처럼 보여주는 오해의 소지가 있는 메시지를
띄우고 있었다(코드 버그는 아니고 실제 원인은 환경설정 — `.env`의
`LLM2_API_URL`/`LLM2_MODEL`을 사내 실제 LLM 엔드포인트로 채워야 함).
`pipeline/llm_client.py`에 `is_configured()`(LLM2_API_URL 설정 여부만
빠르게 확인, `call_llm()`의 재시도/HTTP오류 등 다른 실패 사유와는 구분)를
추가하고, `services/nl_query.py.answer_question()`(전체 파이프라인의
단일 진입점) 맨 앞에서 확인해 미설정이면 "AI 검색을 지금 사용할 수
없습니다(사내 LLM 서버 설정이 필요합니다) — 관리자에게 문의해주세요"를
즉시 보여주도록 했다. `call_llm()` 자체의 반환 계약(항상 문자열, 예외
없음)은 그대로 둬서 다른 10여 개 호출부(배치 스크립트 등)에 영향이
없게 했다 — `nl_query.py` 한 곳에서만 사전 체크하는 방식으로 최소
범위로 고쳤다.

**검증**: 5개 항목 모두 합성 데이터로 직접 실행 확인 — `org_code_label_maps()`
매핑/폴백(매핑 있음/없음 각각), `_org_code` 기반 필터 매칭 유지,
`_col_dept_task()` 엑셀 셀 값, `is_configured()` 참/거짓, `team_refer_sync_tooltip()`
콜백 로직. `pages/admin.py`/`pages/researcher_list.py` 둘 다 Dash 컨텍스트에서
`layout()` 전체 렌더링 재확인. 변경된 모든 파일 `py_compile` 통과.
**미검증**: 실제 브라우저에서 CSS 리사이즈/호버 툴팁/필터 아이콘 숨김이
의도대로 보이는지, 좁은 화면에서 실제로 좌우 스크롤이 없어지는지.
