// Real frontend with local API fixtures; no account, database, or LLM required.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const baseUrl = process.env.UI_BASE_URL || "http://127.0.0.1:3146";
const siteUrl = process.env.EXPECTED_SITE_URL || "http://localhost:3000";
const output = path.join(__dirname, "artifacts", "brand");
const results = [], failures = [];

async function capture(page, label) {
  if (label.startsWith("dashboard-")) await page.locator("#workspace-main").getByText("파일이 없어도 먼저 경험해보세요", { exact: true }).waitFor();
  await page.evaluate(() => document.fonts.ready);
  await page.mouse.move(page.viewportSize().width - 1, 1);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${label}: horizontal overflow`);
  await page.screenshot({ path: path.join(output, `${label}.png`), fullPage: true, animations: "disabled" });
  results.push(label);
  console.log(`PASS ${label}`);
}

async function checkLogo(logo, theme, symbolOnly = false) {
  await logo.waitFor({ state: "visible" });
  await logo.page().waitForFunction(({ svg, box, ink, minWidth }) =>
    svg.getAttribute("viewBox") === box && getComputedStyle(svg).color === ink && svg.getBoundingClientRect().width >= minWidth,
  { svg: await logo.elementHandle(), box: symbolOnly ? "0 0 64 64" : "0 0 320 64", ink: theme === "dark" ? "rgb(242, 244, 247)" : "rgb(32, 38, 47)", minWidth: symbolOnly ? 16 : 120 });
  const details = await logo.evaluate((svg) => ({
    width: svg.getBoundingClientRect().width, viewBox: svg.getAttribute("viewBox"),
    ink: getComputedStyle(svg).color, accent: getComputedStyle(svg.querySelector("path")).stroke,
  }));
  assert.ok(details.width >= (symbolOnly ? 16 : 120), `logo minimum size: ${JSON.stringify(details)}`);
  assert.equal(details.viewBox, symbolOnly ? "0 0 64 64" : "0 0 320 64");
  assert.equal(details.ink, theme === "dark" ? "rgb(242, 244, 247)" : "rgb(32, 38, 47)");
  assert.equal(details.accent, theme === "dark" ? "rgb(130, 180, 255)" : "rgb(36, 91, 181)");
}

async function installFixtures(page) {
  await page.route("**/api/**", async (route) => {
    const request = route.request(), p = new URL(request.url()).pathname;
    let body;
    if (request.method() === "OPTIONS") body = {};
    else if (["/api/auth/login", "/api/auth/refresh"].includes(p)) body = { access_token: "brand-fixture", refresh_token: "brand-fixture" };
    else if (p === "/api/auth/me") body = { email: "brand@example.test" };
    else if (p === "/api/projects") body = { projects: [{ id: "brand-store", name: "성수점", description: "" }] };
    else if (p.endsWith("/tables")) body = { tables: [] };
    else if (p === "/api/conversations") body = { conversations: [] };
    else if (p === "/api/dashboard/widgets") body = { widgets: [] };
    else if (p === "/api/library/files/sample-workspace") body = { project: null };
    else if (p.endsWith("/cash-entries")) body = { entries: [], total: 0 };
    else if (p.endsWith("/ledger-sources")) body = { sources: [] };
    else { failures.push(`Unexpected API request: ${request.method()} ${p}`); await route.abort(); return; }
    await route.fulfill({ json: body, headers: { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" } });
  });
}

async function main() {
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({ channel: process.env.BROWSER_CHANNEL || "chrome", headless: true });
  try {
    for (const theme of ["dark", "light"]) {
      const context = await browser.newContext({ viewport: { width: 1600, height: 1000 }, colorScheme: theme, reducedMotion: "reduce", locale: "ko-KR" });
      await context.addInitScript((value) => localStorage.setItem("theme", value), theme);
      const page = await context.newPage();
      page.setDefaultTimeout(15000);
      page.on("pageerror", (error) => failures.push(error.message));
      page.on("response", (response) => { if (response.status() >= 400) failures.push(`${response.status()} ${response.url()}`); });
      await installFixtures(page);
      await page.goto(baseUrl);
      await page.getByLabel("이메일", { exact: true }).waitFor();
      assert.equal(await page.title(), "DATA:EZ — 흩어진 매출을, 한눈에");
      for (const selector of ['meta[property="og:image"]', 'meta[name="twitter:image"]']) {
        assert.equal(await page.locator(selector).getAttribute("content"), new URL("/og-dataez.png", siteUrl).href);
      }
      const share = await page.request.get(`${baseUrl}/og-dataez.png`);
      assert.equal(share.status(), 200);
      const png = await share.body();
      assert.equal(png.readUInt32BE(16), 1200); assert.equal(png.readUInt32BE(20), 630);
      assert.equal((await page.request.get(`${baseUrl}/favicon.svg`)).status(), 200);
      for (const [width, height] of [[1600, 1000], [1024, 600], [768, 1024], [390, 844], [320, 568]]) {
        await page.setViewportSize({ width, height });
        await checkLogo(page.locator('svg[aria-label="DATA:EZ"]:visible'), width >= 1024 ? "dark" : theme);
        if (width >= 1024) {
          const children = await page.locator(".brand-login-panel > .relative").evaluateAll((nodes) => nodes.map((node) => {
            const rect = node.getBoundingClientRect(); return { top: rect.top, bottom: rect.bottom };
          }));
          assert.ok(children[1].top - children[0].bottom >= 39, "brand logo clear space on short screens");
          assert.ok(children[2].top - children[1].bottom >= 39, "brand footer clear space on short screens");
        }
        await capture(page, `login-${theme}-${width}`);
        if (width <= 390) {
          await page.getByRole("button", { name: "회원가입", exact: true }).click();
          await page.getByLabel("이름", { exact: true }).waitFor();
          await capture(page, `signup-${theme}-${width}`);
          await page.getByRole("button", { name: "로그인", exact: true }).click();
        }
      }
      await page.setViewportSize({ width: 1600, height: 1000 });
      await page.getByLabel("이메일", { exact: true }).fill("brand@example.test");
      await page.getByLabel("비밀번호", { exact: true }).fill("local-fixture-only");
      await page.locator('button[type="submit"]').click();
      await page.waitForURL("**/dashboard");
      const brandButton = page.getByRole("button", { name: "DATA:EZ 대시보드", exact: true });
      await checkLogo(brandButton.locator("svg"), theme);
      await page.getByRole("combobox", { name: "현재 작업 가게" }).waitFor();
      await capture(page, `dashboard-${theme}-1600`);
      await page.getByRole("button", { name: "메뉴 접기", exact: true }).click();
      await checkLogo(brandButton.locator("svg"), theme, true);
      assert.ok(await brandButton.evaluate((button) => {
        const mark = button.querySelector("svg").getBoundingClientRect();
        const sidebar = button.parentElement.getBoundingClientRect();
        return Math.abs(mark.x + mark.width / 2 - (sidebar.x + sidebar.width / 2)) < 1;
      }), "collapsed mark is centered");
      await page.getByRole("button", { name: "분석 이력", exact: true }).click();
      await brandButton.click();
      assert.equal(await page.locator("header h1").innerText(), "대시보드");
      await capture(page, `dashboard-${theme}-collapsed`);
      const opposite = theme === "dark" ? "light" : "dark";
      await page.getByRole("combobox", { name: "화면 테마" }).selectOption(opposite);
      await checkLogo(brandButton.locator("svg"), opposite, true);
      await page.getByRole("button", { name: "메뉴 펼치기", exact: true }).click();
      await checkLogo(brandButton.locator("svg"), opposite);
      await page.getByRole("combobox", { name: "화면 테마" }).selectOption(theme);
      for (const [width, height] of [[768, 1024], [390, 844], [320, 568]]) {
        await page.setViewportSize({ width, height });
        await capture(page, `dashboard-${theme}-${width}`);
        if (width < 768) {
          await page.getByRole("button", { name: "작업 메뉴 열기", exact: true }).click();
          const drawer = page.getByRole("dialog", { name: "작업 메뉴", exact: true });
          await checkLogo(drawer.locator('svg[aria-label="DATA:EZ"]'), theme);
          const logoBox = await drawer.getByRole("button", { name: "DATA:EZ 대시보드" }).boundingBox();
          const closeBox = await drawer.getByRole("button", { name: "Close", exact: true }).boundingBox();
          assert.ok(logoBox.x + logoBox.width < closeBox.x, "mobile logo must clear drawer close button");
          await capture(page, `dashboard-${theme}-${width}-menu`);
          await drawer.getByRole("button", { name: "DATA:EZ 대시보드" }).click();
          await drawer.waitFor({ state: "hidden" });
          assert.equal(await page.locator("#workspace-menu-toggle").evaluate((el) => el === document.activeElement), true);
        }
      }
      await context.close();
    }
    assert.deepEqual(failures, [], "browser/API errors");
    await fs.writeFile(path.join(output, "results.json"), JSON.stringify({ baseUrl, siteUrl, checks: results, errors: failures }, null, 2));
    console.log(`PASS ${results.length} brand screenshots; themes, navigation, metadata, and responsive checks`);
  } finally { await browser.close(); }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
