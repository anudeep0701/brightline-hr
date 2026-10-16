-- Additive: retain existing explanations and their original evidence digests.
ALTER TABLE enrichments ADD COLUMN report jsonb;
ALTER TABLE enrichments ADD COLUMN evidence_payload jsonb;
ALTER TABLE enrichments ADD COLUMN prompt_version varchar(64) NOT NULL DEFAULT 'legacy-v1';
ALTER TABLE enrichments ADD COLUMN fallback_code varchar(32);
-- Legacy records are regenerated on the next operator explanation request.
