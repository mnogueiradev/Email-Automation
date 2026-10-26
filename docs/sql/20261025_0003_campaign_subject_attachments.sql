-- TiDB migration: add campaign subjects and binary attachments.
-- Apply after 20261017_0002 has been applied.
-- Run this with the TiDB deployment/DDL account, not the runtime account.

ALTER TABLE campaigns
    ADD COLUMN subject VARCHAR(998) NULL;

CREATE TABLE campaign_attachments (
    id BIGINT NOT NULL AUTO_INCREMENT,
    campaign_id BIGINT NOT NULL,
    filename VARCHAR(255) NOT NULL,
    content_type VARCHAR(255) NOT NULL,
    size_bytes INT NOT NULL,
    content LONGBLOB NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT pk_campaign_attachments PRIMARY KEY (id),
    CONSTRAINT fk_campaign_attachments_campaign_id_campaigns
        FOREIGN KEY (campaign_id) REFERENCES campaigns (id)
);

CREATE INDEX ix_campaign_attachments_campaign_id
    ON campaign_attachments (campaign_id);

UPDATE alembic_version
SET version_num = '20261025_0003'
WHERE version_num = '20261017_0002';
