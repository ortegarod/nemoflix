CREATE TABLE IF NOT EXISTS datasets (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    description  TEXT,
    image_count  INTEGER,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed any datasets already referenced in training_jobs
INSERT INTO datasets (id, name)
SELECT DISTINCT dataset, dataset
FROM training_jobs
WHERE dataset IS NOT NULL
ON CONFLICT DO NOTHING;
