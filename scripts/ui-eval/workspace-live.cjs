// Invoked by workspace-live.py; all requests reach the real API. No route mocks.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { openChat, openLatestAnalysis } = require('./workspace-helpers.cjs');
const out = process.env.LIVE_ARTIFACTS, ui = process.env.LIVE_UI_URL, api = process.env.NEXT_PUBLIC_API_URL;
const phase = process.argv[2];
if (!out || !ui || !api) throw new Error('Use workspace-live.py --live-llm');

async function main() {
  const input = JSON.parse(await fs.readFile(path.join(out, 'browser-input.json'), 'utf8'));
  const checkpoint = phase === 'resumed' ? JSON.parse(await fs.readFile(path.join(out, 'checkpoint.json'), 'utf8')) : {};
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1100 }, reducedMotion: 'reduce',
    ...(phase === 'resumed' ? { storageState: path.join(out, 'session.json') } : {}) });
  const page = await context.newPage();
  page.setDefaultTimeout(20000);
  const report = { phase, passed: false, api_mocks: false, checks: [], errors: [], turns: [] };
  const pass = label => { report.checks.push(label); console.log('PASS: ' + label); };
  page.on('pageerror', error => report.errors.push(error.message));
  let accessToken;
  page.on('response', async r => {
    if (/\/api\/auth\/(login|refresh)$/.test(r.url()) && r.ok()) accessToken = (await r.json()).access_token;
  });
  const main = page.locator('#workspace-main');
  const response = (suffix, method = 'POST', timeout = 25000) => {
    const promise = page.waitForResponse(r => r.url().endsWith(suffix) && r.request().method() === method, { timeout });
    promise.catch(() => {}); return promise;
  };
  const json = async pending => { const r = await pending; assert.ok(r.ok(), `${r.status()}: ${await r.text()}`); return r.json(); };
  const request = async (route, options = {}) => {
    const r = await fetch(api + route, { ...options, headers: { Authorization: `Bearer ${accessToken}`, ...options.headers } });
    assert.ok(r.ok, `${r.status} ${route}: ${await r.clone().text()}`);
    return r.json();
  };
  const widgets = () => request(`/api/dashboard/widgets?project_id=${input.project_id}`);
  const screenshot = async name => {
    await page.screenshot({ path: path.join(out, name + '.png'), animations: 'disabled', fullPage: true });
  };
  async function ask(question) {
    await openChat(page);
    await page.getByRole('textbox', { name: '분석 요청', exact: true }).fill(question);
    const pending = response('/messages/stream', 'POST', 300000);
    await page.getByRole('button', { name: '분석 요청 보내기', exact: true }).click();
    console.log('LLM: ' + question, { phase });
    const r = await pending;
    assert.equal(r.status(), 200);
    // Chromium can discard completed SSE response bodies. Read the persisted
    // result only after the actual UI finishes receiving the stream; subsequent
    // checks require that same result to be visible and usable in the browser.
    await page.waitForFunction(() => !document.querySelector('[aria-label="분석 요청"]')?.disabled, null, { timeout: 300000 });
    const conversation = new URL(r.url()).pathname.split('/')[3];
    const history = (await request(`/api/conversations/${conversation}/messages`)).messages;
    const result = history.at(-1), questionMessage = history.at(-2);
    assert.equal(result?.role, 'assistant');
    assert.equal(questionMessage?.content, question);
    report.turns.push({ question, result });
    return result;
  }
  async function showResult(result) {
    await page.locator('#workspace-chat').getByRole('button', { name: /결과 보기/ }).last().click();
    await main.getByRole('button', { name: `${result.charts[0].title} 집계표·SQL`, exact: true }).waitFor();
    await main.locator('[data-chart-ready="true"] svg').first().waitFor();
  }
  function values(chart) {
    return chart.data.map(row => [String(row[chart.x_key]).slice(0, 10), String(row[chart.y_key])]);
  }
  async function exactTable(title, amounts) {
    await main.getByRole('button', { name: `${title} 집계표·SQL`, exact: true }).click();
    const dialog = page.getByRole('dialog');
    const text = await dialog.getByRole('table', { name: '정확한 집계 결과' }).innerText();
    for (const amount of amounts) assert.ok(text.includes(amount), `${amount} missing: ${text}`);
    await dialog.getByText('실행 SQL과 매개변수', { exact: true }).click();
    assert.match(await dialog.innerText(), /SELECT/i);
    return dialog;
  }
  try {
    await page.goto(phase === 'resumed' ? ui + '/dashboard' : ui);
    if (phase === 'initial') {
      await page.getByLabel('이메일', { exact: true }).fill(input.email);
      await page.getByLabel('비밀번호', { exact: true }).fill(input.password);
      await page.locator('form button[type=submit]').click();
      await page.waitForURL('**/dashboard');
    }
    await page.getByRole('combobox', { name: '현재 작업 가게' }).selectOption(input.project_id);
    if (phase === 'initial') {
      await page.getByRole('button', { name: '데이터 관리', exact: true }).click();
      await page.getByRole('button', { name: '파일 보관함', exact: true }).click();
      const upload = response('/api/library/files');
      await page.getByLabel('보관할 파일', { exact: true }).setInputFiles(path.join(out, input.filename));
      const file = await json(upload); checkpoint.file_id = file.file_id;
      const row = main.getByRole('article', { name: input.filename, exact: true });
      await row.getByRole('button', { name: '미리보기', exact: true }).click();
      await main.getByText('100000.01', { exact: true }).waitFor();
      const preparation = response(`/api/library/files/${file.file_id}/prepare`);
      await main.getByRole('button', { name: '검사한 파일을 분석에 연결', exact: true }).click();
      const ready = await json(preparation); checkpoint.table_id = ready.bindings[0].table_id;
      await row.getByText('분석 가능', { exact: true }).waitFor();
      await screenshot('live-library');
      pass('Real login, original upload, exact preview and one-time ledger preparation');

      await page.getByRole('button', { name: '새 분석', exact: true }).click();
      const discovery = await ask('보관함에서 성수점_9월_매출.csv 파일을 찾아줘. 파일 후보만 알려주고 아직 분석하거나 새로 가져오지는 마.');
      assert.ok(discovery.steps.some(s => s.tool_name === 'search_library_files' && s.tool_output.files?.some(f => f.file_id === checkpoint.file_id)));
      await page.locator('#workspace-chat').getByRole('button', { name: /성수점_9월_매출.csv.*확인하고 선택/ }).click();
      const picker = page.getByRole('dialog', { name: '보관함에서 파일 선택' });
      await picker.getByRole('combobox', { name: `${input.filename} 분석 범위`, exact: true }).selectOption('linked_ledger');
      await picker.getByRole('checkbox', { name: `${input.filename} 분석에 선택`, exact: true }).check();
      await picker.getByRole('checkbox', { name: /파일별 분석 범위와 가게/ }).check();
      await picker.getByRole('button', { name: '선택한 파일로 분석', exact: true }).click();
      pass('Real LLM file discovery leads to explicit library/whole-ledger selection');

      const result = await ask('선택한 성수점 파일에 연결된 장부 전체에서 paid_at 발생일별 amount 합계를 꺾은선 그래프로 미리 보여줘. 원화 금액이며 음수 취소는 원본 부호대로 합산해. 기간은 장부 전체 기간이고 다른 장부는 제외해. 나중에 새 거래를 반영해 다시 계산할 수 있는 지표로 준비하되, 아직 대시보드에 저장하지 마.');
      assert.equal((await widgets()).widgets.length, 0);
      const chart = result.charts.find(c => c.metric_definition);
      assert.ok(chart, 'Natural-language preview must carry a reusable definition');
      assert.equal(chart.chart_type, 'line');
      assert.equal(chart.metric_definition.table_id, checkpoint.table_id);
      assert.deepEqual(values(chart), [['2026-09-01', '100000.01'], ['2026-09-02', '150000.02'], ['2026-09-03', '80000.03']]);
      assert.equal(result.steps.find(s => s.tool_name === 'library_references').tool_output.files[0].file_id, checkpoint.file_id);
      await showResult(result);
      await exactTable(chart.title, ['100,000.01', '150,000.02', '80,000.03']);
      await screenshot('live-execution-sql'); await page.keyboard.press('Escape');
      await screenshot('live-analysis');
      pass('Real LLM produces scoped SQL/line chart with exact signed decimals and no save');

      await main.getByRole('button', { name: '대시보드에 저장', exact: true }).click();
      await main.getByLabel('저장 표시 단위', {exact:true}).selectOption('KRW');
      await main.getByLabel('저장 갱신 주기', {exact:true}).selectOption('3600');
      await main.getByRole('button', {name:'설정으로 미리보기',exact:true}).click();
      await main.getByLabel('저장 전 미리보기').waitFor();
      await screenshot('live-save-settings');
      const saved = response(`/api/projects/${input.project_id}/metrics`);
      await main.getByRole('button', {name:'이 설정으로 저장',exact:true}).click();
      const widget = await json(saved); checkpoint.widget_id = widget.id; checkpoint.title = chart.title;
      await main.getByRole('button', { name: '대시보드에서 보기', exact: true }).click();
      const card = main.locator(`#dashboard-widget-${widget.id}`);
      await card.waitFor();
      const schedule = response(`/metrics/${widget.id}/schedule`, 'PATCH');
      await card.getByRole('combobox', { name: `${chart.title} 갱신 주기` }).selectOption('3600');
      await json(schedule);
      const handle = card.locator('.react-resizable-handle');
      await handle.scrollIntoViewIfNeeded(); const box = await handle.boundingBox();
      const layout = response('/api/dashboard/widgets/layout', 'PUT');
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await page.mouse.down();
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2 + 80, { steps: 12 }); await page.mouse.up();
      await json(layout);
      checkpoint.layout = (await widgets()).widgets[0].layout;
      const append = new FormData(); append.append('file', new Blob(['paid_at,amount,method\n2026-09-02,25000.04,카드\n']), 'manual-append.csv');
      await request(`/api/projects/${input.project_id}/tables/${checkpoint.table_id}/append`, { method: 'POST', body: append });
      const refresh = response(`/metrics/${widget.id}/refresh`);
      await card.getByRole('button', { name: `${chart.title} 재계산`, exact: true }).click();
      const recalculated = await json(refresh);
      assert.deepEqual(values(recalculated.widget_data), [['2026-09-01', '100000.01'], ['2026-09-02', '175000.06'], ['2026-09-03', '80000.03']]);
      await exactTable(chart.title, ['175,000.06']); await page.keyboard.press('Escape');
      pass('Real save, schedule, resize and public-API append → manual recalculation');
      await page.reload();
      await page.getByRole('button', { name: '대시보드', exact: true }).click();
      await main.locator(`#dashboard-widget-${widget.id}`).waitFor();
      assert.deepEqual((await widgets()).widgets[0].layout, checkpoint.layout);
      await openLatestAnalysis(page);
      await main.getByRole('button', { name: '대시보드에서 보기', exact: true }).waitFor();
      assert.equal(await page.locator('[aria-label="선택한 보관 파일"] button').count(), 1);
      assert.equal((await widgets()).widgets.length, 1);
      pass('Reload restores source selection, saved state and resized layout without duplicates');
      await fs.writeFile(path.join(out, 'checkpoint.json'), JSON.stringify(checkpoint, null, 2));
      await context.storageState({ path: path.join(out, 'session.json') });
    } else {
      await page.getByRole('button', { name: '대시보드', exact: true }).click();
      await main.locator(`#dashboard-widget-${checkpoint.widget_id}`).waitFor();
      assert.deepEqual((await widgets()).widgets[0].layout, checkpoint.layout);
      await exactTable(checkpoint.title, ['100,000.01', '175,000.06', '85,000.08']);
      await screenshot('live-refreshed-sql'); await page.keyboard.press('Escape');
      await main.evaluate(el => el.scrollTo({ top: 0, left: 0 }));
      await screenshot('live-dashboard-dark');
      await page.getByRole('combobox', { name: '화면 테마' }).selectOption('light');
      await page.waitForFunction(() => [...document.querySelectorAll('[data-chart-engine] svg path')].some(p => getComputedStyle(p).stroke === 'rgb(36, 91, 181)'));
      await screenshot('live-dashboard-light');
      pass('New browser after API restart shows the actual scheduler result, layout and both themes');

      await openLatestAnalysis(page);
      assert.equal(await page.locator('[aria-label="선택한 보관 파일"] button').count(), 1);
      const followup = await ask('새 거래가 추가되었으니 현재 선택한 성수점 파일의 연결 장부 전체에서 amount 전체 합계를 다시 조회해서 표로 보여줘. 음수 취소를 유지하고 다른 장부는 제외해. 기존 대시보드 지표를 추가로 저장하지 마. 원본 파일에 있던 행만의 합계와 혼동하지 말아줘.');
      assert.ok(followup.table_data?.some(row => Object.values(row).some(value => String(value) === '360000.15')), 'Follow-up must read the updated full ledger');
      await page.locator('#workspace-chat').getByRole('button', { name: /결과 보기/ }).last().click();
      await main.getByText('360000.15', { exact: true }).waitFor();
      await screenshot('live-followup');
      assert.equal((await widgets()).widgets.length, 1);
      pass('Follow-up uses restored file context and current cumulative ledger without saving again');

      await page.getByRole('button', { name: '새 분석', exact: true }).click();
      await page.getByRole('button', { name: '보관함에서 선택', exact: true }).click();
      const picker = page.getByRole('dialog', { name: '보관함에서 파일 선택' });
      await picker.getByRole('button', { name: '내 계정 전체', exact: true }).click();
      await picker.getByRole('combobox', { name: '연남점_매출.csv 분석 범위', exact: true }).selectOption('linked_ledger');
      await picker.getByRole('checkbox', { name: '연남점_매출.csv 분석에 선택', exact: true }).check();
      await picker.getByRole('checkbox', { name: /파일별 분석 범위와 가게/ }).check();
      await picker.getByRole('button', { name: '선택한 파일로 분석', exact: true }).click();
      const external = await ask('이번에 선택한 연남점 파일의 연결 장부에서 amount 전체 합계만 표로 보여줘. 성수점 자료는 포함하지 말고, 대시보드 저장은 하지 마.');
      assert.ok(external.table_data?.some(row => Object.values(row).some(value => String(value) === '54321.09')));
      assert.equal(external.steps.find(s => s.tool_name === 'library_references').tool_output.files[0].project_id, input.other_project_id);
      assert.equal(await page.getByRole('combobox', { name: '현재 작업 가게' }).inputValue(), input.project_id);
      await page.locator('#workspace-chat').getByRole('button', { name: /결과 보기/ }).last().click();
      await main.getByText('54321.09', { exact: true }).waitFor();
      await screenshot('live-other-store');
      pass('Explicit other-store selection scopes the real model query without switching workspace');

      await page.getByRole('button', {name:'새 분석',exact:true}).click();
      await page.getByRole('button', {name:'보관함에서 선택',exact:true}).click();
      await picker.getByRole('checkbox', {name:`${input.filename} 분석에 선택`,exact:true}).check();
      assert.equal(await picker.getByRole('combobox',{name:`${input.filename} 분석 범위`,exact:true}).inputValue(),'original_file');
      await picker.getByRole('checkbox',{name:/파일별 분석 범위와 가게/}).check();
      await picker.getByRole('button',{name:'선택한 파일로 분석',exact:true}).click();
      const original = await ask('선택한 파일 원본의 paid_at 날짜별 amount 합계를 원화 꺾은선 그래프로 미리 보여줘. 전체 기간과 음수 취소를 그대로 유지하고 연결 장부의 추가 거래는 제외해. 재계산 가능한 지표로 준비하되 아직 저장하지 마.');
      const originalChart = original.charts.find(c=>c.metric_definition);
      assert.ok(originalChart);
      assert.notEqual(originalChart.metric_definition.table_id,checkpoint.table_id);
      assert.deepEqual(values(originalChart),[['2026-09-01','100000.01'],['2026-09-02','150000.02'],['2026-09-03','80000.03']]);
      assert.equal(originalChart.scope_label,'파일 원본만');
      await showResult(original);
      await main.getByRole('button',{name:'대시보드에 저장',exact:true}).click();
      await main.getByLabel('저장 지표 이름',{exact:true}).fill('원본 파일 일별 매출');
      await main.getByLabel('저장 표시 단위',{exact:true}).selectOption('KRW');
      await main.getByRole('button',{name:'설정으로 미리보기',exact:true}).click();
      await main.getByLabel('저장 전 미리보기').waitFor();
      await screenshot('live-original-settings');
      const originalSave=response(`/api/projects/${input.project_id}/metrics`);
      await main.getByRole('button',{name:'이 설정으로 저장',exact:true}).click();
      const originalWidget=await json(originalSave);
      assert.equal(originalWidget.widget_data.scope_label,'파일 원본만');
      await main.getByRole('button',{name:'대시보드에서 보기',exact:true}).click();
      const originalCard=main.locator(`#dashboard-widget-${originalWidget.id}`);
      const originalRefresh=response(`/metrics/${originalWidget.id}/refresh`);
      await originalCard.getByRole('button',{name:'원본 파일 일별 매출 재계산',exact:true}).click();
      assert.deepEqual(values((await json(originalRefresh)).widget_data),values(originalChart));
      await page.reload();
      await main.locator(`#dashboard-widget-${originalWidget.id}`).getByText(/파일 원본만/).first().waitFor();
      assert.equal((await widgets()).widgets.length,2);
      pass('Original-file model analysis excludes appended ledger rows; edited name/unit/manual schedule and scope survive save/refresh/reload');

      await page.getByRole('combobox',{name:'현재 작업 가게'}).selectOption(input.other_project_id);
      await page.getByRole('button',{name:'대시보드',exact:true}).click();
      await main.getByRole('button',{name:'샘플 데이터로 시작',exact:true}).click();
      await page.getByLabel('분석 요청',{exact:true}).waitFor();
      const sampleProject=await page.getByRole('combobox',{name:'현재 작업 가게'}).inputValue();
      assert.notEqual(sampleProject,input.project_id); assert.notEqual(sampleProject,input.other_project_id);
      const sampleQuestion=await page.getByLabel('분석 요청',{exact:true}).inputValue();
      assert.match(sampleQuestion,/샘플 파일.*원본/);
      assert.match(await page.getByLabel('선택한 보관 파일').innerText(),/파일 원본만/);
      await screenshot('live-sample-start');
      const sampleResult=await ask(sampleQuestion);
      const sampleChart=sampleResult.charts.find(c=>c.metric_definition);
      assert.ok(sampleChart);assert.equal(sampleChart.scope_label,'파일 원본만');
      assert.deepEqual(sampleChart.data.map(row=>String(row[sampleChart.y_key])),['164500','190000','139800','195900']);
      await showResult(sampleResult);
      await main.getByRole('button',{name:'대시보드에 저장',exact:true}).click();
      await main.getByLabel('저장 지표 이름',{exact:true}).fill('샘플 카페 일별 매출');
      await main.getByLabel('저장 표시 단위',{exact:true}).selectOption('KRW');
      await main.getByLabel('저장 갱신 주기',{exact:true}).selectOption('86400');
      await main.getByRole('button',{name:'설정으로 미리보기',exact:true}).click();
      await main.getByLabel('저장 전 미리보기').waitFor();
      const sampleSave=response(`/api/projects/${sampleProject}/metrics`);
      await main.getByRole('button',{name:'이 설정으로 저장',exact:true}).click();
      const sampleWidget=await json(sampleSave);
      assert.equal(sampleWidget.refresh_interval_seconds,86400);
      await main.getByRole('button',{name:'대시보드에서 보기',exact:true}).click();
      await main.locator(`#dashboard-widget-${sampleWidget.id}`).waitFor();
      await screenshot('live-sample-dashboard');
      assert.equal((await widgets()).widgets.length,2);
      pass('First-use button creates a separate sample store and original-file question; actual model chart saves with reviewed title/unit/24-hour refresh');

    }
    assert.deepEqual(report.errors, []); report.passed = true;
  } catch (error) {
    report.failure = error.stack;
    await screenshot(`failure-${phase}`).catch(() => {});
    throw error;
  } finally {
    await fs.writeFile(path.join(out, `browser-${phase}.json`), JSON.stringify(report, null, 2));
    await browser.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
