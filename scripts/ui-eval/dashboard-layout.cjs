// Real browser interactions against Next.js with a persistent in-memory API fixture.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

async function main() {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const out = path.join(__dirname, '../../.local-test/dashboard-layout');
  await fs.mkdir(out, { recursive: true });
  const report = { checks: [], errors: [], fixtureOnly: true };
  const page = await browser.newPage({ viewport: { width: 1600, height: 1100 }, reducedMotion: 'reduce' });
  page.setDefaultTimeout(15000);
  page.on('pageerror', error => report.errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') report.errors.push(message.text()); });
  const chart = { chart_type: 'bar', x_key: 'day', y_key: 'amount', data: [{ day: '09/18', amount: '30000' }], unit: 'KRW' };
  const widgets = [
    { id: 'chart-a', title: '현금 매출', widget_type: 'chart', widget_data: chart, layout: { x: 0, y: 0, w: 6, h: 4 } },
    { id: 'chart-b', title: '카드 매출', widget_type: 'chart', widget_data: chart, layout: { x: 6, y: 0, w: 6, h: 4 } },
  ];
  let writes = 0;
  await page.route('**/api/**', async route => {
    const req = route.request(), url = new URL(req.url()), p = url.pathname;
    let body = {}, status = 200;
    if (req.method() === 'OPTIONS') {}
    else if (p === '/api/auth/refresh') body = { access_token: 'fixture', refresh_token: 'fixture' };
    else if (p === '/api/auth/me') body = { email: 'owner@example.test' };
    else if (p === '/api/projects') body = { projects: [{ id: 'store-a', name: '성수점' }] };
    else if (p === '/api/conversations') body = { conversations: [] };
    else if (p.endsWith('/tables')) body = { tables: [] };
    else if (p.endsWith('/ledger-sources')) body = { sources: [] };
    else if (p === '/api/dashboard/widgets/layout') {
      writes++;
      for (const item of req.postDataJSON().layouts) widgets.find(w => w.id === item.id).layout = item.layout;
      body = { status: 'ok' };
    } else if (p === '/api/dashboard/widgets') body = { widgets };
    else { status = 404; report.errors.push(`Unexpected request: ${p}`); }
    await route.fulfill({ status, contentType: 'application/json', headers: { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*', 'access-control-allow-methods': '*' }, body: JSON.stringify(body) });
  });
  await page.addInitScript(() => localStorage.setItem('dataez_refresh_token', 'fixture'));
  const a = page.locator('#dashboard-widget-chart-a'), b = page.locator('#dashboard-widget-chart-b');
  const waitLayout = async () => {
    await a.waitFor(); await b.waitFor();
    await page.waitForFunction(() => document.querySelectorAll('[data-chart-ready="true"]').length === 2);
    // Read after the grid's transform transition and responsive remount settle.
    await page.waitForFunction(() => !document.getAnimations().some(a => a.playState === 'running' && a.effect?.getTiming().iterations !== Infinity));
  };
  const top = locator => locator.evaluate(node => node.offsetTop + new DOMMatrix(getComputedStyle(node).transform).m42);
  const saved = () => JSON.parse(JSON.stringify(widgets.map(w => w.layout)));
  const assertNoOverlap = async () => {
    const [first, second] = await Promise.all([a.boundingBox(), b.boundingBox()]);
    assert.ok(first.x + first.width <= second.x + 1 || second.x + second.width <= first.x + 1 || first.y + first.height <= second.y + 1 || second.y + second.height <= first.y + 1, 'widgets must not overlap');
  };
  const drag = async (locator, dx, dy) => {
    const handle = locator.locator('.widget-drag-handle');
    await handle.scrollIntoViewIfNeeded();
    const rect = await handle.boundingBox();
    await page.mouse.move(rect.x + rect.width / 2, rect.y + rect.height / 2);
    await page.mouse.down();
    await page.mouse.move(rect.x + rect.width / 2 + dx, rect.y + rect.height / 2 + dy, { steps: 18 });
    await page.mouse.up();
    await waitLayout();
  };
  try {
    await page.goto((process.env.UI_BASE_URL || 'http://127.0.0.1:3140') + '/dashboard');
    await waitLayout();
    assert.equal(writes, 0);
    const initialTop = await top(a);
    const nextSave = page.waitForResponse(r => r.url().endsWith('/widgets/layout') && r.request().method() === 'PUT');
    await drag(a, 0, 228);
    await nextSave;
    assert.equal(widgets[0].layout.y, 3, 'vertical drag must preserve three empty rows above the chart');
    assert.equal(await top(a), initialTop + 228);
    assert.equal(widgets[1].layout.y, 0, 'moving a chart into empty space must not move its neighbour');
    report.checks.push('vertical drag preserves empty space and saves the exact dropped row');
    const placed = saved(), afterDragWrites = writes;
    await page.reload(); await waitLayout();
    assert.equal(await top(a), initialTop + 228);
    assert.deepEqual(saved(), placed); assert.equal(writes, afterDragWrites);
    report.checks.push('reload restores the saved free placement without automatic compaction or writes');
    await page.screenshot({ path: path.join(out, 'free-placement-desktop.png'), fullPage: true });
    for (const width of [768, 390, 320, 1600]) {
      await page.setViewportSize({ width, height: 1100 }); await waitLayout();
      await assertNoOverlap();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
      assert.equal(writes, afterDragWrites); assert.deepEqual(saved(), placed);
    }
    assert.equal(await top(a), initialTop + 228);
    await page.getByRole('button', { name: '메뉴 접기', exact: true }).click(); await waitLayout();
    await page.getByRole('button', { name: '메뉴 펼치기', exact: true }).click(); await waitLayout();
    assert.equal(writes, afterDragWrites); assert.equal(await top(a), initialTop + 228);
    report.checks.push('320–1600px and sidebar changes avoid overlap and preserve the saved desktop gap');
    const resize = a.locator('.react-resizable-handle').first();
    await resize.scrollIntoViewIfNeeded(); const handle = await resize.boundingBox();
    const nextResize = page.waitForResponse(r => r.url().endsWith('/widgets/layout') && r.request().method() === 'PUT');
    await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
    await page.mouse.down(); await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2 + 76, { steps: 12 }); await page.mouse.up();
    await nextResize; await waitLayout();
    assert.equal(widgets[0].layout.h, 5); assert.equal(widgets[0].layout.y, 3);
    await page.reload(); await waitLayout();
    assert.equal(await top(a), initialTop + 228); assert.equal(widgets[0].layout.h, 5);
    report.checks.push('resizing and reloading preserve the chosen vertical position');
    await drag(a, 0, -76);
    assert.equal(widgets[0].layout.y, 2); assert.equal(await top(a), initialTop + 152);
    await assertNoOverlap();
    report.checks.push('chart can move upward again without snapping to the top');
    const beforeCollision = saved();
    const [first, second] = await Promise.all([a.boundingBox(), b.boundingBox()]);
    await drag(a, second.x - first.x, 0);
    assert.deepEqual(saved(), beforeCollision, 'dropping onto another chart must not displace either chart');
    await assertNoOverlap();
    await drag(a, second.x - first.x, 228);
    assert.equal(widgets[0].layout.x, 6); assert.equal(widgets[0].layout.y, 5);
    assert.deepEqual(widgets[1].layout, beforeCollision[1]);
    const diagonal = saved();
    await page.reload(); await waitLayout();
    assert.deepEqual(saved(), diagonal); assert.equal(await top(a), initialTop + 380);
    await assertNoOverlap();
    report.checks.push('occupied positions do not shift neighbours; free horizontal/vertical placement survives reload');
    assert.deepEqual(report.errors, []); report.passed = true;
  } catch (error) {
    report.passed = false; report.failure = error.stack;
    await page.screenshot({ path: path.join(out, 'failure.png'), fullPage: true });
    throw error;
  } finally {
    await fs.writeFile(path.join(out, 'receipt.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2)); await browser.close();
  }
}
main().catch(() => { process.exitCode = 1; });
