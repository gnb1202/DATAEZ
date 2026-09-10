-- Runtime ensure_library() applies the same additive migration.
CREATE TABLE IF NOT EXISTS sample_workspace_restarts (
    user_id UUID NOT NULL,
    request_id UUID NOT NULL,
    previous_project_id UUID NOT NULL,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(user_id, request_id)
);
ALTER TABLE sample_workspace_restarts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON sample_workspace_restarts FROM PUBLIC;
