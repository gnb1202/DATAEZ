"""Offline Linux probe; no DB, cloud credentials, lifespan or LLM requests.

Run inside the API dependency image with the current api directory at /candidate.
This measures installed files, not a Vercel-built deployment bundle.
"""
import hashlib
import importlib.metadata as metadata
import io
import json
import os
from pathlib import Path
import platform
import resource
import secrets
import site
import sys
import time


def size(path):
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.is_dir() else path.stat().st_size


def main():
    root = Path("/candidate")
    sys.path.insert(0, str(root))
    os.environ.update(
        APP_ENV="production", JWT_SECRET_KEY=secrets.token_hex(32),
        OPENAI_API_KEY="offline-probe-not-a-real-key",
        DATABASE_URL="postgresql://unused:unused@127.0.0.1:1/unused",
        STORAGE_BACKEND="local", LOCAL_STORAGE_PATH="/tmp/dataez-probe",
        METRIC_SCHEDULER_ENABLED="false", IMPORT_CLEANUP_ENABLED="false",
        INDEX_WORKER_ENABLED="false", PYTHONDONTWRITEBYTECODE="1",
    )
    packages = {d.metadata["Name"]: d.version for d in metadata.distributions()}
    # Use pip's bundled parser so the probe doesn't add runtime dependencies.
    from pip._vendor.packaging.requirements import Requirement
    requirements = []
    for raw in (root / "requirements.txt").read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            req = Requirement(line)
            installed = metadata.version(req.name)
            requirements.append({"requirement": line, "installed": installed,
                                 "matches": req.specifier.contains(installed)})
    assert all(r["matches"] for r in requirements), requirements
    package_root = Path(site.getsitepackages()[0])
    directories = sorted(({"name": p.name, "bytes": size(p)} for p in package_root.iterdir()),
                         key=lambda p: p["bytes"], reverse=True)
    digest = hashlib.sha256()
    for p in sorted((root / "app").rglob("*.py")):
        digest.update(str(p.relative_to(root)).encode())
        digest.update(p.read_bytes())
    report = {
        "scope": "offline Linux dependency/import/parser probe, NOT Vercel deployment or full API validation",
        "python": platform.python_version(), "architecture": platform.machine(),
        "source_sha256": digest.hexdigest(),
        "requirements_sha256": hashlib.sha256((root / "requirements.txt").read_bytes()).hexdigest(),
        "requirements": requirements, "installed_packages": packages,
        "site_packages_bytes": sum(p["bytes"] for p in directories),
        "site_packages_without_pyc_bytes": sum(p.stat().st_size for p in package_root.rglob("*")
                                               if p.is_file() and p.suffix != ".pyc"),
        "largest_package_directories": directories[:12],
        "app_python_bytes": sum(p.stat().st_size for p in (root / "app").rglob("*.py")),
    }
    started = time.perf_counter()
    import app.main as api
    report["app_import_seconds"] = round(time.perf_counter() - started, 3)
    report["route_count"] = len(api.app.routes)
    report["import_peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    from app.korean_text import tokenize_korean
    started = time.perf_counter()
    words = tokenize_korean("강남점 이번 달 카드 매출과 현금 매출 비교")
    assert words
    report["korean_first_call_seconds"] = round(time.perf_counter() - started, 3)
    report["korean_tokens"] = words
    report["korean_peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    from app.data_import import prepare_import, validate_upload
    from openpyxl import Workbook
    report["parse_cases"] = []
    for extension, count in [("csv", 1000), ("csv", 10000), ("csv", 100000), ("xlsx", 1000), ("xlsx", 10000)]:
        headers = ["transaction_id", "store", "method", "amount"]
        rows = [(f"TX{i:08d}", "강남점", "카드", 12000 + i % 100) for i in range(count)]
        if extension == "csv":
            import csv
            stream = io.StringIO(newline="")
            writer = csv.writer(stream)
            writer.writerow(headers)
            writer.writerows(rows)
            content = stream.getvalue().encode("utf-8-sig")
        else:
            book = Workbook(write_only=True)
            sheet = book.create_sheet()
            sheet.append(headers)
            for row in rows:
                sheet.append(row)
            stream = io.BytesIO()
            book.save(stream)
            content = stream.getvalue()
        started = time.perf_counter()
        prepared = prepare_import(content, f"synthetic.{extension}")
        assert len(prepared.rows) == count
        assert sum(row[3] for row in prepared.rows) == sum(row[3] for row in rows)
        report["parse_cases"].append({"extension": extension, "rows": count,
            "file_bytes": len(content), "parse_seconds": round(time.perf_counter() - started, 3),
            "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "row_count_and_amount_sum_match": True})
    # Proves the application accepts a payload that Vercel's gateway rejects.
    payload = b"column\n" + b"x" * 6_000_000
    validate_upload(payload, "size-probe.csv")
    report["application_accepts_6mb_upload"] = True
    report["lifespan_executed"] = False
    report["external_requests"] = 0  # enforced by Docker --network none
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
