"""Package public portfolio documents only; never include raw account/video files."""
from pathlib import Path
import hashlib
import json
import re
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'output/portfolio-demo/submission-20260914.zip'
FILES = [
    'docs/portfolio-demo/PORTFOLIO_GUIDE.html',
    'docs/portfolio-demo/SUBMISSION.html',
    'docs/portfolio-demo/SUBMISSION.md',
    'docs/evaluations/post-merge-20260914/verification.json',
    'docs/evaluations/post-merge-20260914/oracle.json',
]
readme = '''# DATA:EZ 포트폴리오 전달 자료

ZIP을 풀고 docs/portfolio-demo/SUBMISSION.html을 브라우저로 여세요.
상세 설명은 같은 폴더의 PORTFOLIO_GUIDE.html에 있습니다.
두 HTML에는 폰트와 필요한 이미지·구조도가 포함되어 있습니다.
한 페이지의 인쇄 버튼은 브라우저 인쇄/PDF 저장을 엽니다.
폰트 라이선스는 각 HTML 하단에 있습니다.

공개 서비스: https://dataez.vercel.app/
소스와 기존 검증 문서: https://github.com/gnb1202/DATAEZ
외부 링크에는 인터넷 연결이 필요합니다. 09-14 공개 확인 기록은 ZIP에도 포함했습니다.
동영상은 이 ZIP에 포함하지 않았습니다. 기존 영상은 별도 로컬 전달 자료이며 공개 영상 URL은 없습니다.
원시 대화·계정 파일·비밀정보는 포함하지 않았습니다.

먼저 한 페이지 → 상세 가이드에서 직무 선택 → 기술 판단과 근거 → 3분 설명 순서로 사용하세요.
24/24는 고정 개발 회귀셋의 결과이며 일반 정확도나 독립 블라인드 평가가 아닙니다.
본인 기여 문장은 직접 결정하고 설명할 수 있는 범위로 조정하세요.
'''
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(OUTPUT, 'w', zipfile.ZIP_DEFLATED) as archive:
    archive.writestr('READ_ME.md', readme)
    for name in FILES:
        path = ROOT / name
        if path.suffix == '.md':
            # Keep bundled links local; redirect other relative evidence links
            # to the existing public repository instead of shipping broken paths.
            def link(match):
                label, target = match.groups()
                if '://' in target or target.startswith('#'):
                    return match.group(0)
                resolved = (path.parent / target).resolve().relative_to(ROOT).as_posix()
                if resolved in FILES:
                    return match.group(0)
                return f'[{label}](https://github.com/gnb1202/DATAEZ/blob/main/{resolved})'
            archive.writestr(name, re.sub(r'\[([^\]]+)\]\(([^)]+)\)', link, path.read_text(encoding='utf-8')))
        else:
            archive.write(path, name)
with zipfile.ZipFile(OUTPUT) as archive:
    assert archive.testzip() is None
    assert set(archive.namelist()) == set(FILES + ['READ_ME.md'])
    extracted = Path(tempfile.mkdtemp(prefix='dataez-submission-'))
    archive.extractall(extracted)
    for name in FILES:
        if not name.endswith('.md'):
            assert (extracted / name).read_bytes() == (ROOT / name).read_bytes()
receipt = {
    'artifact': OUTPUT.relative_to(ROOT).as_posix(),
    'sha256': hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),
    'bytes': OUTPUT.stat().st_size,
    'files': FILES + ['READ_ME.md'],
    'zip_integrity': 'passed',
    'extraction_hashes': 'passed; HTML/JSON unchanged in fresh temporary folder',
    'browser_portability_review': 'pending',
    'video_included': False,
}
(ROOT / 'docs/portfolio-demo/submission-package-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(json.dumps({'zip': str(OUTPUT), 'extracted': str(extracted)}, ensure_ascii=False))
