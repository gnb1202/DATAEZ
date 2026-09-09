const { openChat } = require('./workspace-helpers.cjs');
// G: real source form -> CSV review -> streaming agent -> saved category charts.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const out = process.env.LIVE_ARTIFACTS, ui = process.env.LIVE_UI_URL;
if (!out || !ui) throw new Error('Use scripts/payment-eval/run.py --browser');

(async () => {
  const input = JSON.parse(await fs.readFile(path.join(out, 'browser-input.json'), 'utf8'));
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } });
  const report = { api_mocks: false, real_streaming_model: true, turns: [], checks: [], errors: [] };
  page.setDefaultTimeout(30000);
  page.on('pageerror', e => report.errors.push(e.message));
  const response = suffix => page.waitForResponse(r => r.url().endsWith(suffix) && r.request().method() === 'POST', { timeout: 180000 });
  async function json(promise) {
    const res = await promise;
    assert.ok(res.ok(), `${res.status()}: ${await res.text()}`);
    return res.json();
  }
  try {
    await page.goto(ui);
    await page.getByLabel('이메일', { exact: true }).fill(input.email);
    await page.getByLabel('비밀번호', { exact: true }).fill(input.password);
    await page.locator('form button[type=submit]').click();
    await page.waitForURL('**/dashboard');
    const nav = page.getByRole('navigation', { name: '작업 메뉴' });
    await nav.waitFor();
    await nav.getByRole('button', { name: '데이터 관리', exact: true }).click();
    const panel = page.getByRole('region', { name: '출처별 파일 반영' });
    await panel.getByRole('button', { name: '새 출처 등록', exact: true }).click();
    const form = panel.getByRole('form', { name: '새 출처 등록' });
    for (const [label, value] of [['출처 이름', '결제 분석원장'], ['제공자', '가상PG'], ['가맹점·계정', 'G001'], ['자료 종류', '결제취소이벤트'],
      ['금액 컬럼', '거래금액'], ['발생일시 컬럼', '거래일시'], ['이벤트 ID 컬럼 (선택)', '거래번호'], ['원거래 ID 컬럼 (선택)', '원거래번호'],
      ['결제수단 컬럼', '결제수단'], ['판매채널 컬럼', '판매채널'], ['PG 수수료 컬럼', 'PG수수료']]) {
      await form.getByLabel(label, { exact: true }).fill(value);
    }
    await form.getByLabel('금액 해석').selectOption('signed');
    const pending = response(`/api/projects/${input.project_id}/ledger-sources`);
    await form.getByRole('button', { name: '출처와 장부 만들기' }).click();
    report.source = await json(pending);
    assert.equal(report.source.mapping.fee_column, 'PG수수료');
    await form.waitFor({ state: 'hidden' });
    for (const [filename, added, duplicates] of [['01_gangnam_pg.csv', 40, 0], ['03_gangnam_pg_overlap.csv', 14, 12]]) {
      await panel.getByLabel('결제 파일').setInputFiles(path.join(input.samples, filename));
      const preview = page.waitForResponse(r => /\/imports\/[^/]+\/preview$/.test(r.url()) && r.request().method() === 'POST', { timeout: 180000 });
      await panel.getByRole('button', { name: '업로드·미리보기' }).click();
      const batch = await json(preview);
      assert.equal(batch.summary.counts.new, added);
      assert.equal(batch.summary.counts.duplicate, duplicates);
      if (!duplicates) {
        await panel.getByText('결제수단 카드 · 채널 예약웹 · 수수료 3000원', { exact: true }).first().waitFor();
        await page.screenshot({ path: path.join(out, 'attribute-review.png'), fullPage: true });
      }
      const committed = response(`/api/projects/${input.project_id}/imports/${batch.id}/commit`);
      await panel.getByRole('button', { name: '장부에 반영', exact: true }).click();
      assert.equal((await json(committed)).rows_added, added);
      await panel.getByText('장부 반영 완료', { exact: true }).waitFor();
      report.checks.push({ filename, added, duplicates });
    }
    await page.getByRole('region', { name: '검색 갱신 상태' }).getByRole('listitem', { name: '결제 분석원장', exact: true }).getByText('검색 준비 완료', { exact: true }).waitFor();
    await openChat(page);
    const box = page.locator('textarea');
    for (const question of [
      '의미 검색으로 01_gangnam_pg.csv가 반영된 장부를 찾고, 전체 기간 결제수단별 순결제액을 막대차트로 대시보드에 저장해줘. 제목은 결제수단별 순결제액, 갱신은 매시간으로 해줘.',
      '결제 분석원장의 전체 기간 판매채널별 PG 수수료 합계를 막대차트로 대시보드에 추가해줘. 제목은 채널별 PG 수수료, 자동 갱신은 꺼줘.'
    ]) {
      await box.fill(question);
      const pending = response('/messages/stream');
      await page.locator('form button[type=submit]').click();
      const res = await pending;
      assert.equal(res.status(), 200);
      const stream = await res.text();
      assert.match(stream, /"type":\s*"done"/);
      assert.doesNotMatch(stream, /"type":\s*"error"/);
      await page.waitForFunction(() => !document.querySelector('textarea')?.disabled);
      report.turns.push({ question, stream });
    }
    await nav.getByRole('button', { name: '대시보드', exact: true }).click();
    await page.getByText('결제수단별 순결제액', { exact: true }).waitFor();
    await page.getByText('채널별 PG 수수료', { exact: true }).waitFor();
    await page.locator('[data-chart-engine="echarts"] svg').first().waitFor();
    await page.evaluate(() => Promise.all(document.getAnimations().filter(a => a.effect?.getTiming().iterations !== Infinity).map(a => a.finished.catch(() => {}))));
    await page.screenshot({ path: path.join(out, 'attribute-dashboard.png'), fullPage: true });
    assert.deepEqual(report.errors, []);
    report.passed = true;
    console.log('PASS: source mappings, 54 events, category charts saved through real chat');
  } catch (error) {
    report.passed = false;
    report.failure = error.stack;
    await page.screenshot({ path: path.join(out, 'browser-failure.png'), fullPage: true }).catch(() => {});
    throw error;
  } finally {
    await fs.writeFile(path.join(out, 'browser.json'), JSON.stringify(report, null, 2));
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
