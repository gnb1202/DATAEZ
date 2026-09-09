const { openChat } = require('./workspace-helpers.cjs');
// H: existing source -> inspected restoration -> old/new imports -> same widget.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const out = process.env.LIVE_ARTIFACTS, ui = process.env.LIVE_UI_URL;
if (!out || !ui) throw new Error('Use scripts/restore-eval/run.py --browser');

(async () => {
  const input = JSON.parse(await fs.readFile(path.join(out, 'browser-input.json'), 'utf8'));
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } });
  const report = { api_mocks: false, real_streaming_model: true, errors: [] };
  page.setDefaultTimeout(30000);
  page.on('pageerror', error => report.errors.push(error.message));
  const response = suffix => page.waitForResponse(r => r.url().endsWith(suffix) && r.request().method() === 'POST', { timeout: 180000 });
  async function json(pending) {
    const res = await pending;
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
    const restoration = panel.getByRole('region', { name: '과거 속성 복원' });
    await restoration.getByRole('button', { name: '과거 속성 복원', exact: true }).click();
    const form = restoration.getByRole('form', { name: '과거 속성 복원 검사' });
    for (const [label, value] of [['결제수단 원본 컬럼', '결제수단'], ['판매채널 원본 컬럼', '판매채널'], ['PG 수수료 원본 컬럼', 'PG수수료']]) {
      await form.getByLabel(label, { exact: true }).fill(value);
    }
    const pending = response('/attribute-restorations/preview');
    await form.getByRole('button', { name: '원본 검사·복원 미리보기' }).click();
    report.preview = await json(pending);
    assert.equal(report.preview.report.row_count, 54);
    assert.equal(report.preview.report.attributes.fee.provided, 54);
    assert.equal(report.preview.report.pending_uploads, 1);
    const applyButton = restoration.getByRole('button', { name: '검사한 속성 복원 적용' });
    await applyButton.waitFor();
    await page.screenshot({ path: path.join(out, 'restore-preview.png'), fullPage: true });
    const applied = response(`/attribute-restorations/${report.preview.id}/apply`);
    await applyButton.click();
    report.applied = await json(applied);
    assert.equal(report.applied.index_status, 'queued');
    assert.equal(report.applied.result.rule_version, 2);
    assert.equal(report.applied.result.table_id, input.table_id);
    await restoration.getByText('속성 복원 완료', { exact: true }).waitFor();
    await restoration.getByRole('button', { name: '변경 행 보기', exact: true }).click();
    await restoration.getByText('PG 수수료: 미제공 → 3000원', { exact: true }).first().waitFor();
    await restoration.getByRole('button', { name: '다음 변경 행', exact: true }).click();
    await restoration.getByText('2 / 3', { exact: true }).waitFor();
    await page.screenshot({ path: path.join(out, 'restore-audit.png'), fullPage: true });
    const originLink = restoration.getByRole('link', { name: '원본 반영 기록 보기', exact: true }).first();
    const target = new URL(await originLink.getAttribute('href'), ui);
    assert.equal(target.searchParams.get('source'), report.applied.source_id);
    const originBatch = target.searchParams.get('batch');
    const originLoaded = page.waitForResponse(r => r.url().endsWith(`/imports/${originBatch}`) && r.request().method() === 'GET');
    await originLink.click();
    report.origin_view = await json(originLoaded);
    assert.equal(report.origin_view.status, 'committed');
    await panel.getByText('장부 반영 완료', { exact: true }).waitFor();

    report.imports = [];
    for (const [filename, expectedAdded] of [[path.join(input.samples, '01_gangnam_pg.csv'), 0], [input.next_file, 1]]) {
      await panel.getByLabel('결제 파일').setInputFiles(filename);
      const preview = page.waitForResponse(r => /\/imports\/[^/]+\/preview$/.test(r.url()) && r.request().method() === 'POST');
      await panel.getByRole('button', { name: '업로드·미리보기' }).click();
      const batch = await json(preview);
      assert.equal(batch.summary.counts.new, expectedAdded);
      const committed = response(`/imports/${batch.id}/commit`);
      await panel.getByRole('button', { name: '장부에 반영', exact: true }).click();
      const result = await json(committed);
      assert.equal(result.rows_added, expectedAdded);
      report.imports.push(result);
      await panel.getByText('장부 반영 완료', { exact: true }).waitFor();
    }
    await page.getByRole('region', { name: '검색 갱신 상태' }).getByRole('listitem', { name: '기존 결제원장', exact: true }).getByText('검색 준비 완료', { exact: true }).waitFor();
    await nav.getByRole('button', { name: '대시보드', exact: true }).click();
    const refreshed = response(`/metrics/${input.metric_id}/refresh`);
    await page.getByRole('button', { name: '기존 순결제액 재계산', exact: true }).click();
    report.refreshed = await json(refreshed);
    assert.equal(report.refreshed.id, input.metric_id);
    assert.equal(report.refreshed.widget_data.value, '1408000');

    await openChat(page);
    const question = '의미 검색으로 기존 결제원장을 찾고, 복원된 PG 수수료의 전체 기간 합계 지표를 대시보드에 저장해줘. 제목은 복원된 PG 수수료, 자동갱신은 꺼줘.';
    await page.locator('textarea').fill(question);
    const streamResponse = response('/messages/stream');
    await page.locator('form button[type=submit]').click();
    const res = await streamResponse;
    assert.equal(res.status(), 200);
    report.stream = await res.text();
    report.question = question;
    assert.match(report.stream, /"type":\s*"done"/);
    assert.doesNotMatch(report.stream, /"type":\s*"error"/);
    await page.waitForFunction(() => !document.querySelector('textarea')?.disabled);
    await nav.getByRole('button', { name: '대시보드', exact: true }).click();
    await page.getByText('복원된 PG 수수료', { exact: true }).waitFor();
    assert.match(await page.locator('main').innerText(), /42,240|42240/);
    await page.evaluate(() => Promise.all(document.getAnimations().filter(a => a.effect?.getTiming().iterations !== Infinity).map(a => a.finished.catch(() => {}))));
    await page.screenshot({ path: path.join(out, 'restored-dashboard.png'), fullPage: true });
    assert.deepEqual(report.errors, []);
    report.passed = true;
    console.log('PASS: restore 54 old events, replay 40, append 1, preserve old metric, save restored fees');
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
