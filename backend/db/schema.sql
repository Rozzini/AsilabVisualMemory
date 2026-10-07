PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS devices (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    last_seen   TEXT,
    stats       TEXT                -- last heartbeat stats (JSON)
);

-- One row per uploaded video (server-side processing pipeline)
CREATE TABLE IF NOT EXISTS jobs (
    id                  TEXT PRIMARY KEY,
    filename            TEXT NOT NULL,
    video_path          TEXT NOT NULL,
    status              TEXT NOT NULL,   -- queued | processing | analyzing | completed | failed
    progress            REAL NOT NULL DEFAULT 0,
    duration_s          REAL,
    observations_total  INTEGER NOT NULL DEFAULT 0,
    stats               TEXT,            -- detector counters (JSON)
    error               TEXT,
    created_at          TEXT NOT NULL,
    completed_at        TEXT
);

-- Raw evidence, from a device or from an uploaded video
CREATE TABLE IF NOT EXISTS observations (
    id              TEXT PRIMARY KEY,
    source          TEXT NOT NULL,       -- device | upload
    device_id       TEXT,
    job_id          TEXT,
    timestamp       TEXT NOT NULL,
    video_offset_s  REAL,
    type            TEXT NOT NULL,       -- baseline | visual_change
    frames          TEXT NOT NULL,       -- JSON list of file names in evidence/<id>/
    metadata        TEXT,                -- JSON from the producer (detector scores...)
    status          TEXT NOT NULL,       -- pending | processed | dismissed | failed
    attempts        INTEGER NOT NULL DEFAULT 0,
    result          TEXT,                -- raw vision result (JSON)
    error           TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_obs_status ON observations(status);
CREATE INDEX IF NOT EXISTS ix_obs_job ON observations(job_id);

-- Semantic interpretation of an observation
CREATE TABLE IF NOT EXISTS memories (
    id               TEXT PRIMARY KEY,
    observation_id   TEXT NOT NULL REFERENCES observations(id),
    source           TEXT NOT NULL,
    device_id        TEXT,
    job_id           TEXT,
    timestamp        TEXT NOT NULL,
    video_offset_s   REAL,
    event_type       TEXT NOT NULL,
    summary          TEXT NOT NULL,
    objects          TEXT NOT NULL,      -- JSON list of {name, action, location_before, location_after}
    location_before  TEXT,
    location_after   TEXT,
    confidence       REAL,
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_mem_device ON memories(device_id, timestamp);
CREATE INDEX IF NOT EXISTS ix_mem_job ON memories(job_id, video_offset_s);
CREATE INDEX IF NOT EXISTS ix_mem_ts ON memories(timestamp);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    memory_id UNINDEXED,
    summary,
    objects,
    locations,
    tokenize = 'porter unicode61'
);
