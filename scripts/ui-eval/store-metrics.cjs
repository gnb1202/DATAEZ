const { openChat } = require('./workspace-helpers.cjs');
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const out=process.env.LIVE_ARTIFACTS,ui=process.env.LIVE_UI_URL;
if (!out || !ui) throw new Error('Use scripts/store-metrics-eval/run.py');
(async()=>{
  const input=JSON.parse(await fs.readFile(path.join(out,'browser-input.json'),'utf8'));
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage({viewport:{width:1600,height:1200}}); page.setDefaultTimeout(45000);
  const report={errors:[],api_mocks:false,chat:[]};
  page.on('pageerror',e=>report.errors.push(e.message));
  const response=(suffix,method='POST')=>{const p=page.waitForResponse(r=>r.url().endsWith(suffix)&&r.request().method()===method,{timeout:240000});p.catch(()=>{});return p;};
  async function json(p){const r=await p;assert.ok(r.ok(),await r.text());return r.json();}
  const nav=page.getByRole('navigation',{name:'작업 메뉴'});
  async function shot(name){await page.evaluate(()=>Promise.all(document.getAnimations().filter(a=>a.effect?.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{}))));await page.screenshot({path:path.join(out,name),fullPage:true});}
  async function chat(question){
    await openChat(page);
    await page.locator('textarea').fill(question);const pending=response('/messages/stream');
    await page.locator('form button[type=submit]').click();const r=await pending;assert.equal(r.status(),200);const stream=await r.text();
    assert.match(stream,/"type":\s*"done"/);assert.doesNotMatch(stream,/"type":\s*"error"/);report.chat.push({question,stream});
    await page.waitForFunction(()=>!document.querySelector('textarea')?.disabled);
  }
  try{
    await page.goto(ui);await page.getByLabel('이메일',{exact:true}).fill(input.email);await page.getByLabel('비밀번호',{exact:true}).fill(input.password);
    await page.locator('form button[type=submit]').click();await page.waitForURL('**/dashboard');
    await nav.getByRole('button',{name:'대시보드',exact:true}).waitFor();
    await page.getByRole('combobox', { name: '현재 작업 가게' }).selectOption({ label: '강남점' });
    await page.waitForURL(url=>url.searchParams.get('project')===input.project_id);
    await nav.getByRole('button',{name:'대시보드',exact:true}).click();
    const form=page.locator('details[aria-label="여러 가게 지표 만들기"]');
    await form.locator(':scope > summary').click();
    await form.getByLabel('여러 가게 지표 이름',{exact:true}).fill('두 가게 합계');
    for(const name of ['강남점','홍대점']){
      await form.getByLabel(name,{exact:true}).check();
      const fields=form.getByRole('group',{name,exact:true});
      await fields.getByLabel('장부 1',{exact:true}).selectOption(input.tables[name]);
      await fields.getByLabel('금액 컬럼',{exact:true}).selectOption('amount');
      await fields.getByLabel('결제·취소 발생일',{exact:true}).selectOption('occurred_at');
    }
    await form.getByLabel('비교 방식',{exact:true}).selectOption('none');
    let pending=response('/metrics/preview');await form.getByRole('button',{name:'여러 가게 결과 미리보기',exact:true}).click();
    const preview=await json(pending);assert.equal(preview.value,'250000');assert.equal(preview.stores.length,2);
    await form.getByLabel(/각 가게의 원화 결제/).check();
    await shot('store-selection.png');
    pending=response('/metrics');await form.getByRole('button',{name:'여러 가게 지표 저장',exact:true}).click();report.manual=await json(pending);
    await chat('강남점과 홍대점의 이번 달 순결제액을 가게별 막대그래프로 비교해서 대시보드에 저장해줘. 각 가게의 결제원장은 원화 거래별 결제·취소 내역이고 amount에 취소는 음수로 들어있어. occurred_at 기준, 수수료는 빼지 마. 수원점은 포함하지 마. 제목은 두 지점 비교, 매시간 갱신으로 해줘.');
    await nav.getByRole('button',{name:'대시보드',exact:true}).click();
    const title='두 지점 비교';
    await page.getByRole('button',{name:title+' 집계표·SQL',exact:true}).click();
    const dialog=page.getByRole('dialog');let table=dialog.getByRole('table',{name:'정확한 집계 결과'});
    assert.match(await table.innerText(),/80,000원/);assert.match(await table.innerText(),/170,000원/);assert.doesNotMatch(await table.innerText(),/수원점/);
    await dialog.getByText('가게별 출처와 연결 기준',{exact:true}).click();
    await dialog.getByText('실행 SQL과 매개변수',{exact:true}).click();assert.match(await dialog.innerText(),/UNION ALL/);
    await shot('store-comparison-sql.png');await page.keyboard.press('Escape');
    const widget=page.locator('.react-grid-item').filter({has:page.getByRole('button',{name:title+' 수정·이력',exact:true})});
    await dialog.waitFor({state:'hidden'});
    const handle=widget.locator('.react-resizable-handle');await handle.scrollIntoViewIfNeeded();
    const box=await handle.boundingBox();assert.ok(box);const layout=response('/widgets/layout','PUT');
    await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();await page.mouse.move(box.x+box.width/2,box.y+box.height/2+120,{steps:10});await page.mouse.up();
    const lr=await layout;assert.ok(lr.ok());report.savedLayout=lr.request().postDataJSON().layouts.find(l=>l.id!==report.manual.id);
    await chat('방금 저장한 두 지점 비교 지표의 공통 기간을 지난달로 바꿔줘. 강남점과 홍대점만 그대로 비교하고 제목, 위치와 매시간 갱신은 유지해줘. 새 지표를 추가하지 말고 기존 지표를 수정해줘.');
    await nav.getByRole('button',{name:'대시보드',exact:true}).click();await page.getByRole('button',{name:title+' 집계표·SQL',exact:true}).click();
    table=dialog.getByRole('table',{name:'정확한 집계 결과'});assert.match(await table.innerText(),/60,000원/);assert.match(await table.innerText(),/40,000원/);
    await shot('store-comparison-edited.png');await page.keyboard.press('Escape');
    await chat('이번에는 강남점과 수원점 두 가게의 이번 달 순결제액을 같은 기준으로 가게별 비교 그래프로 미리보기만 해줘. 저장하지 마. 거래가 없는 가게도 선택 대상에서 빼지 말고 데이터 없음으로 남겨줘.');
    await page.getByRole('button',{name:/집계표·SQL$/}).last().click();table=dialog.getByRole('table',{name:'정확한 집계 결과'});
    assert.match(await table.innerText(),/수원점/);assert.match(await table.innerText(),/거래가 없습니다/);assert.equal(await table.locator('tbody tr').count(),2);
    await shot('empty-store-comparison.png');await page.keyboard.press('Escape');
    await nav.getByRole('button',{name:'대시보드',exact:true}).click();await page.getByRole('button',{name:title+' 수정·이력',exact:true}).waitFor();
    await shot('store-dashboard.png');await page.reload();await nav.getByRole('button',{name:'대시보드',exact:true}).click();
    await page.getByRole('button',{name:title+' 수정·이력',exact:true}).waitFor();assert.equal(await page.locator('.react-grid-item').count(),2);
    assert.deepEqual(report.errors,[]);report.passed=true;console.log('PASS: store selection, manual total, natural comparison/edit, empty store and reload');
  }catch(e){report.passed=false;report.failure=e.stack;await shot('browser-failure.png').catch(()=>{});throw e;}
  finally{await fs.writeFile(path.join(out,'browser.json'),JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
