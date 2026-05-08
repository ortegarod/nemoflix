CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT,
    synopsis TEXT,
    aspect_ratio TEXT NOT NULL DEFAULT '9:16',
    duration_seconds INT,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'planning', 'ready', 'rendering', 'completed', 'failed')),
    characters JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_projects_updated_at ON projects(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);

CREATE TABLE IF NOT EXISTS project_scenes (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    scene_number INT NOT NULL,
    title TEXT,
    setting TEXT NOT NULL DEFAULT 'interior',
    weather TEXT NOT NULL DEFAULT 'clear',
    summary TEXT,
    location TEXT,
    time_of_day TEXT,
    characters JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(project_id, scene_number)
);

CREATE INDEX IF NOT EXISTS idx_project_scenes_project ON project_scenes(project_id, scene_number);

CREATE TABLE IF NOT EXISTS project_shots (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    scene_id TEXT NOT NULL REFERENCES project_scenes(id) ON DELETE CASCADE,
    shot_number INT NOT NULL,
    text TEXT,
    voiceover TEXT,
    image_prompt TEXT,
    motion_prompt TEXT,
    camera_motion TEXT,
    characters JSONB NOT NULL DEFAULT '[]'::jsonb,
    duration_seconds INT NOT NULL DEFAULT 5,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'rendering_image', 'image_ready', 'animating', 'video_ready', 'failed')),
    image_file TEXT,
    video_file TEXT,
    image_prompt_id TEXT,
    video_prompt_id TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(scene_id, shot_number)
);

CREATE INDEX IF NOT EXISTS idx_project_shots_project ON project_shots(project_id);
CREATE INDEX IF NOT EXISTS idx_project_shots_scene ON project_shots(scene_id, shot_number);
CREATE INDEX IF NOT EXISTS idx_project_shots_status ON project_shots(status);
