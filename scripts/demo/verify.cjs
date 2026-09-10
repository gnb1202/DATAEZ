// Real browser/API/DB/LLM acceptance. Invoked by verify.py --live-llm.
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { createRequire } = require('node:module');
const { chromium } = createRequire(path.resolve(__dirname, '../ui-eval/package.json'))('playwright');
const { openLatestAnalysis } = require('../ui-eval/workspace-helpers.cjs');
const [phase, out, ui, api] = process.argv.slice(2);
if (!['initial', 'resumed'].includes(phase) || !out || !ui || !api) throw Error('Use verify.py --live-llm');
const write = (name, value) => fs.writeFile(path.join(out, name), JSON.stringify(value, null, 2));
const read = async name => JSON.parse(await fs.readFile(path.join(out, name), 'utf8'));

async function main() {
  const browser = await chromium.launch({channel: process.env.DEMO_BROWSER_CHANNEL || 'msedge', headless: true});
  const context = await browser.newContext({viewport:{width:1600,height:1100}, reducedMotion:'reduce',
    ...(phase === 'resumed' ? {storageState: path.join(out, 'session.json')} : {})});
  const page = await context.newPage(); page.setDefaultTimeout(25000);
  const report = {phase, passed:false, api_mocks:false, checks:[], errors:[]};
  const pass = label => {report.checks.push(label); console.log('PASS: '+label);};
  let token;
  page.on('pageerror', e => report.errors.push(e.message));
  page.on('response', async r => {if (/\/api\/auth\/(login|refresh)$/.test(r.url()) && r.ok()) token = (await r.json()).access_token;});
  const request = async (route, options={}) => {
    const r = await fetch(api+route, {...options, headers:{Authorization:`Bearer ${token}`, ...options.headers}});
    assert.ok(r.ok, `${r.status} ${route}: ${await r.clone().text()}`); return r.json();
  };
  const post = (route, body) => request(route, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const pending = (suffix, method='POST', timeout=30000) => {
    const p = page.waitForResponse(r => r.url().endsWith(suffix) && r.request().method()===method, {timeout}); p.catch(()=>{}); return p;
  };
  const json = async p => {const r=await p; assert.ok(r.ok(), await r.text()); return r.json();};
  const shot = name => page.screenshot({path:path.join(out,name+'.png'),fullPage:true,animations:'disabled'});
  const dashboard = () => page.getByRole('button',{name:'대시보드',exact:true}).click();
  const guide = async () => {
    const details=page.getByLabel('첫 대시보드 안내');
    await details.waitFor({state:'attached'});
    const outer=page.getByText('지표 만들기·시작 안내',{exact:true});
    if (await outer.count() && await outer.locator('..').getAttribute('open')===null) await outer.click();
    if (await details.getAttribute('open')===null) await details.locator('summary').first().click();
  };
  const widgets = pid => request(`/api/dashboard/widgets?project_id=${pid}`);
  const mainView = page.locator('#workspace-main');
  let checkpoint = phase==='resumed' ? await read('checkpoint.json') : {};
  try {
    if (phase==='initial') {
      const account={name:'포트폴리오 데모',email:`demo-${crypto.randomUUID()}@example.test`,password:crypto.randomBytes(24).toString('base64url')+'Aa1!'};
      await post('/api/auth/signup',account); await write('access.json',account);
      await page.goto(ui);
      await page.getByLabel('이메일',{exact:true}).fill(account.email);
      await page.getByLabel('비밀번호',{exact:true}).fill(account.password);
      await page.locator('form button[type=submit]').click();
      await page.waitForURL('**/dashboard*');
      const presetResponse=pending('/sample-workspace/dashboard');
      await page.getByRole('button',{name:'예시 대시보드 보기',exact:true}).click();
      const preset=await json(presetResponse);
      checkpoint.project_id=preset.project.id; checkpoint.file_id=preset.file.file_id;
      checkpoint.table_id=preset.file.bindings[0].table_id;
      await mainView.locator('[id^="dashboard-widget-"]').first().waitFor();
      await mainView.getByText('690,200원',{exact:true}).waitFor();
      assert.equal((await widgets(checkpoint.project_id)).widgets.length,3);
      await guide();
      const replay=pending('/sample-workspace/dashboard');
      await page.getByRole('button',{name:'예시 대시보드 보기',exact:true}).click(); await json(replay);
      assert.equal((await widgets(checkpoint.project_id)).widgets.length,3);
      pass('Real login and preset dashboard; repeat creates exactly three widgets');
      await shot('preset-dashboard');
      await guide();
      await page.getByRole('button',{name:'샘플 데이터로 시작',exact:true}).click();
      const input=page.getByRole('textbox',{name:'분석 요청',exact:true}); await input.waitFor();
      assert.match(await input.inputValue(), /샘플 파일의 원본 행만/);
      assert.equal((await request(`/api/conversations?project_id=${checkpoint.project_id}`)).total,0);
      pass('Sample selects original file and drafts the question without automatically sending it');
      const stream=pending('/messages/stream','POST',300000);
      await page.getByRole('button',{name:'분석 요청 보내기',exact:true}).click();
      const r=await stream; assert.equal(r.status(),200);
      checkpoint.conversation_id=new URL(r.url()).pathname.split('/')[3];
      await page.waitForFunction(()=>!document.querySelector('[aria-label="분석 요청"]')?.disabled,null,{timeout:300000});
      const history=await request(`/api/conversations/${checkpoint.conversation_id}/messages`);
      const result=history.messages.at(-1);
      const chart=result.charts?.find(c=>c.metric_definition); assert.ok(chart,'LLM must return a recalculable chart');
      assert.deepEqual(chart.data.map(r=>[r.dimension,String(r.value)]),[
        ['2026-09-01','164500'],['2026-09-02','190000'],['2026-09-03','139800'],['2026-09-04','195900']]);
      assert.equal(chart.chart_type,'line');
      assert.equal(chart.scope_label,'파일 원본만');
      checkpoint.original_table_id=chart.metric_definition.table_id;
      assert.notEqual(checkpoint.original_table_id,checkpoint.table_id);
      checkpoint.title=chart.title;
      await mainView.getByRole('button',{name:`${chart.title} 집계표·SQL`,exact:true}).click();
      const dialog=page.getByRole('dialog');
      assert.match(await dialog.getByRole('table',{name:'정확한 집계 결과'}).innerText(),/190,000/);
      await dialog.getByText('실행 SQL과 매개변수',{exact:true}).click(); assert.match(await dialog.innerText(),/SELECT/);
      await shot('sample-sql'); await page.keyboard.press('Escape');
      pass('Real LLM creates exact signed daily amounts, original scope, line chart and inspectable SQL');
      await mainView.getByRole('button',{name:'대시보드에 저장',exact:true}).click();
      await mainView.getByLabel('저장 표시 단위',{exact:true}).selectOption('KRW');
      await mainView.getByLabel('저장 갱신 주기',{exact:true}).selectOption('0');
      await mainView.getByRole('button',{name:'설정으로 미리보기',exact:true}).click();
      await mainView.getByLabel('저장 전 미리보기').waitFor();
      const saved=pending(`/api/projects/${checkpoint.project_id}/metrics`);
      await mainView.getByRole('button',{name:'이 설정으로 저장',exact:true}).click();
      checkpoint.widget_id=(await json(saved)).id;
      await mainView.getByRole('button',{name:'대시보드에서 보기',exact:true}).click();
      const card=mainView.locator(`#dashboard-widget-${checkpoint.widget_id}`); await card.waitFor();
      const handle=card.locator('.react-resizable-handle'); await handle.scrollIntoViewIfNeeded();
      const box=await handle.boundingBox(); const resized=pending('/api/dashboard/widgets/layout','PUT');
      await page.mouse.move(box.x+box.width/2,box.y+box.height/2); await page.mouse.down();
      await page.mouse.move(box.x+box.width/2,box.y+box.height/2+80,{steps:12}); await page.mouse.up(); await json(resized);
      const append=new FormData(); append.append('file',new Blob(['paid_at,amount,method\n2026-09-05,30000,card\n']),'demo-additional.csv');
      await request(`/api/projects/${checkpoint.project_id}/tables/${checkpoint.table_id}/append`,{method:'POST',body:append});
      for (const [table,value] of [[checkpoint.original_table_id,'690200'],[checkpoint.table_id,'720200']]) {
        const preview=await post(`/api/projects/${checkpoint.project_id}/metrics/preview`,{definition:{table_id:table,column:'amount',unit:'KRW'}});
        assert.equal(preview.value,value);
      }
      checkpoint.widgets=(await widgets(checkpoint.project_id)).widgets;
      checkpoint.messages=history.messages;
      const raw=await fetch(api+`/api/library/files/${checkpoint.file_id}/download`,{headers:{Authorization:`Bearer ${token}`}}); assert.ok(raw.ok);
      checkpoint.file_hash=crypto.createHash('sha256').update(Buffer.from(await raw.arrayBuffer())).digest('hex');
      pass('UI saves/resizes the LLM metric; additional ledger transaction changes 690200 to 720200 while original stays fixed');
      await context.storageState({path:path.join(out,'session.json')}); await write('checkpoint.json',checkpoint);
      await shot('saved-dashboard');
    } else {
      await page.goto(ui+`/dashboard?project=${checkpoint.project_id}`);
      await page.locator('#workspace-main, form').first().waitFor();
      if (await page.getByLabel('이메일',{exact:true}).isVisible()) {
        const account=await read('access.json');
        await page.getByLabel('이메일',{exact:true}).fill(account.email);
        await page.getByLabel('비밀번호',{exact:true}).fill(account.password);
        await page.locator('form button[type=submit]').click();
        await page.waitForURL('**/dashboard*');
        await page.getByRole('combobox',{name:'현재 작업 가게'}).selectOption(checkpoint.project_id);
        report.reauthenticated=true;
      }
      await mainView.locator(`#dashboard-widget-${checkpoint.widget_id}`).waitFor();
      await mainView.getByText('690,200원',{exact:true}).waitFor();
      assert.deepEqual((await widgets(checkpoint.project_id)).widgets,checkpoint.widgets);
      assert.deepEqual((await request(`/api/conversations/${checkpoint.conversation_id}/messages`)).messages,checkpoint.messages);
      const raw=await fetch(api+`/api/library/files/${checkpoint.file_id}/download`,{headers:{Authorization:`Bearer ${token}`}}); assert.ok(raw.ok);
      assert.equal(crypto.createHash('sha256').update(Buffer.from(await raw.arrayBuffer())).digest('hex'),checkpoint.file_hash);
      await openLatestAnalysis(page);
      await mainView.getByRole('button',{name:`${checkpoint.title} 집계표·SQL`,exact:true}).waitFor();
      pass('After browser and all services restart: original bytes, conversation, metric definitions and layouts match');
      await dashboard(); await guide();
      const beforeRestart=(await request('/api/library/files/sample-workspace')).project.id;
      await page.getByRole('button',{name:'샘플 체험 다시 시작',exact:true}).click();
      const dialog=page.getByRole('dialog',{name:'새 샘플 가게에서 체험하기'});
      assert.match(await dialog.innerText(),/이전 샘플의 파일·대화·대시보드는 그대로/);
      await dialog.getByRole('button',{name:'취소',exact:true}).click();
      assert.equal((await request('/api/library/files/sample-workspace')).project.id,beforeRestart);
      await page.getByRole('button',{name:'샘플 체험 다시 시작',exact:true}).click();
      const restarted=pending('/sample-workspace/restart'); await dialog.getByRole('button',{name:'새 샘플 만들기',exact:true}).click();
      const fresh=await json(restarted); assert.notEqual(fresh.project.id,beforeRestart);
      await page.getByRole('textbox',{name:'분석 요청',exact:true}).waitFor();
      assert.equal((await widgets(fresh.project.id)).widgets.length,0);
      assert.deepEqual((await widgets(checkpoint.project_id)).widgets,checkpoint.widgets);
      assert.deepEqual((await request(`/api/conversations/${checkpoint.conversation_id}/messages`)).messages,checkpoint.messages);
      pass('Restart dialog cancellation is inert; confirmation opens a fresh sample and preserves previous saved work');
      await shot('fresh-sample');
      await page.goto(ui+`/dashboard?project=${checkpoint.project_id}`);
      await mainView.locator(`#dashboard-widget-${checkpoint.widget_id}`).waitFor();
      await shot('resumed-dashboard');
    }
    assert.deepEqual(report.errors,[]); report.passed=true;
  } catch(e) {report.errors.push(e.stack); await shot('failure-'+phase).catch(()=>{}); throw e;}
  finally {await context.storageState({path:path.join(out,'session.json')}); await write('report-'+phase+'.json',report); await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
