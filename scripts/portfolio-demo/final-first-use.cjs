// New synthetic account, all onboarding mutations through the real public UI.
const {chromium}=require('../ui-eval/node_modules/playwright');
const fs=require('node:fs/promises');
const path=require('node:path');
const crypto=require('node:crypto');
const assert=require('node:assert/strict');
async function main(){
 const out=path.resolve('.local-test/portfolio-demo/final-qa');
 await fs.mkdir(out,{recursive:true});
 const statePath=path.join(out,'account.json');
 const state={site:'https://dataez.vercel.app',api:'https://dataez-api.vercel.app',
  email:'portfolio-qa-'+crypto.randomUUID()+'@example.invalid',password:crypto.randomBytes(24).toString('base64url')+'!aA7',
  stage:'credentials_prepared',final_qa:true};
 await fs.writeFile(statePath,JSON.stringify(state,null,2),{flag:'wx'});
 const save=()=>fs.writeFile(statePath,JSON.stringify(state,null,2));
 const report={passed:false,api_mocks:false,synthetic:true,checks:[],page_errors:0};
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:900},locale:'ko-KR',reducedMotion:'reduce'});
 page.setDefaultTimeout(30000);page.on('pageerror',()=>report.page_errors++);
 const response=(suffix)=>{const p=page.waitForResponse(r=>r.url().endsWith(suffix)&&r.request().method()==='POST');p.catch(()=>{});return p;};
 const json=async p=>{const r=await p;assert.ok(r.ok(),'HTTP '+r.status());return r.json();};
 const screenshot=async name=>page.screenshot({path:path.join(out,name+'.png'),mask:[page.getByRole('button',{name:'설정 및 계정',exact:true})]});
 try{
  await page.goto(state.site);await page.getByRole('button',{name:'회원가입',exact:true}).click();
  await page.getByLabel('이름',{exact:true}).fill('포트폴리오 최종 QA');
  await page.getByLabel('이메일',{exact:true}).fill(state.email);
  await page.getByLabel('비밀번호',{exact:true}).fill(state.password);
  const signup=response('/api/auth/signup');
  state.stage='signup_pending';await save();
  await page.locator('form button[type=submit]').click();const auth=await json(signup);
  state.token=auth.access_token;state.refresh_token=auth.refresh_token;state.stage='signed_up';await save();
  await page.waitForURL('**/dashboard');
  await page.getByRole('button',{name:'가게 추가',exact:true}).waitFor();await screenshot('first-empty');
  report.checks.push('UI signup and empty workspace without pre-seeded data');
  async function store(name){
   await page.getByRole('button',{name:'가게 추가',exact:true}).click();
   const d=page.getByRole('dialog');await d.getByLabel('가게 이름',{exact:true}).fill(name);
   const pending=response('/api/projects');await d.getByRole('button',{name:'만들기',exact:true}).click();
   const result=await json(pending);await d.waitFor({state:'hidden'});return {project_id:result.id,name};
  }
  state.recording=await store('최종 QA · 카드와 현금');await save();
  state.showcase=await store('최종 QA · 빈 비교 가게');await save();
  await page.getByRole('combobox',{name:'현재 작업 가게'}).selectOption(state.recording.project_id);
  await page.getByRole('button',{name:'데이터 관리',exact:true}).click();
  await page.getByRole('button',{name:'파일 보관함',exact:true}).click();
  const bytes=Buffer.from((await fs.readFile('samples/demo/portfolio-original.csv','utf8')).replace(/\r\n/g,'\n'));
  const filename='최종QA_카드현금.csv';state.recording.filename=filename;state.stage='upload_pending';await save();
  const uploaded=response('/complete');
  await page.getByLabel('보관할 파일',{exact:true}).setInputFiles({name:filename,mimeType:'text/csv',buffer:bytes});
  const file=await json(uploaded);state.recording.file_id=file.file_id;state.stage='uploaded';await save();
  const main=page.locator('#workspace-main'),row=main.getByRole('article',{name:filename,exact:true});
  await row.getByRole('button',{name:'미리보기',exact:true}).click();
  await main.getByLabel('파일 미리보기').waitFor();await screenshot('first-preview');
  const prepared=response('/api/library/files/'+file.file_id+'/prepare');
  await main.getByRole('button',{name:'검사한 파일을 분석에 연결',exact:true}).click();
  const ready=await json(prepared);state.recording.table_id=ready.bindings[0].table_id;await save();
  await row.getByText('분석 가능',{exact:true}).waitFor();
  assert.equal(await row.getByRole('combobox',{name:filename+' 분석 범위',exact:true}).inputValue(),'original_file');
  const download=await fetch(state.api+'/api/library/files/'+file.file_id+'/download',{headers:{Authorization:'Bearer '+state.token}});
  assert.equal(download.status,200);assert.deepEqual(Buffer.from(await download.arrayBuffer()),bytes);
  report.checks.push('UI creates two stores, signed upload, preview and ledger preparation; original scope is default; download bytes exact');
  const data=await fetch(state.api+`/api/projects/${state.recording.project_id}/tables/${state.recording.table_id}/data`,{headers:{Authorization:'Bearer '+state.token}});
  const ledger=await data.json();assert.equal(ledger.total_count,8);
  assert.equal(ledger.rows.reduce((a,r)=>a+BigInt(r.amount),0n).toString(),'690200');
  state.stage='ready_for_analysis';state.out=path.join(out,'analysis');await fs.mkdir(state.out);await save();
  await screenshot('first-ready');report.checks.push('Independent initial ledger: 8 rows / 690200');
  assert.equal(report.page_errors,0);report.passed=true;
 }catch(e){report.failure={name:e.name,message:e.message};await screenshot('first-failure').catch(()=>{});throw e;}
 finally{await fs.writeFile(path.join(out,'first-use.json'),JSON.stringify(report,null,2));await browser.close();}
 console.log(JSON.stringify(report));
}
main().catch(e=>{console.error(e.name+': '+e.message.slice(0,500));process.exitCode=1;});
