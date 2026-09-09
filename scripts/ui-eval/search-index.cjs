// I: live UI against a disposable API. No requests or responses are mocked.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const out = process.env.LIVE_ARTIFACTS, ui = process.env.LIVE_UI_URL, phase = process.argv[2];
if (!out || !ui || !['pending', 'retry', 'recovered'].includes(phase)) throw new Error('Use scripts/index-eval/run.py');

(async () => {
  const input = JSON.parse(await fs.readFile(path.join(out, 'browser-input.json'), 'utf8'));
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } });
  page.setDefaultTimeout(45000);
  const report = { phase, errors: [], api_mocks: false };
  page.on('pageerror', error => report.errors.push(error.message));
  try {
    await page.goto(ui);
    await page.getByLabel('이메일', { exact: true }).fill(input.email);
    await page.getByLabel('비밀번호', { exact: true }).fill(input.password);
    await page.locator('form button[type=submit]').click();
    await page.waitForURL('**/dashboard');
    await page.getByRole('combobox', { name: '현재 작업 가게' }).selectOption({ label: '검색 갱신 검증점' });
    await page.getByRole('navigation', { name: '작업 메뉴' }).getByRole('button', { name: '데이터 관리', exact: true }).click();
    const panel = page.getByRole('region', { name: '검색 갱신 상태' });
    const ledger = panel.getByRole('listitem', { name: '카드 매출', exact: true });
    await ledger.waitFor();
    if (phase === 'pending') {
      await ledger.getByText('갱신 대기', { exact: true }).waitFor();
      for (const [name, text, key] of [['환불규정.txt', '예약 취소는 방문 하루 전까지 전액 환불합니다. 당일 취소는 환불하지 않습니다.', 'document'], ['빈문서.txt', '', 'empty_document']]) {
        await panel.getByLabel('검색 참고 문서', { exact: true }).setInputFiles({ name, mimeType: 'text/plain', buffer: Buffer.from(text) });
        const pending = page.waitForResponse(r => r.url().endsWith('/documents') && r.request().method() === 'POST');
        await panel.getByRole('button', { name: '문서 올리기', exact: true }).click();
        const response = await pending;
        assert.ok(response.ok());
        report[key] = await response.json();
        assert.equal(report[key].index_status, 'pending');
        await panel.getByRole('listitem', { name, exact: true }).getByText('갱신 대기', { exact: true }).waitFor();
      }
    } else if (phase === 'retry') {
      await ledger.getByText('자동 재시도 대기', { exact: true }).waitFor();
      await panel.getByRole('listitem', { name: '환불규정.txt', exact: true }).getByText('자동 재시도 대기', { exact: true }).waitFor();
      await panel.getByRole('listitem', { name: '빈문서.txt', exact: true }).getByText('확인 필요', { exact: true }).waitFor();
    } else {
      await ledger.getByText('검색 준비 완료', { exact: true }).waitFor();
      await panel.getByRole('listitem', { name: '환불규정.txt', exact: true }).getByText('검색 준비 완료', { exact: true }).waitFor();
      const pending = page.waitForResponse(r => /\/search-index\/[^/]+\/retry$/.test(r.url()) && r.request().method() === 'POST');
      await ledger.getByRole('button', { name: '검색 다시 갱신', exact: true }).click();
      const response = await pending;
      assert.ok(response.ok());
      report.manual_retry = await response.json();
      assert.equal(report.manual_retry.status, 'pending');
      // Observe the completion response, not the previous rendered success.
      await page.waitForResponse(async r => r.url().includes('/search-index?') && r.ok() &&
        (await r.json()).jobs.some(j => j.table_meta_id === input.table_id && j.status === 'succeeded' && j.attempts === 1));
      await ledger.getByText('검색 준비 완료', { exact: true }).waitFor();
      page.once('dialog', dialog => dialog.accept());
      const deletion = page.waitForResponse(r => r.url().includes('/documents/') && r.request().method() === 'DELETE');
      await panel.getByRole('button', { name: '빈문서.txt 문서 삭제', exact: true }).click();
      assert.ok((await deletion).ok());
      await panel.getByRole('listitem', { name: '빈문서.txt', exact: true }).waitFor({ state: 'detached' });
    }
    await panel.scrollIntoViewIfNeeded();
    await panel.screenshot({ path: path.join(out, 'index-'+phase+'.png') });
    report.passed = report.errors.length === 0;
  } catch (error) {
    report.failure = error.stack;
    await page.screenshot({ path: path.join(out, 'failure-'+phase+'.png'), fullPage: true });
    throw error;
  } finally {
    await fs.writeFile(path.join(out, 'browser-'+phase+'.json'), JSON.stringify(report, null, 2));
    await browser.close();
  }
})().catch(error => { process.stderr.write(error.stack+'\n'); process.exitCode = 1; });
