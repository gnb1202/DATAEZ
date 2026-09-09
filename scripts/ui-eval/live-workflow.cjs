const { openLatestAnalysis } = require('./workspace-helpers.cjs');
// Invoked by live-run.py. Every browser request reaches the real application.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const { randomUUID } = require("node:crypto");
const ui = process.env.LIVE_UI_URL, api = process.env.NEXT_PUBLIC_API_URL;
const out = process.env.LIVE_ARTIFACTS, phase = process.argv[2];
if (!ui || !api || !out) throw new Error("Use live-run.py to create an isolated run");
const checkpointPath = path.join(out, "checkpoint.json");

async function main() {
  const browser = await chromium.launch({ channel: process.env.BROWSER_CHANNEL || "msedge", headless: true });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1200 },
    ...(phase === "resumed" ? { storageState: path.join(out, "session.json") } : {}) });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  const errors = [];
  page.on("pageerror", e => errors.push(e.message));
  let accessToken;
  page.on("response", async response => {
    if (/\/api\/auth\/(signup|login|refresh)$/.test(response.url()) && response.ok()) {
      accessToken = (await response.json()).access_token;
    }
  });
  const response = (suffix, method = "POST") => page.waitForResponse(r => r.url().endsWith(suffix) && r.request().method() === method);
  async function jsonResponse(promise) {
    const res = await promise;
    assert.equal(res.ok(), true, `${res.status()} ${res.url()} ${await res.text()}`);
    return res.json();
  }
  async function request(route, opts = {}) {
    const res = await fetch(api + route, { ...opts, headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}`, ...opts.headers } });
    assert.equal(res.ok, true, `${res.status} ${route}: ${await res.clone().text()}`);
    return res.json();
  }
  async function createStore(name) {
    // An empty account offers the store selector; later stores use its menu.
    await page.getByRole("button", { name: "가게 추가", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("가게 이름", { exact: true }).fill(name);
    const pending = response("/api/projects");
    await dialog.getByRole("button", { name: "만들기", exact: true }).click();
    const store = await jsonResponse(pending);
    await dialog.waitFor({ state: "hidden" });
    return store.id;
  }
  async function tables() {
    await page.getByRole("navigation", { name: "작업 메뉴" }).getByRole("button", { name: "데이터 관리", exact: true }).click();
    return page.getByRole("region", { name: "출처별 파일 반영" });
  }
  async function source(panel, project, name, idColumn = "id") {
    await panel.getByRole("button", { name: "새 출처 등록", exact: true }).click();
    const form = panel.getByRole("form", { name: "새 출처 등록" });
    for (const [label, value] of [["출처 이름", name], ["제공자", "합성 검증"], ["가맹점·계정", name], ["자료 종류", "결제 이벤트"],
      ["금액 컬럼", "money"], ["발생일시 컬럼", "day"], ["이벤트 ID 컬럼 (선택)", idColumn]]) {
      await form.getByLabel(label, { exact: true }).fill(value);
    }
    await form.getByLabel("금액 해석").selectOption("signed");
    const pending = response(`/api/projects/${project}/ledger-sources`);
    await form.getByRole("button", { name: "출처와 장부 만들기" }).click();
    const created = await jsonResponse(pending);
    await form.waitFor({ state: "hidden" });
    return created;
  }
  async function upload(panel, filename, content, replay = false) {
    await fs.writeFile(path.join(out, filename), content, "utf8");
    await panel.getByLabel("결제 파일").setInputFiles(path.join(out, filename));
    const pending = page.waitForResponse(r => /\/imports(?:\/[\w-]+\/preview)?$/.test(r.url()) && r.request().method() === "POST" && (replay || r.url().endsWith("/preview")));
    await panel.getByRole("button", { name: "업로드·미리보기" }).click();
    return jsonResponse(pending);
  }
  async function commit(panel, project, batch) {
    const pending = response(`/api/projects/${project}/imports/${batch.id}/commit`);
    await panel.getByRole("button", { name: "장부에 반영", exact: true }).click();
    const result = await jsonResponse(pending);
    await panel.getByText("장부 반영 완료", { exact: true }).waitFor();
    return result;
  }
  try {
    if (phase === "initial") {
      await page.goto(ui);
      await page.getByRole("button", { name: "회원가입", exact: true }).click();
      await page.getByLabel("이름", { exact: true }).fill("통합 검증");
      await page.getByLabel("이메일", { exact: true }).fill(`live-${randomUUID()}@example.test`);
      await page.getByLabel("비밀번호", { exact: true }).fill("Live-test-only!2026");
      await page.locator("form button[type=submit]").click();
      await page.waitForURL("**/dashboard");
      const projectId = await createStore("통합검증 강남점");
      let panel = await tables();
      const card = await source(panel, projectId, "카드 매출");
      const firstCsv = "id,money,day\n0001,200000,2026-09-01\n0002,100000,2026-09-02\nR0001,-50000,2026-09-03\n";
      const first = await upload(panel, "card-first.csv", firstCsv);
      assert.equal(first.summary.amount, "250000");
      assert.equal(first.summary.counts.new, 3);
      const committed = await commit(panel, projectId, first);
      assert.equal(committed.rows_added, 3);

      await page.getByRole("button", { name: "대시보드", exact: true }).click();
      await page.getByText("갱신 가능한 지표 만들기", { exact: true }).click();
      await page.getByLabel("지표 이름", { exact: true }).fill("순매출 검증");
      await page.getByLabel("장부", { exact: true }).selectOption(card.table_id);
      await page.getByLabel("숫자 컬럼", { exact: true }).selectOption("amount");
      await page.getByLabel("자동 갱신", { exact: true }).selectOption("3600");
      const metricPending = response(`/api/projects/${projectId}/metrics`);
      await page.getByRole("button", { name: "계산하고 대시보드에 추가", exact: true }).click();
      const metric = await jsonResponse(metricPending);
      assert.equal(metric.widget_data.value, "250000");
      await page.getByRole("button", { name: "순매출 검증 재계산" }).waitFor();
      // Exercise real resizing and its persisted layout PATCH.
      const widget = page.locator(".react-grid-item").filter({ has: page.getByRole("button", { name: "순매출 검증 재계산" }) });
      const handle = widget.locator(".react-resizable-handle").first();
      const box = await handle.boundingBox();
      assert.ok(box);
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      const layoutPending = response("/api/dashboard/widgets/layout", "PUT");
      await page.mouse.down();
      await page.mouse.move(box.x + 130, box.y + 85, { steps: 12 });
      await page.mouse.up();
      await jsonResponse(layoutPending);
      const widgets = await request(`/api/dashboard/widgets?project_id=${projectId}`);
      const savedLayout = widgets.widgets.find(w => w.id === metric.id).layout;
      assert.notDeepEqual(savedLayout, metric.layout);
      panel = await tables();
      const replay = await upload(panel, "card-renamed.csv", firstCsv, true);
      assert.equal(replay.rows_added, 0);
      assert.equal(replay.id, first.id);
      const overlap = await upload(panel, "card-overlap.csv", "id,money,day\n0001,200000,2026-09-01\nR0001,-50000,2026-09-03\n0003,50000,2026-09-04\n");
      assert.equal(overlap.summary.counts.duplicate, 2);
      assert.equal(overlap.summary.amount, "50000");
      await panel.getByText(/card-first.csv · 2행 비교/).waitFor();
      const overlapResult = await commit(panel, projectId, overlap);
      assert.equal(overlapResult.rows_added, 1);
      const conflict = await upload(panel, "card-conflict.csv", "id,money,day\n0001,999000,2026-09-01\n");
      assert.equal(conflict.summary.counts.conflict, 1);
      assert.equal(await panel.getByRole("button", { name: "장부에 반영", exact: true }).isDisabled(), true);

      // A separate ID-less cash ledger exercises persisted candidate decisions.
      const cash = await source(panel, projectId, "현금 매출", "");
      const cashFirst = await upload(panel, "cash-first.csv", "money,day,note\n1000,2026-09-01,first\n");
      await commit(panel, projectId, cashFirst);
      const cashNext = await upload(panel, "cash-candidate.csv", "money,day,note\n1000,2026-09-01,possible duplicate\n2000,2026-09-02,new\n");
      assert.equal(cashNext.summary.counts.candidate, 1);
      assert.equal(await panel.getByRole("button", { name: "장부에 반영", exact: true }).isDisabled(), true);
      const choice = response(`/api/projects/${projectId}/imports/${cashNext.id}/decisions`);
      await panel.getByLabel("2행 처리", { exact: true }).selectOption("exclude");
      const decided = await jsonResponse(choice);
      assert.notEqual(decided.preview_token, cashNext.preview_token);
      const cashResult = await commit(panel, projectId, decided);
      assert.equal(cashResult.result.candidates_excluded, 1);
      assert.equal(cashResult.rows_added, 1);
      await page.screenshot({ path: path.join(out, "live-review.png"), fullPage: true, animations: "disabled" });

      const otherProject = await createStore("통합검증 홍대점");
      panel = await tables();
      await panel.getByText("제공자·계정별 출처를 먼저 등록한 뒤 파일을 연결해주세요.", { exact: true }).waitFor();
      // Both foreign store path and foreign owner are denied by the real API.
      let denied = await fetch(`${api}/api/projects/${otherProject}/imports/${first.id}`, { headers: { Authorization: `Bearer ${accessToken}` } });
      assert.equal(denied.status, 404);
      const foreign = await fetch(`${api}/api/auth/signup`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: `foreign-${randomUUID()}@example.test`, password: "Live-test-only!2026", name: "다른 소유자" }) });
      assert.equal(foreign.ok, true);
      const foreignToken = (await foreign.json()).access_token;
      denied = await fetch(`${api}/api/projects/${projectId}/imports/${first.id}`, { headers: { Authorization: `Bearer ${foreignToken}` } });
      assert.equal(denied.status, 404);
      await page.getByRole("combobox", { name: "현재 작업 가게" }).selectOption({ label: "통합검증 강남점" });
      await page.getByRole("button", { name: "대시보드", exact: true }).click();
      await page.getByRole("button", { name: "순매출 검증 재계산" }).waitFor();
      await page.getByText(/장부 반영:.*재계산 필요/).waitFor();
      await context.storageState({ path: path.join(out, "session.json") });
      await fs.writeFile(checkpointPath, JSON.stringify({ projectId, otherProject, metricId: metric.id, cardId: card.id,
        firstId: first.id, overlapId: overlap.id, cashId: cash.id, savedLayout }), "utf8");
      console.log("PASS: real signup, two stores, sources, CSV review/commit/replay/conflict/candidate, metric and resize");
    } else {
      const state = JSON.parse(await fs.readFile(checkpointPath, "utf8"));
      await page.goto(`${ui}/dashboard?project=${state.projectId}`);
      await page.getByRole("button", { name: "통합검증 강남점", exact: true }).waitFor();
      await page.getByRole("button", { name: "순매출 검증 재계산" }).waitFor();
      await page.getByText("300000", { exact: true }).waitFor();
      const data = await request(`/api/dashboard/widgets?project_id=${state.projectId}`);
      const widget = data.widgets.find(w => w.id === state.metricId);
      assert.equal(widget.widget_data.value, "300000");
      assert.deepEqual(widget.layout, state.savedLayout);
      assert.equal(widget.refresh_interval_seconds, 3600);
      const recalculation = response(`/api/projects/${state.projectId}/metrics/${state.metricId}/refresh`);
      await page.getByRole("button", { name: "순매출 검증 재계산" }).click();
      assert.equal((await jsonResponse(recalculation)).widget_data.value, "300000");
      await page.getByRole("button", { name: "순매출 검증 재계산", disabled: false }).waitFor();
      await page.screenshot({ path: path.join(out, "live-dashboard.png"), fullPage: true, animations: "disabled" });
      const replay = await request(`/api/projects/${state.projectId}/imports/${state.overlapId}/commit`, { method: "POST", body: JSON.stringify({ preview_token: randomUUID() }) });
      assert.equal(replay.rows_added, 0);
      assert.equal(replay.result.rows_inserted, 1);
      const rows = await request(`/api/projects/${state.projectId}/imports/${state.overlapId}/rows`);
      assert.equal(rows.rows.filter(r => r.classification === "duplicate").length, 2);
      assert.ok(rows.rows.every(r => r.target_row_id));
      await page.reload();
      await page.getByRole("button", { name: "순매출 검증 재계산" }).waitFor();
      await page.goto(`${ui}/dashboard?project=${state.projectId}&section=tables&source=${state.cardId}&batch=${state.overlapId}`);
      const linkedPanel = page.getByRole("region", { name: "출처별 파일 반영" });
      await linkedPanel.getByText("장부 반영 완료", { exact: true }).waitFor();
      assert.equal(await linkedPanel.getByLabel("반영할 출처").inputValue(), state.cardId);
      await linkedPanel.getByText(/card-first.csv · 2행 비교/).waitFor();
      await page.getByRole("banner").getByText("카드 매출", { exact: true }).waitFor();
      await page.screenshot({ path: path.join(out, "live-linked-review.png"), fullPage: true, animations: "disabled" });
      await openLatestAnalysis(page);
      const chatLink = page.getByRole("link", { name: "card-overlap.csv 검토하기", exact: true });
      await chatLink.waitFor();
      await page.screenshot({ path: path.join(out, "live-chat-review.png"), fullPage: true, animations: "disabled" });
      await chatLink.click();
      await page.getByRole("region", { name: "출처별 파일 반영" }).getByText("장부 반영 완료", { exact: true }).waitFor();
      console.log("PASS: restarted API, rotated refresh token, 300000 metric, layout, history and replay persist");
    }
    assert.deepEqual(errors, []);
  } catch (e) {
    await page.screenshot({ path: path.join(out, `failure-${phase}.png`), fullPage: true }).catch(() => {});
    await fs.writeFile(path.join(out, `failure-${phase}.txt`), await page.locator("body").innerText()).catch(() => {});
    throw e;
  } finally { await browser.close(); }
}
main().catch(e => { console.error(e); process.exitCode = 1; });
