"""Render the submission's print CSS to A4; requires WeasyPrint 70 and pypdf.

This is document rendering, not a browser print-dialog test. On Windows, see
https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#windows
for Pango and WEASYPRINT_DLL_DIRECTORIES. No app dependencies are changed.
"""
from pathlib import Path
import hashlib
import json

from pypdf import PdfReader
from weasyprint import HTML, __version__

ROOT = Path(__file__).resolve().parents[2]
source = ROOT / 'docs/portfolio-demo/SUBMISSION.html'
output = ROOT / 'output/pdf/DATAEZ-SUBMISSION.pdf'
output.parent.mkdir(parents=True, exist_ok=True)
HTML(filename=str(source), media_type='print').write_pdf(output)
pdf = PdfReader(output)
assert len(pdf.pages) == 1, 'Submission must fit on one A4 page'
page = pdf.pages[0]
assert abs(float(page.mediabox.width) - 595.276) < 0.1
assert abs(float(page.mediabox.height) - 841.890) < 0.1
text = ''.join(page.extract_text().split())
for required in ['DATA:EZ', '문제와 해결', '설명할 기술 판단 3가지',
                 '검증 근거와 한계', '구성과 기여', '22/24 → 24/24',
                 '690,200원 · 8행', '공개 영상 URL은 없다.']:
    assert ''.join(required.split()) in text, required
links = [str(a.get_object().get('/A', {}).get('/URI'))
         for a in page.get('/Annots', [])]
assert set(links) == {
    'https://dataez.vercel.app/',
    'https://github.com/gnb1202/DATAEZ',
    'https://github.com/gnb1202/DATAEZ/blob/main/docs/portfolio-demo/CASE_STUDY.md',
}, links
receipt = {
    'source': source.relative_to(ROOT).as_posix(),
    'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
    'artifact': output.relative_to(ROOT).as_posix(),
    'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
    'bytes': output.stat().st_size,
    'renderer': f'WeasyPrint {__version__}',
    'pages': len(pdf.pages),
    'page_size': 'A4 (595.276 x 841.890 pt)',
    'required_text': 'passed',
    'external_link_annotations': links,
    'visual_review': 'pending; render all pages with Poppler and inspect',
    'browser_print_dialog': 'not tested; in-app tab_content_export unsupported',
}
receipt_path = ROOT / 'docs/portfolio-demo/submission-pdf-receipt.json'
receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(json.dumps(receipt, ensure_ascii=False))
