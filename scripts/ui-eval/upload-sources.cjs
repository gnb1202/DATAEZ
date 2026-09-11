// Real rendered workspace and browser upload helper; deterministic API/Storage fixtures.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs/promises');
const path = require('node:path');

async function main() {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const out = path.join(__dirname, 'artifacts', 'upload-sources');
  await fs.mkdir(out, { recursive: true });
  const checks = [];
  try {
    const page = await browser.newPage({ viewport:{width:1440,height:1000}, acceptDownloads:true });
    page.setDefaultTimeout(30000);
    const bytes = Buffer.alloc(6*1024*1024, 'x');
    const hash = crypto.createHash('sha256').update(bytes).digest('hex');
    const file = { file_id:'file-1', filename:'매출-원본.txt', size_bytes:bytes.length,
      created_at:new Date().toISOString(), status:'stored', kind:'document', project_id:'store-a', project_name:'성수점', bindings:[] };
    let files = [], putCount=0, reservations=0, failCompletion=false;
    const errors=[];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('https://storage.example.test/**', async route => {
      const req=route.request();
      assert.equal(req.headers().authorization,undefined);
      if (req.method()==='PUT') {
        putCount++;
        assert.equal(req.postDataBuffer().length, bytes.length);
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
      else if(p==='/api/conversations') body=method==='POST'?{conversation_id:'conv-1',project_id:'store-a',title:'분석'}:{conversations:[]};
      else if(p.endsWith('/messages')) body={messages:[]};
      else if(p.endsWith('/messages/stream')) {
        const text=req.postDataBuffer().toString();
        assert.ok(req.postDataBuffer().length<1500);assert.ok(text.includes('stored_file_ids')&&text.includes('file-1'));
        checks.push('chat sends only stored_file_ids after 6MiB Storage PUT');
        await route.fulfill({contentType:'text/event-stream',headers:{'access-control-allow-origin':'*'},body:'data: '+JSON.stringify({type:'done',data:{message_id:'msg-1',content:'분석 완료',steps:[],charts:[],table_data:[]}})+'\n\n'});return;
      }
      else if(p.endsWith('/documents')&&method==='POST') { assert.ok(req.postDataBuffer().length<1000);assert.ok(req.postDataBuffer().toString().includes('stored_file_id'));checks.push('document upload sends only stored_file_id');body={file_id:'file-1'}; }
      else if(p.endsWith('/import-mapping/inspect')) { assert.ok(req.postDataBuffer().length<1000);assert.ok(req.postDataBuffer().toString().includes('stored_file_id'));checks.push('mapping inspection sends only stored_file_id');body={columns:['amount','occurred_at'],row_count:1,suggested_mapping:{},candidates:{},sample:[],first_sheet_only:false}; }
      else if(p==='/api/library/files') { assert.equal(method,'GET'); body={files,total:files.length}; }
      else if(p==='/api/uploads/capabilities') body={direct_upload:true,max_size_bytes:20*1024*1024};
      else if(p==='/api/uploads') {
        const payload=req.postDataJSON(); reservations++;
        assert.equal(payload.content_hash,hash); assert.equal(payload.project_id,'store-a');
         assert.equal(payload.size_bytes,bytes.length);
        assert.ok(req.postDataBuffer().length<1000);
        status=201; body={session_id:'session-1',upload_url:'https://storage.example.test/upload?token=fixture'};
      } else if(p==='/api/uploads/session-1/complete') {
        if(failCompletion) {status=422;body={detail:'전송된 파일의 크기 또는 해시가 일치하지 않습니다.'};}
        else {files=[file]; body={...file,replayed:false};}
      } else if(p==='/api/library/files/file-1/download-url') body={url:'https://storage.example.test/download?token=fixture'};
      else { errors.push(method+' '+p);status=404; }
      await route.fulfill({status,headers:{'access-control-allow-origin':'*','access-control-allow-headers':'*'},contentType:'application/json',body:JSON.stringify(body)});
    });
    await page.addInitScript(()=>localStorage.setItem('dataez_refresh_token','fixture'));
    await page.goto(process.env.UI_BASE_URL || 'http://127.0.0.1:3132/dashboard');
    await page.getByRole('button',{name:'새 분석',exact:true}).click();
    await page.getByRole('textbox',{name:'분석 요청',exact:true}).fill('첨부 매출을 분석해줘');
    await page.locator('#workspace-chat input[type="file"]').setInputFiles({name:'매출.csv',mimeType:'text/csv',buffer:bytes});
    await page.getByRole('button',{name:'분석 요청 보내기'}).click();
    await page.getByText('분석 완료',{exact:true}).first().waitFor();
    assert.equal(putCount,1);
    await page.getByRole('button',{name:'데이터 관리',exact:true}).click();
    await page.getByLabel('검색 참고 문서',{exact:true}).setInputFiles({name:'규정.txt',mimeType:'text/plain',buffer:bytes});
    await page.getByRole('button',{name:'문서 올리기',exact:true}).click();
    await page.getByText('문서를 저장했습니다. 검색 준비는 자동으로 진행됩니다.',{exact:true}).waitFor();
    assert.equal(putCount,2);
    await page.screenshot({path:path.join(out,'stored-source-paths.png'),fullPage:true});
    assert.deepEqual(errors,[]);
    await fs.writeFile(path.join(out,'report.json'),JSON.stringify({passed:true,api_mocks:true,checks},null,2));
    console.log(JSON.stringify({passed:true,api_mocks:true,checks}));
  } finally { await browser.close(); }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
