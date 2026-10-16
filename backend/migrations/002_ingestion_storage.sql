-- Preserve v1 data while adding the ingestion/analytics storage boundaries.

ALTER TABLE request_logs RENAME TO request_events;

ALTER TABLE incidents RENAME TO health_incidents;

CREATE TABLE integration_config (
	tenant_id VARCHAR(64) NOT NULL,
	integration_id VARCHAR(64) NOT NULL,
	latency_target_ms INTEGER NOT NULL,
	max_gap_minutes INTEGER NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (tenant_id, integration_id),
	FOREIGN KEY(tenant_id, integration_id) REFERENCES integrations (tenant_id, id),
	CONSTRAINT ck_config_positive_targets CHECK (latency_target_ms > 0 AND max_gap_minutes > 0)
);

CREATE TABLE metric_rollups (
	id VARCHAR(36) NOT NULL,
	tenant_id VARCHAR(64) NOT NULL,
	integration_id VARCHAR(64) NOT NULL,
	window_start TIMESTAMP WITH TIME ZONE NOT NULL,
	window_end TIMESTAMP WITH TIME ZONE NOT NULL,
	calculated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	metrics JSON NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(tenant_id, integration_id) REFERENCES integrations (tenant_id, id),
	UNIQUE (tenant_id, integration_id, window_start, window_end),
	UNIQUE (tenant_id, integration_id, id),
	CONSTRAINT ck_rollup_window CHECK (window_end > window_start)
);

CREATE INDEX ix_rollups_window ON metric_rollups (tenant_id, integration_id, window_end);

INSERT INTO integration_config (tenant_id, integration_id, latency_target_ms, max_gap_minutes, updated_at)
SELECT tenant_id, id, latency_target_ms, max_gap_minutes, now() FROM integrations;

ALTER TABLE integrations DROP COLUMN latency_target_ms, DROP COLUMN max_gap_minutes;

ALTER TABLE request_events
ADD COLUMN received_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
ADD COLUMN integration_name VARCHAR(160),
ADD COLUMN integration_type VARCHAR(64),
ADD COLUMN error_code VARCHAR(128),
ADD COLUMN error_message VARCHAR(2000),
ADD COLUMN raw_event JSON NOT NULL DEFAULT '{}';

UPDATE request_events e SET integration_name=i.name, integration_type=i.category,
raw_event=json_build_object('tenant_id',e.tenant_id,'event_id',e.event_id,'integration_id',e.integration_id,
'occurred_at',e.occurred_at,'status_code',e.status_code,'latency_ms',e.latency_ms,
'timed_out',e.timed_out,'error_category',e.error_category,'legacy_backfill',true)
FROM integrations i WHERE e.tenant_id=i.tenant_id AND e.integration_id=i.id;

INSERT INTO metric_rollups (id, tenant_id, integration_id, window_start, window_end, calculated_at, metrics)
SELECT id, tenant_id, integration_id, bucket - INTERVAL '15 minutes', bucket, evaluated_at, evidence->'metrics'
FROM health_snapshots;

ALTER TABLE health_snapshots ADD COLUMN metric_rollup_id VARCHAR(36);

UPDATE health_snapshots SET metric_rollup_id=id;

ALTER TABLE health_snapshots ALTER COLUMN metric_rollup_id SET NOT NULL,
ADD CONSTRAINT fk_snapshot_rollup FOREIGN KEY (tenant_id,integration_id,metric_rollup_id)
REFERENCES metric_rollups (tenant_id,integration_id,id);

ALTER TABLE enrichments ADD COLUMN tenant_id VARCHAR(64), ADD COLUMN integration_id VARCHAR(64);

UPDATE enrichments e SET tenant_id=s.tenant_id, integration_id=s.integration_id
FROM health_snapshots s WHERE e.snapshot_id=s.id;

ALTER TABLE enrichments ALTER COLUMN tenant_id SET NOT NULL, ALTER COLUMN integration_id SET NOT NULL,
ADD CONSTRAINT fk_enrichment_tenant_snapshot FOREIGN KEY (tenant_id,integration_id,snapshot_id)
REFERENCES health_snapshots (tenant_id,integration_id,id);

ALTER TABLE integration_config ENABLE ROW LEVEL SECURITY;

ALTER TABLE metric_rollups ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON integration_config, metric_rollups FROM PUBLIC;
