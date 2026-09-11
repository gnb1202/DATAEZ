// Browser UI contract. Durable hash/transaction behavior is covered on real PG.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs/promises");

async function main() {
  const browser = await chromium.launch({ channel: process.env.BROWSER_CHANNEL || "msedge", headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
    const errors = [], uploadKeys = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const stores = [{ id: "store-a", name: "강남점", description: "" }, { id: "store-b", name: "홍대점", description: "" }];
    const columns = [{ name: "event_id", type: "TEXT" }, { name: "amount", type: "NUMERIC" }, { name: "occurred_at", type: "TIMESTAMPTZ" }];
    let sources = [], batch, created, previewError = true, stale = true;
    await page.route("**/api/**", async (route) => {
      const request = route.request(), url = new URL(request.url()), p = url.pathname;
      let body = {}, status = 200;
      if (request.method() === "OPTIONS") body = {};
      else if (p === "/api/auth/refresh") body = { access_token: "ui-fixture", refresh_token: "ui-fixture" };
      else if (p === "/api/uploads/capabilities") body = { direct_upload: false, max_size_bytes: 20 * 1024 * 1024 };
      else if (p === "/api/library/files/sample-workspace") body = { project: null };
      else if (p === "/api/auth/me") body = { email: "ui@example.test" };
      else if (p === "/api/conversations") body = { conversations: [] };
      else if (p === "/api/projects") body = { projects: stores };
      else if (p.endsWith("/attribute-restorations")) body = { restorations: [] };
      else if (p.endsWith("/cash-entries")) body = { entries: [], total: 0 };
      else if (p.endsWith("/search-index")) body = { jobs: [], counts: {}, total: 0, search_enabled: false, worker_enabled: false, max_attempts: 3 };
      else if (p.endsWith("/tables")) body = { tables: p.includes("store-a") ? sources.map((source) => ({
        id: source.table_id, name: source.name, project_id: "store-a", ledger_source_id: source.id,
        columns_schema: columns, row_count: batch?.status === "committed" ? 3 : 0,
      })) : [] };
      else if (p.endsWith("/tables/table-1/data")) body = { columns, total_count: batch?.status === "committed" ? 3 : 0,
        rows: batch?.status === "committed" ? [
          { event_id: "000012345678901234567890", amount: "100000", occurred_at: "2026-09-01T00:00:00+09:00" },
          { event_id: "0002", amount: "200000", occurred_at: "2026-09-01T00:00:00+09:00" },
          { event_id: "0003", amount: "-50000", occurred_at: "2026-09-02T00:00:00+09:00" },
        ] : [] };
      else if (p === "/api/dashboard/widgets") body = { widgets: [] };
      else if (p.includes("/conversations")) body = { conversations: [] };
      else if (p.endsWith("/ledger-sources")) {
        if (request.method() === "POST") {
          created = request.postDataJSON();
          sources = [{ ...created, id: "source-1", table_id: "table-1", row_count: 0, data_revision: 0 }];
          body = sources[0];
        } else body = { sources: p.includes("store-a") ? sources : [] };
      } else if (p.endsWith("/imports") && request.method() === "POST") {
        uploadKeys.push(request.postDataBuffer().toString().match(/name="request_key"\r\n\r\n([^\r]+)/)[1]);
        if (!batch) batch = { id: "batch-1", filename: "payments.csv", status: "uploaded", created_at: "2026-09-08T00:00:00Z" };
        body = { ...batch, replayed: batch.status === "committed", rows_added: 0 };
      } else if (p.endsWith("/imports")) body = { batches: batch ? [batch] : [], total: batch ? 1 : 0 };
      else if (p.endsWith("/preview")) {
        if (previewError) { status = 422; body = { detail: "3행 money: 유효한 금액을 입력해주세요." }; }
        else {
          batch = { ...batch, status: "ready", preview_token: "preview-1", summary: { row_count: 3, amount: "250000", sample: [
            { row: 2, event_id: "000012345678901234567890", amount: "100000", occurred_at: "2026-09-01T00:00:00+09:00" },
            { row: 3, event_id: "0002", amount: "200000", occurred_at: "2026-09-01T00:00:00+09:00" },
            { row: 4, event_id: "0003", amount: "-50000", occurred_at: "2026-09-02T00:00:00+09:00" },
          ] } }; body = batch;
        }
      } else if (p.endsWith("/commit")) {
        if (stale) { status = 409; body = { detail: "출처 데이터 또는 미리보기가 변경되었습니다. 미리보기를 다시 확인해주세요." }; }
        else {
          batch = { ...batch, status: "committed", rows_added: 3, replayed: false, result: { rows_inserted: 3, total_row_count: 3, amount: "250000" } };
          body = batch;
        }
      } else if (p.endsWith("/imports/batch-1")) body = batch;
      else throw new Error(`Unexpected API request: ${request.method()} ${p}`);
      await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body), headers: { "access-control-allow-origin": "*" } });
    });
    await page.addInitScript(() => localStorage.setItem("dataez_refresh_token", "ui-fixture"));
    await page.goto(process.env.UI_BASE_URL || "http://127.0.0.1:3100/dashboard");
    await page.getByRole("button", { name: "데이터 관리", exact: true }).click();
    const panel = page.getByRole("region", { name: "출처별 파일 반영" });
    await panel.getByRole("button", { name: "새 출처 등록", exact: true }).click();
    const form = panel.getByRole("form", { name: "새 출처 등록" });
    for (const [label, value] of [["출처 이름", "카드 장부"], ["제공자", "카드사A"], ["가맹점·계정", "가맹점1"], ["자료 종류", "결제 이벤트"], ["금액 컬럼", "money"], ["발생일시 컬럼", "day"], ["이벤트 ID 컬럼 (선택)", "id"]]) {
      await form.getByLabel(label, { exact: true }).fill(value);
    }
    await form.getByLabel("금액 해석").selectOption("signed");
    await form.getByRole("button", { name: "출처와 장부 만들기" }).click();
    await panel.getByLabel("반영할 출처").waitFor();
    assert.equal(created.mapping.event_kind, "signed");
    assert.equal(created.mapping.event_id_column, "id");
    const input = panel.getByLabel("결제 파일");
    await input.setInputFiles({ name: "payments.csv", mimeType: "text/csv", buffer: Buffer.from("id,money,day\n0001,100000,2026-09-01\n") });
    await panel.getByRole("button", { name: "업로드·미리보기" }).click();
    await panel.getByRole("alert").waitFor();
    assert.match(await panel.getByRole("alert").innerText(), /3행 money/);
    assert.equal(await input.evaluate((el) => el.files[0].name), "payments.csv");
    assert.equal(await panel.getByRole("button", { name: "장부에 반영" }).isDisabled(), true);
    previewError = false;
    await panel.getByRole("button", { name: "업로드·미리보기" }).click();
    await panel.getByText("반영 예정 3행 · 250000원", { exact: true }).waitFor();
    assert.equal(uploadKeys[0], uploadKeys[1]);
    await panel.getByText("000012345678901234567890", { exact: true }).waitFor();
    await panel.getByRole("button", { name: "장부에 반영" }).click();
    await panel.getByRole("alert").waitFor();
    assert.equal(await panel.getByRole("button", { name: "장부에 반영" }).isDisabled(), true);
    stale = false;
    await panel.getByRole("button", { name: "중복 검사·미리보기" }).click();
    await panel.getByRole("button", { name: "장부에 반영" }).click();
    await panel.getByText("장부 반영 완료", { exact: true }).waitFor();
    await page.getByText("출처 관리", { exact: true }).waitFor();
    await page.getByRole("cell", { name: "000012345678901234567890", exact: true }).waitFor();
    await page.getByRole("cell", { name: "100,000", exact: true }).waitFor();
    await input.setInputFiles({ name: "renamed.csv", mimeType: "text/csv", buffer: Buffer.from("id,money,day\n0001,100000,2026-09-01\n") });
    await panel.getByRole("button", { name: "업로드·미리보기" }).click();
    await panel.getByText("이미 반영한 파일입니다. 이번 추가는 0건입니다.", { exact: true }).waitFor();
    assert.notEqual(uploadKeys[1], uploadKeys[2]);
    await fs.mkdir(path.join(__dirname, "artifacts"), { recursive: true });
    await page.screenshot({ path: path.join(__dirname, "artifacts/ledger-imports.png"), fullPage: true });
    await page.getByRole("combobox", { name: "현재 작업 가게" }).selectOption("store-b");
    await page.getByRole("button", { name: "데이터 관리", exact: true }).click();
    await panel.getByText("제공자·계정별 출처를 먼저 등록한 뒤 파일을 연결해주세요.", { exact: true }).waitFor();
    assert.equal(await panel.getByLabel("반영할 출처").count(), 0);
    assert.equal(await panel.getByText("이미 반영한 파일입니다. 이번 추가는 0건입니다.", { exact: true }).count(), 0);
    assert.deepEqual(errors, []);
    console.log("PASS: source mapping, validation/retry key, stale preview, commit, renamed-file replay, history and store switch (API fixtures).");
  } finally { await browser.close(); }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
