-- Telemetry schema for Daedal Studio (ds-mvp).
--
-- GENERATED from pythonsrc/telemetry/db.py: `python -m pythonsrc.telemetry.db --ddl`.
-- Do not edit by hand; tests/test_supabase_migration.py fails if this file and the
-- code disagree. Every statement is idempotent, and the server runs the same DDL
-- on startup, so applying this file is optional but keeps Supabase's migration
-- history truthful.

CREATE TABLE IF NOT EXISTS print_job (
    job_id TEXT PRIMARY KEY,
    prompt TEXT NOT NULL,
    printer_id TEXT NOT NULL,
    printer_firmware TEXT NOT NULL,
    slicer TEXT NOT NULL,
    profile_name TEXT NOT NULL,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    outcome TEXT NOT NULL,
    generation_model TEXT,
    generation_model_version TEXT,
    generation_backend TEXT,
    generation_params JSONB,
    generation_cost_eur DOUBLE PRECISION,
    generation_duration_s DOUBLE PRECISION,
    mesh_features JSONB,
    printability_score DOUBLE PRECISION,
    printability_verdict TEXT,
    printability_report JSONB,
    blueprint_model TEXT,
    blueprint_model_version TEXT,
    blueprint_seed BIGINT,
    blueprint_prompt_engineered TEXT,
    blueprint_params JSONB,
    blueprint_sha256 TEXT,
    blueprint_duration_s DOUBLE PRECISION,
    raw_mesh_sha256 TEXT,
    raw_mesh_features JSONB,
    repaired_mesh_sha256 TEXT,
    repaired_mesh_features JSONB,
    slice_status TEXT,
    slice_error TEXT,
    slice_duration_s DOUBLE PRECISION,
    estimated_print_time_s BIGINT,
    filament_used_mm DOUBLE PRECISION,
    filament_used_mm3 DOUBLE PRECISION,
    filament_used_g DOUBLE PRECISION,
    support_filament_mm3 DOUBLE PRECISION,
    layer_count INTEGER,
    slice_stats JSONB,
    material_type TEXT,
    material_brand TEXT,
    material_colour TEXT,
    nozzle_diameter_mm DOUBLE PRECISION,
    process_params JSONB,
    request_params JSONB,
    requested_size_mm DOUBLE PRECISION,
    size_source TEXT,
    requested_scale_axis TEXT,
    parent_job_id TEXT,
    regeneration_reason TEXT,
    download_count INTEGER DEFAULT 0,
    outcome_source TEXT,
    outcome_reported_at TIMESTAMPTZ,
    git_sha TEXT,
    used_reference_assets INTEGER,
    dispatched_printer_url TEXT,
    repair_report JSONB,
    print_duration_s DOUBLE PRECISION,
    fit_photo_path TEXT
);

CREATE INDEX IF NOT EXISTS idx_print_job_started_at ON print_job (started_at DESC);

CREATE INDEX IF NOT EXISTS idx_print_job_outcome ON print_job (outcome);

CREATE TABLE IF NOT EXISTS telemetry_sample (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id TEXT NOT NULL,
    sampled_at TIMESTAMPTZ NOT NULL,
    gcode_line BIGINT,
    z_height_mm DOUBLE PRECISION,
    hotend_actual_c DOUBLE PRECISION,
    hotend_target_c DOUBLE PRECISION,
    bed_actual_c DOUBLE PRECISION,
    bed_target_c DOUBLE PRECISION,
    print_speed_pct DOUBLE PRECISION,
    extrusion_factor_pct DOUBLE PRECISION,
    fan_speed_pct DOUBLE PRECISION,
    CONSTRAINT telemetry_sample_job_id_fkey FOREIGN KEY (job_id) REFERENCES print_job (job_id)
);

CREATE INDEX IF NOT EXISTS idx_telemetry_sample_job_time ON telemetry_sample (job_id, sampled_at);

CREATE TABLE IF NOT EXISTS failure_event (
    event_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL,
    gcode_line BIGINT,
    z_height_mm DOUBLE PRECISION,
    failure_type TEXT NOT NULL,
    source TEXT NOT NULL,
    notes TEXT,
    snapshot JSONB NOT NULL,
    CONSTRAINT failure_event_job_id_fkey FOREIGN KEY (job_id) REFERENCES print_job (job_id)
);

CREATE INDEX IF NOT EXISTS idx_failure_event_job ON failure_event (job_id);

CREATE TABLE IF NOT EXISTS telemetry_collector_claim (
    job_id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    claimed_at TIMESTAMPTZ NOT NULL,
    heartbeat_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT telemetry_collector_claim_job_id_fkey FOREIGN KEY (job_id) REFERENCES print_job (job_id)
);

CREATE TABLE IF NOT EXISTS job_event (
    event_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    kind TEXT NOT NULL,
    detail JSONB,
    CONSTRAINT job_event_job_id_fkey FOREIGN KEY (job_id) REFERENCES print_job (job_id)
);

CREATE INDEX IF NOT EXISTS idx_job_event_job_kind ON job_event (job_id, kind);

CREATE TABLE IF NOT EXISTS app_config (
    key TEXT PRIMARY KEY,
    value_encrypted BYTEA,
    updated_at TIMESTAMPTZ
);

ALTER TABLE print_job ENABLE ROW LEVEL SECURITY;

ALTER TABLE telemetry_sample ENABLE ROW LEVEL SECURITY;

ALTER TABLE failure_event ENABLE ROW LEVEL SECURITY;

ALTER TABLE telemetry_collector_claim ENABLE ROW LEVEL SECURITY;

ALTER TABLE job_event ENABLE ROW LEVEL SECURITY;

ALTER TABLE app_config ENABLE ROW LEVEL SECURITY;
