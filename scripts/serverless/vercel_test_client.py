"""Small HTTP test adapter using the authenticated Vercel CLI protection bypass.

Tokens and JSON request bodies go through stdin, never shell arguments or logs.
"""
from pathlib import Path
import json
import shutil
import subprocess
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[2]


class VercelTestClient:
    def __init__(self, deployment):
        self.deployment = deployment
        self.stage = ROOT / ".local-test/vercel-api-preview"
        project = json.loads((self.stage / ".vercel/project.json").read_text())
        assert project["projectId"] == "prj_YV4Vf5std97PnGaKwyWzr4LHG940"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path, **kwargs):
        return self.request("POST", path, **kwargs)

    def request(self, method, path, *, headers=None, json=None, data=None, files=None):
        import json as json_module
        assert path.startswith("/") and not path.startswith("//")
        def quote(value):
            return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r') + '"'
        lines = ["silent", "show-error", 'write-out = "\\n%{http_code}"', "request = " + quote(method)]
        for key, value in (headers or {}).items():
            lines.append("header = " + quote(f"{key}: {value}"))
        if json is not None:
            lines += ['header = "Content-Type: application/json"', "data = " + quote(json_module.dumps(json))]
        paths = []
        try:
            header_path = ROOT / '.local-test/supabase' / (uuid4().hex + '.headers')
            header_path.parent.mkdir(parents=True, exist_ok=True)
            paths.append(header_path)
            lines.append('dump-header = ' + quote(header_path.as_posix()))
            for key, value in (data or {}).items():
                lines.append("form-string = " + quote(f"{key}={value}"))
            for key, (filename, content, content_type) in (files or {}).items():
                temp = ROOT / ".local-test/supabase" / (uuid4().hex + ".upload")
                temp.parent.mkdir(parents=True, exist_ok=True)
                temp.write_bytes(content)
                paths.append(temp)
                lines.append("form = " + quote(f'{key}=@{temp.as_posix()};filename={filename};type={content_type}'))
            result = subprocess.run([shutil.which("npx"), "--yes", "vercel@59.15.1", "curl", path,
                                     "--deployment", self.deployment, "--", "--config", "-"],
                                    cwd=self.stage, input=("\n".join(lines) + "\n").encode(), capture_output=True, timeout=90)
            if result.returncode:
                raise RuntimeError("Vercel test HTTP command failed")
            body, status = result.stdout.rsplit(b"\n", 1)
            # curl may include proxy/redirect headers before the final response.
            blocks = header_path.read_bytes().replace(b'\r\n', b'\n').strip().split(b'\n\n')
            final = [block for block in blocks if block.startswith(b'HTTP/')][-1]
            response_headers = [(key.strip(), value.strip()) for line in final.split(b'\n')[1:]
                                if b':' in line for key, value in [line.split(b':', 1)]]
            return httpx.Response(int(status), content=body, headers=response_headers)
        finally:
            for temp in paths:
                temp.unlink(missing_ok=True)
