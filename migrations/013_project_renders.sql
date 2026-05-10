-- Project render versions
-- Each final video render of a project gets a numbered version record,
-- same pattern as project_shot_versions.

CREATE TABLE IF NOT EXISTS project_renders (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    render_number INT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    final_video TEXT,
    error_message TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(project_id, render_number)
);

CREATE INDEX IF NOT EXISTS idx_project_renders_project ON project_renders(project_id, render_number DESC);
CREATE INDEX IF NOT EXISTS idx_project_renders_status ON project_renders(project_id, status) WHERE status = 'completed';
