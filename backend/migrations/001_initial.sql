-- Initial PostgreSQL schema. Immutable after application.

CREATE TABLE tenants (
	id VARCHAR(64) NOT NULL,
	name VARCHAR(160) NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE access_tokens (
	digest VARCHAR(64) NOT NULL,
	tenant_id VARCHAR(64) NOT NULL,
	role VARCHAR(20) NOT NULL,
	PRIMARY KEY (digest),
	CONSTRAINT ck_token_role CHECK (role IN ('reader', 'operator')),
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE TABLE integrations (
	tenant_id VARCHAR(64) NOT NULL,
	id VARCHAR(64) NOT NULL,
	name VARCHAR(160) NOT NULL,
	category VARCHAR(64) NOT NULL,
	owner VARCHAR(160) NOT NULL,
	latency_target_ms INTEGER NOT NULL,
	max_gap_minutes INTEGER NOT NULL,
	PRIMARY KEY (tenant_id, id),
	CONSTRAINT ck_positive_targets CHECK (latency_target_ms > 0 AND max_gap_minutes > 0),
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);

CREATE TABLE health_snapshots (
	id VARCHAR(36) NOT NULL,
	tenant_id VARCHAR(64) NOT NULL,
	integration_id VARCHAR(64) NOT NULL,
	bucket TIMESTAMP WITH TIME ZONE NOT NULL,
	evaluated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	status VARCHAR(20) NOT NULL,
	score INTEGER,
	evidence JSON NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(tenant_id, integration_id) REFERENCES integrations (tenant_id, id),
	UNIQUE (tenant_id, integration_id, bucket),
	UNIQUE (tenant_id, integration_id, id),
	CONSTRAINT ck_health_status CHECK (status IN ('healthy', 'degraded', 'unhealthy', 'unknown'))
);

CREATE TABLE request_logs (
	tenant_id VARCHAR(64) NOT NULL,
	event_id VARCHAR(128) NOT NULL,
	integration_id VARCHAR(64) NOT NULL,
	occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
	status_code INTEGER NOT NULL,
	latency_ms FLOAT NOT NULL,
	timed_out BOOLEAN NOT NULL,
	error_category VARCHAR(32) NOT NULL,
	PRIMARY KEY (tenant_id, event_id),
	FOREIGN KEY(tenant_id, integration_id) REFERENCES integrations (tenant_id, id),
	CONSTRAINT ck_log_values CHECK (status_code >= 100 AND status_code <= 599 AND latency_ms >= 0)
);

CREATE TABLE enrichments (
	id VARCHAR(36) NOT NULL,
	snapshot_id VARCHAR(36) NOT NULL,
	generated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	source VARCHAR(32) NOT NULL,
	explanation VARCHAR(2400) NOT NULL,
	evidence_digest VARCHAR(64) NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (snapshot_id),
	FOREIGN KEY(snapshot_id) REFERENCES health_snapshots (id)
);

CREATE TABLE incidents (
	id VARCHAR(36) NOT NULL,
	tenant_id VARCHAR(64) NOT NULL,
	integration_id VARCHAR(64) NOT NULL,
	opening_snapshot_id VARCHAR(36) NOT NULL,
	last_snapshot_id VARCHAR(36) NOT NULL,
	opened_at TIMESTAMP WITH TIME ZONE NOT NULL,
	resolved_at TIMESTAMP WITH TIME ZONE,
	recovery_streak INTEGER NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(tenant_id, integration_id) REFERENCES integrations (tenant_id, id),
	FOREIGN KEY(tenant_id, integration_id, opening_snapshot_id) REFERENCES health_snapshots (tenant_id, integration_id, id),
	FOREIGN KEY(tenant_id, integration_id, last_snapshot_id) REFERENCES health_snapshots (tenant_id, integration_id, id),
	FOREIGN KEY(opening_snapshot_id) REFERENCES health_snapshots (id),
	FOREIGN KEY(last_snapshot_id) REFERENCES health_snapshots (id)
);

CREATE INDEX ix_access_tokens_tenant_id ON access_tokens (tenant_id);

CREATE INDEX ix_snapshots_history ON health_snapshots (tenant_id, integration_id, bucket);

CREATE INDEX ix_logs_window ON request_logs (tenant_id, integration_id, occurred_at);

CREATE UNIQUE INDEX ix_one_open_incident ON incidents (tenant_id, integration_id) WHERE resolved_at IS NULL;

ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE tenants FROM PUBLIC;

ALTER TABLE access_tokens ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE access_tokens FROM PUBLIC;

ALTER TABLE integrations ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE integrations FROM PUBLIC;

ALTER TABLE health_snapshots ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE health_snapshots FROM PUBLIC;

ALTER TABLE request_logs ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE request_logs FROM PUBLIC;

ALTER TABLE enrichments ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE enrichments FROM PUBLIC;

ALTER TABLE incidents ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE incidents FROM PUBLIC;
