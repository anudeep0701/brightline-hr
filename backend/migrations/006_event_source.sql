-- Additive provenance; do not infer the origin of existing request events.
ALTER TABLE request_events ADD COLUMN source_type varchar(16) NOT NULL DEFAULT 'UNKNOWN';
ALTER TABLE request_events ADD CONSTRAINT ck_event_source_type
    CHECK (source_type IN ('LIVE_API','FILE_IMPORT','DEMO','UNKNOWN'));
