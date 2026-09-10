const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const [accessPath, baseUrl, outputDir] = process.argv.slice(2);

if (!accessPath || !baseUrl || !outputDir) {
  throw new Error("Usage: node brand-dashboard-screenshot.cjs <access.json> <base-url> <output-dir>");
}

const origin = new URL(baseUrl).origin;
const access = JSON.parse(fs.readFileSync(accessPath, "utf8"));
fs.mkdirSync(outputDir, { recursive: true });

async function capture(browser, theme) {
  const context = await browser.newContext({
    viewport: { width: 1600, height: 1000 },
    colorScheme: theme,
    locale: "ko-KR",
  });
  const page = await context.newPage();
  await page.addInitScript((value) => localStorage.setItem("theme", value), theme);
  await page.goto(origin, { waitUntil: "domcontentloaded" });
  await page.getByLabel("이메일").fill(access.email);
  await page.getByLabel("비밀번호").fill(access.password);
  await page.getByRole("button", { name: "로그인", exact: true }).last().click();
  await page.waitForSelector('button[aria-label="DATA:EZ 대시보드"]', { timeout: 20000 });
  await page.waitForTimeout(1200);
  await page.screenshot({ path: path.join(outputDir, `dashboard-${theme}.png`) });

  if (theme === "dark") {
    await page.getByRole("button", { name: "메뉴 접기" }).click();
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(outputDir, "dashboard-dark-collapsed.png") });
  }

  await context.close();
}

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    await capture(browser, "dark");
    await capture(browser, "light");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
