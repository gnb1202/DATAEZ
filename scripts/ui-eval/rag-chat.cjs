const { openChat } = require('./workspace-helpers.cjs');
// Real UI -> SSE agent -> real RAG/SQL -> persisted widget. No request interception.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const out = process.env.LIVE_ARTIFACTS;
const ui = process.env.LIVE_UI_URL;
if (!out || !ui) throw new Error('Use scripts/rag-eval/run.py --browser');

(async () => {
  const input = JSON.parse(await fs.readFile(path.join(out, 'browser-input.json'), 'utf8'));
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
  const report = { real_streaming_model: true, api_mocks: false, turns: [], errors: [] };
  page.setDefaultTimeout(30000);
  page.on('pageerror', err => report.errors.push(err.message));
  try {
    await page.goto(ui);
    await page.getByLabel('이메일', { exact: true }).fill(input.email);
    await page.getByLabel('비밀번호', { exact: true }).fill(input.password);
    await page.locator('form button[type=submit]').click();
    await page.waitForURL('**/dashboard');
    // Login redirects before the new page finishes rotating its session token.
    // Wait for authenticated content before issuing a full document navigation.
    await page.getByRole('navigation', { name: '작업 메뉴' }).waitFor();
    await page.goto(`${ui}/dashboard?project=${input.project_id}&section=ai-chat`);
    await openChat(page);
    const box = page.locator('textarea');
    async function chat(question) {
      await box.fill(question);
      const pending = page.waitForResponse(r => /\/messages\/stream$/.test(r.url()) && r.request().method() === 'POST', { timeout: 180000 });
      await page.locator('form button[type=submit]').click();
      const response = await pending;
      assert.equal(response.status(), 200);
      const body = await response.text();
      assert.ok(body.includes('"type": "done"') || body.includes('"type":"done"'), 'Stream completed with a done event');
      assert.ok(!body.includes('"type": "error"') && !body.includes('"type":"error"'), 'No stream error');
      await box.waitFor({ state: 'visible' });
      await page.waitForFunction(() => !document.querySelector('textarea')?.disabled);
      report.turns.push({ question, status: response.status(), stream: body });
    }
    await chat('의미 검색으로 01_gangnam_pg.csv가 반영된 장부를 먼저 찾고 전체 기간 순결제액 합계 지표를 대시보드에 저장해줘. 제목은 검색으로 만든 순결제액, 자동 갱신은 꺼줘.');
    await page.screenshot({ path: path.join(out, 'chat-save.png'), fullPage: true });
    await chat('방금 저장한 그 지표를 매시간 새로고침하도록 바꿔줘.');
    await page.getByRole('navigation', { name: '작업 메뉴' }).getByRole('button', { name: '대시보드', exact: true }).click();
    await page.getByText('검색으로 만든 순결제액', { exact: true }).waitFor();
    assert.match(await page.locator('main').innerText(), /1,358,000|1358000/);
    await page.evaluate(() => Promise.all(document.getAnimations().filter(a => a.effect?.getTiming().iterations !== Infinity).map(a => a.finished.catch(() => {}))));
    await page.screenshot({ path: path.join(out, 'dashboard-metric.png'), fullPage: true });
    assert.deepEqual(report.errors, []);
    report.passed = true;
    console.log('PASS: live chat searched, saved 1,358,000, and changed the same metric to hourly');
  } catch (err) {
    report.passed = false;
    report.failure = err.stack;
    await page.screenshot({ path: path.join(out, 'browser-failure.png'), fullPage: true }).catch(() => {});
    throw err;
  } finally {
    await fs.writeFile(path.join(out, 'browser.json'), JSON.stringify(report, null, 2));
    await browser.close();
  }
})().catch(err => { console.error(err); process.exitCode = 1; });
