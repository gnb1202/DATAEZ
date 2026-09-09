// Real browser + actual dashboard UI, with API fixtures; no live DB or LLM.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs/promises");

async function main() {
  const browser = await chromium.launch({ channel: process.env.BROWSER_CHANNEL || "msedge", headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const stores = [{ id: "store-a", name: "강남점", description: "" }, { id: "store-b", name: "홍대점", description: "" }];
    const tables = ["현금", "카드", "취소"].map((name, i) => ({
      id: `table-${i}`, project_id: "store-a", name, row_count: 1,
      columns_schema: [{ name: "금액", type: "NUMERIC" }, { name: "일자", type: "DATE" }],
    }));
    let widgets = [], previews = [], saved, failPreview = false;
    function result(definition) {
      return { value: "250000", formatted: "250000원", metric_definition: definition,
        calculated_at: "2026-09-08T00:00:00Z", label: "통합 결제액 (원)",
        source_table_name: definition.sources.map((s) => s.label).join(" + "),
        period_label: "이번 달", calculation_label: "원화 결제 이벤트 합계 · 취소 장부는 차감",
        sources: definition.sources.map((s) => ({ ...s, table_name: s.label, included_rows: 1 })) };
    }
    await page.route("**/api/**", async (route) => {
      const request = route.request(), url = new URL(request.url()), p = url.pathname;
      let body = {}, status = 200;
      if (request.method() === "OPTIONS") body = {};
      else if (p === "/api/auth/refresh") body = { access_token: "ui-fixture", refresh_token: "ui-fixture" };
      else if (p === "/api/auth/me") body = { email: "ui-fixture@example.test" };
      else if (p === "/api/conversations") body = { conversations: [] };
      else if (p === "/api/projects") body = { projects: stores };
      else if (p.endsWith("/tables")) body = { tables: p.includes("store-a") ? tables : [] };
      else if (p === "/api/dashboard/widgets") body = { widgets: url.searchParams.get("project_id") === "store-a" ? widgets : [] };
      else if (p === "/api/dashboard/widgets/layout") body = { ok: true };
      else if (p === "/api/projects/store-a/metrics/preview") {
        const definition = request.postDataJSON().definition;
        previews.push(definition);
        if (failPreview) { status = 422; body = { detail: "금액이 비어 있는 행 1건이 있습니다." }; }
        else body = result(definition);
      } else if (p === "/api/projects/store-a/metrics") {
        saved = request.postDataJSON();
        const widget = { id: "metric-1", widget_type: "kpi", title: saved.title,
          widget_data: result(saved.definition), layout: { x: 0, y: 0, w: 6, h: 7 },
          refresh_interval_seconds: saved.refresh_interval_seconds };
        widgets = [widget]; body = widget; status = 201;
      } else if (p.endsWith("/ledger-sources") && request.method() === "GET") {
        body = { sources: [] }; // These fixture tables are ordinary, unmanaged ledgers.
      } else throw new Error(`Unexpected API request: ${request.method()} ${p}`);
      await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body),
        headers: { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" } });
    });
    await page.addInitScript(() => localStorage.setItem("dataez_refresh_token", "ui-fixture"));
    await page.goto(process.env.UI_BASE_URL || "http://127.0.0.1:3100/dashboard");
    await page.getByText("여러 장부의 결제액 합치기", { exact: true }).click();
    const form = page.locator("details").filter({ has: page.locator("summary", { hasText: "여러 장부의 결제액 합치기" }) });
    await form.getByLabel("지표 이름", { exact: true }).fill("현금·카드 통합 결제액");
    await form.getByLabel(/^집계/).selectOption("none");
    await form.getByLabel(/^기간/).selectOption("this_month");
    await form.getByLabel(/^갱신/).selectOption("3600");
    await form.getByRole("button", { name: "장부 추가", exact: true }).click();
    for (let i = 0; i < 3; i++) {
      const group = form.getByRole("group", { name: `장부 ${i + 1}`, exact: true });
      await group.getByLabel(/^장부/).selectOption(`table-${i}`);
      await group.getByLabel(/^금액 컬럼/).selectOption("금액");
      await group.getByLabel(/^결제·취소일 컬럼/).selectOption("일자");
      if (i === 2) await group.getByLabel(/^금액 처리/).selectOption("refund");
    }
    await form.getByRole("button", { name: "통합 결과 미리보기", exact: true }).click();
    await form.getByText("계산 결과 250000원", { exact: true }).waitFor();
    assert.equal(await form.getByRole("button", { name: "대시보드에 저장", exact: true }).isDisabled(), true);
    assert.equal(previews[0].sources[2].amount_mode, "refund");
    assert.equal(previews[0].time_range, "this_month");
    failPreview = true;
    await form.getByRole("button", { name: "통합 결과 미리보기", exact: true }).click();
    await form.getByRole("alert").waitFor();
    assert.equal(await form.getByRole("button", { name: "대시보드에 저장", exact: true }).count(), 0);
    failPreview = false;
    await form.getByRole("button", { name: "통합 결과 미리보기", exact: true }).click();
    await form.getByText("계산 결과 250000원", { exact: true }).waitFor();
    await form.getByRole("checkbox").check();
    await form.getByRole("button", { name: "대시보드에 저장", exact: true }).click();
    await page.getByText("현금·카드 통합 결제액", { exact: true }).waitFor();
    assert.deepEqual(saved.definition, previews.at(-1));
    assert.equal(saved.refresh_interval_seconds, 3600);
    const artifactDir = path.join(__dirname, "artifacts");
    await fs.mkdir(artifactDir, { recursive: true });
    await page.screenshot({ path: path.join(artifactDir, "multi-metric.png"), fullPage: true, animations: "disabled" });
    await page.getByRole("combobox", { name: "현재 작업 가게" }).selectOption("store-b");
    await page.getByText("장부 관리에서 이 가게의 데이터를 먼저 등록해주세요.").waitFor({ state: "attached" });
    assert.equal(await page.getByText("현금·카드 통합 결제액", { exact: true }).count(), 0);
    assert.equal(await page.getByText("여러 장부의 결제액 합치기", { exact: true }).count(), 0);
    assert.deepEqual(errors, []);
    console.log("PASS: mapping, refund, preview, failure clears preview, save, schedule, store switch, no browser errors (API fixtures).");
  } finally { await browser.close(); }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
