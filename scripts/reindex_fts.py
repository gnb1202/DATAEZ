"""Rebuild content_tsv for existing rows after migration 002.

Migration 002 replaces the generated content_tsv column with an ordinary one
the application populates, so rows written before it have an empty tsvector and
are invisible to the sparse half of the hybrid search until re-analysed.

Only the tsvector is rebuilt — embeddings are untouched, so this costs no API
calls and can be re-run safely.

    cd api && python ../scripts/reindex_fts.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

from app.db import _connect  # noqa: E402
from app.korean_text import to_tsvector_input  # noqa: E402

BATCH = 500


def reindex_table(table: str) -> int:
    total = 0
    with _connect() as conn:
        while True:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, content FROM {table}
                    WHERE content_tsv IS NULL
                    LIMIT %s
                    """,
                    (BATCH,),
                )
                rows = cur.fetchall()
                if not rows:
                    break
                for row in rows:
                    cur.execute(
                        f"UPDATE {table} SET content_tsv = to_tsvector('simple', %s) WHERE id = %s",
                        (to_tsvector_input(row["content"]), row["id"]),
                    )
            conn.commit()
            total += len(rows)
            print(f"  {table}: {total} rows reindexed", flush=True)
    return total


def main() -> int:
    grand_total = 0
    # Table names are literals, not user input — no identifier injection path.
    for table in ("schema_embeddings", "document_chunks"):
        print(f"Reindexing {table} ...")
        grand_total += reindex_table(table)
    print(f"Done. {grand_total} rows reindexed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
