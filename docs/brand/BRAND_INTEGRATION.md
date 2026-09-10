# Gathered Ledger 통합 검증

2026-09-11 · 기준 커밋 `604b41e` · 작업 브랜치 `codex/brand-gathered-ledger`

## 작업 격리와 커밋 범위

기존 `codex/demo-usability` 체크아웃의 미커밋 파일을 보존하고, 별도
`D:\Github\DATAEZ-brand` worktree에 BI 변경을 복사해 검토·수정했다.
원래 체크아웃의 파일·인덱스·브랜치를 이 작업에서 변경하지 않았다.
푸시·배포·활성 브랜치로의 병합은 수행하지 않았다.

변경은 다음 단위로 분리한다.

1. **브랜드 마스터:** 가이드, B안 SVG·PNG·HTML 원본, 전달 ZIP,
   재생성 도구. 초기 A·B·C 비교 시안은 원래 폴더에 보존하고 커밋에서 제외한다.
2. **제품 적용:** 공용 로고, 로그인, 사이드바, 스타일, 파비콘과 로그인 배경.
3. **공유·배포 설정과 검증:** 공유 메타데이터·이미지, Docker 빌드 인자,
   환경변수 예시, 검증 스크립트·캡처, 결정 기록과 이 기록.

## 수정한 문제

- 기존 PNG 중 128px 블루 심볼이 완전히 투명하고, 180·192px 앱 아이콘과
  256px 심볼이 잘려 있었다. Windows Chrome CLI의 최소 창 너비 영향을 받지
  않도록 Playwright의 정확한 viewport로 SVG를 렌더링하도록 수정했다.
  SVG 형태와 색상을 유지한 채 PNG 28개와 전달 ZIP을 갱신했다.
- 높이 600px 로그인 화면에서 로고·본문·푸터 사이 여백이 사라졌다.
  패널에 최소 간격을 주어 화면이 낮아도 보호 여백을 유지한다.
- 모바일 로그인 제목·설명의 한글 단어가 중간에서 끊기는 줄바꿈을 보완했다.
- 접힌 사이드바 심볼의 중심을 맞추고 로고 버튼의 클릭 영역을 확보했다.
- 빈 문자열이나 공백만 있는 `NEXT_PUBLIC_SITE_URL`은 로컬 기본값을 사용한다.
  공개 주소의 앞뒤 공백은 제거한다.
- 결정 기록에서 과거의 “제품 적용 전” 상태와 이후 확정 상태를 구분했다.

## 검증 결과

| 검증 | 결과 |
|---|---|
| `web`: `npm ci --no-audit --no-fund`, `npm run build` | 성공, TypeScript 및 정적 페이지 생성 통과 |
| `web`: `npm run lint` | 오류 0개, 기존 파일의 경고 12개 유지 |
| `git diff --check` | 통과 |
| 실제 Chromium + 프로덕션 standalone 서버 | 다크·라이트 28개 화면 및 동작 검사 통과 |
| 로그인·회원가입 | 가로 넘침 없음, 로고 최소 크기·테마 색상 확인 |
| 사이드바 | 다크·라이트 접기·펼치기, 접힌 상태의 테마 전환, 로고의 대시보드 이동 확인 |
| 모바일 메뉴 | 로고와 닫기 버튼 겹침 없음, 로고 클릭 시 메뉴 닫힘과 포커스 복귀 확인 |
| 공유 메타데이터 | OG·X 이미지 주소, 1200×630 PNG 응답, 파비콘 응답 확인 |
| Compose | 로컬 기본값과 지정한 HTTPS 주소 모두 web 빌드 인자로 전달됨 |
| 마스터 PNG | 28개 크기·투명 배경·빈 이미지·잘림 검사 통과 |
| 전달 ZIP | CRC 정상, 39개 파일이 `master/`와 바이트 단위 일치 |
| 앱 이미지 | OG·로그인 배경이 전달용 원본과 바이트 단위 일치 |

화면 크기는 로그인 `1600×1000`, `1024×600`, `768×1024`, `390×844`,
`320×568`; 대시보드 `1600×1000`, `768×1024`, `390×844`, `320×568`이다.
대표 캡처는 [applications](../../outputs/brand/gathered-ledger/applications)에
있다. 전체 캡처·검사 목록은 재실행 시 `scripts/ui-eval/artifacts/brand/`에 생성한다.

인증·대시보드 API는 결정적인 로컬 fixture를 사용했다. 실제 계정·DB·LLM을
사용하는 통합 검증이나 외부 공유 크롤러 검증은 이번 범위에 포함하지 않았다.

## 재현

저장소 루트에서 `npm ci --prefix scripts/ui-eval`을 실행한다. Chrome이 필요하며
Edge를 사용할 경우 `BROWSER_CHANNEL=msedge`로 지정할 수 있다.

```powershell
# 로컬 개발 서버를 실행한 상태에서
$env:UI_BASE_URL = 'http://127.0.0.1:3146'
$env:EXPECTED_SITE_URL = 'http://localhost:3000'
node scripts/ui-eval/brand.cjs

# 마스터 PNG 검증·출력 및 전달 ZIP 갱신
pwsh -File scripts/brand/export-master-assets.ps1
```

이번 프로덕션 검증은 빌드에만 `NEXT_PUBLIC_SITE_URL`을
` https://brand-preview.example.test `로 지정하고 실행 시에는 다른 주소를
사용했다. 결과 메타데이터는 앞뒤 공백을 제거한 빌드 주소를 유지했다.
이 `.test` 주소는 검증용이며 저장된 서비스 설정이 아니다.

## 남은 배포 설정

**실제 서비스 주소 미정.** `NEXT_PUBLIC_SITE_URL`의 localhost 기본값은 로컬 전용이다.
공개 HTTPS 도메인이 정해지면 해당 값을 빌드 환경에 지정하고 web 이미지를
재빌드해야 한다. [배포 문서](../DEPLOYMENT.md#pending-public-site-origin-2026-09-11)의
체크리스트에 따라 공개 공유 이미지 응답을 확인한다.
