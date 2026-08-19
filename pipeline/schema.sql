-- 연구원 대시보드 PostgreSQL — 적재 후 인덱스/유니크 인덱스
--
-- 테이블 자체는 pipeline/load_to_db.py 의 to_sql(if_exists='replace') 가
-- 각 CSV의 실제 컬럼 구성에 맞춰 생성한다(전 컬럼 TEXT). 따라서 여기에는
-- CREATE TABLE 을 두지 않는다(사내 데이터 컬럼이 달라도 자동으로 맞춤).
--
-- 이 파일은 적재가 끝난 '뒤' 실행된다(replace 가 테이블을 drop 하므로).
-- 모든 문장은 IF NOT EXISTS 로 멱등. 대상 테이블/컬럼이 없으면 load_to_db 가
-- 해당 문장을 건너뛴다.

-- 코멘트 upsert 키: ON CONFLICT (researcher_id, year, commenter_type) 가
-- 이 유니크 인덱스를 사용한다.
CREATE UNIQUE INDEX IF NOT EXISTS comments_uniq
    ON comments (researcher_id, year, commenter_type);

-- researcher_id 조회 인덱스 (전 테이블 공통 컬럼)
CREATE INDEX IF NOT EXISTS idx_researchers_id   ON researchers (researcher_id);
CREATE INDEX IF NOT EXISTS idx_evaluations_id   ON evaluations (researcher_id);
CREATE INDEX IF NOT EXISTS idx_education_id      ON education (researcher_id);
CREATE INDEX IF NOT EXISTS idx_incentive_id      ON incentive_selection (researcher_id);
CREATE INDEX IF NOT EXISTS idx_leadership_id     ON leadership (researcher_id);
CREATE INDEX IF NOT EXISTS idx_transfers_id      ON transfers (researcher_id);
CREATE INDEX IF NOT EXISTS idx_tasks_id          ON tasks (researcher_id);
CREATE INDEX IF NOT EXISTS idx_nurturing_id      ON nurturing (researcher_id);
CREATE INDEX IF NOT EXISTS idx_awards_id         ON awards (researcher_id);
CREATE INDEX IF NOT EXISTS idx_comments_id       ON comments (researcher_id);
CREATE INDEX IF NOT EXISTS idx_publications_id   ON publications (researcher_id);
CREATE INDEX IF NOT EXISTS idx_patents_id        ON patents (researcher_id);
CREATE INDEX IF NOT EXISTS idx_techtransfer_id   ON technology_transfer (researcher_id);
CREATE INDEX IF NOT EXISTS idx_certifications_id ON certifications (researcher_id);
CREATE INDEX IF NOT EXISTS idx_succession_id     ON succession (researcher_id);

-- 전문성 관련 JSON 파생 테이블(pipeline/load_to_db.py의 JSON_TABLES) — 각각
-- 항목당 키가 유일해야 정상이라 유니크로 걸어, 원본 JSON에 중복 키가 있으면
-- (드문 데이터 문제) 여기서 걸러진다(실패해도 load_to_db가 경고만 남기고 계속).
CREATE UNIQUE INDEX IF NOT EXISTS uniq_expertise_profiles_id
    ON expertise_profiles (researcher_id);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_researcher_similarity_id
    ON researcher_similarity (researcher_id);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_project_expertise_analysis_name
    ON project_expertise_analysis (project_name);
