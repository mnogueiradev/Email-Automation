-- TiDB migration: add the audit log for manual email job resolutions.
-- Apply only when alembic_version contains 20261013_0001.

CREATE TABLE email_job_events (
    id BIGINT NOT NULL AUTO_INCREMENT,
    job_id BIGINT NOT NULL,
    event_type VARCHAR(40) NOT NULL,
    previous_status VARCHAR(24) NOT NULL,
    new_status VARCHAR(24) NOT NULL,
    actor VARCHAR(80) NOT NULL DEFAULT 'local_api',
    duplicate_risk_acknowledged BOOL NOT NULL DEFAULT 0,
    note VARCHAR(500) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT pk_email_job_events PRIMARY KEY (id),
    CONSTRAINT fk_email_job_events_job_id_email_jobs
        FOREIGN KEY (job_id) REFERENCES email_jobs (id)
);

CREATE INDEX ix_email_job_events_job_created
    ON email_job_events (job_id, created_at);

UPDATE alembic_version
SET version_num = '20261017_0002'
WHERE version_num = '20261013_0001';
