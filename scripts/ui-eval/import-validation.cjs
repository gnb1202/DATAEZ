// Actual upload modal with API fixtures: an error must preserve the user's file.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");

async function main() {
  const browser = await chromium.launch({ channel: process.env.BROWSER_CHANNEL || "msedge", headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    let attempts = 0;
    await page.route("**/api/**", async (route) => {
      const p = new URL(route.request().url()).pathname;
      let body = {}, status = 200;
      if (p === "/api/auth/refresh") body = { access_token: "ui-fixture", refresh_token: "ui-fixture" };
      else if (p === "/api/uploads/capabilities") body = { direct_upload: false, max_size_bytes: 20 * 1024 * 1024 };
      else if (p === "/api/library/files/sample-workspace") body = { project: null };
      else if (p === "/api/auth/me") body = { email: "ui@example.test" };
      else if (p === "/api/projects") body = { projects: [{ id: "store-a", name: "강남점", description: "" }] };
      else if (p.endsWith("/cash-entries")) body = { entries: [], total: 0 };
      else if (p.endsWith("/search-index")) body = { jobs: [], counts: {}, total: 0, search_enabled: false, worker_enabled: false, max_attempts: 3 };
      else if (p.endsWith("/tables")) body = { tables: [] };
      else if (p.endsWith("/ledger-sources")) body = { sources: [] };
      else if (p === "/api/dashboard/widgets") body = { widgets: [] };
      else if (p.endsWith("/tables/import")) {
        attempts++;
        status = 422;
        body = { detail: "3행 amount: 정수 컬럼에 소수를 저장할 수 없습니다.", issues: [{ row: 3, column: "amount" }] };
      } else if (p.includes("/conversations")) body = { conversations: [] };
      else throw new Error(`Unexpected API request: ${p}`);
      await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body), headers: { "access-control-allow-origin": "*" } });
    });
    await page.addInitScript(() => localStorage.setItem("dataez_refresh_token", "ui-fixture"));
    await page.goto(process.env.UI_BASE_URL || "http://127.0.0.1:3100/dashboard");
    await page.getByRole("button", { name: "데이터 관리", exact: true }).click();
    await page.getByRole("button", { name: "CSV 가져오기", exact: true }).first().click();
    const dialog = page.getByRole("dialog");
    await dialog.locator('input[type="file"]').setInputFiles({ name: "ledger.csv", mimeType: "text/csv", buffer: Buffer.from("amount\n1\n1.2\n") });
    await dialog.getByRole("button", { name: "가져오기", exact: true }).click();
    await dialog.getByRole("alert").waitFor();
    assert.match(await dialog.getByRole("alert").innerText(), /3행 amount/);
    assert.equal(await dialog.isVisible(), true);
    assert.equal(await dialog.getByLabel("장부 이름", { exact: true }).inputValue(), "ledger");
    assert.equal(await dialog.getByRole("button", { name: "가져오기", exact: true }).isEnabled(), true);
    await dialog.getByRole("button", { name: "가져오기", exact: true }).click();
    await dialog.getByRole("alert").waitFor();
    assert.equal(attempts, 2);
    assert.deepEqual(errors, []);
    console.log("PASS: import error displays row/column, modal and file stay available, retry works (API fixtures).");
  } finally { await browser.close(); }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
