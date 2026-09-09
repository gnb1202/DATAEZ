const { openChat } = require('./workspace-helpers.cjs');
// Real browser and model acceptance; invoke via formula-charts-eval/run.py.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const out = process.env.LIVE_ARTIFACTS, ui = process.env.LIVE_UI_URL;
if (!out || !ui) throw new Error('Use scripts/formula-charts-eval/run.py');
(async () => {
  const input = JSON.parse(await fs.readFile(path.join(out, 'browser-input.json'), 'utf8'));
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } });
  page.setDefaultTimeout(45000);
  const report = { errors: [], api_mocks: false, chat: [] };
  page.on('pageerror', error => report.errors.push(error.message));
  const response = (suffix, method = 'POST') => { const pending = page.waitForResponse(r => r.url().endsWith(suffix) && r.request().method() === method, { timeout: 240000 }); pending.catch(() => {}); return pending; };
  async function json(promise) { const r = await promise; assert.ok(r.ok(), await r.text()); return r.json(); }
  const nav = page.getByRole('navigation', { name: '작업 메뉴' });
  async function chat(question) {
    await openChat(page);
    await page.locator('textarea').fill(question);
    const pending = response('/messages/stream');
    await page.locator('form button[type=submit]').click();
    const r = await pending; assert.equal(r.status(), 200);
    const stream = await r.text();
    assert.match(stream, /"type":\s*"done"/); assert.doesNotMatch(stream, /"type":\s*"error"/);
    report.chat.push({ question, stream });
    await page.waitForFunction(() => !document.querySelector('textarea')?.disabled);
  }
  async function screenshot(name) {
    await page.evaluate(() => Promise.all(document.getAnimations().filter(a => a.effect?.getTiming().iterations !== Infinity).map(a => a.finished.catch(() => {}))));
    await page.screenshot({ path: path.join(out, name), fullPage: true });
  }
  const title='주별 수수료 차감액';
  try {
    await page.goto(ui);
    await page.getByLabel('이메일', { exact: true }).fill(input.email);
    await page.getByLabel('비밀번호', { exact: true }).fill(input.password);
    await page.locator('form button[type=submit]').click();
    await page.waitForURL('**/dashboard');
    await chat(`검증 결제원장의 전체 기간 순결제액에서 PG 수수료 합계를 뺀 값을 주별 꺾은선 그래프로 만들고 대시보드에 저장해줘. occurred_at 기준이며 금액과 수수료는 원본 부호 그대로 합산해. 제목은 ${title}, 자동 갱신은 매시간으로 해줘.`);
    await nav.getByRole('button', { name: '대시보드', exact: true }).click();
    await page.getByRole('button', { name: title+' 집계표·SQL', exact: true }).click();
    const dialog=page.getByRole('dialog');
    let table=dialog.getByRole('table', { name:'정확한 집계 결과' });
    assert.match(await table.innerText(),/271,600원/);
    assert.match(await table.innerText(),/48,500원/);
    assert.match(await table.innerText(),/281,300원/);
    await dialog.getByText('실행 SQL과 매개변수', { exact:true }).click();
    assert.match(await dialog.innerText(),/UNION ALL/);
    assert.match(await dialog.innerText(),/Asia\/Seoul/);
    await screenshot('weekly-sql.png');
    await page.keyboard.press('Escape');
    const widget=page.locator('.react-grid-item').filter({has:page.getByRole('button',{name:title+' 수정·이력',exact:true})});
    const handle=widget.locator('.react-resizable-handle');
    const box=await handle.boundingBox(); assert.ok(box);
    const layout=response('/widgets/layout','PUT');
    await page.mouse.move(box.x+box.width/2,box.y+box.height/2); await page.mouse.down();
    await page.mouse.move(box.x+box.width/2,box.y+box.height/2+180,{steps:12}); await page.mouse.up();
    const layoutResponse=await layout;
    assert.ok(layoutResponse.ok(),await layoutResponse.text());
    report.savedLayout=layoutResponse.request().postDataJSON().layouts[0];
    await chat(`방금 저장한 ${title} 지표를 월별 막대그래프로 수정해줘. 양쪽 집계의 전체 기간과 부호 처리, 제목, 위치와 자동 갱신 주기는 유지하고 기존 지표를 수정해줘.`);
    await nav.getByRole('button', { name: '대시보드', exact: true }).click();
    await page.getByRole('button',{name:title+' 수정·이력',exact:true}).waitFor();
    await page.getByRole('button',{name:title+' 집계표·SQL',exact:true}).click();
    table=dialog.getByRole('table',{name:'정확한 집계 결과'});
    assert.match(await table.innerText(),/320,100원/); assert.match(await table.innerText(),/281,300원/);
    assert.equal(await table.locator('tbody tr').count(),2);
    await screenshot('monthly-table.png'); await page.keyboard.press('Escape');
    await chat('검증 결제원장의 전체 기간에 대해 occurred_at 기준 일별 금액 취소율을 재사용 가능한 꺾은선 그래프로 미리보기만 해줘. 분자는 각 날짜의 refund 금액 합계의 절댓값, 분모는 payment 금액 합계야. 취소 거래가 없는 날의 합계는 0으로 처리하고 승인 거래가 없는 날의 비율은 계산 불가로 남겨줘. 아직 저장하지 마.');
    await page.getByRole('button',{name:/집계표·SQL$/}).last().click();
    table=dialog.getByRole('table',{name:'정확한 집계 결과'});
    assert.match(await table.innerText(),/10\.0000%/);
    assert.match(await table.innerText(),/분모가 0/);
    assert.match(await table.innerText(),/0 적용/);
    await screenshot('ratio-gaps.png'); await page.keyboard.press('Escape');
    const pinned=response('/metrics');
    await page.getByRole('button',{name:'대시보드에 고정',exact:true}).last().click();
    report.pinned=await json(pinned); assert.equal(report.pinned.widget_data.metric_definition.version,4);
    await nav.getByRole('button',{name:'대시보드',exact:true}).click();
    await page.getByRole('button',{name:title+' 수정·이력',exact:true}).waitFor();
    await screenshot('formula-charts-dashboard.png');
    await page.reload();
    await nav.getByRole('button',{name:'대시보드',exact:true}).click();
    await page.getByRole('button',{name:title+' 수정·이력',exact:true}).waitFor();
    assert.equal(await page.locator('.react-grid-item').count(),2);
    assert.deepEqual(report.errors,[]); report.passed=true;
    console.log('PASS: weekly save, SQL detail, resize, monthly edit, ratio gaps, pin and reload');
  } catch(err) { report.passed=false; report.failure=err.stack; await screenshot('browser-failure.png').catch(()=>{}); throw err; }
  finally { await fs.writeFile(path.join(out,'browser.json'),JSON.stringify(report,null,2)); await browser.close(); }
})().catch(err=>{console.error(err);process.exitCode=1;});
