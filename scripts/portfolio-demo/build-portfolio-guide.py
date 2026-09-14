"""Build an offline, self-contained portfolio guide from reviewed evidence.

Run Archify deliver first; the build checks its exact artifact hash.
No model calls, deployment or account data access.
"""
from pathlib import Path
import base64
import hashlib
import html
import json
import re

ROOT = Path(__file__).resolve().parents[2]
def data_uri(path, mime):
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")

receipt = json.loads((ROOT / '.local-test/portfolio-guide-archify-receipt.json').read_text(encoding='utf-8-sig'))
arch = (ROOT / '.local-test/portfolio-guide-architecture.html').read_bytes()
assert receipt['ok'] and receipt['validation']['checksPassed'] == 9
assert hashlib.sha256(arch).hexdigest() == receipt['artifact']['sha256']
assert hashlib.sha256((ROOT / 'docs/portfolio-demo/architecture.json').read_bytes()).hexdigest() == receipt['specification']['sha256']
svg = re.search(r'<svg\b[\s\S]*?</svg>', arch.decode('utf-8')).group(0)
svg = svg.replace('<svg ', '<svg xmlns="http://www.w3.org/2000/svg" data-theme="light" ', 1)
svg = re.sub(r'\s(data-[\w-]+)(?=\s|>)', r' \1=""', svg)
arch_css = '\n'.join(re.findall(r'<style[^>]*>([\s\S]*?)</style>', arch.decode('utf-8')))
# Printing uses the unchanged diagram inside an isolated data document to avoid
# importing the Archify viewer's global CSS into the guide.
# Standalone SVG needs its original diagram styles for print readability.
svg = svg.replace('>', '><style>' + arch_css.replace('&', '&amp;').replace('<', '&lt;') + '</style>', 1)
print_uri = 'data:image/svg+xml;base64,' + base64.b64encode(svg.encode()).decode()
template = (ROOT / 'scripts/portfolio-demo/portfolio-guide.template.html').read_text(encoding='utf-8')
replacements = {
    '__FONT400__': data_uri(ROOT / 'web/app/fonts/spoqa-400.woff2', 'font/woff2'),
    '__FONT700__': data_uri(ROOT / 'web/app/fonts/spoqa-700.woff2', 'font/woff2'),
    '__SCREENSHOT__': data_uri(ROOT / 'docs/portfolio-demo/assets/phase-2-dashboard-dark.png', 'image/png'),
    '__ARCHITECTURE_BASE64__': base64.b64encode(arch).decode(),
    '__ARCHITECTURE_SVG__': '<img style="width:100%" alt="DATA:EZ 배포 구조" src="' + print_uri + '">',
    '__FONT_LICENSE__': html.escape('\n\n'.join((ROOT / f'web/public/font-licenses/{name}').read_text(encoding='utf-8') for name in ['spoqa-LICENSE.txt', 'spoqa-OFL.txt'])),
}
for key, value in replacements.items():
    assert key in template
    template = template.replace(key, value)
assert not re.search(r'__[A-Z][A-Z0-9_]+__', template)
out = ROOT / 'docs/portfolio-demo/PORTFOLIO_GUIDE.html'
out.write_text(template, encoding='utf-8', newline='\n')
public_receipt = {
    'date': '2026-09-14', 'artifact': 'PORTFOLIO_GUIDE.html',
    'basis': ['CASE_STUDY.md', 'FINAL_QA.md', 'architecture.json', '../AGENT_QUALITY_PIPELINE.md', '../CHAT_QUALITY_OBSERVABILITY.md', '../evaluations/post-merge-20260914/verification.json'],
    'archify': {key: receipt[key] for key in ['type', 'specification', 'artifact', 'validation']},
    'diagram_note': 'Existing verified architecture reused unchanged; a new workflow candidate was abandoned after two unsuccessful correction rounds. The guide uses a separate HTML explanation of the request flow.',
    'standalone': True,
    'sha256': hashlib.sha256(out.read_bytes()).hexdigest(),
    'bytes': out.stat().st_size,
    'visual_review': 'pending',
}
submission = (ROOT / 'scripts/portfolio-demo/submission.template.html').read_text(encoding='utf-8')
for key in ['__FONT400__', '__FONT700__', '__FONT_LICENSE__']:
    assert key in submission
    submission = submission.replace(key, replacements[key])
assert not re.search(r'__[A-Z][A-Z0-9_]+__', submission)
submission_out = ROOT / 'docs/portfolio-demo/SUBMISSION.html'
submission_out.write_text(submission, encoding='utf-8', newline='\n')
public_receipt['submission'] = {
    'artifact': 'SUBMISSION.html',
    'sha256': hashlib.sha256(submission_out.read_bytes()).hexdigest(),
    'bytes': submission_out.stat().st_size,
    'standalone': True,
    'visual_review': 'pending',
}
(ROOT / 'docs/portfolio-demo/portfolio-guide-receipt.json').write_text(json.dumps(public_receipt, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(json.dumps({'output': str(out), 'bytes': out.stat().st_size}))
