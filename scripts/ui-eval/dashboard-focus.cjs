// Real Edge + Next.js; isolated API fixtures, no production data or model calls.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

async function main() {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const out = path.join(__dirname, '../../.local-test/dashboard-focus');
  await fs.mkdir(out, { recursive: true });
  const checks = [], errors = [], requests = [], writes = [];
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  page.setDefaultTimeout(20000);
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  const stores = [{ id: 'store-a', name: '성수점' }, { id: 'store-b', name: '연남점' }];
  let noStores = false;
  const table = { id: 'table-a', project_id: 'store-a', name: '결제 장부', row_count: 3, columns_schema: [{ name: 'amount', type: 'NUMERIC' }, { name: 'occurred_at', type: 'DATE' }] };
  const definition = { table_id: 'table-a', operation: 'sum', column: 'amount', time_range: 'all' };
  const data = { value: '690200', unit: 'KRW', period_label: '2026.09.01 – 2026.09.03', source_table_name: '결제 장부', calculated_at: '2026-09-18T00:00:00Z', metric_definition: definition };
  const chart = { ...data, chart_type: 'bar', x_key: 'dimension', y_key: 'value', data: [{ dimension: '09/01', value: '210000' }, { dimension: '09/02', value: '290000' }, { dimension: '09/03', value: '190200' }] };
  const widgets = [
    { id: 'kpi-a', widget_type: 'kpi', title: '전체 순결제액', widget_data: data, layout: { x: 0, y: 0, w: 4, h: 5 }, refresh_interval_seconds: 3600 },
    { id: 'chart-a', widget_type: 'chart', title: '일별 결제액', widget_data: chart, layout: { x: 4, y: 0, w: 8, h: 7 } },
  ];
  const base = (process.env.UI_BASE_URL || 'http://127.0.0.1:3140').replace(/\/$/, '');
  try {
    await page.route('**/api/**', async route => {
      const req = route.request(), url = new URL(req.url()), p = url.pathname, method = req.method();
      requests.push(`${method} ${p}`);
      let body = {}, status = 200;
      if (method === 'OPTIONS') {}
      else if (p === '/api/auth/refresh') body = { access_token: 'fixture', refresh_token: 'fixture' };
      else if (p === '/api/auth/me') body = { email: 'owner@example.test' };
      else if (p === '/api/projects' && method === 'POST') {
        const created = { id: 'store-created', name: req.postDataJSON().name };
        stores.push(created); noStores = false; body = created;
      }
      else if (p === '/api/projects') body = { projects: noStores ? [] : stores };
      else if (p === '/api/conversations') body = { conversations: [] };
      else if (p.endsWith('/tables')) body = { tables: p.includes('store-a') ? [table] : [] };
      else if (p.endsWith('/tables/table-a/data')) body = { data: [], total: 0, columns: ['amount', 'occurred_at'] };
      else if (p.endsWith('/ledger-sources')) body = { sources: p.includes('store-a') ? [{ id: 'source-a', table_id: 'table-a', name: '결제 장부', row_count: 3, storage_mode: 'canonical' }] : [] };
      else if (p.endsWith('/cash-entries')) body = { entries: [], total: 0 };
      else if (p.endsWith('/search-index')) body = { jobs: [], counts: {}, total: 0 };
      else if (p === '/api/library/files/sample-workspace') body = { project: null };
      else if (p === '/api/library/files') body = { files: [], total: 0 };
      else if (p === '/api/dashboard/widgets') body = { widgets: url.searchParams.get('project_id') === 'store-a' ? widgets : [] };
      else if (p.endsWith('/metrics/preview')) body = chart;
      else if (p.endsWith('/metrics') && method === 'POST') {
        const payload = req.postDataJSON(); writes.push(payload);
        const widget = { id: `created-${writes.length}`, title: payload.title, widget_type: 'kpi', widget_data: { ...data, metric_definition: payload.definition }, layout: { x: 0, y: 7, w: 4, h: 5 } };
        widgets.push(widget); body = widget;
      } else if (p.endsWith('/schedule')) body = { refresh_interval_seconds: req.postDataJSON().refresh_interval_seconds };
      else if (p.endsWith('/refresh')) body = { widget_data: data };
      else { status = 404; errors.push(`Unexpected request ${method} ${p}`); }
      await route.fulfill({ status, contentType: 'application/json', headers: { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*', 'access-control-allow-methods': '*' }, body: JSON.stringify(body) });
    });
    await page.addInitScript(() => localStorage.setItem('dataez_refresh_token', 'fixture'));
    const main = page.locator('#workspace-main');
    const nav = name => page.getByRole('navigation', { name: '작업 메뉴' }).getByRole('button', { name, exact: true });
    const cleanDashboard = async () => {
      await page.getByRole('heading', { name: '대시보드', exact: true }).waitFor();
      assert.equal(await main.locator('form').count(), 0);
      assert.equal(await main.getByText('샘플 데이터로 시작', { exact: true }).count(), 0);
      assert.equal(await page.locator('#workspace-chat-toggle').count(), 0);
      assert.equal(await page.locator('#workspace-chat').isVisible(), false);
    };
    await page.goto(base + '/dashboard');
    await main.locator('[data-chart-ready="true"]').waitFor();
    await cleanDashboard();
    assert((await main.locator('#dashboard-widget-chart-a').boundingBox()).y < 250);
    assert(!requests.some(req => req.includes('/sample-workspace')));
    checks.push('saved charts appear first; dashboard has no setup/forms/chat or sample API request');

    for (const width of [1440, 768, 390]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      for (const theme of ['dark', 'light']) {
        await page.getByRole('combobox', { name: '화면 테마' }).selectOption(theme);
        await main.locator('[data-chart-ready="true"]').waitFor();
        await page.waitForFunction(() => { const el = document.getElementById('workspace-main'); return el.scrollWidth <= el.clientWidth + 1; });
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
        await page.screenshot({ path: path.join(out, `dashboard-${width}-${theme}.png`) });
      }
    }
    await page.getByRole('button', { name: '작업 메뉴 열기' }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'AI 분석', exact: true }).click();
    await page.locator('#workspace-chat-toggle').click();
    await page.getByRole('textbox', { name: '분석 요청', exact: true }).fill('이번 달 매출 추이를 보여줘');
    await page.keyboard.press('Escape');
    await page.getByRole('button', { name: '작업 메뉴 열기' }).click();
    await page.getByRole('dialog').getByRole('button', { name: '대시보드', exact: true }).click();
    await cleanDashboard();
    checks.push('1440/768/390 dark/light: charts fit; mobile navigation and chat sheet work');

    await page.setViewportSize({ width: 1440, height: 1000 });
    await nav('AI 분석').click();
    await page.locator('#workspace-chat-toggle').click();
    assert.equal(await page.getByRole('textbox', { name: '분석 요청', exact: true }).inputValue(), '이번 달 매출 추이를 보여줘');
    await nav('대시보드').click();
    await cleanDashboard();
    await nav('AI 분석').click();
    assert.equal(await page.getByRole('textbox', { name: '분석 요청', exact: true }).inputValue(), '이번 달 매출 추이를 보여줘');
    checks.push('navigation hides chat outside analysis and preserves its draft');

    await page.getByRole('tab', { name: '직접 지표 만들기' }).click();
    assert.equal(await page.locator('#workspace-chat').isVisible(), false);
    await page.waitForURL('**view=metrics');
    await page.reload();
    await page.getByRole('tabpanel', { name: '직접 지표 만들기' }).waitFor();
    await main.getByText('갱신 가능한 지표 만들기', { exact: true }).click();
    const form = main.locator('form').first();
    await form.getByLabel('지표 이름', { exact: true }).fill('직접 만든 매출 합계');
    await form.getByLabel('장부', { exact: true }).selectOption('table-a');
    await form.getByLabel('숫자 컬럼', { exact: true }).selectOption('amount');
    await form.getByRole('button', { name: '계산하고 대시보드에 추가' }).click();
    await main.locator('#dashboard-widget-created-1').waitFor();
    await cleanDashboard();
    assert.equal(writes[0].definition.table_id, 'table-a');
    checks.push('manual builder tab survives reload; save returns to dashboard with new widget');

    await nav('데이터 관리').click();
    await page.getByRole('tab', { name: '시작 안내·샘플' }).click();
    await main.getByRole('button', { name: '샘플 데이터로 시작', exact: true }).waitFor();
    await page.waitForURL('**view=setup');
    await page.reload();
    await page.getByRole('tabpanel', { name: '시작 안내·샘플' }).waitFor();
    await page.screenshot({ path: path.join(out, 'data-setup.png') });
    const guide = page.getByLabel('첫 대시보드 안내', { exact: true });
    if (!(await guide.getAttribute('open') === '')) await guide.locator(':scope > summary').click();
    await guide.getByLabel('첫 지표 이름', { exact: true }).fill('안내에서 만든 첫 지표');
    await guide.getByRole('button', { name: '첫 지표 미리보기' }).click();
    await guide.getByRole('button', { name: '첫 지표 저장' }).click();
    await main.locator('#dashboard-widget-created-2').waitFor();
    await cleanDashboard();
    await nav('데이터 관리').click();
    await page.getByRole('tab', { name: '파일 보관함' }).click();
    await page.waitForURL('**view=files');
    await page.reload();
    await page.getByRole('tabpanel', { name: '파일 보관함' }).waitFor();
    checks.push('setup/sample and file library live under data management; guide preview/save works');

    await nav('대시보드').click();
    await page.getByRole('combobox', { name: '현재 작업 가게' }).selectOption('store-b');
    await main.getByText('저장한 지표가 아직 없습니다', { exact: true }).waitFor();
    await cleanDashboard();
    assert.equal(await main.locator('.react-grid-item').count(), 0);
    await main.getByRole('button', { name: '직접 지표 만들기', exact: true }).click();
    await main.getByText('갱신 가능한 지표 만들기', { exact: true }).click();
    await main.getByText('장부 관리에서 이 가게의 데이터를 먼저 등록해주세요.', { exact: true }).waitFor();
    checks.push('store switch isolates widgets and keeps empty-state actions usable');

    noStores = true;
    await page.goto(base + '/dashboard');
    await main.getByRole('button', { name: '가게와 데이터 준비하기' }).click();
    await main.getByRole('button', { name: '첫 가게 만들기' }).click();
    await page.getByRole('dialog').getByLabel('가게 이름', { exact: true }).waitFor();
    await page.getByRole('dialog').getByLabel('가게 이름', { exact: true }).fill('첫 가게');
    await page.getByRole('dialog').getByRole('button', { name: '만들기', exact: true }).click();
    await page.getByRole('tabpanel', { name: '시작 안내·샘플' }).waitFor();
    await main.getByRole('button', { name: '파일 연결·반영하러 가기', exact: true }).waitFor();
    assert.equal(await page.getByRole('combobox', { name: '현재 작업 가게' }).inputValue(), 'store-created');
    checks.push('new account creates its first store and continues setup');
    assert.deepEqual(errors, []);
    await fs.writeFile(path.join(out, 'receipt.json'), JSON.stringify({ passed: true, mode: 'real Edge UI with synthetic API fixtures; no live model', checks, errors }, null, 2));
    console.log(checks.map(check => `PASS ${check}`).join('\n'));
  } catch (error) {
    await page.screenshot({ path: path.join(out, 'failure.png') }).catch(() => {});
    await fs.writeFile(path.join(out, 'receipt.json'), JSON.stringify({ passed: false, checks, errors, failure: error.stack }, null, 2));
    throw error;
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
