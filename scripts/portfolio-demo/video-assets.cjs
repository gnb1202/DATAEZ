const {chromium}=require('../ui-eval/node_modules/playwright');
const fs=require('node:fs/promises');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
async function main(){
 const out=path.resolve('output/portfolio-demo');await fs.mkdir(path.join(out,'assets'),{recursive:true});
 const font=(await fs.readFile('web/app/fonts/spoqa-500.woff2')).toString('base64');
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1920,height:1080},deviceScaleFactor:1});
 const cards={
  problem:{tag:'DATA:EZ · 기술 데모',title:'흩어진 매출 파일에서<br>내 가게의 통계로.',lead:'여러 결제수단과 가게의 기록을 모으고, 필요한 통계를 대화로 만듭니다.',items:[['01 · 보관','가게별 파일과 분석 범위'],['02 · 질문','날짜별 순결제액을 알려줘'],['03 · 활용','검증하고 저장한 대시보드']],note:'합성 데이터 · 실제 공개 앱 시연'},
  search:{tag:'동작 구조 · 검색과 집계',title:'자료를 찾는 일과<br>금액을 계산하는 일.',lead:'관련 파일·스키마·문서를 찾는 검색과, 선택한 데이터의 SQL 집계를 구분합니다.',items:[['자료 선택','이번 시연은 파일을 직접 선택'],['지표 정의','LLM이 계산 조건을 도구 인자로 구성'],['DB 집계','서버가 출처·권한·조건을 검증']],note:'이번 녹화에서 RAG 검색을 실행한 것은 아닙니다.'},
  append:{tag:'데모 준비 작업',title:'연결 장부에<br>카드 거래 한 건을 추가.',lead:'2026.09.05 · +30,000원 · API로 합성 거래 1회 반영',items:[['파일 원본','업로드 당시 8행을 보존'],['누적 장부','8행 → 9행'],['다음 동작','두 지표를 각각 재계산']],note:'실제 PG 거래의 자동 수집 기능이 아닙니다.'},
  limits:{tag:'동작 구조 · 현재 규모의 운영',title:'작은 데모에도<br>실행 경계는 명확하게.',lead:'Vercel 웹·API와 Supabase 데이터·원본 저장소를 사용합니다.',items:[['직접 업로드','서명된 URL → 원본 저장 → 서버 확인'],['유한 AI 실행','시간·반복·요청 횟수 제한'],['DB와 Cron','공유 요청 한도 · 저장 지표 재계산']],note:'Redis 없음 · 외부 PG 수집과 정기 재계산은 구분'},
  evidence:{tag:'검증과 다음 과제',title:'실제 흐름은 검증하고,<br>남은 과제는 구분합니다.',lead:'공개 서비스에서 실제 모델·SQL·저장·재계산·가게 전환을 확인했습니다.',items:[['완료','수정본 리허설 2회 연속 통과'],['집계표 합계','원본 690,200원 / 누적 720,200원'],['후속 과제','실제 PG · 고객 사용성 · 대규모 부하']],note:'합성 데이터 검증 · 고객 성과나 모든 질문의 정확성을 보장하지 않습니다.'},
  end:{tag:'DATA:EZ',title:'우리 가게 매출,<br>한눈에.',lead:'파일에서 통계로, 통계에서 내 대시보드로.',items:[['직접 체험','dataez.vercel.app'],['구현과 검증','github.com/gnb1202/DATAEZ']],note:'포트폴리오 데모 · 합성 데이터'}
 };
 for(const [name,c] of Object.entries(cards)){
  await page.setContent(`<!doctype html><meta charset="utf-8"><style>@font-face{font-family:Spoqa;src:url(data:font/woff2;base64,${font})}*{box-sizing:border-box}body{margin:0;background:#171b20;color:#f2f4f7;font-family:Spoqa;padding:104px 132px}header{font-size:23px;color:#82b4ff;letter-spacing:.04em}h1{font-size:76px;line-height:1.32;letter-spacing:-.045em;font-weight:500;margin:54px 0 26px}p{font-size:26px;line-height:1.7;color:#afb9c7;margin:0}.items{display:flex;border-top:1px solid #3b4552;border-bottom:1px solid #3b4552;margin-top:68px}.item{flex:1;padding:30px 28px 35px 0}.item+.item{border-left:1px solid #3b4552;padding-left:36px}.item label{display:block;color:#82b4ff;font-size:20px;margin-bottom:18px}.item strong{font-size:26px;font-weight:500;line-height:1.55}footer{font-size:18px;color:#9ba7b8;margin-top:38px}</style><header>${c.tag}</header><h1>${c.title}</h1><p>${c.lead}</p><div class="items">${c.items.map(([a,b])=>`<div class="item"><label>${a}</label><strong>${b}</strong></div>`).join('')}</div><footer>${c.note}</footer>`);
  await page.evaluate(()=>document.fonts.ready);
  await page.screenshot({path:path.join(out,'assets',name+'.png')});
 }
 await page.goto(pathToFileURL(path.resolve('docs/portfolio-demo/architecture.html')).href);
 await page.keyboard.press('t');
 await page.evaluate(()=>document.fonts.ready);
 await page.screenshot({path:path.join(out,'assets','architecture.png')});
 await browser.close();console.log('Rendered seven video explanation cards, including the validated architecture artifact');
}
main().catch(e=>{console.error(e.message);process.exitCode=1});
