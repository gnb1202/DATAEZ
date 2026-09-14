// Real Next.js/Edge UI; deterministic API fixtures. DB authorization is tested separately.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

async function main() {
  const browser = await chromium.launch({channel:'msedge',headless:true});
  const out=path.join(__dirname,'../../.local-test/quality-observability/ui');
  await fs.mkdir(out,{recursive:true});
  const checks=[], errors=[];
  try {
    const page=await browser.newPage({viewport:{width:1440,height:900},reducedMotion:'reduce'});
    page.setDefaultTimeout(15000);page.on('pageerror',e=>errors.push(e.message));
    let admin=true,feedback=null,loseResponse=false,review=null,candidate=null,runReads=0;
    const id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
    const chart={chart_type:'line',title:'합성 일별 매출',x_key:'day',y_key:'amount',unit:'KRW',data:[{day:'09-01',amount:30000},{day:'09-02',amount:40000}]};
    const run=()=>({id,user_id:'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',question:'합성 파일의 날짜별 매출을 보여줘',answer:'합성 매출의 일별 집계입니다.',status:'completed',observed_status:'completed',started_at:'2026-09-13T00:00:00Z',duration_ms:2400,version:{worker:'fixture-model',code_sha256:'synthetic-fixture'},rating:-1,review,candidate,charts:[chart],steps:[{tool_name:'preview_metric',tool_input:{operation:'sum'}}],usage:{total_tokens:300}});
    await page.route('**/api/**',async route=>{
      const req=route.request(),u=new URL(req.url()),p=u.pathname,method=req.method();
      let body={},status=200;
      if(method==='OPTIONS') {}
      else if(p==='/api/auth/refresh') body={access_token:'fixture',refresh_token:'fixture'};
      else if(p==='/api/auth/me') body={email:'synthetic@example.test'};
      else if(p==='/api/quality/access') body={admin};
      else if(p.endsWith('/feedback')) {
        if(method==='PUT') {feedback=req.postDataJSON();if(loseResponse){loseResponse=false;await route.abort();return;}}
        body={feedback};
      }
      else if(p.endsWith('/review')) {review=req.postDataJSON();body={review};}
      else if(p.endsWith('/candidate')) {if(method==='PUT'){candidate=req.postDataJSON();body={candidate};}else body={schema_version:1,kind:'synthetic_regression_candidate',...candidate};}
      else if(p==='/api/quality/runs') {runReads++;body={runs:[run()],total:1};}
      else if(p===`/api/quality/runs/${id}`) body=run();
      else if(p==='/api/projects') body={projects:[{id:'store-a',name:'합성 가게',description:''}]};
      else if(p==='/api/conversations') body={conversations:[{conversation_id:'conv-a',title:'합성 분석',project_id:'store-a'}]};
      else if(p.endsWith('/messages')) body={messages:[{message_id:id,role:'assistant',content:'합성 분석 결과입니다.',steps:[],charts:[]}]};
      else if(p==='/api/dashboard/widgets') body={widgets:[]};
      else if(p.endsWith('/tables')) body={tables:[]};
      else if(p.endsWith('/cash-entries')) body={entries:[],total:0};
      else if(p.endsWith('/ledger-sources')) body={sources:[]};
      else if(p.endsWith('/sample-workspace')) body={project:null};
      else if(p.endsWith('/search-index')) body={jobs:[],counts:{},total:0};
      else {status=404;errors.push(`Unexpected request: ${p}`);}
      await route.fulfill({status,contentType:'application/json',headers:{'access-control-allow-origin':'*','access-control-allow-headers':'*','access-control-allow-methods':'*'},body:JSON.stringify(body)});
    });
    await page.addInitScript(()=>localStorage.setItem('dataez_refresh_token','fixture'));
    const base=process.env.UI_BASE_URL || 'http://127.0.0.1:3140';
    await page.goto(base+'/quality');
    await page.getByRole('button',{name:/합성 파일의 날짜별 매출/}).click();
    await page.getByRole('combobox',{name:'검토 판정',exact:true}).selectOption('fail');
    await page.getByRole('combobox',{name:'문제 분류'}).selectOption('scope');
    await page.getByRole('textbox',{name:'검토 근거'}).fill('합성 사례: 범위 선택을 재확인해야 함');
    await page.getByRole('button',{name:'검토 저장',exact:true}).click();
    await page.getByText('검토를 저장했습니다.',{exact:true}).waitFor();
    await page.getByRole('textbox',{name:'합성 질문',exact:true}).fill('합성 파일의 원본 매출만 보여줘');
    await page.getByRole('textbox',{name:'기대 동작',exact:true}).fill('합성 원본 파일의 행만 집계한다');
    await page.getByRole('checkbox').check();
    await page.getByRole('button',{name:'후보 저장',exact:true}).click();
    await page.getByRole('button',{name:'저장된 후보 JSON 내보내기'}).waitFor();
    const download=page.waitForEvent('download');
    await page.getByRole('button',{name:'저장된 후보 JSON 내보내기'}).click();
    const file=await download;await file.saveAs(path.join(out,'candidate.json'));
    const exported=JSON.parse(await fs.readFile(path.join(out,'candidate.json'),'utf8'));
    assert.equal(exported.question,'합성 파일의 원본 매출만 보여줘');assert(!JSON.stringify(exported).includes(id));
    checks.push('admin review -> synthetic candidate -> downloaded JSON, no original run UUID');
    for(const [w,h] of [[1440,900],[768,1024],[390,844]]) for(const theme of ['dark','light']) {
      await page.setViewportSize({width:w,height:h});
      await page.evaluate(theme=>{document.documentElement.classList.remove('dark','light');document.documentElement.classList.add(theme);},theme);
      await page.getByText('모델·프롬프트 버전',{exact:true}).click();
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      await page.screenshot({path:path.join(out,`quality-${w}-${theme}.png`),fullPage:true});
    }
    checks.push('Edge 1440/768/390 dark/light, no horizontal overflow (mobile emulation)');
    await page.setViewportSize({width:1440,height:900});
    await page.goto(base+'/dashboard');
    await page.getByRole('button',{name:'분석 이력',exact:true}).click();
    await page.locator('#workspace-main .divide-y > button').first().click();
    await page.getByRole('button',{name:'👎 아쉬워요',exact:true}).click();
    await page.getByRole('combobox',{name:'어떤 부분이 아쉬웠나요?'}).selectOption('calculation');
    await page.getByRole('textbox',{name:'의견 (선택)'}).fill('합성 금액을 다시 확인해주세요');
    loseResponse=true;
    await page.getByRole('button',{name:'평가 저장',exact:true}).click();
    await page.getByText(/Failed to fetch|fetch failed|NetworkError/).waitFor();
    assert.equal(await page.getByRole('textbox',{name:'의견 (선택)'}).inputValue(),'합성 금액을 다시 확인해주세요');
    await page.getByRole('button',{name:'평가 저장',exact:true}).click();
    await page.getByText('평가를 저장했습니다.',{exact:true}).waitFor();
    assert.equal(feedback.rating,-1);assert.equal(feedback.reason,'calculation');
    await page.screenshot({path:path.join(out,'feedback-saved.png')});
    await page.reload();
    await page.getByRole('button',{name:'분석 이력',exact:true}).click();
    await page.locator('#workspace-main .divide-y > button').first().click();
    await page.waitForFunction(()=>Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='👎 아쉬워요'&&b.getAttribute('aria-pressed')==='true'));
    checks.push('answer feedback response loss retains draft; PUT retry and reload recover saved rating');
    admin=false;const before=runReads;
    await page.goto(base+'/quality');
    await page.getByText('관리자로 지정된 계정만 열 수 있습니다.',{exact:true}).waitFor();
    assert.equal(runReads,before);assert.equal(await page.getByRole('region',{name:'실행 목록'}).count(),0);
    checks.push('non-admin page does not request or show run logs');
    assert.deepEqual(errors,[]);
    await fs.writeFile(path.join(out,'receipt.json'),JSON.stringify({passed:true,mode:'real Edge UI, mocked API; no real model',checks,errors},null,2));
    console.log(JSON.stringify({passed:true,checks,out},null,2));
  } finally {await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
