"""Check submission assets and navigation links without running app/model calls."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen
import base64
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / 'docs/evaluations/submission-20260914'
REPO_PREFIX = 'https://github.com/gnb1202/DATAEZ/blob/main/'


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        if tag == 'a' and 'href' in attrs:
            self.links.append(attrs['href'])


urls = set()
checks = []
for name in ['PORTFOLIO_GUIDE.html', 'SUBMISSION.html']:
    path = ROOT / 'docs/portfolio-demo' / name
    source = path.read_text(encoding='utf-8')
    parsed = Links()
    parsed.feed(source)
    assert len(parsed.ids) == len(set(parsed.ids)), name
    assert not re.search(r'__[A-Z][A-Z0-9_]+__', source), name
    assert source.count('data:font/woff2;base64,') == 2, name
    for href in parsed.links:
        target = urlsplit(href)
        if target.scheme in ['http', 'https']:
            urls.add(href)
            continue
        resolved = (path.parent / unquote(target.path)).resolve() if target.path else path
        assert resolved.is_relative_to(ROOT) and resolved.is_file(), href
        if target.fragment and resolved.suffix == '.html':
            dest = Links()
            dest.feed(resolved.read_text(encoding='utf-8'))
            assert unquote(target.fragment) in dest.ids, href
    checks.append({'artifact': path.relative_to(ROOT).as_posix(),
                   'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                   'unique_ids': True, 'embedded_fonts': 2,
                   'placeholders_absent': True, 'local_links_and_anchors': 'passed'})
    if name == 'PORTFOLIO_GUIDE.html':
        encoded = re.search(r'<script id="archify-content"[^>]*>([^<]+)</script>', source).group(1)
        embedded = Links()
        embedded.feed(base64.b64decode(encoded).decode('utf-8'))
        urls.update(href for href in embedded.links if href.startswith(('http://', 'https://')))
        # The role switcher builds hrefs from fixed repository path literals.
        for path_literal in re.findall(r"\['[^']+','((?:api|web|docs)/[^']+)'\]", source):
            assert (ROOT / path_literal).is_file(), path_literal
            urls.add(REPO_PREFIX + path_literal)

for name in ['SUBMISSION.md', 'SUBMISSION_QA.md']:
    path = ROOT / 'docs/portfolio-demo' / name
    for href in re.findall(r'\[[^\]]+\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
        if href.startswith(('http://', 'https://')):
            urls.add(href)
        elif not href.startswith('#'):
            target = (path.parent / urlsplit(href).path).resolve()
            assert target.is_relative_to(ROOT) and target.is_file(), href

for url in urls:
    if url.startswith(REPO_PREFIX):
        assert (ROOT / unquote(urlsplit(url).path.split('/blob/main/', 1)[1])).is_file(), url


def probe(url):
    try:
        with urlopen(Request(url, method='HEAD', headers={'User-Agent': 'DATAEZ-Submission-LinkCheck/1.0'}), timeout=25) as response:
            return {'url': url, 'status': response.status, 'final_url': response.url}
    except HTTPError as exc:
        return {'url': url, 'status': exc.code}
    except Exception as exc:
        return {'url': url, 'status': None, 'error': type(exc).__name__}


with ThreadPoolExecutor(max_workers=3) as pool:
    http = list(pool.map(probe, sorted(urls)))
result = {
    'checked_at_utc': datetime.now(timezone.utc).isoformat(),
    'static': checks,
    'http_method': 'HEAD, redirects followed; no authentication',
    'http_scope': 'HTML navigation including fixed role links and embedded Archify credit; external links in submission Markdown. Not every URL written inside license prose.',
    'http': http,
    'http_successes': sum(r['status'] == 200 for r in http),
    'http_total': len(http),
}
EVIDENCE.mkdir(parents=True, exist_ok=True)
(EVIDENCE / 'artifact-checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(json.dumps({'static': 'passed', 'http_successes': result['http_successes'],
                  'http_total': len(http), 'unresolved': [r for r in http if r['status'] != 200]}, ensure_ascii=False))
if result['http_successes'] != len(http):
    raise SystemExit(1)
