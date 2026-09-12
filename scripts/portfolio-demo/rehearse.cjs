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
  if(input.final_qa)await assert.rejects(fs.access(path.join(input.out,'rehearsal.json')),{code:'ENOENT'},'Final QA take already attempted; inspect state instead of replaying');
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
  let storageState;
  if(input.record){
    const auth=await browser.newContext(); const login=await auth.newPage();
    await login.goto(input.site);
    await login.getByLabel('이메일',{exact:true}).fill(input.email);
    await login.getByLabel('비밀번호',{exact:true}).fill(input.password);
    await login.locator('form button[type=submit]').click(); await login.waitForURL('**/dashboard');
    await login.getByRole('combobox',{name:'현재 작업 가게'}).selectOption(project);
    storageState=await auth.storageState(); await auth.close();
  }
  const context = await browser.newContext({viewport:{width:1920,height:1080},locale:'ko-KR',reducedMotion:'reduce',
    ...(input.record?{storageState,recordVideo:{dir:path.join(input.out,'raw'),size:{width:1920,height:1080}}}:{})});
  if(input.record)await context.addInitScript(()=>{
    document.addEventListener('DOMContentLoaded',()=>{
      const style=document.createElement('style');
      style.textContent='[aria-label="설정 및 계정"] span.text-\\[11px\\]{visibility:hidden!important} #demo-pointer{position:fixed;width:20px;height:20px;border:2px solid #82b4ff;border-radius:50%;background:#82b4ff33;pointer-events:none;z-index:2147483647;transform:translate(-50%,-50%);left:-30px;top:-30px}';
      document.head.append(style);
      const pointer=document.createElement('div');pointer.id='demo-pointer';document.body.append(pointer);
      document.addEventListener('mousemove',e=>{pointer.style.left=e.clientX+'px';pointer.style.top=e.clientY+'px';});
      document.addEventListener('mousedown',()=>pointer.style.background='#82b4ffbb');
      document.addEventListener('mouseup',()=>pointer.style.background='#82b4ff33');
    });
  });
  const videoEpoch=Date.now(); report.recording=!!input.record; report.marks=[];
  const mark=async(name,hold=0)=>{if(input.record){report.marks.push({name,time:(Date.now()-videoEpoch)/1000});await checkpoint();if(hold)await new Promise(resolve=>setTimeout(resolve,hold*1000));}};
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
    if(input.record){await page.goto(input.site+'/dashboard');await page.waitForURL('**/dashboard');}else{
    await page.goto(input.site);
    await page.getByLabel('이메일',{exact:true}).fill(input.email);
    await page.getByLabel('비밀번호',{exact:true}).fill(input.password);
    await page.locator('form button[type=submit]').click(); await page.waitForURL('**/dashboard');
    }
    const selector=page.getByRole('combobox',{name:'현재 작업 가게'});
    await selector.selectOption(project);
    for (const prompt of scenario.prompts) {
      report.stage=prompt.id+'_select'; await checkpoint();
      await page.getByRole('button',{name:'새 분석',exact:true}).click();
      await page.getByRole('button',{name:'데이터 관리',exact:true}).click();
      await page.getByRole('button',{name:'파일 보관함',exact:true}).click();
      const filename=take.filename || '샘플_카페_매출.csv';
      const row=main.getByRole('article',{name:filename,exact:true});
      await row.waitFor(); await mark(prompt.id+'_library',3);
      if(input.record){await row.getByRole('button',{name:'미리보기',exact:true}).click();await main.getByLabel('파일 미리보기').scrollIntoViewIfNeeded();await mark(prompt.id+'_file_preview',4);await main.getByRole('button',{name:'미리보기 닫기',exact:true}).click();}
      await row.getByRole('combobox',{name:filename+' 분석 범위',exact:true}).selectOption(prompt.scope);
      await row.getByRole('checkbox',{name:filename+' 분석에 선택',exact:true}).check();
      await main.getByRole('checkbox',{name:/파일별 분석 범위와 가게/}).check();
      await mark(prompt.id+'_scope',3);await screenshot(prompt.id+'-library');
      await main.getByRole('button',{name:'선택한 파일을 채팅에 추가',exact:true}).click();
      await openChat(page);
      await page.getByRole('textbox',{name:'분석 요청',exact:true}).fill(prompt.text);
      await mark(prompt.id+'_question',4);
      const started=Date.now(), streamed=response('/messages/stream','POST',240000);
      report.stage=prompt.id+'_streaming'; await checkpoint();
      await mark(prompt.id+'_send');
      await page.getByRole('button',{name:'분석 요청 보내기',exact:true}).click();
      const stream=await streamed; assert.equal(stream.status(),200);
      const conversation=new URL(stream.url()).pathname.split('/')[3];
      const query={id:prompt.id,scope:prompt.scope,conversation_id:conversation};
      report.queries.push(query); await checkpoint();
      await page.waitForFunction(()=>!document.querySelector('[aria-label="분석 요청"]')?.disabled,null,{timeout:240000});
      await mark(prompt.id+'_answered');
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
      await mark(prompt.id+'_analysis',5);await screenshot(prompt.id+'-analysis');
      assert.ok(chart.execution?.sql, 'Expected server SQL evidence');
      await resultCard.getByRole('button',{name:/집계표·SQL$/}).first().click();
      const detail=page.getByRole('dialog');
      await detail.getByRole('table',{name:'정확한 집계 결과'}).waitFor();
      assert.equal(await detail.locator('tbody tr').count(),4);
      await mark(prompt.id+'_table',4);
      await detail.getByText('실행 SQL과 매개변수',{exact:true}).click();
      await mark(prompt.id+'_sql',5);await screenshot(prompt.id+'-sql');
      await page.keyboard.press('Escape');
      await mark(prompt.id+'_save_start');
      await resultCard.getByRole('button',{name:'대시보드에 저장',exact:true}).click();
      await resultCard.getByLabel('저장 지표 이름',{exact:true}).fill(prompt.saved_title);
      await resultCard.getByLabel('저장 표시 단위',{exact:true}).selectOption('KRW');
      await resultCard.getByLabel('저장 갱신 주기',{exact:true}).selectOption('0');
      await mark(prompt.id+'_settings',4);
      await resultCard.getByRole('button',{name:'설정으로 미리보기',exact:true}).click();
      await resultCard.getByLabel('저장 전 미리보기').waitFor();
      await mark(prompt.id+'_save_preview',4);
      const saved=response('/api/projects/'+project+'/metrics');
      await resultCard.getByRole('button',{name:'이 설정으로 저장',exact:true}).click();
      const widget=await json(saved); query.widget_id=widget.id;
      report.stage=prompt.id+'_saved'; await checkpoint();
      await resultCard.getByRole('button',{name:'대시보드에서 보기',exact:true}).click();
      await main.locator('#dashboard-widget-'+widget.id).waitFor();
      if((input.record || input.final_qa) && prompt.id==='Q1'){
        await page.locator('#workspace-chat-toggle').click(); await main.evaluate(el=>el.scrollTo(0,0));
        const w=main.locator('#dashboard-widget-'+widget.id);
        await mark('Q1_dashboard',4);
        const h=await w.locator('.react-resizable-handle-se').boundingBox(),b=await w.boundingBox();
        const resized=response('/api/dashboard/widgets/layout','PUT');await mark('Q1_resize');
        await page.mouse.move(h.x+h.width/2,h.y+h.height/2);await page.mouse.down();
        await page.mouse.move(h.x+h.width/2+b.width+16,h.y+h.height/2,{steps:60});await page.mouse.up();await json(resized);
        assert.equal((await widgets())[0].layout.w,12);
        await mark('Q1_resized',3);await page.reload();await selector.waitFor();
        await page.getByRole('button',{name:'대시보드',exact:true}).click();await w.waitFor();
        assert.equal((await widgets())[0].layout.w,12);await mark('Q1_complete',8);await screenshot('Q1-complete');
      }
      await pass(`${prompt.id}: real LLM → exact daily values → manual preview/save (${query.elapsed_seconds}s)`);
    }
    await mark('append_explained',4);
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
      await mark('refresh_'+query.id,2);
      const pending=response('/metrics/'+query.widget_id+'/refresh');
      await main.locator('#dashboard-widget-'+query.widget_id).getByRole('button',{name:scenario.prompts[i].saved_title+' 재계산',exact:true}).click();
      const result=await json(pending);
      checkChart(result.widget_data,i===0?scenario.expected.before.daily:scenario.expected.after.ledger_daily);
      query.after_daily=daily(result.widget_data);
      if(input.record){await main.locator('#dashboard-widget-'+query.widget_id).getByRole('button',{name:/집계표·SQL$/}).click();await mark('after_table_'+query.id,6);await screenshot('after-'+query.id);await page.keyboard.press('Escape');}
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
    if(input.record || input.final_qa){const h=await first.locator('.react-resizable-handle-se').boundingBox(),b=await first.boundingBox();const resized=response('/api/dashboard/widgets/layout','PUT');await page.mouse.move(h.x+h.width/2,h.y+h.height/2);await page.mouse.down();await page.mouse.move(h.x+h.width/2-(b.width+16)/2,h.y+h.height/2,{steps:60});await page.mouse.up();await json(resized);}
    await mark('pair_layout');
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
    await mark('pair_reload',3);await page.reload(); await selector.waitFor(); assert.equal(await selector.inputValue(),project);
    await page.getByRole('button',{name:'대시보드',exact:true}).click();
    await main.locator('[data-chart-ready="true"] svg').first().waitFor();
    const reloaded=await widgets(); assert.deepEqual(reloaded.map(w=>({id:w.id,layout:w.layout})),report.layouts);
    await main.evaluate(el=>el.scrollTo(0,0));
    report.viewport=await main.locator('[id^="dashboard-widget-"]').evaluateAll(nodes=>nodes.map(el=>{const r=el.getBoundingClientRect();return {top:r.top,bottom:r.bottom,width:r.width};}));
    assert.ok(report.viewport.every(r=>r.top>=0&&r.bottom<=1080&&r.width>400),'Both charts must fit the first viewport');
    await mark('pair_complete',8);await screenshot('dashboard-dark');
    await page.getByRole('combobox',{name:'화면 테마'}).selectOption('light');
    await page.waitForFunction(()=>document.documentElement.classList.contains('light'));
    await screenshot('dashboard-light');
    if(input.record)await page.getByRole('combobox',{name:'화면 테마'}).selectOption('dark');
    await mark('store_switch');await selector.selectOption(input.showcase.project_id);
    if(!input.final_qa)await main.locator('[id^="dashboard-widget-"]').first().waitFor();
    await page.waitForFunction(n=>document.querySelectorAll('[id^="dashboard-widget-"]').length===n,input.final_qa?0:3);
    await mark('showcase',5);await selector.selectOption(project);
    await first.waitFor();await mark('returned',5); assert.equal(await main.locator('[id^="dashboard-widget-"]').count(),2);
    await pass('Real drag layout persisted across reload/store switching; both charts visible at 1920×1080, dark/light captured');
    assert.equal(report.page_error_count,0); report.passed=true; report.stage='complete';
  } catch(error) {
    report.failure={name:error.name,message:error.message.slice(0,1600)};
    await screenshot('failure').catch(()=>{});
    console.error('Stopped at '+report.stage+': '+error.message.slice(0,700)); process.exitCode=1;
  } finally {
    await mark('end');report.finished_at=new Date().toISOString(); await context.close();
    if(input.record)report.video_path=await page.video().path();
    await checkpoint(); await browser.close();
  }
}
main().catch(()=>{console.error('Rehearsal failed; inspect private checkpoint');process.exitCode=1;});
