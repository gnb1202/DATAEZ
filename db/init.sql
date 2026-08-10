CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY,
  email VARCHAR(255) UNIQUE NOT NULL,
  name VARCHAR(255),
  password_hash TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS files (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  filename TEXT NOT NULL,
  storage_key TEXT,
  size_bytes BIGINT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS query_history (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  file_id UUID REFERENCES files(id),
  question TEXT NOT NULL,
  response_summary TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  token_hash TEXT UNIQUE NOT NULL,
  expires_at TIMESTAMP NOT NULL,
  revoked_at TIMESTAMP NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS conversations (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  file_id UUID REFERENCES files(id),
  title TEXT NOT NULL DEFAULT 'New conversation',
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
  id UUID PRIMARY KEY,
  conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  steps JSONB,
  charts JSONB,
  table_data JSONB,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dashboard_widgets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id),
  file_id UUID REFERENCES files(id),
  widget_type TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  widget_data JSONB NOT NULL,
  layout JSONB NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- =========================================================
-- Projects & Table Meta (코어 기능 재정의)
-- =========================================================

CREATE TABLE IF NOT EXISTS projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id),
  name VARCHAR(255) NOT NULL,
  description TEXT DEFAULT '',
  deleted_at TIMESTAMP NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_projects_user_id ON projects(user_id);

CREATE TABLE IF NOT EXISTS table_meta (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id),
  name VARCHAR(255) NOT NULL,
  description TEXT DEFAULT '',
  columns_schema JSONB NOT NULL DEFAULT '[]',
  row_count INTEGER NOT NULL DEFAULT 0,
  source_file_id UUID REFERENCES files(id),
  deleted_at TIMESTAMP NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_table_meta_project ON table_meta(project_id);
CREATE INDEX IF NOT EXISTS idx_table_meta_user ON table_meta(user_id);

-- =========================================================
-- Performance indexes for common query patterns
-- =========================================================
CREATE INDEX IF NOT EXISTS idx_files_user_created ON files(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversations_user_updated ON conversations(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_conv_created ON messages(conversation_id, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expires ON refresh_tokens(expires_at);
CREATE INDEX IF NOT EXISTS idx_query_history_user_created ON query_history(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_projects_user_updated ON projects(user_id, updated_at DESC);

-- =========================================================
-- Table & Column Comments (for documentation / tooling)
-- =========================================================
COMMENT ON TABLE users IS 'Registered user accounts';
COMMENT ON TABLE files IS 'Uploaded file metadata (CSV/XLSX). Actual data in S3 or local storage';
COMMENT ON TABLE query_history IS 'Legacy query log — retained for audit purposes';
COMMENT ON TABLE refresh_tokens IS 'JWT refresh token hashes for token rotation';
COMMENT ON TABLE conversations IS 'AI chat conversations, scoped to a project';
COMMENT ON TABLE messages IS 'Individual messages within a conversation (user + assistant)';
COMMENT ON TABLE dashboard_widgets IS 'Pinned charts and KPIs on the dashboard';
COMMENT ON TABLE projects IS 'Top-level workspace — groups tables and conversations';
COMMENT ON TABLE table_meta IS 'Metadata for user data tables (schema, row count, source file)';

COMMENT ON COLUMN messages.steps IS 'JSON array of agent reasoning steps (tool calls, outputs)';
COMMENT ON COLUMN messages.charts IS 'JSON array of generated chart configs';
COMMENT ON COLUMN messages.table_data IS 'JSON array of query result rows';
COMMENT ON COLUMN table_meta.columns_schema IS 'JSON array of {name, type, nullable} column definitions';
COMMENT ON COLUMN dashboard_widgets.widget_data IS 'JSON blob with chart config or KPI data';
COMMENT ON COLUMN dashboard_widgets.layout IS 'JSON object with grid position {x, y, w, h}';

-- =========================================================
-- Audit Log (변경 이력 추적)
-- =========================================================
CREATE TABLE IF NOT EXISTS audit_log (
  id BIGSERIAL PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  action TEXT NOT NULL,
  resource_type TEXT NOT NULL,
  resource_id TEXT,
  detail JSONB,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_resource ON audit_log(resource_type, resource_id);
COMMENT ON TABLE audit_log IS 'Tracks who changed what and when — for compliance and undo support';
