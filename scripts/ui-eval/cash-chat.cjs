// Real Edge + Next.js, synthetic API responses. No production ledger/model calls.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const fs = require('node:fs/promises');
const path = require('node:path');

async function main() {
  const out = path.join(__dirname, '../../.local-test/cash-chat');
  await fs.mkdir(out, { recursive: true });
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  page.setDefaultTimeout(15000);
  const checks = [], errors = [], commits = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error' && /Maximum update|Hydration|React/.test(message.text())) errors.push(message.text()); });
  const storeA = randomUUID(), storeB = randomUUID();
  const stores = [{ id: storeA, name: '성수점' }, { id: storeB, name: '연남점' }];
  const entries = new Map();
  let mode = 'ok', failRead = false, tableReads = 0, readCount = 0, sent = 0, releaseCommit;
  const newEntry = (overrides = {}) => {
    const value = { id: randomUUID(), project_id: storeA, status: 'draft', confirmation_token: randomUUID(), is_expired: false,
      payload: { amount: '30000', occurred_on: '2026-09-18', kind: 'payment', channel: '매장', memo: '점심 현금 매출', original_event_id: null }, similar: { count: 0, entries: [] }, ...overrides };
    entries.set(value.id, value); return value;
  };
  const publicResult = entry => {
    const { confirmation_token, similar, ...value } = entry;
    return { ...value, similar_count: similar.count, review_url: `/dashboard?project=${value.project_id}&section=tables&cash_draft=${value.id}` };
  };
  const answer = entry => ({ message_id: 'cash-result', role: 'assistant', content: '현금 입력 초안을 준비했습니다. 내용을 확인하고 반영 확정을 눌러주세요.',
    steps: [{ type: 'tool_call', tool_name: 'draft_cash_entry', tool_input: { amount: entry.payload.amount }, tool_output: publicResult(entry) }] });
  let current = newEntry(), message = answer(current);
  const headers = { 'access-control-allow-origin': '*', 'access-control-allow-methods': '*', 'access-control-allow-headers': '*' };
  const card = () => page.locator('#workspace-chat').getByRole('region', { name: '현금 입력 반영 확인', exact: true });
  const nav = label => page.getByRole('navigation', { name: '작업 메뉴' }).getByRole('button', { name: label, exact: true });
  const openHistory = async () => {
    await nav('분석 이력').click();
    await page.locator('#workspace-main').getByRole('button', { name: /현금 입력 대화/ }).click();
    await page.getByRole('textbox', { name: '분석 요청', exact: true }).waitFor();
  };
  const ready = () => card().getByRole('button', { name: '반영 확정', exact: true }).waitFor();
  try {
    await page.route('**/api/**', async route => {
      const req = route.request(), url = new URL(req.url()), p = url.pathname, method = req.method();
      let body = {}, status = 200;
      if (method === 'OPTIONS') {}
      else if (p === '/api/auth/refresh') body = { access_token: 'fixture', refresh_token: 'fixture' };
      else if (p === '/api/auth/me') body = { email: 'owner@example.test' };
      else if (p === '/api/projects') body = { projects: stores };
      else if (p.endsWith('/tables')) { tableReads++; body = { tables: [] }; }
      else if (p.endsWith('/ledger-sources')) body = { sources: [] };
      else if (p.endsWith('/search-index')) body = { jobs: [], counts: {}, total: 0 };
      else if (p.endsWith('/cash-entries')) body = { entries: [...entries.values()], total: entries.size, today: '2026-09-18' };
      else if (p.includes('/cash-entries/')) {
        const parts = p.split('/'), entry = entries.get(parts[5]);
        if (!entry || parts[3] !== entry.project_id) { status = 404; body = { detail: '현재 가게의 현금 입력 기록이 없습니다.' }; }
        else if (method === 'POST' && p.endsWith('/commit')) {
          commits.push({ id: entry.id, body: req.postDataJSON() });
          if (mode === 'delay') await new Promise(resolve => { releaseCommit = resolve; });
          if (mode === 'conflict') {
            mode = 'ok'; entry.similar = { count: 1, entries: [{ id: randomUUID(), payload: { ...entry.payload, memo: '동시에 반영된 기록' } }] };
            status = 409; body = { detail: '같은 날짜·종류·금액의 현금 기록이 있습니다.' };
          } else {
            assert.equal(req.postDataJSON().confirmation_token, entry.confirmation_token);
            if (entry.similar.count) assert.equal(req.postDataJSON().separate_transaction, true);
            entry.status = 'committed'; body = entry;
            if (mode === 'lost' || mode === 'unknown') { failRead = mode === 'unknown'; mode = 'ok'; await route.abort('failed'); return; }
          }
        } else {
          readCount++;
          if (failRead) { failRead = false; status = 503; body = { detail: '연결 실패 테스트' }; }
          else body = entry;
        }
      } else if (p === '/api/conversations') body = method === 'POST' ? { conversation_id: 'cash-conversation' } : { conversations: [{ conversation_id: 'cash-conversation', title: '현금 입력 대화' }] };
      else if (p.endsWith('/messages/stream')) {
        sent++;
        await route.fulfill({ contentType: 'text/event-stream', headers, body: `data: ${JSON.stringify({ type: 'done', data: message })}\n\n` }); return;
      } else if (p.endsWith('/messages')) body = { messages: [message] };
      else if (p === '/api/dashboard/widgets') body = { widgets: [] };
      else { status = 404; errors.push(`Unexpected ${method} ${p}`); }
      await route.fulfill({ status, contentType: 'application/json', headers, body: JSON.stringify(body) });
    });
    await page.addInitScript(() => localStorage.setItem('dataez_refresh_token', 'fixture'));
    const base = process.env.UI_BASE_URL || 'http://127.0.0.1:3140/dashboard';
    await page.goto(base);
    await page.getByRole('button', { name: '새 분석', exact: true }).click();
    await page.getByRole('textbox', { name: '분석 요청', exact: true }).fill('오늘 현금 매출 3만원, 매장, 점심 현금 매출로 기록해줘');
    message.steps[0].tool_output.payload = { ...current.payload, amount: '99999' };
    await page.getByRole('button', { name: '분석 요청 보내기' }).click();
    await ready();
    await card().getByText('30,000원', { exact: true }).waitFor();
    assert.equal(commits.length, 0);
    assert.equal(sent, 1);
    await card().screenshot({ path: path.join(out, 'cash-confirm-dark.png') });
    const beforeTables = tableReads;
    await card().getByRole('button', { name: '반영 확정', exact: true }).dblclick();
    await card().getByText(/반영 완료/).waitFor();
    assert.equal(commits.length, 1);
    assert.equal(sent, 1);
    assert(tableReads > beforeTables);
    assert.deepEqual(commits[0].body, { confirmation_token: current.confirmation_token, separate_transaction: false });
    await page.reload(); await openHistory();
    await card().getByText(/반영 완료/).waitFor();
    assert.equal(await card().getByRole('button', { name: '반영 확정', exact: true }).count(), 0);
    checks.push('streamed draft fetches real server values; explicit double-click writes once, updates data and survives history reload');

    current = newEntry({ similar: { count: 1, entries: [{ id: randomUUID(), payload: { ...current.payload, memo: '기존 점심 매출' } }] } });
    message = answer(current); await openHistory(); await ready();
    assert(await card().getByRole('button', { name: '반영 확정', exact: true }).isDisabled());
    await card().getByRole('checkbox').check();
    mode = 'conflict';
    await card().getByRole('button', { name: '반영 확정', exact: true }).click();
    await card().getByText('매장 · 동시에 반영된 기록', { exact: true }).waitFor();
    assert.equal(await card().getByRole('checkbox').isChecked(), false);
    assert(await card().getByRole('button', { name: '반영 확정', exact: true }).isDisabled());
    await card().getByRole('checkbox').check();
    await card().getByRole('button', { name: '반영 확정', exact: true }).click();
    await card().getByText(/반영 완료/).waitFor();
    checks.push('duplicate acknowledgement required; new concurrent duplicate resets acknowledgement before retry');

    for (const failure of ['lost', 'unknown']) {
      current = newEntry(); message = answer(current); await openHistory(); await ready();
      mode = failure; const before = commits.length;
      await card().getByRole('button', { name: '반영 확정', exact: true }).click();
      if (failure === 'unknown') {
        await card().getByRole('button', { name: '현재 상태 다시 확인' }).waitFor();
        assert.equal(await card().getByRole('button', { name: '반영 확정', exact: true }).count(), 0);
        await card().getByRole('button', { name: '현재 상태 다시 확인' }).click();
      }
      await card().getByText(/반영 완료/).waitFor();
      assert.equal(commits.length, before + 1);
    }
    checks.push('lost commit response reconciles by GET; failed reconciliation blocks further writes until status is known');

    for (const overrides of [{ is_expired: true }, { status: 'cancelled' }]) {
      current = newEntry(overrides); message = answer(current); await openHistory();
      await card().getByText(/새 초안을 요청/).waitFor();
      assert.equal(await card().getByRole('button', { name: '반영 확정', exact: true }).count(), 0);
    }
    checks.push('expired and cancelled drafts have no commit action');

    current = newEntry(); message = answer(current);
    message.steps.push({ ...message.steps[0], type: 'tool_result' });
    await openHistory(); await ready();
    assert.equal(await card().count(), 1);
    await nav('데이터 관리').click();
    current.status = 'committed';
    await nav('AI 분석').click();
    await card().getByText(/반영 완료/).waitFor();
    checks.push('duplicate tool frames create one card; reopening chat refreshes a record committed elsewhere');

    current = newEntry(); message = answer(current); message.steps[0].tool_output.project_id = storeB;
    const beforeRead = readCount; await openHistory();
    assert.equal(await card().count(), 0); assert.equal(readCount, beforeRead);
    message = answer(current); message.steps[0].tool_name = 'query_data'; await openHistory();
    assert.equal(await card().count(), 0); assert.equal(readCount, beforeRead);
    checks.push('foreign-store and unrelated tool output cannot create confirmation actions');

    current = newEntry({ payload: { ...current.payload, kind: 'refund', amount: '9007199254740993.01', original_event_id: 'CASH-original-record', memo: '취소 기록 확인' } });
    message = answer(current); await openHistory(); await ready();
    await card().getByText('−9,007,199,254,740,993.01원', { exact: true }).waitFor();
    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 844 });
      for (const theme of ['dark', 'light']) {
        await page.evaluate(theme => { document.documentElement.classList.remove('dark', 'light'); document.documentElement.classList.add(theme); }, theme);
        await ready();
        await card().getByRole('button', { name: '반영 확정', exact: true }).scrollIntoViewIfNeeded();
        assert(await card().evaluate(el => el.scrollWidth <= el.clientWidth + 1));
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
        await card().screenshot({ path: path.join(out, `cash-refund-${width}-${theme}.png`) });
      }
    }
    checks.push('refund sign, exact decimal amount and original record survive 320/390px dark/light layouts');

    await page.keyboard.press('Escape'); await page.setViewportSize({ width: 1440, height: 1000 });
    await page.locator('#workspace-chat-toggle').click();
    mode = 'delay';
    await card().getByRole('button', { name: '반영 확정', exact: true }).click();
    await card().getByRole('button', { name: '반영 중…', exact: true }).waitFor();
    await page.getByRole('combobox', { name: '현재 작업 가게' }).selectOption(storeB);
    mode = 'ok'; releaseCommit();
    await page.getByRole('heading', { name: 'AI 분석', exact: true }).waitFor();
    assert.equal(await card().count(), 0);
    assert.equal(await page.getByRole('combobox', { name: '현재 작업 가게' }).inputValue(), storeB);
    checks.push('in-flight confirmation completion never enters another store workspace');
    assert.deepEqual(errors, []);
    await fs.writeFile(path.join(out, 'receipt.json'), JSON.stringify({ passed: true, mode: 'Edge + Next.js with synthetic API fixtures; no live LLM/ledger', checks, errors }, null, 2));
    console.log(checks.map(check => `PASS ${check}`).join('\n'));
  } catch (error) {
    await page.screenshot({ path: path.join(out, 'failure.png') }).catch(() => {});
    await fs.writeFile(path.join(out, 'receipt.json'), JSON.stringify({ passed: false, checks, errors, failure: error.stack }, null, 2));
    throw error;
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
