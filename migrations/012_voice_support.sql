-- Add voice support for TTS

-- Add voice JSONB to characters table
ALTER TABLE characters ADD COLUMN IF NOT EXISTS voice JSONB;

-- Add speaker to project_shots
ALTER TABLE project_shots ADD COLUMN IF NOT EXISTS speaker TEXT;

-- Add narrator_voice to projects
ALTER TABLE projects ADD COLUMN IF NOT EXISTS narrator_voice JSONB;
