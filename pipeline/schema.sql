-- 연구원 대시보드 PostgreSQL 스키마
-- 모든 컬럼 TEXT (현재 CSV가 dtype=str로 읽히는 동작과 일치, 8자리 zero-pad 보존)
-- 적재: pipeline/load_to_db.py 가 이 DDL 실행 후 TRUNCATE + append 한다.

CREATE TABLE IF NOT EXISTS researchers (
    researcher_id TEXT,
    name          TEXT,
    gender        TEXT,
    department    TEXT,
    org_code      TEXT,
    position      TEXT,
    hire_year     TEXT,
    birth_year    TEXT,
    photo_path    TEXT
);

CREATE TABLE IF NOT EXISTS evaluations (
    researcher_id TEXT,
    year          TEXT,
    grade         TEXT,
    score         TEXT
);

CREATE TABLE IF NOT EXISTS education (
    researcher_id   TEXT,
    degree          TEXT,
    major           TEXT,
    school          TEXT,
    graduation_year TEXT
);

CREATE TABLE IF NOT EXISTS incentive_selection (
    researcher_id TEXT,
    year          TEXT,
    selected      TEXT,
    category      TEXT,
    note          TEXT
);

CREATE TABLE IF NOT EXISTS leadership (
    researcher_id TEXT,
    year          TEXT,
    overall_score TEXT,
    vision        TEXT,
    communication TEXT,
    execution     TEXT,
    collaboration TEXT,
    development   TEXT
);

CREATE TABLE IF NOT EXISTS transfers (
    researcher_id TEXT,
    date          TEXT,
    type          TEXT,
    description   TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    researcher_id TEXT,
    task_name     TEXT,
    start_date    TEXT,
    end_date      TEXT,
    input_rate    TEXT
);

CREATE TABLE IF NOT EXISTS nurturing (
    researcher_id    TEXT,
    category         TEXT,
    subcategory      TEXT,
    start_date       TEXT,
    end_date         TEXT,
    country          TEXT,
    city             TEXT,
    institution      TEXT,
    major            TEXT,
    service_end_date TEXT,
    year             TEXT
);

CREATE TABLE IF NOT EXISTS awards (
    researcher_id TEXT,
    award_date    TEXT,
    award_type    TEXT,
    award_name    TEXT,
    awarding_org  TEXT,
    description   TEXT
);

CREATE TABLE IF NOT EXISTS comments (
    researcher_id   TEXT,
    year            TEXT,
    commenter_type  TEXT,
    comment_raw     TEXT,
    comment_summary TEXT,
    strengths       TEXT,
    improvements    TEXT,
    CONSTRAINT comments_uniq UNIQUE (researcher_id, year, commenter_type)
);

CREATE TABLE IF NOT EXISTS publications (
    researcher_id   TEXT,
    author_type     TEXT,
    is_corresponding TEXT,
    title           TEXT,
    journal         TEXT,
    pub_type        TEXT,
    pub_date        TEXT,
    pub_year        TEXT,
    author_rank     TEXT,
    total_authors   TEXT,
    author_info     TEXT,
    contribution    TEXT
);

CREATE TABLE IF NOT EXISTS patents (
    researcher_id     TEXT,
    application_id    TEXT,
    title             TEXT,
    title_ko          TEXT,
    status            TEXT,
    share_ratio       TEXT,
    is_lead_inventor  TEXT,
    patent_grade      TEXT,
    patent_grade_a_sub TEXT,
    application_no    TEXT,
    application_date  TEXT,
    registration_no   TEXT,
    registration_date TEXT,
    country           TEXT
);

CREATE TABLE IF NOT EXISTS technology_transfer (
    researcher_id TEXT,
    transfer_date TEXT,
    tech_name     TEXT,
    recipient     TEXT,
    amount        TEXT,
    transfer_type TEXT
);

CREATE TABLE IF NOT EXISTS certifications (
    researcher_id TEXT,
    cert_type     TEXT,
    cert_name     TEXT,
    score         TEXT,
    grade         TEXT,
    date_obtained TEXT
);

CREATE TABLE IF NOT EXISTS succession (
    researcher_id  TEXT,
    org_code       TEXT,
    department     TEXT,
    rank_type      TEXT,
    rank_order     TEXT,
    nominated_year TEXT
);

-- researcher_id 인덱스 (조회 성능)
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
