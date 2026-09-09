// C-stage UI contracts. Hashes, decisions and DB races are tested on real PG.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");

async function main() {
  const browser = await chromium.launch({ channel: process.env.BROWSER_CHANNEL || "msedge", headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
    const errors = [], decisionRequests = [], adoptionRequests = [];
    page.on("pageerror", (e) => errors.push(e.message));
    const mapping = { amount_column: "money", occurred_at_column: "day", event_id_column: "id", event_kind: "signed" };
    let sources = [{ id: "source-1", table_id: "table-1", name: "카드 결제", provider: "카드사A", account: "가맹점1", feed: "결제 이벤트", mapping, event_index_version: 1 }];
    const columns = [{ name: "id", type: "TEXT" }, { name: "money", type: "NUMERIC" }, { name: "day", type: "DATE" }];
    let batch, reviewRows = [], mode = "overlap";
    const event = (id, amount) => ({ event_id: id, original_event_id: null, event_kind: "payment", amount, occurred_at: "2026-09-01T00:00:00+09:00", currency: "KRW" });
    const prior = (id) => ({ filename: "이전 결제.csv", batch_id: "prior", row_number: 2, target_row_id: 1, normalized: event(id, "100000") });
    function ready() {
      if (mode === "conflict") {
        reviewRows = [{ row_number: 2, normalized: event("0001", "999000"), classification: "conflict", reason: "같은 이벤트 ID의 금액·일시·원거래 등 내용이 다릅니다.", matched: prior("0001"), decision: null }];
        return { ...batch, status: "failed", review_version: 1, preview_token: "conflict-token", summary: { row_count: 1, amount: "0", can_commit: false, counts: { new: 0, duplicate: 0, candidate: 0, conflict: 1, included: 0, excluded: 0, unresolved: 0 }, sample: [] } };
      }
      reviewRows = [
        { row_number: 2, normalized: event("0001", "100000"), classification: "duplicate", reason: "같은 이벤트 ID와 계산 내용이 이미 있습니다.", matched: prior("0001"), decision: null },
        { row_number: 3, normalized: event("0002", "100000"), classification: "candidate", reason: "ID가 없는 거래와 종류·한국 날짜·금액·통화가 같습니다. 자동 제외하지 않습니다.", matched: prior(null), decision: null },
        { row_number: 4, normalized: event("0003", "50000"), classification: "new", reason: "새 이벤트입니다.", matched: null, decision: null },
      ];
      return { ...batch, status: "ready", review_version: 1, preview_token: "first-token", summary: { row_count: 3, amount: "50000", can_commit: false, counts: { new: 1, duplicate: 1, candidate: 1, conflict: 0, included: 1, excluded: 0, unresolved: 1 }, sample: [] } };
    }
    await page.route("**/api/**", async (route) => {
      const req = route.request(), url = new URL(req.url()), p = url.pathname;
      let body = {}, status = 200;
      if (req.method() === "OPTIONS") body = {};
      else if (p === "/api/auth/refresh") body = { access_token: "ui-fixture", refresh_token: "ui-fixture" };
      else if (p === "/api/auth/me") body = { email: "ui@example.test" };
      else if (p === "/api/conversations") body = { conversations: [] };
      else if (p === "/api/projects") body = { projects: [{ id: "store-a", name: "강남점" }, { id: "store-b", name: "홍대점" }] };
      else if (p === "/api/dashboard/widgets") body = { widgets: [] };
      else if (p.includes("/conversations")) body = { conversations: [] };
      else if (p.endsWith("/attribute-restorations")) body = { restorations: [] };
      else if (p.endsWith("/cash-entries")) body = { entries: [], total: 0 };
      else if (p.endsWith("/search-index")) body = { jobs: [], counts: {}, total: 0, search_enabled: false, worker_enabled: false, max_attempts: 3 };
      else if (p.endsWith("/tables")) body = { tables: [
        { id: "table-1", name: "카드 결제", project_id: "store-a", row_count: 1, columns_schema: columns, ledger_source_id: "source-1" },
        { id: "legacy", name: "과거 매출", project_id: "store-a", row_count: 1, columns_schema: columns, ledger_source_id: sources.length > 1 ? "source-2" : null },
      ] };
      else if (p.endsWith("/data")) body = { columns, rows: [], total_count: 0 };
      else if (p.endsWith("/ledger-sources/preview-adoption")) {
        adoptionRequests.push(req.postDataJSON());
        body = { row_count: 1, counts: { duplicate: 0, conflict: 0, candidate: 0 }, can_adopt: true, adoption_token: "adoption-token", issues: [] };
      } else if (p.endsWith("/ledger-sources")) {
        if (req.method() === "POST") {
          const payload = req.postDataJSON();
          assert.equal(payload.existing_table_id, "legacy"); assert.equal(payload.adoption_token, "adoption-token");
          body = { ...payload, id: "source-2", table_id: "legacy", event_index_version: 1 };
          sources = [...sources, body];
        } else body = { sources: p.includes("store-a") ? sources : [] };
      } else if (p.endsWith("/imports") && req.method() === "POST") {
        batch = { id: mode === "overlap" ? "batch-1" : "batch-2", filename: mode === "overlap" ? "overlap.csv" : "conflict.csv", status: "uploaded", created_at: "2026-09-08T00:00:00Z", review_version: 0 };
        body = batch;
      } else if (p.endsWith("/imports")) body = { batches: batch ? [batch] : [], total: batch ? 1 : 0 };
      else if (p.endsWith("/preview")) { batch = ready(); body = batch; }
      else if (p.endsWith("/rows")) {
        const filter = url.searchParams.get("classification");
        const items = filter ? reviewRows.filter((r) => r.classification === filter) : reviewRows;
        body = { rows: items, total: items.length, preview_token: batch.preview_token };
      } else if (p.endsWith("/decisions")) {
        const payload = req.postDataJSON(); decisionRequests.push(payload);
        reviewRows[1].decision = payload.decisions[0].decision;
        batch = { ...batch, preview_token: "decided-token", summary: { ...batch.summary, can_commit: true,
          counts: { ...batch.summary.counts, unresolved: 0, excluded: 1 } } }; body = batch;
      } else if (p.endsWith("/commit")) {
        assert.equal(req.postDataJSON().preview_token, "decided-token");
        batch = { ...batch, status: "committed", result: { rows_inserted: 1, total_row_count: 2, amount: "50000", duplicates_skipped: 1, candidates_excluded: 1 } };
        body = batch;
      } else if (/\/imports\/batch-[12]$/.test(p)) body = batch;
      else throw new Error(`Unexpected API ${req.method()} ${p}`);
      await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body), headers: { "access-control-allow-origin": "*" } });
    });
    await page.addInitScript(() => localStorage.setItem("dataez_refresh_token", "ui-fixture"));
    await page.goto(process.env.UI_BASE_URL || "http://127.0.0.1:3100/dashboard");
    await page.getByRole("button", { name: "데이터 관리", exact: true }).click();
    const panel = page.getByRole("region", { name: "출처별 파일 반영" });
    const file = panel.getByLabel("결제 파일");
    await file.setInputFiles({ name: "overlap.csv", mimeType: "text/csv", buffer: Buffer.from("id,money,day\n0003,50000,2026-09-01\n") });
    await panel.getByRole("button", { name: "업로드·미리보기" }).click();
    await panel.getByText(/총 3행 · 신규 1 · 중복 1 · 후보 1/).waitFor();
    assert.equal(await panel.getByRole("button", { name: "장부에 반영" }).isDisabled(), true);
    await panel.getByLabel("판정 보기").selectOption("candidate");
    await panel.getByText("이전 결제.csv · 2행 비교", { exact: true }).click();
    await panel.getByText(/기존 금액 100000원/).waitFor();
    await panel.getByLabel("3행 처리").selectOption("exclude");
    await panel.getByRole("button", { name: "장부에 반영" }).click();
    await panel.getByText("중복 제외 1행 · 사용자 제외 1행", { exact: true }).waitFor();
    assert.deepEqual(decisionRequests[0], { preview_token: "first-token", decisions: [{ row_number: 3, decision: "exclude" }] });
    mode = "conflict";
    await file.setInputFiles({ name: "conflict.csv", mimeType: "text/csv", buffer: Buffer.from("id,money,day\n0001,999000,2026-09-01\n") });
    await panel.getByRole("button", { name: "업로드·미리보기" }).click();
    await panel.getByText("같은 이벤트 ID의 금액·일시·원거래 등 내용이 다릅니다.", { exact: true }).waitFor();
    assert.equal(await panel.getByRole("button", { name: "장부에 반영" }).isDisabled(), true);
    await fs.mkdir(path.join(__dirname, "artifacts"), { recursive: true });
    await page.screenshot({ path: path.join(__dirname, "artifacts/event-review.png"), fullPage: true, animations: "disabled" });
    await panel.getByRole("button", { name: "새 출처 등록", exact: true }).click();
    const form = panel.getByRole("form", { name: "새 출처 등록" });
    await form.getByLabel("대상 장부").selectOption("legacy");
    for (const [label, value] of [["출처 이름", "과거 카드 매출"], ["제공자", "카드사B"], ["가맹점·계정", "계정1"], ["자료 종류", "결제"], ["금액 컬럼", "money"], ["발생일시 컬럼", "day"], ["이벤트 ID 컬럼 (선택)", "id"]]) await form.getByLabel(label, { exact: true }).fill(value);
    await form.getByRole("button", { name: "기존 장부 전체 검사" }).click();
    await form.getByRole("button", { name: "검사한 장부를 출처로 전환" }).waitFor();
    await form.getByLabel("가맹점·계정").fill("계정2");
    assert.equal(await form.getByRole("button", { name: "검사한 장부를 출처로 전환" }).count(), 0);
    await form.getByRole("button", { name: "기존 장부 전체 검사" }).click();
    await form.getByRole("button", { name: "검사한 장부를 출처로 전환" }).click();
    await panel.getByLabel("반영할 출처").selectOption("source-2");
    assert.equal(adoptionRequests.length, 2);
    assert.equal(adoptionRequests[1].account, "계정2");
    await page.getByRole("combobox", { name: "현재 작업 가게" }).selectOption("store-b");
    await panel.getByText("제공자·계정별 출처를 먼저 등록한 뒤 파일을 연결해주세요.", { exact: true }).waitFor();
    assert.equal(await panel.getByLabel("3행 처리").count(), 0);
    assert.deepEqual(errors, []);
    console.log("PASS: event reasons/provenance, explicit candidate decision, refreshed token, conflict blocks commit, adoption review invalidation, store isolation (API fixtures).");
  } finally { await browser.close(); }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
