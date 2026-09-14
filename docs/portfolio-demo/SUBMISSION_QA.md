# 제출 자료 마감 검증

2026-09-14에 수행한 제출 자료 검증이다. 09-12 제품 QA와 09-14 앞선 공개 UI 실행은 별도 기록이며 이번에 반복하지 않았다.

- [한 페이지 HTML](SUBMISSION.html) · [A4 PDF](../../output/pdf/DATAEZ-SUBMISSION.pdf) · [상세 가이드](PORTFOLIO_GUIDE.html)
- [이번 검증 기록](../evaluations/submission-20260914/verification.json) · [PDF 해시·검수](submission-pdf-receipt.json) · [ZIP 해시·구성](submission-package-receipt.json)

## 이번에 확인한 범위

- Codex 인앱 브라우저에서 저장소 `docs`를 localhost HTTP로 제공했다. 실제 `innerWidth` 320/390/1280px와 스크롤 너비를 대조했고 가로 넘침이 없었다. 모바일 본문·하단·툴바, 데스크톱 표시와 상세 가이드 링크를 확인했다. 320px에서 인쇄 버튼 글자가 나뉘던 문제는 툴바 줄바꿈으로 수정했다.
- HTML 인쇄 CSS를 **WeasyPrint 70.0**으로 출력했다. A4 1장, 주요 문구와 한글, 외부 링크 3개를 검사하고 Poppler PNG로 전체 페이지의 여백·잘림·겹침을 검수했다. 해당 렌더러의 flex 링크 클릭 영역 누락은 인쇄용 nav를 일반 배치로 바꿔 해결했다.
- 빌더가 기존 Archify 구조도·명세의 해시와 9개 검사 기록을 확인했다. 상세 가이드 HTML은 이전 검수본과 바이트가 같아 과거 검수에 해시로 연결한다. 새로 전체 가이드를 검수한 것으로 표시하지 않는다.
- 로컬 API를 다시 실행해 **545 passed / 268 skipped**, 웹 빌드 통과를 확인했다. 로컬 빌드는 API URL이 설정되지 않은 빌드 검사이며 공개 로그인 검증이 아니다. 과거 평가 도구 41개·실제 모델 24문항을 재실행하지 않았다.
- 전달 ZIP은 공개 파일 allowlist만 포함하며, 새 임시 폴더에 해제해 CRC와 HTML/JSON/PDF 바이트를 대조한다. Markdown의 번들 밖 상대 링크는 공개 저장소 링크로 변환한다. 영상은 포함하지 않는다.

## 남은 제한

- ZIP 해제본의 `file://` 직접 열기는 이전 브라우저 URL 정책 차단을 존중해 재시도하거나 다른 경로로 우회하지 않았다. localhost 렌더와 해제 파일 해시 검사를 직접 열기 성공으로 해석하지 않는다. 받는 환경에서 직접 열기는 사용자 확인 항목이다.
- 인앱 브라우저의 `tab_content_export`가 지원되지 않아 **브라우저 자체 인쇄 대화상자 결과는 미검증**이다. 동봉 PDF는 별도 문서 렌더러 결과다.
- 실제 모바일 기기, 전체 접근성 감사, 상세 가이드의 모든 인쇄 페이지 분할은 이번 범위에 포함하지 않았다.
- 외부 링크 HTTP 검사는 검사 시점의 접근 가능성만 확인하며 연결된 문서 전체의 주장이나 외부 서비스 기능을 재검증하지 않는다.

## 재생성

템플릿을 수정하고 `scripts/portfolio-demo/build-portfolio-guide.py`를 실행한다. 빌더는 Git에 없는 `.local-test/portfolio-guide-architecture.html`과 검증 영수증을 필요로 하므로 새 clone에서 바로 재생성된다고 보장하지 않는다. 배포된 HTML/PDF를 읽는 데 이 파일은 필요 없다.

PDF는 선택적 문서 도구 WeasyPrint 70.0·pypdf와 Windows Pango를 설치한 환경에서 `python scripts/portfolio-demo/render-submission.py`로 생성한다. [공식 설치 안내](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#windows). 앱 의존성은 변경하지 않았다. 생성 직후 PDF 영수증은 pending이며 Poppler 렌더 검수 후에만 갱신한다.

그 다음 `python scripts/portfolio-demo/package-submission.py`를 실행한다. 패키징은 검수된 PDF와 원본 HTML의 해시가 일치해야 진행한다. 새 ZIP의 브라우저 검증은 다시 pending이 되므로 실제 수행 결과 또는 위 제한을 명시한다.
