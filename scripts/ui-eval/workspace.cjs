// Actual Next.js workspace with deterministic API fixtures; no live DB or LLM.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const deferred = () => { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; };

async function main() {
  const browser = await chromium.launch({ channel: process.env.BROWSER_CHANNEL || "msedge", headless: true });
  const artifacts = path.join(__dirname, "artifacts", "workspace");
  await fs.mkdir(artifacts, { recursive: true });
  const checks = [];
  const check = (label) => { checks.push(label); console.log(`PASS ${label}`); };
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" });
    page.setDefaultTimeout(12000);
    const errors = [], requests = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const stores = [{ id: "store-a", name: "성수점", description: "" }, { id: "store-b", name: "연남점", description: "" }];
    const chart = { chart_type: "bar", title: "일별 결제액", x_key: "day", y_key: "amount", unit: "KRW", data: [{ day: "9/1", amount: "120000.12" }, { day: "9/2", amount: "180000.34" }, { day: "9/3", amount: "210000.56" }] };
    const answer = (id, content = "성수점의 일별 결제액입니다.") => ({ message_id: id, role: "assistant", content, charts: [chart], steps: [], suggestions: [] });
    const conversations = { "store-a": [{ conversation_id: "old-a", title: "성수점 지난 분석", project_id: "store-a" }], "store-b": [{ conversation_id: "old-b", title: "연남점 지난 분석", project_id: "store-b" }] };
    const history = { "old-a": [answer("old-result-a", "성수점 과거 결과")], "old-b": [answer("old-result-b", "연남점 과거 결과")] };
    const widgets = { "store-a": [], "store-b": [] };
    let createGate, streamGate, messageGate, errorFrame = false, failCreate = false;
    let sent = 0, created = 0, layoutWrites = 0;
    await page.route("**/api/**", async (route) => {
      const request = route.request(), url = new URL(request.url()), p = url.pathname, method = request.method();
      requests.push({ p, method });
      let body = {}, status = 200;
      const headers = { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" };
      if (method === "OPTIONS") body = {};
      else if (p === "/api/auth/refresh") body = { access_token: "workspace-fixture", refresh_token: "workspace-fixture" };
      else if (p === "/api/uploads/capabilities") body = { direct_upload: false, max_size_bytes: 20 * 1024 * 1024 };
      else if (p === "/api/auth/me") body = { email: "owner@example.test" };
      else if (p === "/api/projects") body = { projects: stores };
      else if (p === "/api/library/files/sample-workspace") body = { project: null };
      else if (p.endsWith("/cash-entries")) body = { entries: [], total: 0 };
      else if (p.endsWith("/search-index")) body = { jobs: [], counts: {}, total: 0, search_enabled: false, worker_enabled: false, max_attempts: 3 };
      else if (p.endsWith("/tables")) body = { tables: [] };
      else if (p.endsWith("/ledger-sources")) body = { sources: [] };
      else if (p === "/api/conversations" && method === "GET") body = { conversations: conversations[url.searchParams.get("project_id")] || [] };
      else if (p === "/api/conversations" && method === "POST") {
        created++;
        if (createGate) { const gate = createGate; createGate = null; await gate.promise; }
        if (failCreate) { status = 500; body = { detail: "대화 생성 실패 테스트" }; }
        else {
          const store = request.postDataJSON().project_id;
          body = { conversation_id: `new-${created}`, title: "새 매출 분석", project_id: store };
          conversations[store].unshift(body);
        }
      } else if (p.endsWith("/messages/stream")) {
        sent++;
        const id = p.split("/")[3];
        if (streamGate) { const gate = streamGate; streamGate = null; await gate.promise; }
        const result = answer(`stream-${sent}`);
        history[id] = [result];
        const frame = errorFrame ? { type: "error", data: { message: "연결 중단 테스트" } } : { type: "done", data: result };
        await route.fulfill({ contentType: "text/event-stream", headers, body: `data: ${JSON.stringify({ type: "heartbeat" })}\n\ndata: ${JSON.stringify(frame)}\n\n` }).catch(() => {});
        return;
      } else if (p.endsWith("/messages")) {
        const id = p.split("/")[3];
        if (messageGate) { const gate = messageGate; messageGate = null; await gate.promise; }
        body = { messages: history[id] || [] };
      } else if (p === "/api/dashboard/widgets/layout") { layoutWrites++; body = { ok: true }; }
      else if (p === "/api/dashboard/widgets" && method === "POST") {
        body = { ...request.postDataJSON(), id: "widget-1" }; widgets[body.project_id].push(body);
      } else if (p === "/api/dashboard/widgets") body = { widgets: widgets[url.searchParams.get("project_id")] || [] };
      else { errors.push(`Unexpected fixture request: ${method} ${p}`); status = 404; }
      await route.fulfill({ status, contentType: "application/json", headers, body: JSON.stringify(body) }).catch(() => {});
    });
    await page.addInitScript(() => localStorage.setItem("dataez_refresh_token", "workspace-fixture"));
    await page.goto(process.env.UI_BASE_URL || "http://127.0.0.1:3132/dashboard");
    const main = page.locator("#workspace-main");
    const input = () => page.getByRole("textbox", { name: "분석 요청", exact: true });
    await page.getByRole("combobox", { name: "현재 작업 가게" }).waitFor();
    assert.equal(created, 0);
    assert.equal(await page.locator("html").getAttribute("class"), "dark");
    assert.equal(await page.evaluate(() => getComputedStyle(document.body).backgroundColor), "rgb(25, 27, 31)");
    check("dark Charcoal + Blue default; no empty conversation created on entry");

    await page.getByRole("button", { name: "새 분석", exact: true }).click();
    await input().fill("카드와 현금 매출을 비교해줘");
    await page.locator('#workspace-chat input[type="file"]').setInputFiles({ name: "payments.csv", mimeType: "text/csv", buffer: Buffer.from("date,amount\n2026-09-01,120000") });
    await page.getByRole("button", { name: "AI 채팅 닫기", exact: true }).click();
    await page.getByRole("button", { name: "대시보드", exact: true }).click();
    await page.getByRole("button", { name: "분석 이력", exact: true }).click();
    await page.locator("#workspace-chat-toggle").click();
    assert.equal(await input().inputValue(), "카드와 현금 매출을 비교해줘");
    await page.getByText("payments.csv", { exact: true }).waitFor();
    assert.equal(created, 0);
    check("draft and attachment survive close and navigation without server writes");

    await input().dispatchEvent("keydown", { key: "Enter", code: "Enter", isComposing: true });
    assert.equal(sent, 0);
    const inflight = deferred(); streamGate = inflight;
    await page.getByRole("button", { name: "분석 요청 보내기" }).click();
    await page.waitForFunction(() => document.querySelector('[aria-label="분석 요청 보내기"]')?.disabled);
    await page.getByRole("button", { name: "AI 채팅 닫기", exact: true }).click();
    inflight.resolve();
    await page.locator("#workspace-chat-toggle").click();
    await page.getByRole("button", { name: /일별 결제액.*결과 보기/ }).click();
    await main.getByText("성수점의 일별 결제액입니다.", { exact: true }).waitFor();
    assert.equal(sent, 1);
    check("Korean IME Enter does not send; hiding chat preserves in-flight result");
    await main.locator('[data-chart-ready="true"] svg').first().waitFor();
    await page.mouse.move(900, 100);
    await page.screenshot({ path: path.join(artifacts, "workspace-dark.png"), animations: "disabled" });

    await page.getByRole("combobox", { name: "화면 테마" }).selectOption("light");
    assert.equal(await page.evaluate(() => getComputedStyle(document.body).backgroundColor), "rgb(245, 247, 250)");
    await page.waitForFunction(() => [...document.querySelectorAll("#workspace-main [data-chart-engine] svg path")].some(bar => getComputedStyle(bar).fill === "rgb(36, 91, 181)"));
    const chartHost = main.locator('[data-chart-ready="true"]').first();
    await chartHost.focus(); await chartHost.press("ArrowRight");
    const tooltip = main.locator(".dataez-chart-tooltip").first();
    await tooltip.getByText("120,000.12원", { exact: true }).waitFor();
    assert.equal(await tooltip.evaluate((node) => getComputedStyle(node).backgroundColor), "rgb(255, 255, 255)");
    await page.screenshot({ path: path.join(artifacts, "workspace-light.png"), animations: "disabled" });
    check("light palette reaches chart and tooltip; exact decimal amount preserved");

    await main.getByRole("button", { name: "대시보드에 저장" }).click();
    await main.getByRole("button", { name: "이 설정으로 저장", exact: true }).click();
    await main.getByText("저장 완료", { exact: true }).waitFor();
    assert.equal(widgets["store-a"][0].project_id, "store-a");
    assert.equal(widgets["store-a"][0].widget_data.data[0].amount, "120000.12");
    await page.getByRole("button", { name: "대시보드", exact: true }).click();
    await main.getByText("일별 결제액", { exact: true }).waitFor();
    const beforeToggle = layoutWrites;
    await page.getByRole("button", { name: "AI 채팅 닫기", exact: true }).click();
    await delay(500);
    assert.equal(layoutWrites, beforeToggle, "chat width change must not rewrite saved layout");
    const handle = main.locator(".widget-drag-handle").first();
    const box = await handle.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down(); await page.mouse.move(box.x + 110, box.y + 20, { steps: 10 }); await page.mouse.up();
    await delay(200);
    assert.ok(layoutWrites > beforeToggle);
    const beforeResize = layoutWrites;
    await main.locator(".react-resizable-handle").first().scrollIntoViewIfNeeded();
    const resize = await main.locator(".react-resizable-handle").first().boundingBox();
    await page.mouse.move(resize.x + resize.width / 2, resize.y + resize.height / 2);
    await page.mouse.down(); await page.mouse.move(resize.x - 90, resize.y + 100, { steps: 10 }); await page.mouse.up();
    await delay(200);
    assert.ok(layoutWrites > beforeResize);
    check("saving targets selected store; drag/resize persist, chat width change does not");

    await page.reload();
    await page.getByRole("combobox", { name: "현재 작업 가게" }).waitFor();
    assert.equal(await page.locator("html").getAttribute("class"), "light");
    await page.getByRole("combobox", { name: "화면 테마" }).selectOption("system");
    await page.emulateMedia({ colorScheme: "dark" });
    await page.waitForFunction(() => document.documentElement.classList.contains("dark"));
    await page.emulateMedia({ colorScheme: "light" });
    await page.waitForFunction(() => document.documentElement.classList.contains("light"));
    check("theme persists on reload and follows live system changes");

    await page.getByRole("button", { name: "분석 이력", exact: true }).click();
    await main.getByRole("button", { name: /성수점 지난 분석/ }).click();
    await main.getByText("성수점 과거 결과", { exact: true }).waitFor();
    await input().fill("후속 질문 초안");
    await page.getByRole("button", { name: "데이터 관리", exact: true }).click();
    await page.getByRole("region", { name: "검색 갱신 상태" }).waitFor();
    assert.equal(await input().inputValue(), "후속 질문 초안");
    await page.getByRole("button", { name: /일별 결제액.*결과 보기/ }).click();
    await main.getByText("성수점 과거 결과", { exact: true }).waitFor();
    check("history resumes centrally; result and unsent follow-up survive data navigation");
    const refreshCount = requests.filter((item) => item.p === "/api/auth/refresh").length;
    // Isolate same-store review navigation from the ledger review API fixtures.
    await main.evaluate((node) => { const link = document.createElement("a"); link.href = "/dashboard?project=store-a&section=tables"; link.textContent = "검토 연결 테스트"; node.append(link); });
    await main.getByRole("link", { name: "검토 연결 테스트" }).click();
    await page.getByRole("region", { name: "검색 갱신 상태" }).waitFor();
    assert.equal(await input().inputValue(), "후속 질문 초안");
    assert.equal(requests.filter((item) => item.p === "/api/auth/refresh").length, refreshCount);
    check("same-store review link opens data without reloading or losing the composer");


    const oldMessages = deferred(); messageGate = oldMessages;
    await page.getByRole("button", { name: "분석 이력", exact: true }).click();
    await main.getByRole("button", { name: /성수점 지난 분석/ }).click();
    await page.getByRole("combobox", { name: "현재 작업 가게" }).selectOption("store-b");
    oldMessages.resolve();
    await page.getByRole("button", { name: "분석 이력", exact: true }).click();
    await main.getByRole("button", { name: /연남점 지난 분석/ }).click();
    await main.getByText("연남점 과거 결과", { exact: true }).waitFor();
    assert.equal(await page.getByText("성수점 과거 결과", { exact: true }).count(), 0);
    assert.equal(await input().inputValue(), "");
    check("late history response cannot enter another store; composer scope resets");

    const oldStream = deferred(); streamGate = oldStream;
    await input().fill("늦은 응답 테스트");
    await page.getByRole("button", { name: "분석 요청 보내기" }).click();
    await page.getByRole("combobox", { name: "현재 작업 가게" }).selectOption("store-a");
    oldStream.resolve();
    await page.getByRole("button", { name: "새 분석", exact: true }).click();
    await input().fill("새 가게 초안");
    await delay(300);
    assert.equal(await page.getByText("성수점의 일별 결제액입니다.", { exact: true }).count(), 0);
    assert.equal(await input().inputValue(), "새 가게 초안");
    check("late streaming response cannot enter the replacement workspace");

    const pendingCreate = deferred(); createGate = pendingCreate;
    const sentBeforeCreate = sent;
    await page.getByRole("button", { name: "분석 요청 보내기" }).click();
    await page.getByRole("button", { name: "새 분석", exact: true }).click();
    await input().fill("새 대화의 입력");
    pendingCreate.resolve(); await delay(300);
    assert.equal(sent, sentBeforeCreate);
    assert.equal(await input().inputValue(), "새 대화의 입력");
    check("new analysis invalidates a pending conversation creation");

    failCreate = true;
    await page.getByRole("button", { name: "분석 요청 보내기" }).click();
    await page.locator("#workspace-chat").getByText("대화 생성 실패 테스트", { exact: true }).waitFor();
    assert.equal(await input().inputValue(), "새 대화의 입력");
    failCreate = false; errorFrame = true;
    await page.getByRole("button", { name: "분석 요청 보내기" }).click();
    await page.locator("#workspace-chat").getByText("연결 중단 테스트", { exact: true }).waitFor();
    const afterError = sent; await delay(200); assert.equal(sent, afterError);
    errorFrame = false;
    check("creation failure keeps input; stream failure is visible and never auto-retried");

    await page.getByRole("button", { name: "새 분석", exact: true }).click();
    await input().fill("모바일에서도 유지할 질문");
    await page.locator('#workspace-chat input[type="file"]').setInputFiles({ name: "mobile.csv", mimeType: "text/csv", buffer: Buffer.from("amount\n100") });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("dialog").waitFor();
    assert.equal(await input().inputValue(), "모바일에서도 유지할 질문");
    await page.getByText("mobile.csv", { exact: true }).waitFor();
    for (let i = 0; i < 15; i++) await page.keyboard.press("Tab");
    assert.equal(await page.evaluate(() => !!document.activeElement?.closest('[role="dialog"]')), true);
    await page.screenshot({ path: path.join(artifacts, "workspace-mobile-chat.png"), animations: "disabled" });
    await page.keyboard.press("Escape");
    await page.getByRole("dialog").waitFor({ state: "hidden" });
    assert.equal(await page.evaluate(() => document.activeElement?.id), "workspace-chat-toggle");
    await page.locator("#workspace-chat-toggle").click();
    assert.equal(await input().inputValue(), "모바일에서도 유지할 질문");
    await page.keyboard.press("Escape");
    await page.getByRole("dialog").waitFor({ state: "hidden" });
    await page.getByRole("button", { name: "작업 메뉴 열기" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "분석 이력", exact: true }).click();
    await page.getByRole("dialog").waitFor({ state: "hidden" });
    check("mobile chat keeps composer/file, traps focus, Escape restores trigger; mobile menu works");
    for (const width of [320, 390, 768, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `page overflow at ${width}`);
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: path.join(artifacts, "workspace-mobile.png"), animations: "disabled" });
    assert.deepEqual(errors, []);
    check("320–1440px page containment; zero browser errors or unexpected API requests");
    await fs.writeFile(path.join(artifacts, "results.json"), JSON.stringify({ checks, sent, created, layoutWrites, errors, fixtureOnly: true }, null, 2));
    console.log(`${checks.length} workspace checks passed (API fixtures).`);
  } finally { await browser.close(); }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
