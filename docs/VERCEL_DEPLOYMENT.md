# Vercel 프론트엔드 배포

2026-09-11 · 공개 주소: **https://dataez.vercel.app**

프론트와 API의 Production 연결 및 실제 공개 데모 검증을 완료했다. 현재 로그인·회원가입·업로드·AI 분석·저장 지표를 사용할 수 있다. [공개 데모 기록](PUBLIC_DEMO_ACCEPTANCE.md)과 [최신 main 통합·로그인 배포 기록](LOGIN_RELEASE.md)을 우선한다. 아래 초기 배포 기록은 당시 상태를 보존한다.

## 프로젝트 설정

| 항목 | 값 |
|---|---|
| 프로젝트 | `dataez` |
| GitHub | `gnb1202/DATAEZ` |
| 배포 브랜치 | `main` |
| Root Directory | `web` |
| Framework | Next.js |
| Node.js | `24.x` |
| 설치 | `npm ci` |
| 빌드 | `npm run build` |
| 출력 디렉터리 | Next.js 기본값 |

GitHub 연결 후 `4029310` 푸시가 실제 production 배포를 생성했음을 확인했다.
최초 성공 배포는 `dpl_FKqqknu18R9Ld9Pkbo9DfXBn515H`이며,
[해당 배포](https://vercel.com/gnb1202-navercoms-projects/dataez/FKqqknu18R9Ld9Pkbo9DfXBn515H)의
상태는 `READY`였다. 공개 URL은 Vercel 계정에 로그인하지 않은 브라우저로 검증했다.

## 환경변수와 현재 동작

- `NEXT_PUBLIC_API_URL`: 현재 미설정. production에서는 localhost로 대체하지 않고
  인증 입력과 API 호출을 막는다. 저장된 과거 세션이 있어도 refresh 요청을 보내지 않는다.
- `NEXT_PUBLIC_SITE_URL`: 현재 미설정. Vercel의 production hostname으로 공유 이미지의
  절대 주소를 만든다. 실제 응답은 `https://dataez.vercel.app/og-dataez.png`다.
- DB 연결 문자열, 모델 API 키, Storage 서버 자격 증명은 Vercel 웹에 등록하지 않았다.
- CLI 링크 과정에서 생성된 `.vercel/`와 `.env.local`은 Git에서 제외한다.

2026-09-11 후속 비용 결정으로 AWS/Lightsail은 보류하고 [Vercel API 적합성](VERCEL_API_FEASIBILITY.md)을 검증했다.
별도 임시 프로젝트의 의존성·파싱·스트리밍 검증 이후, `dataez-api` 보호된 Preview에 전체 API를 배포하고
Supabase DB·Storage 연결을 검증했다. [배포·검증 기록](SUPABASE_SETUP.md#vercel-함수-배포-및-연결-검증)을 참고한다.

검증을 마친 API에 HTTPS 주소가 생기면 Vercel의 production 환경에 `NEXT_PUBLIC_API_URL`을
등록하고 다시 배포한다. API의 `ALLOWED_ORIGINS`에는 공개 프론트 origin을 허용한다.
미리보기 주소는 필요한 주소만 별도로 허용한다. 이후 로그인·업로드·SSE 분석·저장·재접속을
실제 Supabase DB/Storage와 함께 검증한다.

## 배포 방식

이후 업데이트는 검증한 변경을 main에 푸시해 GitHub 연동 배포를 사용한다.
웹에 영향을 주지 않는 변경은 Vercel의 프로젝트 설정에 따라 건너뛸 수 있으므로
배포 목록에서 커밋과 상태를 확인한다.

최초 CLI 시도는 로그인된 Vercel CLI `59.15.1`을 사용했다. 로컬 작업 폴더 전체를
업로드하지 않고, `git archive`에서 커밋된 `web` 파일만 추출한 별도 패키지를 만들었다.
`deploy --dry --json`의 실제 업로드 목록에서 프론트엔드 132개 파일만 포함되고
환경 파일·로컬 실험·비공개 자료·백엔드가 제외됐음을 확인한 뒤 업로드했다.
CLI 배포가 필요하면 같은 방식으로 소스 패키지와 실제 파일 목록을 확인한다.
`.vercelignore` 파일만 보고 제외가 보장된다고 가정하지 않는다.

## 수정한 빌드 문제

첫 배포는 페이지 컴파일 이후 Vercel 패키징 단계에서 `next-server.js.nft.json`
파일 누락으로 실패했다. Docker용 `output: "standalone"`과 Next.js 16.3의
Vercel adapter가 함께 사용될 때의 [보고된 문제](https://github.com/vercel/next.js/issues/96646)와
일치했다. `web/next.config.js`에서 Vercel은 adapter 기본 출력을 사용하고,
Docker에서는 standalone 출력을 유지하도록 분리한 뒤 실제 Vercel 빌드가 통과했다.

## 확인 결과

- Node 24 / Next.js 16.3.4 로컬 프로덕션 Docker 빌드와 TypeScript 검사 통과.
- API 미설정·공백·개발 기본값·지정 HTTPS 주소에 대한 설정 검사 4개 통과.
- 로컬 브라우저 검사 12개, 실제 공개 주소 브라우저 검사 12개 각각 통과.
- 공개 HTTPS 200, 서비스 준비 안내, 인증 입력 비활성, 브랜드 제목·이미지 응답 확인.
- 다크·라이트 데스크톱과 390px 모바일에서 가로 넘침 없음.
- `/dashboard` 직접 접근은 로그인 진입 화면으로 이동한다.
- 과거 세션을 넣어도 API 요청 0건, 브라우저 런타임 오류 0건.

[공개 주소 검사 결과](evaluations/vercel/public-frontend.json).
이는 프론트엔드 배포 검증이며 전체 서비스의 수용 시험이나 실제 사용자 관찰을 대신하지 않는다.
