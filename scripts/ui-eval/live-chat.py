"""Persist a real read-tool result for browser rendering; no model is called."""
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import psycopg
from psycopg.conninfo import conninfo_to_dict

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))


def main():
    db_url = os.environ["DATABASE_URL"]
    config = conninfo_to_dict(db_url)
    assert config.get("host") in {"127.0.0.1", "localhost", "::1"} and not config.get("hostaddr")
    assert config["dbname"].startswith("dataez_live_") and len(config["dbname"]) == 44
    checkpoint = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    from app.agent_tools import ToolExecutor
    from app.db import close_pool
    with psycopg.connect(db_url) as conn:
        user = conn.execute("SELECT user_id FROM dashboard_widgets WHERE id=%s AND project_id=%s", (checkpoint["metricId"], checkpoint["projectId"])).fetchone()[0]
        try:
            executor = ToolExecutor(str(user), checkpoint["projectId"])
            args = {"batch_id": checkpoint["overlapId"]}
            result = executor.execute("inspect_import_review", json.dumps(args))
            assert "error" not in result and not executor.mutations_performed
            conversation_id = str(uuid4())
            conn.execute("INSERT INTO conversations(id,user_id,project_id,title) VALUES (%s,%s,%s,%s)",
                         (conversation_id, user, checkpoint["projectId"], "합성 도구 결과 · 모델 미호출"))
            steps = [{"type": "tool_result", "tool_name": "inspect_import_review", "tool_input": args, "tool_output": result}]
            conn.execute("INSERT INTO messages(id,conversation_id,role,content,steps) VALUES (%s,%s,'assistant',%s,%s::jsonb)",
                         (str(uuid4()), conversation_id, "실제 조회 도구의 검토 화면 연결을 확인하는 고정 메시지입니다. 모델 답변 평가는 아닙니다.", json.dumps(steps, default=str, ensure_ascii=False)))
        finally:
            close_pool()


if __name__ == "__main__":
    main()
