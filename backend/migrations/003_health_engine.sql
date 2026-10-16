-- v2 deterministic health policy, evidence sufficiency and state hysteresis.

ALTER TABLE integration_config ADD COLUMN evaluation_window_minutes INTEGER NOT NULL DEFAULT 15;

ALTER TABLE integration_config ADD COLUMN refresh_minutes INTEGER NOT NULL DEFAULT 5;

ALTER TABLE integration_config ADD COLUMN min_requests INTEGER NOT NULL DEFAULT 20;

ALTER TABLE integration_config ADD COLUMN error_warning FLOAT NOT NULL DEFAULT 0.01;

ALTER TABLE integration_config ADD COLUMN error_critical FLOAT NOT NULL DEFAULT 0.05;

ALTER TABLE integration_config ADD COLUMN error_recovery FLOAT NOT NULL DEFAULT 0.005;

ALTER TABLE integration_config ADD COLUMN timeout_warning FLOAT NOT NULL DEFAULT 0.01;

ALTER TABLE integration_config ADD COLUMN timeout_critical FLOAT NOT NULL DEFAULT 0.05;

ALTER TABLE integration_config ADD COLUMN timeout_recovery FLOAT NOT NULL DEFAULT 0.005;

ALTER TABLE integration_config ADD COLUMN latency_warning_multiplier FLOAT NOT NULL DEFAULT 1.5;

ALTER TABLE integration_config ADD COLUMN latency_critical_multiplier FLOAT NOT NULL DEFAULT 3.0;

ALTER TABLE integration_config ADD COLUMN latency_recovery_multiplier FLOAT NOT NULL DEFAULT 1.25;

ALTER TABLE integration_config ADD COLUMN baseline_enabled BOOLEAN NOT NULL DEFAULT true;

ALTER TABLE integration_config ADD COLUMN baseline_lookback_minutes INTEGER NOT NULL DEFAULT 1440;

ALTER TABLE integration_config ADD COLUMN baseline_min_requests INTEGER NOT NULL DEFAULT 100;

ALTER TABLE integration_config ADD COLUMN baseline_min_delta_ms FLOAT NOT NULL DEFAULT 100.0;

ALTER TABLE integration_config ADD COLUMN unhealthy_bad_windows INTEGER NOT NULL DEFAULT 2;

ALTER TABLE integration_config ADD COLUMN healthy_recovery_windows INTEGER NOT NULL DEFAULT 2;

ALTER TABLE integration_config ADD COLUMN sustained_degraded_windows INTEGER NOT NULL DEFAULT 3;

ALTER TABLE integration_config ADD COLUMN top_error_limit INTEGER NOT NULL DEFAULT 5;

ALTER TABLE integration_config ADD CONSTRAINT ck_config_error_rates CHECK (0 <= error_recovery AND error_recovery < error_warning AND error_warning < error_critical AND error_critical <= 1);

ALTER TABLE integration_config ADD CONSTRAINT ck_config_evidence CHECK (min_requests >= 1 AND baseline_min_requests >= 1 AND baseline_lookback_minutes BETWEEN 5 AND 1440 AND baseline_min_delta_ms >= 0 AND top_error_limit BETWEEN 1 AND 20);

ALTER TABLE integration_config ADD CONSTRAINT ck_config_hysteresis CHECK (unhealthy_bad_windows BETWEEN 2 AND 20 AND healthy_recovery_windows BETWEEN 2 AND 20 AND sustained_degraded_windows BETWEEN unhealthy_bad_windows AND 100);

ALTER TABLE integration_config ADD CONSTRAINT ck_config_latency CHECK (1 <= latency_recovery_multiplier AND latency_recovery_multiplier < latency_warning_multiplier AND latency_warning_multiplier < latency_critical_multiplier);

ALTER TABLE integration_config ADD CONSTRAINT ck_config_timeout_rates CHECK (0 <= timeout_recovery AND timeout_recovery < timeout_warning AND timeout_warning < timeout_critical AND timeout_critical <= 1);

ALTER TABLE integration_config ADD CONSTRAINT ck_config_windows CHECK (evaluation_window_minutes >= refresh_minutes AND evaluation_window_minutes BETWEEN 5 AND 1440 AND refresh_minutes IN (5,10,15));

ALTER TABLE health_snapshots DROP CONSTRAINT ck_health_status;

UPDATE health_snapshots SET status=upper(status);

ALTER TABLE health_snapshots
ADD CONSTRAINT ck_health_status CHECK (status IN ('HEALTHY','DEGRADED','UNHEALTHY','UNKNOWN')),
ADD COLUMN observed_status VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN',
ADD COLUMN evidence_sufficient BOOLEAN NOT NULL DEFAULT false,
ADD COLUMN confidence FLOAT NOT NULL DEFAULT 0,
ADD COLUMN reason_code VARCHAR(64) NOT NULL DEFAULT 'LEGACY_SNAPSHOT',
ADD COLUMN reason_text VARCHAR(2400) NOT NULL DEFAULT 'Historical decision recorded before v2; see original evidence.',
ADD COLUMN bad_window_streak INTEGER NOT NULL DEFAULT 0,
ADD COLUMN degraded_window_streak INTEGER NOT NULL DEFAULT 0,
ADD COLUMN healthy_window_streak INTEGER NOT NULL DEFAULT 0;

UPDATE health_snapshots SET observed_status=status;

ALTER TABLE health_snapshots ADD CONSTRAINT ck_health_evidence CHECK (confidence >= 0 AND confidence <= 1 AND bad_window_streak >= 0 AND degraded_window_streak >= 0 AND healthy_window_streak >= 0);

ALTER TABLE health_snapshots ADD CONSTRAINT ck_health_observed_status CHECK (observed_status IN ('HEALTHY','DEGRADED','UNHEALTHY','UNKNOWN'));
