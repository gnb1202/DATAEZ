// Public UI + API + real model. No routes, mocked responses or synthesized charts.
const { chromium } = require('../ui-eval/node_modules/playwright');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { openChat } = require('../ui-eval/workspace-helpers.cjs');

async function main() {
  const input = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
  const scenario = JSON.parse(await fs.readFile('docs/portfolio-demo/scenario.json', 'utf8'));
  const take = input.recording, project = take.project_id;
  const report = { passed:false, api_mocks:false, synthetic:true, started_at:new Date().toISOString(),
    source_commit:require('node:child_process').execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),
    site:input.site, project_id:project, file_id:take.file_id, table_id:take.table_id,
    stage:'baseline', queries:[], checks:[], page_error_count:0 };
  const checkpoint = () => fs.writeFile(path.join(input.out, 'rehearsal.json'), JSON.stringify(report,null,2)+'\n');
  const pass = async text => { report.checks.push(text); await checkpoint(); console.log('PASS '+text); };
  const request = async (route, options={}) => {
    const response = await fetch(input.api+route, {...options, headers:{ Authorization:'Bearer '+input.token, ...options.headers }});
    assert.ok(response.ok, `HTTP ${response.status} ${route}`);
    return response.json();
  };
  const widgets = async () => (await request('/api/dashboard/widgets?project_id='+project)).widgets;
  const ledger = () => request(`/api/projects/${project}/tables/${take.table_id}/data`);
  const daily = chart => Object.fromEntries(chart.data.map(row => [String(row[chart.x_key]).slice(0,10), String(row[chart.y_key])]));
  const checkChart = (chart, expected) => {
    assert.ok(chart.metric_definition, 'Missing recalculable definition');
    assert.equal(chart.chart_type, 'line'); assert.equal(chart.unit, 'KRW');
    assert.deepEqual(daily(chart), expected);
  };
  const browser = await chromium.launch({channel:'msedge', headless:true});
  const context = await browser.newContext({viewport:{width:1920,height:1080},locale:'ko-KR',reducedMotion:'reduce'});
  await context.addInitScript(()=>localStorage.setItem('theme','dark'));
  const page = await context.newPage(); page.setDefaultTimeout(30000);
  page.on('pageerror',()=>report.page_error_count++);
  const main = page.locator('#workspace-main');
  const response = (suffix, method='POST', timeout=90000) => {
    const pending=page.waitForResponse(r=>r.url().endsWith(suffix)&&r.request().method()===method,{timeout});
    pending.catch(()=>{}); return pending;
  };
  const json = async pending => { const r=await pending; assert.ok(r.ok(),`HTTP ${r.status()}`); return r.json(); };
  const screenshot = async name => {
    await page.evaluate(()=>document.fonts.ready);
    // Capture-time privacy mask only: the account label, never data or results.
    await page.screenshot({path:path.join(input.out,name+'.png'),
      mask:[page.getByRole('button',{name:'설정 및 계정',exact:true}).locator('span.text-\\[11px\\]')],
      maskColor:'#111418'});
  };
  try {
    await checkpoint();
    await page.goto(input.site);
    await page.getByLabel('이메일',{exact:true}).fill(input.email);
    await page.getByLabel('비밀번호',{exact:true}).fill(input.password);
    await page.locator('form button[type=submit]').click(); await page.waitForURL('**/dashboard');
    const selector=page.getByRole('combobox',{name:'현재 작업 가게'});
    await selector.selectOption(project);
    for (const prompt of scenario.prompts) {
      report.stage=prompt.id+'_select'; await checkpoint();
      await page.getByRole('button',{name:'새 분석',exact:true}).click();
      await page.getByRole('button',{name:'데이터 관리',exact:true}).click();
      await page.getByRole('button',{name:'파일 보관함',exact:true}).click();
      const filename='샘플_카페_매출.csv';
      const row=main.getByRole('article',{name:filename,exact:true});
      await row.getByRole('combobox',{name:filename+' 분석 범위',exact:true}).selectOption(prompt.scope);
      await row.getByRole('checkbox',{name:filename+' 분석에 선택',exact:true}).check();
      await main.getByRole('checkbox',{name:/파일별 분석 범위와 가게/}).check();
      await screenshot(prompt.id+'-library');
      await main.getByRole('button',{name:'선택한 파일을 채팅에 추가',exact:true}).click();
      await openChat(page);
      await page.getByRole('textbox',{name:'분석 요청',exact:true}).fill(prompt.text);
      const started=Date.now(), streamed=response('/messages/stream','POST',240000);
      report.stage=prompt.id+'_streaming'; await checkpoint();
      await page.getByRole('button',{name:'분석 요청 보내기',exact:true}).click();
      const stream=await streamed; assert.equal(stream.status(),200);
      const conversation=new URL(stream.url()).pathname.split('/')[3];
      const query={id:prompt.id,scope:prompt.scope,conversation_id:conversation};
      report.queries.push(query); await checkpoint();
      await page.waitForFunction(()=>!document.querySelector('[aria-label="분석 요청"]')?.disabled,null,{timeout:240000});
      query.elapsed_seconds=Number(((Date.now()-started)/1000).toFixed(2));
      const history=(await request('/api/conversations/'+conversation+'/messages')).messages;
      const result=history.at(-1); assert.equal(result.role,'assistant');
      await fs.writeFile(path.join(input.out,prompt.id+'-response.json'),JSON.stringify(result,null,2));
      const chartIndex=result.charts?.findIndex(c=>c.metric_definition);
      const chart=result.charts?.[chartIndex]; assert.ok(chart,'Expected a recalculable chart');
      const resultCard=main.locator('section[aria-label$=" 분석 결과"]').nth(chartIndex);
      query.chart_count=result.charts.length; query.selected_chart_index=chartIndex;
      assert.equal(result.charts.length,1,'A recalculable chart must not be duplicated as a static chart');
      checkChart(chart,scenario.expected.before.daily);
      query.message_id=result.message_id; query.daily=daily(chart);
      query.tool_names=(result.steps || []).map(step=>step.tool_name).filter(Boolean);
      query.token_usage=result.usage || null;
      query.token_usage_note='Null means not exposed by the persisted message API; no billing estimate.';
      query.scope_label=chart.scope_label; query.metric_definition=chart.metric_definition;
      assert.equal(chart.scope_label,prompt.scope==='original_file'?'파일 원본만':'누적 장부 전체');
      assert.equal((await widgets()).length,report.queries.length-1,'Model must not save automatically');
      await page.locator('#workspace-chat').getByRole('button',{name:/결과 보기/}).last().click();
      await main.locator('[data-chart-ready="true"] svg').first().waitFor();
      await screenshot(prompt.id+'-analysis');
      assert.ok(chart.execution?.sql, 'Expected server SQL evidence');
      await resultCard.getByRole('button',{name:/집계표·SQL$/}).first().click();
      const detail=page.getByRole('dialog');
      await detail.getByRole('table',{name:'정확한 집계 결과'}).waitFor();
      assert.equal(await detail.locator('tbody tr').count(),4);
      await detail.getByText('실행 SQL과 매개변수',{exact:true}).click();
      await screenshot(prompt.id+'-sql');
      await page.keyboard.press('Escape');
      await resultCard.getByRole('button',{name:'대시보드에 저장',exact:true}).click();
      await resultCard.getByLabel('저장 지표 이름',{exact:true}).fill(prompt.saved_title);
      await resultCard.getByLabel('저장 표시 단위',{exact:true}).selectOption('KRW');
      await resultCard.getByLabel('저장 갱신 주기',{exact:true}).selectOption('0');
      await resultCard.getByRole('button',{name:'설정으로 미리보기',exact:true}).click();
      await resultCard.getByLabel('저장 전 미리보기').waitFor();
      const saved=response('/api/projects/'+project+'/metrics');
      await resultCard.getByRole('button',{name:'이 설정으로 저장',exact:true}).click();
      const widget=await json(saved); query.widget_id=widget.id;
      report.stage=prompt.id+'_saved'; await checkpoint();
      await resultCard.getByRole('button',{name:'대시보드에서 보기',exact:true}).click();
      await main.locator('#dashboard-widget-'+widget.id).waitFor();
      await pass(`${prompt.id}: real LLM → exact daily values → manual preview/save (${query.elapsed_seconds}s)`);
    }
    const before=await ledger(); assert.equal(before.total_count,8);
    assert.equal(before.rows.reduce((total,row)=>total+BigInt(row.amount),0n).toString(),'690200');
    const appendBytes=await fs.readFile(scenario.append_fixture);
    report.append_sha256=crypto.createHash('sha256').update(appendBytes).digest('hex');
    report.stage='append_pending'; await checkpoint(); // Never retry an uncertain append.
    const form=new FormData(); form.append('file',new Blob([appendBytes]),'additional-transaction.csv');
    await request(`/api/projects/${project}/tables/${take.table_id}/append`,{method:'POST',body:form});
    const after=await ledger(); assert.equal(after.total_count,9);
    assert.equal(after.rows.reduce((total,row)=>total+BigInt(row.amount),0n).toString(),'720200');
    report.stage='appended_once'; report.ledger_rows=9; await checkpoint();
    for (const [i,query] of report.queries.entries()) {
      const pending=response('/metrics/'+query.widget_id+'/refresh');
      await main.locator('#dashboard-widget-'+query.widget_id).getByRole('button',{name:scenario.prompts[i].saved_title+' 재계산',exact:true}).click();
      const result=await json(pending);
      checkChart(result.widget_data,i===0?scenario.expected.before.daily:scenario.expected.after.ledger_daily);
      query.after_daily=daily(result.widget_data);
    }
    const original=await fetch(input.api+'/api/library/files/'+take.file_id+'/download',{headers:{Authorization:'Bearer '+input.token}});
    assert.ok(original.ok); const bytes=Buffer.from(await original.arrayBuffer());
    const digest=buffer=>crypto.createHash('sha256').update(buffer).digest('hex');
    report.original_sha256=digest(bytes);
    // Git may check out the reference CSV with CRLF on Windows; the service's
    // immutable sample is UTF-8/LF. Normalize the fixture, never the download.
    const reference=Buffer.from((await fs.readFile(scenario.original_fixture,'utf8')).replace(/\r\n/g,'\n'));
    assert.equal(report.original_sha256,digest(reference),'Original bytes changed');
    await pass('Append exactly once: ledger 9 rows / 720200; original remains 690200 after both refreshes');
    if(await page.locator('#workspace-chat-toggle').getAttribute('aria-expanded')==='true') await page.locator('#workspace-chat-toggle').click();
    await main.evaluate(el=>el.scrollTo(0,0));
    const first=main.locator('#dashboard-widget-'+report.queries[0].widget_id);
    const handle=first.locator('.widget-drag-handle');
    await handle.scrollIntoViewIfNeeded();
    const box=await handle.boundingBox(), card=await first.boundingBox();
    const layoutSaved=response('/api/dashboard/widgets/layout','PUT');
    await page.mouse.move(box.x+box.width/2,box.y+box.height/2); await page.mouse.down();
    await page.mouse.move(box.x+box.width/2+card.width+16,box.y+box.height/2,{steps:30}); await page.mouse.up();
    await json(layoutSaved);
    const savedWidgets=await widgets();
    assert.ok(savedWidgets.some(w=>w.layout.x>0),'Drag should create two columns');
    report.layouts=savedWidgets.map(w=>({id:w.id,layout:w.layout}));
    await page.reload(); await selector.waitFor(); assert.equal(await selector.inputValue(),project);
    await page.getByRole('button',{name:'대시보드',exact:true}).click();
    await main.locator('[data-chart-ready="true"] svg').first().waitFor();
    const reloaded=await widgets(); assert.deepEqual(reloaded.map(w=>({id:w.id,layout:w.layout})),report.layouts);
    await main.evaluate(el=>el.scrollTo(0,0));
    report.viewport=await main.locator('[id^="dashboard-widget-"]').evaluateAll(nodes=>nodes.map(el=>{const r=el.getBoundingClientRect();return {top:r.top,bottom:r.bottom,width:r.width};}));
    assert.ok(report.viewport.every(r=>r.top>=0&&r.bottom<=1080&&r.width>400),'Both charts must fit the first viewport');
    await screenshot('dashboard-dark');
    await page.getByRole('combobox',{name:'화면 테마'}).selectOption('light');
    await page.waitForFunction(()=>document.documentElement.classList.contains('light'));
    await screenshot('dashboard-light');
    await selector.selectOption(input.showcase.project_id);
    await main.locator('[id^="dashboard-widget-"]').first().waitFor();
    await page.waitForFunction(()=>document.querySelectorAll('[id^="dashboard-widget-"]').length===3);
    await selector.selectOption(project);
    await first.waitFor(); assert.equal(await main.locator('[id^="dashboard-widget-"]').count(),2);
    await pass('Real drag layout persisted across reload/store switching; both charts visible at 1920×1080, dark/light captured');
    assert.equal(report.page_error_count,0); report.passed=true; report.stage='complete';
  } catch(error) {
    report.failure={name:error.name,message:error.message.slice(0,1600)};
    await screenshot('failure').catch(()=>{});
    console.error('Stopped at '+report.stage+': '+error.message.slice(0,700)); process.exitCode=1;
  } finally {
    report.finished_at=new Date().toISOString(); await checkpoint(); await browser.close();
  }
}
main().catch(()=>{console.error('Rehearsal failed; inspect private checkpoint');process.exitCode=1;});
