-- Also applied idempotently by ensure_dashboard_widgets_table on startup.
ALTER TABLE dashboard_widgets ADD COLUMN IF NOT EXISTS refresh_interval_seconds INTEGER NOT NULL DEFAULT 0
  CHECK (refresh_interval_seconds IN (0, 3600, 86400));
ALTER TABLE dashboard_widgets ADD COLUMN IF NOT EXISTS next_refresh_at TIMESTAMPTZ;
ALTER TABLE dashboard_widgets ADD COLUMN IF NOT EXISTS refresh_failures INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_widgets_due ON dashboard_widgets(next_refresh_at)
  WHERE next_refresh_at IS NOT NULL AND refresh_interval_seconds > 0;
