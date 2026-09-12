const {chromium}=require('../ui-eval/node_modules/playwright');
const fs=require('node:fs/promises');
const assert=require('node:assert/strict');
async function main(){
 const browser=await chromium.launch({channel:'msedge',headless:true});const checks=[];
 for(const mode of ['expired_refresh','expired_access_and_refresh']){
  const page=await browser.newPage();let refreshes=0,protectedCalls=0;
  await page.route('**/api/**',async route=>{
   const p=new URL(route.request().url()).pathname;let status=200,body={};
   if(route.request().method()==='OPTIONS'){}
   else if(p==='/api/auth/refresh'){
    refreshes++;if(mode==='expired_refresh'||refreshes>1){status=401;body={detail:'Expired test session'};}
    else body={access_token:'local-fixture-only',refresh_token:'local-fixture-only'};
   }else if(p==='/api/auth/me')body={email:'fixture@example.invalid'};
   else{protectedCalls++;status=401;body={detail:'Expired test access'};}
   await route.fulfill({status,headers:{'access-control-allow-origin':'*','access-control-allow-headers':'*'},contentType:'application/json',body:JSON.stringify(body)});
  });
  await page.addInitScript(()=>localStorage.setItem('dataez_refresh_token','local-expired-fixture'));
  await page.goto('http://127.0.0.1:3132/dashboard');
  await page.getByLabel('비밀번호',{exact:true}).waitFor();
  assert.equal(await page.evaluate(()=>localStorage.getItem('dataez_refresh_token')),null);
  assert.equal(await page.locator('[id^="dashboard-widget-"]').count(),0);
  checks.push({mode,refreshes,protectedCalls,login_restored:true,stored_session_cleared:true});await page.close();
 }
 await browser.close();await fs.writeFile('.local-test/portfolio-demo/final-qa/auth.json',JSON.stringify({passed:true,api_mocks:true,checks},null,2));console.log(JSON.stringify({passed:true,checks}));
}
main().catch(e=>{console.error(e.name+': '+e.message.slice(0,400));process.exitCode=1;});
