// Real Next.js UI, deterministic API fixtures. Server concurrency is tested in PostgreSQL separately.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function main() {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const artifacts = path.join(__dirname, "artifacts", "analysis-dashboard");
  await fs.mkdir(artifacts, { recursive: true });
  const checks = [], errors = [], saves = [];
  const pass = name => { checks.push(name); console.log(`PASS ${name}`); };
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1080 }, reducedMotion: "reduce" });
    page.setDefaultTimeout(12000);
    page.on("pageerror", error => errors.push(error.message));
    const definition = { version: 1, table_id: "table-a", operation: "sum", column: "amount", group_by: "paid_at", date_grain: "day", time_range: "all", date_column: "paid_at", unit: "KRW" };
    const chart = { chart_type: "line", title: "9월 일별 결제액", x_key: "dimension", y_key: "value", unit: "KRW", metric_definition: definition, source_table_name: "결제 누적 장부", period_label: "2026.09.01 – 2026.09.07", calculation_label: "결제·취소 발생일 기준 · 원본 부호 유지 · 수수료 차감 전", calculated_at: "2026-09-10T02:30:00Z", execution: { sql: 'SELECT paid_at::date, sum(amount) FROM payments GROUP BY 1', parameters: [], timezone: "Asia/Seoul" }, data: [210000, 330000, 290000, 420000, 380000, 570000, 620000].map((n, i) => ({ dimension: `09/${String(i + 1).padStart(2, "0")}`, value: `${n}.12` })) };
    const sources = [{ type: "meta", tool_name: "library_references", tool_output: { files: [{ file_id: "file-a", filename: "성수점_9월_카드매출.csv", kind: "ledger", project_id: "store-a", project_name: "성수점", table_id: "table-a", table_name: "결제 누적 장부" }] } }];
    const answer = (id, charts = [chart], steps = sources) => ({ message_id: id, role: "assistant", content: "결제와 취소를 발생일별로 합산했습니다. 연결 장부 전체에 지정한 기간을 적용한 결과입니다.", charts, steps });
    const original = answer("result-1");
    let result = original, fail = false, lost = false, slow = false, schedules = 0, refreshes = 0;
    const widgets = [{ id: "kpi-1", project_id: "store-a", widget_type: "kpi", title: "9월 순결제액", widget_data: { value: "2820000.84", formatted: "2,820,000.84원", label: "결제·취소 금액 합계", metric_definition: { ...definition, group_by: null }, period_label: chart.period_label, source_table_name: chart.source_table_name, calculated_at: chart.calculated_at }, layout: { x: 0, y: 0, w: 4, h: 5 }, refresh_interval_seconds: 3600 }];
    const headers = { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" };
    await page.route("**/api/**", async route => {
      const request = route.request(), url = new URL(request.url()), p = url.pathname, method = request.method();
      let body = {}, status = 200;
      if (method === "OPTIONS") {}
      else if (p === "/api/auth/refresh") body = { access_token: "fixture", refresh_token: "fixture" };
      else if (p === "/api/auth/me") body = { email: "owner@example.test" };
      else if (p === "/api/projects") body = { projects: [{ id: "store-a", name: "성수점" }, { id: "store-b", name: "연남점" }] };
      else if (p === "/api/library/files/sample-workspace") body = { project: null };
      else if (p.endsWith("/tables")) body = { tables: [] };
      else if (p.endsWith("/ledger-sources")) body = { sources: [] };
      else if (p === "/api/conversations") body = { conversations: [{ conversation_id: "history", title: "9월 결제액 분석" }] };
      else if (p.endsWith("/metrics/preview")) body = { ...chart, metric_definition: request.postDataJSON().definition };
      else if (p.endsWith("/messages")) body = { messages: [result] };
      else if (method === "POST" && (p.endsWith("/metrics") || p === "/api/dashboard/widgets")) {
        const data = request.postDataJSON(); saves.push(data);
        const shouldLose = lost, shouldFail = fail;
        if (slow) await pause(600);
        if (shouldFail) { status = 503; body = { detail: "저장 연결 실패 테스트" }; }
        else {
          let widget = widgets.find(w => w.save_key === data.save_key);
          if (!widget) { widget = { ...data, id: `saved-${saves.length}`, widget_type: "chart", widget_data: data.widget_data || result.charts[0], layout: { x: 4, y: 0, w: 8, h: 7 }, refresh_interval_seconds: 0 }; widgets.push(widget); }
          body = widget;
          if (shouldLose) { await route.abort("failed"); return; }
        }
      } else if (p.endsWith("/schedule")) { schedules++; body = { refresh_interval_seconds: request.postDataJSON().refresh_interval_seconds }; }
      else if (p.endsWith("/refresh")) { refreshes++; body = { widget_data: chart }; }
      else if (p.startsWith("/api/dashboard/widgets/") && method === "DELETE") { widgets.splice(widgets.findIndex(w => w.id === p.split("/").at(-1)), 1); }
      else if (p === "/api/dashboard/widgets") body = { widgets: url.searchParams.get("project_id") === "store-a" ? widgets : [] };
      else { errors.push(`Unexpected request ${method} ${p}`); status = 404; }
      await route.fulfill({ status, headers, contentType: "application/json", body: JSON.stringify(body) }).catch(() => {});
    });
    await page.addInitScript(() => localStorage.setItem("dataez_refresh_token", "fixture"));
    await page.goto(process.env.UI_BASE_URL || "http://127.0.0.1:3132/dashboard");
    const main = page.locator("#workspace-main");
    const openResult = async () => {
      await page.getByRole("button", { name: "분석 이력", exact: true }).click();
      await main.getByRole("button", { name: /9월 결제액 분석/ }).click();
      await main.getByRole("region", { name: `${result.charts[0].title} 분석 결과`, exact: true }).waitFor();
      await page.waitForFunction(() => !document.querySelector('#workspace-main button')?.textContent?.includes("저장 상태 확인 중"));
    };
    const prepareSave = async () => {
      await main.getByRole("button", { name: "대시보드에 저장", exact: true }).click();
      if (result.charts[0].metric_definition) {
        await main.getByRole("button", { name: "설정으로 미리보기", exact: true }).click();
        await main.getByLabel("저장 전 미리보기").waitFor();
      }
    };
    const ready = () => main.locator('[data-chart-ready="true"]').first().waitFor();
    await openResult(); await ready();
    await main.getByText("결제 누적 장부", { exact: false }).first().waitFor();
    await main.getByText("누적 장부 전체 · 결제 누적 장부").waitFor();
    await page.screenshot({ path: path.join(artifacts, "analysis-dark.png"), animations: "disabled" });
    pass("result shows source, period, ledger scope and line chart before explanation");

    await main.getByRole("button", { name: `${chart.title} 집계표·SQL` }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByText("210,000.12원", { exact: true }).waitFor();
    await dialog.getByText("실행 SQL과 매개변수", { exact: true }).click();
    await dialog.getByText(chart.execution.sql, { exact: true }).waitFor();
    await page.screenshot({ path: path.join(artifacts, "analysis-evidence.png"), animations: "disabled" });
    await page.keyboard.press("Escape");
    pass("exact data and recorded SQL remain accessible on demand");

    slow = true;
    await prepareSave();
    await main.getByLabel("저장 집계 기간",{exact:true}).selectOption("last_month");
    assert.equal(await main.getByRole("button",{name:"이 설정으로 저장",exact:true}).isEnabled(),false);
    await main.getByRole("button",{name:"설정으로 미리보기",exact:true}).click();
    await main.getByLabel("저장 전 미리보기").waitFor();
    await main.getByRole("button", { name: "이 설정으로 저장", exact: true }).dblclick();
    await main.getByRole("button", { name: "저장 중…", exact: true }).first().waitFor();
    await main.getByText("저장 완료", { exact: true }).waitFor();
    assert.equal(saves.length, 1);
    assert.equal(saves[0].definition.time_range,"last_month");
    assert.equal(saves[0].definition.unit,"KRW");
    pass("period changes invalidate preview and only reviewed period/unit are submitted");
    slow = false;
    await main.getByRole("button", { name: "대시보드에서 보기" }).click();
    await page.waitForFunction(() => document.activeElement?.id.startsWith("dashboard-widget-saved-"));
    await main.locator('[data-chart-ready="true"]').waitFor();
    assert.ok(await main.evaluate(el => el.scrollLeft === 0 && el.scrollWidth <= el.clientWidth + 1), "saved widget must fit the measured grid without horizontal scrolling");
    await page.getByRole("button", { name: "AI 채팅 닫기", exact: true }).click();
    await pause(100);
    await main.evaluate(el => el.scrollTo({ top: 0, left: 0 }));
    await page.screenshot({ path: path.join(artifacts, "dashboard-dark.png"), animations: "disabled" });
    await main.getByRole("combobox", { name: `${chart.title} 갱신 주기` }).selectOption("86400");
    await main.getByRole("button", { name: `${chart.title} 재계산` }).click();
    await page.waitForFunction(() => !document.querySelector('[aria-label="9월 일별 결제액 재계산"]')?.disabled);
    assert.equal(schedules, 1); assert.equal(refreshes, 1);
    pass("double click makes one save; saved widget receives focus; refresh and schedule remain usable");
    await page.getByRole("combobox", { name: "화면 테마" }).selectOption("light");
    await page.waitForFunction(() => [...document.querySelectorAll('[data-chart-engine] svg path')].some(p => getComputedStyle(p).stroke === "rgb(36, 91, 181)"));
    await page.screenshot({ path: path.join(artifacts, "dashboard-light.png"), animations: "disabled" });
    await page.reload(); await openResult();
    await main.getByRole("button", { name: "대시보드에서 보기" }).waitFor();
    assert.equal(saves.length, 1);
    pass("saved state survives reload and history reopening");

    result = answer("retry-result"); fail = true;
    await openResult();
    await prepareSave();
    await main.getByRole("button", { name: "이 설정으로 저장", exact: true }).click();
    await main.getByRole("alert").getByText("저장 연결 실패 테스트").waitFor();
    fail = false;
    await main.getByRole("button", { name: "같은 설정으로 다시 시도", exact: true }).click();
    await main.getByText("저장 완료", { exact: true }).waitFor();
    assert.equal(saves.at(-1).save_key, saves.at(-2).save_key);
    assert.deepEqual(saves.at(-1),saves.at(-2));
    pass("failed save is visible; retry reuses its stable key");

    result = answer("lost-response"); lost = true;
    await openResult(); const beforeLost = saves.length;
    await prepareSave();
    await main.getByRole("button", { name: "이 설정으로 저장", exact: true }).click();
    await main.getByText("저장 완료", { exact: true }).waitFor();
    assert.equal(saves.length, beforeLost + 1); lost = false;
    pass("lost response reconciles committed save without a second write");

    result = answer("agent-saved", [chart], [{ type: "tool_result", tool_name: "save_metric", tool_output: { saved: true, metric_id: widgets[1].id, definition } }]);
    await openResult();
    await main.getByRole("button", { name: "대시보드에서 보기" }).waitFor();
    pass("a metric already saved by the AI is recognized by its result and ID");

    await main.getByRole("button", { name: "대시보드에서 보기" }).click();
    await main.locator(`#dashboard-widget-${widgets[1].id}`).getByRole("button", { name: "위젯 삭제", exact: true }).click();
    await openResult();
    await main.getByRole("button", { name: "대시보드에 저장", exact: true }).waitFor();
    pass("deleting a saved widget clears its saved status when the result is reopened");

    result = answer("late-save"); slow = true;
    await openResult();
    await prepareSave();
    await main.getByRole("button", { name: "이 설정으로 저장", exact: true }).click();
    await main.getByRole("button", { name: "저장 중…", exact: true }).first().waitFor();
    await page.getByRole("combobox", { name: "현재 작업 가게" }).selectOption("store-b");
    await pause(800);
    assert.equal(await main.getByText("저장 완료", { exact: true }).count(), 0);
    assert.equal(await main.getByText(chart.title, { exact: true }).count(), 0);
    slow = false;
    await page.getByRole("combobox", { name: "현재 작업 가게" }).selectOption("store-a");
    pass("late save completion never changes the replacement store workspace");

    const huge = "9007199254740993.01", hostile = '<img src=x onerror="window.chartXss=1">';
    const cases = [
      { ...chart, metric_definition: undefined, execution: undefined, chart_type: "bar", title: "정밀도 확인", data: [{ dimension: hostile, value: huge }, { dimension: "결측", value: null }] },
      { ...chart, chart_type: "pie", title: "결제수단 비중", data: [{ dimension: "카드", value: "80" }, { dimension: "현금", value: "20" }] },
      { ...chart, chart_type: "pie", title: "취소 포함", data: [{ dimension: "결제", value: "80" }, { dimension: "취소", value: "-20" }] },
      { ...chart, chart_type: "pie", title: "0원 구성", data: [{ dimension: "카드", value: "0" }] },
      { ...chart, title: "결측 구성", data: [{ dimension: "카드", value: null }] },
    ];
    result = answer("edge-cases", cases, []); await openResult(); await ready();
    const first = main.getByRole("region", { name: "정밀도 확인 분석 결과" });
    const host = first.locator('[data-chart-ready="true"]'); await host.focus(); await host.press("Home");
    await first.locator(".dataez-chart-tooltip").getByText("9,007,199,254,740,993.01원", { exact: true }).waitFor();
    assert.equal(await page.evaluate(() => window.chartXss), undefined);
    assert.equal(await first.locator(".dataez-chart-tooltip img").count(), 0);
    await host.press("End"); await first.getByRole("status").getByText("결측 · 계산 불가").waitFor();
    await first.getByRole("button", { name: "정밀도 확인 집계표·SQL" }).click();
    await page.getByRole("dialog").getByText("9,007,199,254,740,993.01원", { exact: true }).waitFor();
    await page.getByRole("dialog").getByText("실행 SQL과 매개변수", { exact: true }).click();
    await page.getByRole("dialog").getByText("이 결과에는 실행 SQL이 기록되지 않았습니다.").waitFor();
    await page.keyboard.press("Escape");
    await main.getByText("음수 값이 포함되어 막대그래프로 표시합니다.").waitFor();
    await main.getByText("합계가 0이어서 비율을 표시하지 않습니다.").waitFor();
    await main.getByText("계산 가능한 값이 없습니다.").waitFor();
    assert.equal(await main.locator('[data-chart-kind="pie"] [data-chart-ready="true"] svg').count(), 1);
    pass("bar/line/donut handle exact decimals, nulls, zero and negatives; tooltip labels are inert text");

    result = original; await openResult(); await ready();
    await page.getByRole("button", { name: "AI 채팅 닫기", exact: true }).click();
    for (const width of [320, 390, 768, 1100, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      await pause(100);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `overflow at ${width}`);
      assert.ok(await main.evaluate(el => el.scrollWidth <= el.clientWidth + 1), `main overflow at ${width}`);
      const chartHost = main.locator('[data-chart-ready="true"]').first();
      assert.ok(await chartHost.evaluate(el => Math.abs(el.clientWidth - el.querySelector('svg').getBoundingClientRect().width) < 2));
      if (width === 390) await page.screenshot({ path: path.join(artifacts, "analysis-mobile.png"), animations: "disabled" });
    }
    pass("320–1440px containment and SVG resize after viewport changes");
    assert.deepEqual(errors, []);
    await fs.writeFile(path.join(artifacts, "report.json"), JSON.stringify({ fixture: true, checks, saves: saves.length, browserErrors: errors }, null, 2));
    console.log(`${checks.length} analysis/dashboard checks passed.`);
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error); process.exit(1); });
