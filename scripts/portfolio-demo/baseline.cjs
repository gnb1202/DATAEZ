// Real public browser, no API fixtures. Credentials arrive only over stdin.
const {chromium}=require('../ui-eval/node_modules/playwright');
const fs=require('node:fs/promises');
const path=require('node:path');
const assert=require('node:assert/strict');
async function main(){
 const state=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
 const output=path.resolve('docs/portfolio-demo/assets');await fs.mkdir(output,{recursive:true});
 const report={passed:false,api_mocks:false,checks:[],page_error_count:0};
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const context=await browser.newContext({viewport:{width:1920,height:1080},reducedMotion:'reduce',locale:'ko-KR'});
  await context.addInitScript(()=>localStorage.setItem('theme','dark'));
  const page=await context.newPage();page.setDefaultTimeout(30000);
  page.on('pageerror',()=>report.page_error_count++);
  await page.goto(state.site);
  await page.getByLabel('이메일',{exact:true}).fill(state.email);
  await page.getByLabel('비밀번호',{exact:true}).fill(state.password);
  await page.locator('form button[type=submit]').click();
  await page.waitForURL('**/dashboard');
  const selector=page.getByRole('combobox',{name:'현재 작업 가게'});
  await selector.selectOption(state.showcase.project_id);
  await page.getByRole('button',{name:'대시보드',exact:true}).click();
  await page.locator('[data-chart-ready="true"] svg').first().waitFor();
  await page.evaluate(()=>document.fonts.ready);
  assert.equal(await page.locator('[id^="dashboard-widget-"]').count(),3);
  await page.screenshot({path:path.join(output,'phase-0-example-dashboard.png'),fullPage:true});
  report.checks.push('Public credential login; three explicitly predefined example widgets');
  await selector.selectOption(state.recording.project_id);
  await page.waitForFunction(()=>document.querySelectorAll('[id^="dashboard-widget-"]').length===0);
  await page.getByRole('button',{name:'데이터 관리',exact:true}).click();
  await page.getByRole('button',{name:'파일 보관함',exact:true}).click();
  await page.getByRole('article',{name:'샘플_카페_매출.csv',exact:true}).waitFor();
  await page.screenshot({path:path.join(output,'phase-0-recording-library.png'),fullPage:true});
  report.checks.push('Fresh recording store has original file and no dashboard widgets');
  await page.reload();await selector.waitFor();
  await selector.selectOption(state.recording.project_id);
  assert.equal(await selector.inputValue(),state.recording.project_id);
  await selector.selectOption(state.showcase.project_id);
  await page.getByRole('button',{name:'대시보드',exact:true}).click();
  await page.locator('[data-chart-ready="true"] svg').first().waitFor();
  assert.equal(await page.locator('[id^="dashboard-widget-"]').count(),3);
  report.checks.push('Reload restores authenticated access; prior sample dashboard retained after new sample');
  assert.equal(report.page_error_count,0);report.passed=true;
 }finally{
  await fs.writeFile(path.resolve('docs/portfolio-demo/phase-0-browser.json'),JSON.stringify(report,null,2)+'\n');
  await browser.close();
 }
 console.log(JSON.stringify(report));
}
main().catch(()=>{console.error('Browser baseline failed; credentials and request payloads omitted');process.exitCode=1});
