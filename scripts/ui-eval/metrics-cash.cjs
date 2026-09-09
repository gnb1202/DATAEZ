const { openChat } = require('./workspace-helpers.cjs');
// K/L: real UI and chat; no API routes are mocked.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const out = process.env.LIVE_ARTIFACTS, ui = process.env.LIVE_UI_URL;
if (!out || !ui) throw new Error('Use scripts/metrics-cash-eval/run.py');
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
  try {
    await page.goto(ui);
    await page.getByLabel('이메일', { exact: true }).fill(input.email);
    await page.getByLabel('비밀번호', { exact: true }).fill(input.password);
    await page.locator('form button[type=submit]').click();
    await page.waitForURL('**/dashboard');
    await chat('검증 결제원장의 전체 기간 순결제액에서 PG 수수료 합계를 뺀 계산식 지표를 대시보드에 저장해줘. 금액과 수수료는 원본 부호 그대로 합산해. 제목은 수수료 차감액, 자동 갱신은 매시간으로 해줘.');
    await nav.getByRole('button', { name: '대시보드', exact: true }).click();
    await page.getByRole('button', { name: '수수료 차감액 수정·이력', exact: true }).waitFor();
    assert.match(await page.locator('main').innerText(), /368,?600/);
    await chat('방금 저장한 수수료 차감액 지표의 두 집계 기간을 모두 이번 달로 수정해줘. 제목, 위치와 자동 갱신 주기는 그대로 유지해줘. 새 지표를 추가하는 게 아니라 기존 지표를 수정해줘.');
    await nav.getByRole('button', { name: '대시보드', exact: true }).click();
    await page.getByRole('button', { name: '수수료 차감액 수정·이력', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByText('수수료 차감액 · 버전 2', { exact: true }).waitFor();
    await page.screenshot({ path: path.join(out, 'metric-history.png'), fullPage: true });
    const restored = response('/restore');
    await dialog.getByRole('button', { name: '버전 1 정의 복원', exact: true }).click();
    report.restored = await json(restored);
    assert.equal(report.restored.definition_revision, 3);
    assert.equal(report.restored.refresh_interval_seconds, 3600);
    assert.equal(report.restored.widget_data.value, '368600');
    await dialog.getByText('수수료 차감액 · 버전 3', { exact: true }).waitFor();
    await page.keyboard.press('Escape');
    await chat('오늘 현금 매출 3만원을 기록해줘. 판매 채널은 매장, 메모는 점심 현금 매출이야.');
    const link = page.getByRole('link', { name: '현금 입력 검토하기', exact: true }).last();
    await link.waitFor();
    const href = await link.getAttribute('href');
    const id = new URL(href, ui).searchParams.get('cash_draft');
    const loaded = response(`/cash-entries/${id}`, 'GET');
    await link.click();
    report.chatDraft = await json(loaded);
    assert.equal(report.chatDraft.status, 'draft');
    assert.equal(report.chatDraft.payload.amount, '30000');
    const cash = page.getByRole('region', { name: '현금 직접 입력' });
    await cash.getByText('점심 현금 매출', { exact: true }).first().waitFor();
    await page.screenshot({ path: path.join(out, 'cash-draft.png'), fullPage: true });
    let pending = response(`/cash-entries/${id}/commit`);
    await cash.getByRole('button', { name: '현금 장부에 반영', exact: true }).click();
    report.first = await json(pending);
    assert.equal(report.first.status, 'committed');
    for (const memo of ['오후 현금 매출', '별도 동일 금액 매출']) {
      await cash.getByRole('button', { name: '새 거래 입력', exact: true }).click();
      await cash.getByLabel('금액 (원)', { exact: true }).fill('40000');
      await cash.getByLabel('메모 (선택)', { exact: true }).fill(memo);
      pending = response('/cash-entries/drafts');
      await cash.getByRole('button', { name: '입력 내용 확인', exact: true }).click();
      const draft = await json(pending);
      if (memo.startsWith('별도')) {
        assert.equal(draft.similar.count, 1);
        assert.ok(await cash.getByRole('button', { name: '현금 장부에 반영', exact: true }).isDisabled());
        await cash.getByLabel('기존 기록을 확인했으며 별도 거래입니다.').check();
        await page.screenshot({ path: path.join(out, 'cash-duplicate-review.png'), fullPage: true });
      }
      pending = response(`/cash-entries/${draft.id}/commit`);
      await cash.getByRole('button', { name: '현금 장부에 반영', exact: true }).click();
      const committed = await json(pending); assert.equal(committed.status, 'committed');
    }
    await cash.locator('summary').click();
    await cash.getByText('현금 입력 이력 (3건)', { exact: true }).waitFor();
    await page.screenshot({ path: path.join(out, 'cash-history.png'), fullPage: true });
    await nav.getByRole('button', { name: '대시보드', exact: true }).click();
    await page.getByRole('button', { name: '수수료 차감액 수정·이력', exact: true }).waitFor();
    await page.evaluate(() => Promise.all(document.getAnimations().filter(a => a.effect?.getTiming().iterations !== Infinity).map(a => a.finished.catch(() => {}))));
    await page.screenshot({ path: path.join(out, 'formula-dashboard.png'), fullPage: true });
    assert.deepEqual(report.errors, []); report.passed = true;
    console.log('PASS: formula save/edit/restore and cash chat/manual/duplicate review');
  } catch (err) {
    report.passed = false; report.failure = err.stack;
    await page.screenshot({ path: path.join(out, 'browser-failure.png'), fullPage: true }).catch(() => {});
    throw err;
  } finally { await fs.writeFile(path.join(out, 'browser.json'), JSON.stringify(report, null, 2)); await browser.close(); }
})().catch(err => { console.error(err); process.exitCode = 1; });
