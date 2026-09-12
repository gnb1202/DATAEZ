// Actual app with controlled API failures. No live DB, customer data or LLM.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const crypto=require('node:crypto');
const audit=process.argv.includes('--audit');
const out=path.join(__dirname,'artifacts','usability',audit?'before':'after');
const base=process.env.UI_BASE_URL||'http://127.0.0.1:3133/dashboard';

async function main(){
  await fs.mkdir(out,{recursive:true});
  const browser=await chromium.launch({channel:process.env.BROWSER_CHANNEL||'msedge',headless:true});
  const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
  const page=await context.newPage();page.setDefaultTimeout(18000);
  const report={passed:false,checked_at:new Date().toISOString(),api_mocks:true,live_llm:false,checks:[],errors:[],source_sha256:{}};
  for(const name of ['web/app/hooks/use-workspace-analysis.ts','web/app/components/chat-panel.tsx','web/components/dashboard/chat-dock.tsx','web/components/dashboard/getting-started.tsx','web/components/dashboard/sample-workspace-actions.tsx','web/components/dashboard/sections/dashboard-section.tsx','web/components/dashboard/file-library.tsx']){
    report.source_sha256[name]=crypto.createHash('sha256').update(await fs.readFile(path.resolve(__dirname,'../..',name))).digest('hex');
  }
  page.on('pageerror',e=>report.errors.push(e.message));
  const check=(name,value)=>{report.checks.push({name,passed:!!value});console.log(`${value?'PASS':'FOUND'} ${name}`);if(!audit)assert.ok(value,name);};
  const stores=[{id:'store-a',name:'성수점',description:''},{id:'store-b',name:'연남점',description:''}];
  const file={file_id:'file-a',filename:'9월_카드현금.csv',project_id:'store-a',project_name:'성수점',kind:'table',status:'ready',size_bytes:120,created_at:'2026-09-01T00:00:00Z',bindings:[{kind:'ledger',project_id:'store-a',project_name:'성수점',table_id:'table-a',table_name:'9월 매출',row_count:8}]};
  const definition={version:1,table_id:'original-a',operation:'sum',column:'amount',group_by:'paid_at',date_grain:'day',date_column:'paid_at',time_range:'all',chart_type:'line',unit:'KRW'};
  const chart={title:'일별 결제액',chart_type:'line',x_key:'dimension',y_key:'value',unit:'KRW',metric_definition:definition,scope_label:'파일 원본만',refresh_note:'업로드 당시 행으로 재계산합니다.',data:[{dimension:'2026-09-01',value:'164500'},{dimension:'2026-09-02',value:'190000'}]};
  const answer=(id)=>({message_id:id,role:'assistant',content:'선택한 원본의 일별 결제액입니다.',charts:[chart],steps:[]});
  const widgets={'store-a':[{id:'existing',project_id:'store-a',widget_type:'chart',title:chart.title,widget_data:chart,layout:{x:0,y:0,w:6,h:7}}],'store-b':[]};
  const conversations=[],history={};let created=0,sent=0,mode='ok',saveFails=false,saveLookupFails=false,release,reviewFails=false,reviewEmpty=false;
  const requests=[],bodies=[];
  await page.route('**/api/**',async route=>{
    const req=route.request(),u=new URL(req.url()),p=u.pathname,m=req.method();requests.push({p,m});
    let body={},status=200;
    const headers={'access-control-allow-origin':'*','access-control-allow-headers':'*','access-control-allow-methods':'*'};
    if(m==='OPTIONS'){}
    else if(p==='/api/auth/refresh')body={access_token:'ui-fixture',refresh_token:'ui-fixture'};
    else if(p==='/api/auth/me')body={email:'fixture@example.test'};
    else if(p==='/api/uploads/capabilities')body={direct_upload:false,max_size_bytes:20*1024*1024};
    else if(p==='/api/projects')body={projects:stores};
    else if(p==='/api/library/files/sample-workspace')body={project:null};
    else if(p==='/api/library/files')body={files:[file],total:1};
    else if(p==='/api/library/files/resolve')body={files:req.postDataJSON().selections.map(r=>({...file.bindings[0],...r,filename:file.filename,file_id:file.file_id,table_id:r.scope==='original_file'?'original-a':'table-a'}))};
    else if(p.endsWith('/tables'))body={tables:[]};
    else if(p.endsWith('/ledger-sources'))body={sources:[]};
    else if(p.endsWith('/cash-entries'))body={entries:[],total:0};
    else if(p.endsWith('/search-index'))body={jobs:[],counts:{},total:0,search_enabled:false};
    else if(p==='/api/conversations'&&m==='GET')body={conversations:conversations.filter(c=>c.project_id===u.searchParams.get('project_id')),total:conversations.length};
    else if(p==='/api/conversations'){
      created++;body={conversation_id:'conversation-'+created,project_id:req.postDataJSON().project_id,title:'현재 분석'};conversations.unshift(body);
    }else if(p.endsWith('/messages/stream')){
      sent++;const id=p.split('/')[3];bodies.push(req.postData());
      if(mode==='hold')await new Promise(done=>release=done);
      if(mode==='429'||mode==='503'){await route.fulfill({status:Number(mode),headers,contentType:'application/json',body:JSON.stringify({detail:'격리된 오류 복구 검사'})});return;}
      history[id]=[answer('reply-'+sent)];
      const frame=mode==='error'?{type:'error',data:{message:'응답 연결이 끊겼습니다.'}}:{type:'done',data:answer('reply-'+sent)};
      await route.fulfill({contentType:'text/event-stream',headers,body:`data: ${JSON.stringify(frame)}\n\n`}).catch(()=>{});return;
    }else if(p.endsWith('/messages')){
      if(reviewFails){reviewFails=false;status=503;body={detail:'처리 기록 연결 실패'};}
      else if(reviewEmpty){reviewEmpty=false;body={messages:[]};}
      else body={messages:history[p.split('/')[3]]||[]};
    }
    else if(p==='/api/dashboard/widgets/layout')body={ok:true};
    else if(p==='/api/dashboard/widgets'){
      if(saveLookupFails){saveLookupFails=false;status=503;body={detail:'저장 이력 확인 실패'};}
      else body={widgets:widgets[u.searchParams.get('project_id')]||[]};
    }
    else if(p.endsWith('/metrics/preview'))body={...chart,metric_definition:req.postDataJSON().definition};
    else if(p.endsWith('/metrics')&&m==='POST'){
      const payload=req.postDataJSON();bodies.push(payload);const pid=p.split('/')[3];
      let saved=widgets[pid].find(w=>w.save_key===payload.save_key);
      if(!saved){saved={id:'saved-'+sent,project_id:pid,widget_type:'chart',title:payload.title,widget_data:{...chart,metric_definition:payload.definition},layout:{x:6,y:0,w:6,h:7},save_key:payload.save_key};widgets[pid].push(saved);}
      if(saveFails){saveFails=false;saveLookupFails=true;status=503;body={detail:'저장 응답 확인 실패'};}else body=saved;
    }else{status=404;report.errors.push('Unexpected '+m+' '+p);}
    await route.fulfill({status,headers,contentType:'application/json',body:JSON.stringify(body)}).catch(()=>{});
  });
  await page.addInitScript(()=>localStorage.setItem('dataez_refresh_token','ui-fixture'));
  const input=()=>page.getByRole('textbox',{name:'분석 요청',exact:true});
  const send=()=>page.getByRole('button',{name:'분석 요청 보내기',exact:true});
  const chat=()=>page.locator('#workspace-chat');
  const shot=name=>page.screenshot({path:path.join(out,name+'.png'),animations:'disabled'});
  async function keyActivate(locator){
    for(let i=0;i<100;i++){if(await locator.evaluate(n=>n===document.activeElement)){await page.keyboard.press('Enter');return;}await page.keyboard.press('Tab');}
    throw new Error('Keyboard action unreachable');
  }
  async function sendAndFinish(){const response=page.waitForResponse(r=>r.url().endsWith('/messages/stream'));await send().click();await response;await page.waitForFunction(()=>!document.querySelector('[aria-label="분석 요청"]')?.disabled);}
  try{
    await page.goto(base);await page.locator('#dashboard-widget-existing svg').first().waitFor();
    await page.getByText('시작 안내와 샘플 체험',{exact:true}).click();
    check('Saved dashboard keeps sample/file start in its expandable guide',await page.getByRole('button',{name:'샘플 데이터로 시작',exact:true}).isVisible());await shot('dashboard-entry');
    await page.getByRole('button',{name:'새 분석',exact:true}).click();
    const before=sent;await chat().getByRole('button',{name:/어떤 장부들이 있어|이 가게에서 분석할 수 있는 자료/}).click();
    await page.waitForFunction(()=>!document.querySelector('[aria-label="분석 요청"]')?.disabled);
    check('Question suggestion fills an editable draft without sending a request',sent===before&&(await input().inputValue()).length>0);
    await page.getByRole('button',{name:'새 분석',exact:true}).click();mode='error';
    const question='9월 카드와 현금 합계를 비교해줘. 아직 저장하지 마.';
    await input().fill(question);await chat().locator('input[type=file]').setInputFiles({name:'local.csv',mimeType:'text/csv',buffer:Buffer.from('amount\n100')});
    await sendAndFinish();
    check('Failed response keeps the complete question and original device attachment',await input().inputValue()===question&&await chat().getByText('local.csv',{exact:true}).isVisible());await shot('failed-analysis');
    if(!audit){
      const count=sent;reviewFails=true;
      const review=page.getByRole('button',{name:'이 대화의 처리 결과 확인',exact:true});
      await review.click();await chat().getByText('처리 기록 연결 실패',{exact:true}).waitFor();
      check('History lookup failure preserves draft/file and offers another read without resending',sent===count&&await input().inputValue()===question&&await chat().getByText('local.csv',{exact:true}).isVisible());
      reviewEmpty=true;await review.click();await chat().getByText(/아직 완료된 답변을 확인하지 못했습니다/).waitFor();
      check('An incomplete history is not presented as a completed request and retains the draft',sent===count&&await input().inputValue()===question);
      await review.click();
      await chat().getByText('선택한 원본의 일별 결제액입니다.',{exact:true}).waitFor();
      check('Recovery reads saved messages without another model request and retains draft',sent===count&&await input().inputValue()===question&&await chat().getByText('local.csv',{exact:true}).isVisible());
    }
    await page.getByRole('button',{name:'새 분석',exact:true}).click();
    await page.getByRole('button',{name:'보관함에서 선택',exact:true}).click();
    const picker=page.getByRole('dialog',{name:'보관함에서 파일 선택'});
    const scope=picker.getByRole('combobox',{name:file.filename+' 분석 범위',exact:true});
    check('New file selection defaults to original rows and explains additional transactions',await scope.inputValue()==='original_file'&&await picker.getByText(/이후 장부에 추가한 거래는 제외/).isVisible());
    await scope.selectOption('linked_ledger');check('Cumulative scope explains that refresh includes additional transactions',await picker.getByText(/새로고침 시 추가 거래도 반영/).isVisible());
    await scope.selectOption('original_file');await picker.getByRole('checkbox',{name:file.filename+' 분석에 선택',exact:true}).check();
    await picker.getByRole('checkbox',{name:/파일별.*분석 범위와 가게/}).check();
    const selectedAt=sent;await picker.getByRole('button',{name:/선택한 파일로 분석|선택한 파일을 채팅에 추가/,exact:true}).click();
    check('Adding a library file does not submit a question',sent===selectedAt);
    await input().fill(question);await sendAndFinish();
    check('Failed response retains question and selected original-file scope',await input().inputValue()===question&&await chat().getByLabel('선택한 보관 파일').getByText(/파일 원본만/).isVisible());
    for(const failureStatus of ['429','503']){
      mode=failureStatus;await input().fill(question);await sendAndFinish();
      check('HTTP '+failureStatus+' retains draft and original source',await input().inputValue()===question&&await chat().getByLabel('선택한 보관 파일').getByText(/파일 원본만/).isVisible());
    }
    if(!audit){
      mode='hold';await page.getByRole('button',{name:'새 분석',exact:true}).click();await input().fill('중단해도 유지할 초안');
      const pending=page.waitForRequest(r=>r.url().endsWith('/messages/stream'));await send().click();await pending;
      await page.getByRole('button',{name:'응답 중지',exact:true}).click();release?.();
      check('Stopping response keeps the unsent recovery draft without automatically retrying',await input().inputValue()==='중단해도 유지할 초안');
      await page.getByRole('combobox',{name:'현재 작업 가게'}).selectOption('store-b');
      await page.getByRole('button',{name:'새 분석',exact:true}).click();
      check('Switching stores clears the prior store draft and recovery actions',await input().inputValue()===''&&await page.getByRole('button',{name:'이 대화의 처리 결과 확인',exact:true}).count()===0);
      await page.getByRole('combobox',{name:'현재 작업 가게'}).selectOption('store-a');mode='ok';
      await page.getByRole('button',{name:'새 분석',exact:true}).click();await input().fill('일별 결제액을 원화 그래프로 보여줘');await sendAndFinish();
      await chat().getByRole('button',{name:/일별 결제액.*결과 보기/}).click();
      const main=page.locator('#workspace-main');await keyActivate(main.getByRole('button',{name:'대시보드에 저장',exact:true}));
      const nameField=main.getByLabel('저장 지표 이름',{exact:true});
      for(let i=0;i<100;i++){if(await nameField.evaluate(n=>n===document.activeElement))break;await page.keyboard.press('Tab');}
      assert.ok(await nameField.evaluate(n=>n===document.activeElement),'Save name reachable by keyboard');
      await page.keyboard.press('Control+A');await page.keyboard.type('내 첫 지표');
      if(await page.locator('#workspace-chat-toggle').getAttribute('aria-expanded')==='true')await page.locator('#workspace-chat-toggle').click();
      for(const theme of ['dark','light'])for(const [width,height] of [[1440,900],[768,1024],[390,844]]){
        await page.setViewportSize({width,height});await page.getByRole('combobox',{name:'화면 테마'}).selectOption(theme);
        await main.getByLabel('지표 저장 설정',{exact:true}).scrollIntoViewIfNeeded();
        check(`Save settings ${theme} ${width}px fits workspace`,await main.evaluate(n=>n.scrollWidth<=n.clientWidth+1));
        const saveBox=await main.getByLabel('지표 저장 설정',{exact:true}).boundingBox();
        assert.ok(saveBox.x>=0&&saveBox.x+saveBox.width<=width+1);
        await shot(`save-${theme}-${width}`);
      }
      await page.setViewportSize({width:1440,height:1000});
      await keyActivate(main.getByRole('button',{name:'설정으로 미리보기',exact:true}));await main.getByLabel('저장 전 미리보기').waitFor();
      saveFails=true;await keyActivate(main.getByRole('button',{name:'이 설정으로 저장',exact:true}));
      await keyActivate(main.getByRole('button',{name:'같은 설정으로 다시 시도',exact:true}));await main.getByText('저장 완료',{exact:true}).waitFor();
      check('Keyboard can open save settings, preview, save and retry',true);
      const saves=bodies.filter(b=>typeof b==='object'&&b.save_key);assert.equal(saves.length,2);assert.deepEqual(saves.at(-1),saves.at(-2));
      check('Lost save response retries the identical settings and produces one new widget',widgets['store-a'].filter(w=>w.title==='내 첫 지표').length===1);
    }
    if(await page.locator('#workspace-chat-toggle').getAttribute('aria-expanded')==='true')await page.locator('#workspace-chat-toggle').click();
    for(const width of [390,320]){
      await page.setViewportSize({width,height:844});await page.getByRole('combobox',{name:'화면 테마'}).selectOption(width===390?'dark':'light');
      if(await page.locator('#workspace-chat-toggle').getAttribute('aria-expanded')!=='true')await page.locator('#workspace-chat-toggle').click();
      check(width+'px chat has no horizontal overflow',await chat().evaluate(n=>n.scrollWidth<=n.clientWidth+1));
      check(width+'px question and send action are visible',await input().isVisible()&&await send().isVisible());
      if(!audit){
        mode='error';const mobileQuestion='선택한 파일의 전체 기간에서 결제수단별 금액과 취소가 합계에 어떻게 반영되는지 비교해줘. 원본 부호를 유지하고 아직 저장하지 마.';
        await input().fill(mobileQuestion);await sendAndFinish();
        const footer=chat().locator('textarea').locator('..');
        const recovery=page.getByRole('button',{name:'이 대화의 처리 결과 확인',exact:true});
        const bounds=await send().boundingBox();
        check(width+'px failed request keeps a long draft and reachable recovery/send controls',await input().inputValue()===mobileQuestion&&await recovery.isVisible()&&bounds.y+bounds.height<=844&&await footer.evaluate(n=>n.scrollWidth<=n.clientWidth+1));
        for(let i=0;i<16;i++)await page.keyboard.press('Tab');
        check(width+'px keyboard focus remains inside open chat dialog',await chat().evaluate(n=>n.closest('[role="dialog"]').contains(document.activeElement)));
        await shot('mobile-recovery-'+width);
      }
      await page.keyboard.press('Escape');
      await page.waitForFunction(()=>document.querySelector('#workspace-chat-toggle')?.getAttribute('aria-expanded')==='false');
      await page.waitForFunction(()=>document.activeElement?.id==='workspace-chat-toggle');
      check(width+'px Escape restores keyboard focus to chat toggle',await page.locator('#workspace-chat-toggle').evaluate(n=>n===document.activeElement));await shot('mobile-'+width);
    }
    check('Browser reports no runtime or unhandled fixture errors',report.errors.length===0);
    report.passed=report.checks.every(c=>c.passed);
  }catch(e){report.errors.push(e.stack);await shot('failure').catch(()=>{});throw e;}
  finally{await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
