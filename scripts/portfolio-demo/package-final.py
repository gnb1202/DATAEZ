"""Allowlisted local delivery ZIP; never includes raw recordings or credentials."""
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
source = ROOT / 'output/portfolio-demo'
target = ROOT / 'output/portfolio-demo-delivery.zip'
local = ROOT / '.local-test/portfolio-demo/final-qa'
names = ['index.html', 'product.mp4', 'technical.mp4', 'loop.mp4', 'loop.webm',
         'product.ko.srt', 'technical.ko.srt', 'loop.ko.srt', 'fonts/spoqa.ttf',
         'assets/product-poster.png', 'assets/technical-poster.png', 'assets/loop-poster.png']
names += ['font-licenses/' + p.name for p in (source / 'font-licenses').glob('*') if p.is_file()]
contents = {name: (source / name).read_bytes() for name in names}
contents['README.txt'] = (
    'DATA:EZ portfolio demo / 2026-09-12\n'
    'Unzip, open a terminal in this folder, then run:\n'
    'python -m http.server 3135 --bind 127.0.0.1\n'
    'Open http://127.0.0.1:3135/ in a browser. Python 3 is required.\n'
    'Alternatively open the MP4 files in a local video player.\n'
    'Real public app recording; synthetic data; silent Korean burned-in captions.\n'
    'Original total 690200 KRW; accumulated ledger after one 30000 KRW append: 720200.\n'
    'Product 110s, technical 300s, excerpt loop 12s.\n'
    'Edited with holds, zoom and limited interaction speed adjustment.\n'
    'The 12s excerpt is not an API latency claim. No PG collection was filmed.\n'
    'Videos are local delivery artifacts, not publicly hosted.\n'
    'Source and detailed editing/verification notes: https://github.com/gnb1202/DATAEZ\n'
).encode('utf-8')
manifest = {name: {'bytes':len(data), 'sha256':hashlib.sha256(data).hexdigest()} for name,data in contents.items()}
contents['manifest.json'] = (json.dumps(manifest,indent=2)+'\n').encode()
with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as archive:
    for name,data in contents.items(): archive.writestr(name,data)
extracted = Path(tempfile.mkdtemp(prefix='dataez-delivery-'))
with zipfile.ZipFile(target) as archive:
    assert archive.testzip() is None
    assert set(archive.namelist()) == set(contents)
    archive.extractall(extracted)
for name,data in contents.items(): assert (extracted/name).read_bytes() == data
local.mkdir(parents=True,exist_ok=True)
report = {'passed':True,'zip':str(target),'zip_bytes':target.stat().st_size,
          'zip_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
          'extracted':str(extracted),'files':manifest,'allowlist_only':True}
(local/'package.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'passed':True,'files':len(contents),'zip_bytes':report['zip_bytes'],'extracted':str(extracted)}))
