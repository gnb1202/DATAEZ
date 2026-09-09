const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const out=process.env.LIVE_ARTIFACTS,ui=process.env.LIVE_UI_URL;
if(!out||!ui)throw new Error('Use scripts/onboarding-eval/run.py');
(async()=>{
  const input=JSON.parse(await fs.readFile(path.join(out,'browser-input.json'),'utf8'));
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage({viewport:{width:1600,height:1200}});page.setDefaultTimeout(45000);
  const report={errors:[],api_mocks:false,chat:[]};page.on('pageerror',e=>report.errors.push(e.message));
  const response=(suffix,method='POST')=>{const p=page.waitForResponse(r=>r.url().endsWith(suffix)&&r.request().method()===method,{timeout:120000});p.catch(()=>{});return p;};
  async function json(p){const r=await p;assert.ok(r.ok(),await r.text());return r.json();}
  async function shot(name){await page.evaluate(()=>Promise.all(document.getAnimations().filter(a=>a.effect?.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{}))));await page.screenshot({path:path.join(out,name),fullPage:true});}
  const nav=page.getByRole('navigation',{name:'작업 메뉴'});
  const guide=page.getByLabel('첫 대시보드 안내',{exact:true});
  try{
    await page.goto(ui);await page.getByLabel('이메일',{exact:true}).fill(input.email);await page.getByLabel('비밀번호',{exact:true}).fill(input.password);
    await page.locator('form button[type=submit]').click();await page.waitForURL('**/dashboard');
    await guide.getByRole('button',{name:'첫 가게 만들기',exact:true}).click();
    const dialog=page.getByRole('dialog');let pending;
    await dialog.getByLabel('가게 이름',{exact:true}).fill('처음 카페');pending=response('/api/projects');await dialog.getByRole('button',{name:'만들기',exact:true}).click();report.project_id=(await json(pending)).id;
    await dialog.waitFor({state:'hidden'});await guide.getByRole('button',{name:'파일 연결·반영하러 가기',exact:true}).click();
    const panel=page.getByRole('region',{name:'출처별 파일 반영'});
    await panel.getByRole('button',{name:'파일로 출처 연결',exact:true}).click();const wizard=page.getByRole('region',{name:'파일 연결 안내'});
    await wizard.getByLabel('연결할 결제 파일',{exact:true}).setInputFiles(input.file);
    pending=response('/import-mapping/inspect');await wizard.getByRole('button',{name:'파일 컬럼 확인',exact:true}).click();const inspected=await json(pending);
    assert.equal(inspected.stored,false);assert.equal(inspected.suggested_mapping.amount_column,null);assert.equal(inspected.row_count,4);
    assert.equal(await wizard.getByLabel('결제·취소 금액',{exact:true}).inputValue(),'');
    await wizard.getByLabel('결제·취소 금액',{exact:true}).selectOption('결제금액');
    await wizard.getByLabel('파일 금액 해석',{exact:true}).selectOption('payment');
    await wizard.getByLabel(/거래별 원화 결제/).check();pending=response('/import-mapping/validate');
    await wizard.getByRole('button',{name:'연결한 파일 전체 검사',exact:true}).click();assert.equal((await pending).status(),422);
    await wizard.getByRole('alert').waitFor();assert.match(await wizard.getByRole('alert').innerText(),/음수/);
    assert.equal(await wizard.getByLabel('결제·취소 금액',{exact:true}).inputValue(),'결제금액');
    await wizard.getByLabel('파일 금액 해석',{exact:true}).selectOption('signed');await wizard.getByLabel(/거래별 원화 결제/).check();
    pending=response('/import-mapping/validate');await wizard.getByRole('button',{name:'연결한 파일 전체 검사',exact:true}).click();assert.equal((await json(pending)).amount,'180000');
    await wizard.getByLabel('출처 이름',{exact:true}).fill('시작 결제원장');await wizard.getByLabel('파일 제공처',{exact:true}).fill('샘플 PG');await wizard.getByLabel('가맹점·관리 계정',{exact:true}).fill('DEMO-001');
    await shot('mapping-confirmed.png');pending=response('/imports');await wizard.getByRole('button',{name:'출처 저장하고 중복 검토',exact:true}).click();const uploaded=await json(pending);
    const review=panel.getByLabel('업로드 검토',{exact:true});await review.getByRole('button',{name:'중복 검사·미리보기',exact:true}).click();
    await review.getByRole('button',{name:'장부에 반영',exact:true}).waitFor();await page.waitForFunction(()=>!Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='장부에 반영')?.disabled);
    assert.match(await review.innerText(),/130000원/);await shot('deduplicated-review.png');
    pending=response(`/imports/${uploaded.id}/commit`);await review.getByRole('button',{name:'장부에 반영',exact:true}).click();assert.equal((await json(pending)).result.rows_inserted,3);
    await review.getByText('장부 반영 완료',{exact:true}).waitFor();await page.reload();
    await panel.getByRole('button',{name:/first-payments.csv/}).click();
    await panel.getByRole('button',{name:'대시보드에서 첫 지표 만들기',exact:true}).click();
    await guide.getByLabel('첫 지표의 출처',{exact:true}).waitFor();await guide.getByLabel('첫 지표 이름',{exact:true}).fill('내 첫 일별 결제액');
    pending=response('/metrics/preview');await guide.getByRole('button',{name:'첫 지표 미리보기',exact:true}).click();const preview=await json(pending);assert.deepEqual(preview.data.map(r=>r.value),['100000','-20000','50000']);
    await guide.getByText(/^-\d+(\.\d+)?K$/).first().waitFor();
    await shot('first-metric-preview.png');pending=response('/metrics');await guide.getByRole('button',{name:'첫 지표 저장',exact:true}).click();report.metric_id=(await json(pending)).id;
    await page.getByRole('button',{name:'내 첫 일별 결제액 수정·이력',exact:true}).waitFor();await page.reload();
    await page.getByRole('button',{name:'내 첫 일별 결제액 수정·이력',exact:true}).waitFor();assert.equal(await guide.getAttribute('open'),null);
    await guide.locator(':scope > summary').click();await guide.getByRole('button',{name:'이 출처로 자연어 질문 작성',exact:true}).click();
    const textarea=page.locator('textarea');await textarea.waitFor();await page.waitForFunction(()=>document.querySelector('textarea')?.value.includes('시작 결제원장'));
    const question=await textarea.inputValue();assert.match(question,/미리보기만/);assert.match(question,/저장은 아직 하지 마/);
    // A draft is populated, never submitted until the user clicks Send.
    assert.equal(await page.locator('.react-grid-item').count(),0);
    pending=response('/messages/stream');await page.locator('form button[type=submit]').click();const stream=await (await pending).text();assert.match(stream,/"type":\s*"done"/);assert.doesNotMatch(stream,/"type":\s*"error"/);report.chat.push({question,stream});
    await page.waitForFunction(()=>!document.querySelector('textarea')?.disabled);await page.getByRole('button',{name:/집계표·SQL$/}).last().click();
    const table=dialog.getByRole('table',{name:'정확한 집계 결과'});assert.equal(await table.locator('tbody tr').count(),3);await shot('natural-first-analysis.png');await page.keyboard.press('Escape');
    await nav.getByRole('button',{name:'대시보드',exact:true}).click();
    await page.getByRole('button', { name: '가게 추가', exact: true }).click();
    await dialog.getByLabel('가게 이름',{exact:true}).fill('두 번째 가게');pending=response('/api/projects');await dialog.getByRole('button',{name:'만들기',exact:true}).click();report.other_project_id=(await json(pending)).id;
    await dialog.waitFor({state:'hidden'});await guide.getByRole('button',{name:'파일 연결·반영하러 가기',exact:true}).waitFor();assert.equal(await page.locator('.react-grid-item').count(),0);assert.equal(await guide.getByLabel('첫 지표의 출처',{exact:true}).count(),0);
    await page.getByRole('combobox', { name: '현재 작업 가게' }).selectOption({ label: '처음 카페' });await page.getByRole('button',{name:'내 첫 일별 결제액 수정·이력',exact:true}).waitFor();
    await shot('first-dashboard.png');assert.deepEqual(report.errors,[]);report.passed=true;console.log('PASS: real first-use mapping, validation repair, dedup review, resume, metric, natural draft and store isolation');
  }catch(e){report.passed=false;report.failure=e.stack;await shot('browser-failure.png').catch(()=>{});throw e;}
  finally{await fs.writeFile(path.join(out,'browser.json'),JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
