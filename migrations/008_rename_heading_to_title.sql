DO $$ BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='project_scenes' AND column_name='heading'
  ) THEN
    ALTER TABLE project_scenes RENAME COLUMN heading TO title;
  END IF;
END $$;
