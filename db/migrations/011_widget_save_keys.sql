-- Idempotent saves from analysis results. Schema mirror: app/widget_saves.py.
ALTER TABLE dashboard_widgets ADD COLUMN IF NOT EXISTS save_key TEXT;
ALTER TABLE dashboard_widgets ADD COLUMN IF NOT EXISTS save_fingerprint CHAR(64);
CREATE UNIQUE INDEX IF NOT EXISTS uq_widget_save_key ON dashboard_widgets(user_id,project_id,save_key)
    WHERE save_key IS NOT NULL;
