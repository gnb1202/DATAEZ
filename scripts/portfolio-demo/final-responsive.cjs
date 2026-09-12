// Real saved public data; no model calls. Keyboard and emulated viewport audit.
const {chromium}=require('../ui-eval/node_modules/playwright');
const fs=require('node:fs/promises');
const path=require('node:path');
const assert=require('node:assert/strict');
async function main(){
 const out=path.resolve('.local-test/portfolio-demo/final-qa');
 const state=JSON.parse(await fs.readFile(path.join(out,'account.json'),'utf8'));
 const report={passed:false,api_mocks:false,browser:'Microsoft Edge (Chromium)',mobile:'viewport emulation, not physical Safari',checks:[],page_errors:0};
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:900},locale:'ko-KR',reducedMotion:'reduce'});
 const page=await context.newPage();page.setDefaultTimeout(30000);page.on('pageerror',()=>report.page_errors++);
 const main=page.locator('#workspace-main');
 async function tabTo(locator){for(let i=0;i<100;i++){if(await locator.evaluate(n=>n===document.activeElement))return;await page.keyboard.press('Tab');}throw new Error('Keyboard target unreachable');}
 const shot=async name=>{await page.evaluate(()=>document.fonts.ready);await page.screenshot({path:path.join(out,name+'.png'),mask:[page.getByRole('button',{name:'설정 및 계정',exact:true})]});};
 async function check(name){assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,name+' page overflow');
  if(await main.count())assert.equal(await main.evaluate(n=>n.scrollWidth>n.clientWidth+1),false,name+' workspace overflow');
  await shot(name);report.checks.push(name);}
 async function nav(name){if(page.viewportSize().width<768)await page.getByRole('button',{name:'작업 메뉴 열기',exact:true}).click();await page.getByRole('button',{name,exact:true}).click();}
 try{
  // Login layout matrix with empty forms, so captured media contains no credentials.
  for(const theme of ['dark','light'])for(const [width,height] of [[1440,900],[768,1024],[390,844]]){
   await page.setViewportSize({width,height});await page.goto(state.site);
   await page.evaluate(t=>{localStorage.setItem('theme',t);document.documentElement.classList.remove('light','dark');document.documentElement.classList.add(t);},theme);
   await page.getByLabel('이메일',{exact:true}).waitFor();await check(`login-${theme}-${width}`);
  }
  await page.setViewportSize({width:1440,height:900});await page.goto(state.site);
  await tabTo(page.getByLabel('이메일',{exact:true}));await page.keyboard.type(state.email);
  await page.keyboard.press('Tab');await page.keyboard.type(state.password);
  await tabTo(page.locator('form button[type=submit]'));await page.keyboard.press('Enter');await page.waitForURL('**/dashboard');
  report.checks.push('Keyboard-only login after fresh context');
  await page.getByRole('combobox',{name:'현재 작업 가게'}).selectOption(state.recording.project_id);
  for(const theme of ['dark','light'])for(const [width,height] of [[1440,900],[768,1024],[390,844]]){
   await page.setViewportSize({width,height});await page.getByRole('combobox',{name:'화면 테마'}).selectOption(theme);
   await nav('대시보드');await main.locator('[data-chart-ready="true"] svg').first().waitFor();
   await check(`dashboard-${theme}-${width}`);
   const sql=main.getByRole('button',{name:/집계표·SQL$/}).first();await tabTo(sql);await page.keyboard.press('Enter');
   const dialog=page.getByRole('dialog');await dialog.getByRole('table',{name:'정확한 집계 결과'}).waitFor();
   await check(`sql-${theme}-${width}`);await page.keyboard.press('Escape');
   assert.ok(await sql.evaluate(n=>n===document.activeElement),'SQL focus returns to trigger');
   const toggle=page.locator('#workspace-chat-toggle');await tabTo(toggle);await page.keyboard.press('Enter');
   await page.getByRole('textbox',{name:'분석 요청',exact:true}).waitFor();
   await check(`chat-${theme}-${width}`);
   if(width<1280){await page.keyboard.press('Escape');await page.waitForFunction(()=>document.activeElement?.id==='workspace-chat-toggle');}
   else{const close=page.getByRole('button',{name:'채팅 패널 닫기',exact:true});await tabTo(close);await page.keyboard.press('Enter');}
   await nav('데이터 관리');await page.getByRole('button',{name:'파일 보관함',exact:true}).click();
   await main.getByRole('article',{name:state.recording.filename,exact:true}).waitFor();await check(`files-${theme}-${width}`);
  }
  // Native browser zoom via Ctrl+Plus, inspect resulting devicePixelRatio.
  await page.setViewportSize({width:1440,height:900});await nav('대시보드');
  await main.locator('[data-chart-ready="true"] svg').first().waitFor();
  const before=await page.evaluate(()=>devicePixelRatio);
  await page.keyboard.press('Control+0');for(let i=0;i<4;i++)await page.keyboard.press('Control+Equal');
  const after=await page.evaluate(()=>devicePixelRatio);
  report.zoom={method:'native Ctrl+Plus',before,after,verified:after>=before*1.9};
  if(!report.zoom.verified){
   // Headless Edge ignores native zoom; CDP emulates equivalent CSS viewport + DPR.
   await page.setViewportSize({width:720,height:450});
   const cdp=await context.newCDPSession(page);await cdp.send('Emulation.setDeviceMetricsOverride',{width:720,height:450,deviceScaleFactor:2,mobile:false});
   await page.waitForFunction(()=>innerWidth===720&&devicePixelRatio===2);
   report.zoom={method:'CDP CSS viewport/DPR equivalent of 1440x900 at 200%; not native browser zoom',verified:true};
  }
  await main.locator('[data-chart-ready="true"] svg').first().waitFor();
  await check('dashboard-200-percent-equivalent');
  assert.equal(report.page_errors,0);report.passed=true;
 }catch(e){report.failure={name:e.name,message:e.message};await shot('responsive-failure').catch(()=>{});process.exitCode=1;}
 finally{await fs.writeFile(path.join(out,'responsive.json'),JSON.stringify(report,null,2));await browser.close();}
 console.log(JSON.stringify({passed:report.passed,checks:report.checks.length,failure:report.failure}));
}
main().catch(e=>{console.error(e.name+': '+e.message.slice(0,300));process.exitCode=1;});
