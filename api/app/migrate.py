"""Explicit schema initialization: python -m app.migrate [--bootstrap-sql PATH].

Use a dedicated DATA:EZ database and a direct/session migration connection.
This command is never run by the Vercel build or function startup.
"""
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-sql", type=Path,
                        help="Existing db/init.sql, required only for a new empty database")
    args = parser.parse_args()
    from .db import _connect, close_pool
    from .main import initialize_database
    try:
        if args.bootstrap_sql:
            bootstrap = args.bootstrap_sql.read_text(encoding="utf-8-sig")
            with _connect() as conn:
                conn.execute(bootstrap, prepare=False)
        initialize_database()
        print("DATA:EZ database initialization completed")
    finally:
        close_pool()


if __name__ == "__main__":
    main()
