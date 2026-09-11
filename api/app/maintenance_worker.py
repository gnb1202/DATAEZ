"""Disposable task process. The API kills and waits for it at the hard deadline.

No credentials, provider errors, document contents or SQL are written to stdout.
Committed jobs survive; interrupted transactions roll back and index leases expire.
"""
import json
import logging
import sys
import time


def execute(kind):
    from .config import settings
    from .storage import StorageService
    started = time.monotonic()
    processed = 0
    if kind == 'index':
        from .index_jobs import process_one
        for _ in range(3):
            if time.monotonic() - started >= 60 or not process_one():
                break
            processed += 1
    elif kind == 'metrics':
        from .metric_scheduler import refresh_one_due
        for _ in range(10):
            if time.monotonic() - started >= 60 or not refresh_one_due():
                break
            processed += 1
    elif kind == 'cleanup':
        from .ledger_imports import expire_pending_batches
        from .direct_uploads import cleanup_expired_uploads
        # Originals already attached to files are preserved by each janitor.
        processed += expire_pending_batches(StorageService(), limit=2)
        if settings.storage_backend == 'supabase' and time.monotonic() - started < 60:
            processed += cleanup_expired_uploads(limit=2)
    else:
        raise ValueError('Unknown maintenance task')
    return {'processed': processed}


def main():
    logging.disable(logging.CRITICAL)
    try:
        result = execute(sys.argv[1])
        print(json.dumps(result))
    except Exception:
        print('{"error":"maintenance_failed"}')
        return 1
    finally:
        from .db import close_pool
        close_pool()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
