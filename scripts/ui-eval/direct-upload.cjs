// Real rendered workspace and browser upload helper; deterministic API/Storage fixtures.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs/promises');
const path = require('node:path');

async function main() {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const out = path.join(__dirname, 'artifacts', 'direct-upload');
  await fs.mkdir(out, { recursive: true });
  const checks = [];
  try {
    const page = await browser.newPage({ viewport:{width:1440,height:1000}, acceptDownloads:true });
    page.setDefaultTimeout(30000);
    const bytes = Buffer.alloc(6*1024*1024, 'x');
    const hash = crypto.createHash('sha256').update(bytes).digest('hex');
    const file = { file_id:'file-1', filename:'매출-원본.txt', size_bytes:bytes.length,
      created_at:new Date().toISOString(), status:'stored', kind:'document', project_id:'store-a', project_name:'성수점', bindings:[] };
    let files = [], putCount=0, reservations=0, failCompletion=false, abortTransfer=false, missingTransfer=false;
    const errors=[];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('https://storage.example.test/**', async route => {
      const req=route.request();
      assert.equal(req.headers().authorization,undefined);
      if (req.method()==='PUT') {
        putCount++;
        assert.equal(req.postDataBuffer().length, bytes.length);
        if(abortTransfer){await route.abort('failed');return;}
        await route.fulfill({status:200,contentType:'application/json',body:'{}'});
      } else await route.fulfill({status:200,contentType:'application/octet-stream',body:bytes});
    });
    await page.route('**/api/**', async route => {
      const req=route.request(), p=new URL(req.url()).pathname, method=req.method();
      let body={},status=200;
      if(method==='OPTIONS') body={};
      else if(p==='/api/auth/refresh') body={access_token:'fixture',refresh_token:'fixture'};
      else if(p==='/api/auth/me') body={email:'owner@example.test'};
      else if(p==='/api/projects') body={projects:[{id:'store-a',name:'성수점',description:''}]};
      else if(p==='/api/library/files/sample-workspace') body={project:null};
      else if(p.endsWith('/tables')) body={tables:[]};
      else if(p.endsWith('/ledger-sources')) body={sources:[]};
      else if(p.endsWith('/cash-entries')) body={entries:[],total:0};
      else if(p.endsWith('/search-index')) body={jobs:[],counts:{},total:0,search_enabled:false};
      else if(p==='/api/dashboard/widgets') body={widgets:[]};
      else if(p==='/api/conversations') body={conversations:[]};
      else if(p==='/api/library/files') { assert.equal(method,'GET'); body={files,total:files.length}; }
      else if(p==='/api/uploads/capabilities') body={direct_upload:true,max_size_bytes:20*1024*1024};
      else if(p==='/api/uploads') {
        const payload=req.postDataJSON(); reservations++;
        assert.equal(payload.content_hash,hash); assert.equal(payload.project_id,'store-a');
        assert.equal(payload.filename,file.filename); assert.equal(payload.size_bytes,bytes.length);
        assert.ok(req.postDataBuffer().length<1000);
        status=201; body={session_id:'session-1',upload_url:'https://storage.example.test/upload?token=fixture'};
      } else if(p==='/api/uploads/session-1/complete') {
        if(missingTransfer) {status=409;body={detail:'업로드한 파일을 확인할 수 없습니다.'};}
        else if(failCompletion) {status=422;body={detail:'전송된 파일의 크기 또는 해시가 일치하지 않습니다.'};}
        else {files=[file]; body={...file,replayed:false};}
      } else if(p==='/api/library/files/file-1/download-url') body={url:'https://storage.example.test/download?token=fixture'};
      else { errors.push(method+' '+p);status=404; }
      await route.fulfill({status,headers:{'access-control-allow-origin':'*','access-control-allow-headers':'*'},contentType:'application/json',body:JSON.stringify(body)});
    });
    await page.addInitScript(()=>localStorage.setItem('dataez_refresh_token','fixture'));
    await page.goto(process.env.UI_BASE_URL || 'http://127.0.0.1:3132/dashboard');
    await page.getByRole('button',{name:'데이터 관리',exact:true}).click();
    await page.getByRole('button',{name:'파일 보관함',exact:true}).click();
    const input=page.getByLabel('보관할 파일');
    await input.setInputFiles({name:file.filename,mimeType:'text/plain',buffer:bytes});
    await page.getByText('원본을 보관했습니다. 미리보기에서 검사 후 분석에 연결하세요.',{exact:true}).waitFor();
    assert.equal(putCount,1);assert.equal(reservations,1);
    checks.push('6MiB browser upload uses small JSON reservations and credential-free Storage PUT');
    await page.getByRole('heading',{name:file.filename,exact:true}).waitFor();
    const pending=page.waitForEvent('download');
    await page.getByRole('button',{name:'원본',exact:true}).click();
    const download=await pending;
    assert.equal(download.suggestedFilename(),file.filename);
    const downloaded=await fs.readFile(await download.path());
    assert.equal(crypto.createHash('sha256').update(downloaded).digest('hex'),hash);
    checks.push('signed download preserves Korean filename and bytes');
    await page.screenshot({path:path.join(out,'library-direct-upload.png'),fullPage:true});
    failCompletion=true;
    await input.setInputFiles({name:file.filename,mimeType:'text/plain',buffer:bytes});
    await page.getByRole('alert').getByText('전송된 파일의 크기 또는 해시가 일치하지 않습니다.',{exact:true}).waitFor();
    assert.equal(await page.getByText('전송된 파일을 검증하고 있습니다…',{exact:true}).count(),0);
    checks.push('verification failure is visible and clears progress status');
    failCompletion=false;abortTransfer=true;missingTransfer=true;
    await input.setInputFiles({name:file.filename,mimeType:'text/plain',buffer:bytes});
    await page.getByRole('alert').getByText('업로드한 파일을 확인할 수 없습니다.',{exact:true}).waitFor();
    assert.equal(files.length,1);
    checks.push('Failed Storage transfer plus missing completion is visible; no extra file is registered');
    missingTransfer=false;
    await input.setInputFiles({name:file.filename,mimeType:'text/plain',buffer:bytes});
    await page.getByText('원본을 보관했습니다. 미리보기에서 검사 후 분석에 연결하세요.',{exact:true}).waitFor();
    assert.equal(files.length,1);
    checks.push('Lost Storage response is resolved through authenticated completion, not assumed failed');
    const before=reservations;
    await input.setInputFiles({name:'too-big.txt',mimeType:'text/plain',buffer:Buffer.alloc(20*1024*1024+1)});
    await page.getByRole('alert').getByText(/20MB 이하/).waitFor();
    assert.equal(reservations,before);
    checks.push('oversized file is rejected before reservation or upload');
    assert.deepEqual(errors,[]);
    await fs.writeFile(path.join(out,'report.json'),JSON.stringify({passed:true,api_mocks:true,checks},null,2));
    console.log(JSON.stringify({passed:true,api_mocks:true,checks}));
  } finally { await browser.close(); }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
