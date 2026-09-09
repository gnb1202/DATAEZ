// Actual Next.js UI with deterministic API fixtures. PostgreSQL/API boundary
// tests live separately in api/tests/test_file_library.py; no real LLM here.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");

async function main() {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const artifacts = path.join(__dirname, "artifacts", "file-library");
  await fs.mkdir(artifacts, { recursive: true });
  const checks = [], errors = [];
  const pass = (name) => { checks.push(name); console.log(`PASS ${name}`); };
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" });
    page.setDefaultTimeout(12000);
    page.on("pageerror", (error) => errors.push(error.message));
    const stores = [{ id: "store-a", name: "성수점" }, { id: "store-b", name: "연남점" }];
    const binding = (store, table, name) => ({ kind: "ledger", project_id: store, project_name: stores.find((s) => s.id === store).name, table_id: table, table_name: name, row_count: 1248 });
    const file = (id, name, store, bindings = []) => ({ file_id: id, filename: name, project_id: store, project_name: stores.find((s) => s.id === store)?.name, size_bytes: 32480, created_at: "2026-09-09T10:00:00Z", kind: name.endsWith(".md") ? "document" : "table", status: bindings.length ? "linked" : "stored", bindings });
    const files = [file("file-a", "성수점_9월_카드매출.csv", "store-a", [binding("store-a", "table-a", "카드 매출 누적 장부")]), file("file-b", "연남점_9월_매출.xlsx", "store-b", [binding("store-b", "table-b", "연남점 매출 장부")]), file("file-c", "정산_확인사항.md", "store-a", [{ kind: "document", project_id: "store-a", project_name: "성수점", index_status: "succeeded" }])];
    files[2].status = "document_ready";
    let lastSelections = [], sent = 0, prepared = 0, uploaded = 0, resolveFails = false;
    const conversations = [], history = {};
    const headers = { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" };
    await page.route("**/api/**", async (route) => {
      const request = route.request(), url = new URL(request.url()), p = url.pathname, method = request.method();
      let body = {}, status = 200;
      if (method === "OPTIONS") body = {};
      else if (p === "/api/auth/refresh") body = { access_token: "library-fixture", refresh_token: "library-fixture" };
      else if (p === "/api/auth/me") body = { email: "owner@example.test" };
      else if (p === "/api/projects") body = { projects: stores };
      else if (p === "/api/library/files" && method === "GET") {
        const project = url.searchParams.get("project_id"), search = url.searchParams.get("search") || "", kind = url.searchParams.get("kind");
        const visible = files.filter((f) => (!project || f.project_id === project) && f.filename.includes(search) && (!kind || f.kind === kind));
        body = { files: visible, total: visible.length };
      } else if (p === "/api/library/files" && method === "POST") {
        uploaded++; const f = file("file-new", "현금매출.csv", "store-a"); files.push(f); body = f; status = 201;
      } else if (p === "/api/library/files/resolve") {
        lastSelections = request.postDataJSON().selections;
        if (resolveFails) { status = 404; body = { detail: "파일을 찾을 수 없거나 보관함에서 제거되었습니다." }; }
        else body = { files: lastSelections.map(pick => { const f=files.find(item=>item.file_id===pick.file_id);return {...f.bindings.find(b=>b.table_id===pick.table_id),...pick,filename:f.filename}; }) };
      } else if (p.startsWith("/api/library/files/")) {
        const f = files.find((item) => item.file_id === p.split("/")[4]);
        if (p.endsWith("/preview")) body = { file: f, columns: [{ name: "결제일" }, { name: "금액" }], rows: [{ 결제일: "2026-09-01", 금액: "9007199254740993.01" }], row_count: 1 };
        else if (p.endsWith("/prepare")) { prepared++; f.bindings = [binding("store-a", "table-new", "현금매출.csv · 분석 장부")]; f.status = "linked"; body = f; }
        else if (p.endsWith("/download")) { await route.fulfill({ headers: { ...headers, "content-disposition": "attachment; filename=payments.csv" }, contentType: "application/octet-stream", body: "event_id,amount\n001,100" }); return; }
        else if (method === "DELETE") { files.splice(files.indexOf(f), 1); body = { removed: true }; }
        else body = f;
      } else if (p.endsWith("/search-index")) body = { jobs: [], counts: {}, total: 0, search_enabled: false, worker_enabled: false, max_attempts: 3 };
      else if (p.endsWith("/cash-entries")) body = { entries: [], total: 0 };
      else if (p.endsWith("/tables")) body = { tables: [] };
      else if (p.endsWith("/ledger-sources")) body = { sources: [] };
      else if (p === "/api/dashboard/widgets") body = { widgets: [] };
      else if (p === "/api/conversations" && method === "GET") body = { conversations };
      else if (p === "/api/conversations" && method === "POST") { body = { conversation_id: "conversation-1", title: "선택 파일 매출 분석", project_id: "store-a" }; if (!conversations.length) conversations.push(body); }
      else if (p.endsWith("/messages/stream")) {
        sent++;
        const raw = request.postData();
        assert.match(raw, /library_scope_confirmed/);
        assert.match(raw, /library_selections/);
        assert.doesNotMatch(raw, /filename=/);
        const refs = lastSelections.map((pick) => { const f = files.find((item) => item.file_id === pick.file_id); return { ...f.bindings.find((b) => b.table_id === pick.table_id), file_id: f.file_id, filename: f.filename, scope: pick.scope }; });
        const steps = [{ type: "meta", tool_name: "library_references", tool_output: { files: refs } }];
        const answer = { message_id: `answer-${sent}`, content: "선택한 성수점과 연남점 장부 전체의 매출입니다.", steps, charts: [] };
        history["conversation-1"] = [{ message_id: "user-1", role: "user", content: "선택한 파일로 매출을 비교해줘", steps }, { ...answer, role: "assistant" }];
        await route.fulfill({ contentType: "text/event-stream", headers, body: `data: ${JSON.stringify({ type: "done", data: answer })}\n\n` }); return;
      } else if (p.endsWith("/messages")) body = { messages: history["conversation-1"] || [] };
      else { errors.push(`Unexpected fixture request ${method} ${p}`); status = 404; }
      await route.fulfill({ status, contentType: "application/json", headers, body: JSON.stringify(body) });
    });
    await page.addInitScript(() => localStorage.setItem("dataez_refresh_token", "library-fixture"));
    await page.goto(process.env.UI_BASE_URL || "http://127.0.0.1:3132/dashboard");
    await page.getByRole("button", { name: "새 분석", exact: true }).click();
    await page.getByRole("button", { name: "보관함에서 선택", exact: true }).click();
    const dialog = () => page.getByRole("dialog", { name: "보관함에서 파일 선택" });
    await dialog().getByRole("article", { name: files[0].filename }).waitFor();
    assert.equal(await dialog().getByRole("article", { name: files[1].filename }).count(), 0);
    await dialog().getByRole("checkbox", { name: `${files[0].filename} 분석에 선택` }).check();
    assert.equal(await dialog().getByRole("button", { name: "선택한 파일로 분석", exact: true }).isEnabled(), false);
    await dialog().getByRole("button", { name: "내 계정 전체", exact: true }).click();
    await dialog().getByRole("checkbox", { name: `${files[1].filename} 분석에 선택` }).check();
    await dialog().getByText("연남점 · 다른 가게 포함", { exact: true }).waitFor();
    await dialog().getByRole("checkbox", { name: /파일별 분석 범위와 가게/ }).check();
    assert.equal(await dialog().getByRole("combobox",{name:`${files[0].filename} 분석 범위`,exact:true}).inputValue(),"original_file");
    await dialog().getByRole("combobox",{name:`${files[0].filename} 분석 범위`,exact:true}).selectOption("linked_ledger");
    assert.equal(await dialog().getByRole("button",{name:"선택한 파일로 분석",exact:true}).isEnabled(),false);
    await dialog().getByRole("checkbox",{name:/파일별 분석 범위와 가게/}).check();
    await page.screenshot({ path: path.join(artifacts, "library-picker-dark.png"), animations: "disabled" });
    await dialog().getByRole("button", { name: "선택한 파일로 분석", exact: true }).click();
    assert.equal(uploaded, 0); assert.equal(prepared, 0);
    pass("original-file default, explicit ledger switch resets confirmation; cross-store selection performs no uploads");

    const input = () => page.getByRole("textbox", { name: "분석 요청", exact: true });
    await input().fill("선택한 파일로 매출을 비교해줘");
    await page.getByRole("button", { name: "AI 채팅 닫기", exact: true }).click();
    await page.getByRole("button", { name: "데이터 관리", exact: true }).click();
    await page.locator("#workspace-chat-toggle").click();
    assert.equal(await page.locator('[aria-label="선택한 보관 파일"] button').count(), 2);
    assert.equal(await input().inputValue(), "선택한 파일로 매출을 비교해줘");
    await page.getByRole("button", { name: "분석 요청 보내기" }).click();
    await page.getByText("선택한 성수점과 연남점 장부 전체의 매출입니다.", { exact: true }).waitFor();
    assert.equal(sent, 1); assert.equal(lastSelections[1].include_other_store, true);
    assert.equal(lastSelections[0].scope,"linked_ledger"); assert.equal(lastSelections[1].scope,"original_file");
    assert.equal(await page.locator('[aria-label="분석에 사용한 보관 파일"]').count(), 2);
    pass("selected references and draft survive navigation; stream sends IDs without file bytes and displays source scope");

    await page.getByRole("button", { name: "새 분석", exact: true }).click();
    assert.equal(await page.locator('[aria-label="선택한 보관 파일"]').count(), 0);
    await page.getByRole("button", { name: "분석 이력", exact: true }).click();
    await page.getByRole("button", { name: /선택 파일 매출 분석/ }).click();
    assert.equal(await page.locator('[aria-label="선택한 보관 파일"] button').count(), 2);
    resolveFails = true;
    await input().fill("이어서 합계를 보여줘");
    await page.getByRole("button", { name: "분석 요청 보내기" }).click();
    await page.locator("#workspace-chat").getByText(/파일을 찾을 수 없거나/).waitFor();
    assert.equal(await input().inputValue(), "이어서 합계를 보여줘"); assert.equal(sent, 1);
    resolveFails = false;
    history["conversation-1"].push({ message_id: "candidate-result", role: "assistant", content: "보관함에서 파일을 찾았습니다.", steps: [{ type: "tool_call", tool_name: "search_library_files", tool_output: { files: [files[1]] } }] });
    await page.getByRole("button", { name: "분석 이력", exact: true }).click();
    await page.getByRole("button", { name: /선택 파일 매출 분석/ }).click();
    await page.locator("#workspace-chat").getByRole("button", { name: /연남점_9월_매출.xlsx.*확인하고 선택/ }).click();
    await dialog().getByRole("article", { name: files[1].filename }).waitFor();
    assert.equal(await dialog().getByRole("textbox", { name: "보관함 파일명 검색" }).inputValue(), files[1].filename);
    await page.keyboard.press("Escape");
    pass("history restores references; missing-file validation preserves draft; natural-search candidate opens scoped picker");

    await page.getByRole("button", { name: "AI 채팅 닫기", exact: true }).click();
    await page.getByRole("button", { name: "데이터 관리", exact: true }).click();
    await page.getByRole("button", { name: "파일 보관함", exact: true }).click();
    await page.getByLabel("보관할 파일", { exact: true }).setInputFiles({ name: "현금매출.csv", mimeType: "text/csv", buffer: Buffer.from("date,amount\n2026-09-01,100") });
    const uploadedRow = page.getByRole("article", { name: "현금매출.csv", exact: true });
    await uploadedRow.getByRole("button", { name: "미리보기", exact: true }).click();
    await page.getByText("9007199254740993.01", { exact: true }).waitFor();
    await page.getByRole("button", { name: "검사한 파일을 분석에 연결", exact: true }).click();
    await uploadedRow.getByRole("checkbox", { name: "현금매출.csv 분석에 선택" }).waitFor();
    assert.equal(uploaded, 1); assert.equal(prepared, 1);
    const download = page.waitForEvent("download");
    await uploadedRow.getByRole("button", { name: "원본", exact: true }).click();
    assert.equal((await download).suggestedFilename(), "현금매출.csv");
    await page.getByRole("combobox", { name: "화면 테마" }).selectOption("light");
    await page.locator("#workspace-main").evaluate((element) => element.scrollTo({ top: 0 }));
    await page.screenshot({ path: path.join(artifacts, "library-page-light.png"), animations: "disabled" });
    pass("data-management library uploads, previews exact amounts, prepares once and downloads originals; light theme");

    await uploadedRow.getByRole("button", { name: "보관함에서 제외", exact: true }).click();
    await page.getByText(/연결된 장부와 원본 기록은 유지되며/).waitFor();
    await page.getByRole("button", { name: "제외 확인", exact: true }).click();
    await uploadedRow.waitFor({ state: "detached" });
    await page.getByRole("combobox", { name: "현재 작업 가게" }).selectOption("store-b");
    await page.locator("#workspace-chat-toggle").click();
    assert.equal(await page.locator('[aria-label="선택한 보관 파일"]').count(), 0);
    assert.equal(await input().inputValue(), "");
    pass("library removal is explicit and store switching clears scoped drafts");

    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("button", { name: "보관함에서 선택", exact: true }).click();
    await dialog().getByRole("article", { name: files[1].filename }).waitFor();
    await dialog().getByRole("checkbox", { name: `${files[1].filename} 분석에 선택` }).check();
    await dialog().getByRole("checkbox", { name: /파일별 분석 범위와 가게/ }).check();
    await page.screenshot({ path: path.join(artifacts, "library-picker-mobile.png"), animations: "disabled" });
    await dialog().getByRole("button", { name: "선택한 파일로 분석", exact: true }).click();
    assert.equal(await page.locator('[aria-label="선택한 보관 파일"] button').count(), 1);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    pass("mobile chat sheet opens library dialog and returns with selected file without horizontal overflow");
    assert.deepEqual(errors, []);
    await fs.writeFile(path.join(artifacts, "report.json"), JSON.stringify({ passed: true, checks, api_fixtures: true, llm_evaluated: false }, null, 2));
  } finally { await browser.close(); }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
