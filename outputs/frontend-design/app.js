/* Design prototype. Synthetic data only; no API, LLM or cloud storage calls. */
const $ = (q, root = document) => root.querySelector(q);
const $$ = (q, root = document) => [...root.querySelectorAll(q)];
const iconPaths = {
  store:'<path d="M3 10h18l-2-6H5l-2 6Zm2 0v10h14V10M9 20v-6h6v6M3 10c0 3 4 3 4 0 0 3 5 3 5 0 0 3 5 3 5 0 0 3 4 3 4 0"/>',
  chevron:'<path d="m9 10 3 3 3-3"/>',plus:'<path d="M12 5v14M5 12h14"/>',
  grid:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  folder:'<path d="M3 7V5a2 2 0 0 1 2-2h5l3 3h6a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z"/>',
  history:'<path d="M3 5v5h5M3 10a9 9 0 1 1 0 5M12 7v5l3 2"/>',
  settings:'<path d="m9 3-1 3-3 1-2 3 2 2-1 3 3 3 3-1 2 2 3-2v-3l3-2-1-4-3-1-1-3Z"/><circle cx="11" cy="11" r="3"/>',
  panel:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/>',
  'panel-close':'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16m-7-11 3 3-3 3"/>',
  calendar:'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 11h18"/>',
  files:'<path d="M7 3h10l4 4v12a2 2 0 0 1-2 2H7V3Zm10 0v5h4M3 5v13"/>',
  file:'<path d="M5 3h9l5 5v13H5V3Zm9 0v5h5M8 12h8M8 16h6"/>',
  arrow:'<path d="M5 12h14m-5-5 5 5-5 5"/>',up:'<path d="M12 19V5m-5 5 5-5 5 5"/>',
  line:'<path d="M3 3v18h18M6 15l5-6 4 3 6-8"/>',bars:'<path d="M3 3v18h18M7 17v-6m5 6V6m5 11V9"/>',
  pie:'<path d="M11 3a9 9 0 1 0 10 10H11V3Zm4-1v7h7a8 8 0 0 0-7-7Z"/>',
  return:'<path d="M4 7h10a6 6 0 0 1 0 12H9M8 3 4 7l4 4"/>',check:'<path d="m5 12 4 4L19 6"/>',
  search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',
  upload:'<path d="M4 15v5h16v-5M12 16V3m-5 5 5-5 5 5"/>',
  download:'<path d="M4 15v5h16v-5M12 3v13m-5-5 5 5 5-5"/>',
  close:'<path d="m6 6 12 12M6 18 18 6"/>',chat:'<path d="M4 3h16v14H9l-5 4V3Z"/>'
};
function icons(root = document) { $$('[data-icon]', root).forEach(el => { el.innerHTML = `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${iconPaths[el.dataset.icon] || iconPaths.file}</svg>`; }); }
icons();
const rows = [
  {date:'9/1',card:1510000,cash:340000,refund:50000}, {date:'9/2',card:1780000,cash:430000,refund:80000},
  {date:'9/3',card:1660000,cash:280000,refund:0}, {date:'9/4',card:2100000,cash:530000,refund:120000},
  {date:'9/5',card:2020000,cash:490000,refund:50000}, {date:'9/6',card:2750000,cash:540000,refund:110000},
  {date:'9/7',card:2460000,cash:520000,refund:200000}
];
const money = n => new Intl.NumberFormat('ko-KR').format(n);
const sum = key => rows.reduce((n, r) => n + r[key], 0);
const net = r => r.card + r.cash - r.refund;
const state = {type:'line', scope:'all', view:'workspace', saved:false, pending:false};
const charts = new Map();
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
let palette, tooltip;
let font = 'Arial, "Malgun Gothic", sans-serif';
function syncChartTheme(){
  const style=getComputedStyle(document.documentElement);
  const token=name=>style.getPropertyValue(`--${name}`).trim();
  font=token('font') || font;
  palette={primary:token('chart-primary'),secondary:token('chart-secondary'),cancel:token('chart-cancel'),muted:token('muted'),line:token('chart-grid'),text:token('text'),accentStrong:token('accent-strong'),cancelStrong:token('chart-cancel-strong'),areaStart:token('chart-area-start'),areaEnd:token('chart-area-end')};
  tooltip={trigger:'axis',backgroundColor:token('tooltip-bg'),borderColor:token('tooltip-line'),borderWidth:1,padding:[10,13],textStyle:{color:palette.text,fontFamily:font,fontSize:11},axisPointer:{type:'line',lineStyle:{color:token('line-control'),type:'dashed'}},extraCssText:`border-radius:7px;box-shadow:0 7px 22px ${token('shadow')};`};
}
syncChartTheme();
function makeChart(id, options) { const dom = document.getElementById(id); const chart = charts.get(id) || echarts.init(dom,null,{renderer:'svg'}); charts.set(id,chart); chart.setOption({animation:!reduced,animationDuration:500,animationDurationUpdate:350,textStyle:{fontFamily:font},...options},true); return chart; }
function currentValues(){return rows.map(r => state.scope==='cash'?r.cash:state.scope==='card'?r.card-r.refund:net(r));}
function scopeLabel(){return state.scope==='cash'?'현금 결제액':state.scope==='card'?'카드 순결제액':'순결제액';}
function markDraft(){state.saved=false;$('#draft-status').textContent='저장 전';$('#save-dashboard').innerHTML='<span data-icon="plus"></span>대시보드에 저장';icons($('#save-dashboard'));}
function renderMain(){
  const values=currentValues(), label=scopeLabel();
  $('#chart-title').textContent=`일별 ${label}`;$('#legend-label').textContent=label;
  $('#chart-subtitle').textContent=state.scope==='cash'?'현금 장부에 기록된 결제액이에요.':'결제액에서 카드 취소금액을 차감했어요.';
  $('#scope-caption').textContent=`강남점 · ${state.scope==='cash'?'현금':state.scope==='card'?'카드':'카드 + 현금'} · 수수료 차감 전`;
  $('#main-chart').setAttribute('aria-label',`9월 1일부터 7일까지 일별 ${label}. ${values.map((v,i)=>`${rows[i].date} ${money(v)}원`).join(', ')}`);
  makeChart('main-chart',{
    grid:{left:51,right:26,top:23,bottom:35},tooltip:{...tooltip,formatter:params=>`${params[0].axisValue}<br><span style="color:${palette.primary}">●</span> ${label}<b style="margin-left:22px">${money(params[0].value)}원</b>`},
    xAxis:{type:'category',data:rows.map(r=>r.date),boundaryGap:state.type==='bar',axisLine:{show:false},axisTick:{show:false},axisLabel:{color:palette.muted,fontSize:10,margin:13}},
    yAxis:{type:'value',min:0,splitNumber:4,axisLabel:{color:palette.muted,fontSize:9,formatter:v=>v===0?'0':`${v/10000}만`},splitLine:{lineStyle:{color:palette.line,type:'dashed',opacity:.65}}},
    series:[{name:label,type:state.type,data:values,smooth:false,symbol:'circle',showSymbol:false,symbolSize:7,lineStyle:{width:2.4,color:palette.primary},itemStyle:{color:palette.primary,borderRadius:[4,4,0,0]},barMaxWidth:35,areaStyle:state.type==='line'?{color:new echarts.graphic.LinearGradient(0,0,0,1,[{offset:0,color:palette.areaStart},{offset:1,color:palette.areaEnd}])}:undefined,emphasis:{focus:'series',itemStyle:{color:palette.accentStrong}}}]
  });
  $$('[data-chart]').forEach(b=>{b.classList.toggle('selected',b.dataset.chart===state.type);b.setAttribute('aria-pressed',String(b.dataset.chart===state.type));});
}
function renderCharts(){
  renderMain();
  [['spark-net',rows.map(net),palette.primary],['spark-gross',rows.map(r=>r.card+r.cash),palette.secondary],['spark-refund',rows.map(r=>r.refund),palette.cancel]].forEach(([id,values,color])=>makeChart(id,{grid:{left:2,right:2,top:3,bottom:3},xAxis:{type:'category',show:false,data:rows.map(r=>r.date)},yAxis:{type:'value',show:false,min:0},series:[{type:'line',data:values,smooth:false,showSymbol:false,lineStyle:{color,width:1.6},areaStyle:{color,opacity:.03}}]}));
  makeChart('donut-chart',{tooltip:{...tooltip,trigger:'item',formatter:p=>`${p.name}<br><b>${money(p.value)}원</b> · ${p.percent.toFixed(1)}%`},series:[{type:'pie',radius:['62%','77%'],center:['48%','50%'],startAngle:90,padAngle:3,avoidLabelOverlap:true,label:{show:false},emphasis:{scaleSize:4},itemStyle:{borderRadius:3},data:[{name:'카드',value:sum('card'),itemStyle:{color:palette.primary}},{name:'현금',value:sum('cash'),itemStyle:{color:palette.secondary}}]}],graphic:[{type:'text',left:'center',top:'39%',style:{text:'결제수단',fill:palette.muted,font:`10px ${font}`}},{type:'text',left:'center',top:'51%',style:{text:'2가지',fill:palette.text,font:`500 18px ${font}`}}]});
  makeChart('refund-chart',{tooltip:{...tooltip,formatter:p=>`${p[0].axisValue}<br>취소금액 <b>${money(p[0].value)}원</b>`},grid:{left:37,right:11,top:22,bottom:27},xAxis:{type:'category',data:rows.map(r=>r.date),axisLine:{show:false},axisTick:{show:false},axisLabel:{color:palette.muted,fontSize:9,interval:0}},yAxis:{type:'value',min:0,splitNumber:2,axisLabel:{color:palette.muted,fontSize:9,formatter:v=>v===0?'0':`${v/10000}만`},splitLine:{lineStyle:{color:palette.line,type:'dashed',opacity:.65}}},series:[{name:'취소금액',type:'bar',data:rows.map(r=>r.refund),barMaxWidth:20,itemStyle:{color:palette.cancel,borderRadius:[3,3,0,0]},emphasis:{itemStyle:{color:palette.cancelStrong}}}]});
}
function resizeCharts(){charts.forEach((chart)=>{if(chart.getDom().offsetWidth)chart.resize();});}
const observer=new ResizeObserver(()=>requestAnimationFrame(resizeCharts));observer.observe($('#main'));
function setChat(open){$('#app').classList.toggle('chat-hidden',!open);$('#chat').hidden=!open;$('#chat-toggle').setAttribute('aria-expanded',String(open));requestAnimationFrame(resizeCharts);}
if(innerWidth<=1050)setChat(false);
$('#chat-toggle').onclick=()=>setChat($('#chat').hidden);$('#close-chat').onclick=()=>{setChat(false);$('#chat-toggle').focus();};
let toastTimer;function toast(message){$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,4200);}
function showView(view){state.view=view;['workspace','files','history'].forEach(v=>$(`#${v}-view`).hidden=v!==view);$$('[data-view]').forEach(b=>{b.classList.toggle('active',b.dataset.view===view);if(b.dataset.view===view)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});$('#breadcrumb-current').textContent={workspace:'대시보드',files:'데이터 관리',history:'분석 기록'}[view];if(view==='workspace')requestAnimationFrame(resizeCharts);}
$$('[data-view]').forEach(b=>b.onclick=()=>{showView(b.dataset.view);if(b.dataset.view==='files')setChat(false);});
$('#new-analysis').onclick=()=>{showView('workspace');setChat(true);$('#chat-input').focus();toast('시안에서는 현재 샘플 분석을 이어서 수정합니다.');};
$('#recent-analysis').onclick=$('#open-history').onclick=()=>{showView('workspace');setChat(true);};
$$('[data-chart]').forEach(b=>b.onclick=()=>{state.type=b.dataset.chart;renderMain();markDraft();});
$('#save-dashboard').onclick=()=>{state.saved=true;$('#draft-status').textContent='시안에 저장됨';$('#save-dashboard').innerHTML='<span data-icon="check"></span>저장됨';icons($('#save-dashboard'));toast('현재 시안에 저장했습니다. 새로고침하면 초기 상태로 돌아갑니다.');};
function addMessage(text,user=false){const div=document.createElement('div');div.className=`message ${user?'user-message':'assistant-message'}`;const p=document.createElement('p');p.textContent=text;div.append(p);$('#messages').append(div);div.scrollIntoView({block:'nearest',behavior:reduced?'instant':'smooth'});}
function send(text){if(!text.trim()||state.pending)return;addMessage(text,true);showView('workspace');setChat(true);state.pending=true;let response='이 시안에서는 “막대그래프로 바꿔줘”, “현금만 보여줘”, “카드만 보여줘”, “전체를 선그래프로 보여줘”를 체험할 수 있어요.';let changed=false;
  if(/막대|선그래프|현금|카드|전체/.test(text)){if(/막대/.test(text))state.type='bar';if(/선그래프/.test(text))state.type='line';if(/현금만/.test(text))state.scope='cash';else if(/카드만/.test(text))state.scope='card';else if(/전체|카드와 현금|카드랑 현금/.test(text))state.scope='all';changed=true;response=`${scopeLabel()}을 ${state.type==='line'?'선':'막대'}그래프로 바꿨어요. 선택한 자료의 합계는 ${money(currentValues().reduce((a,b)=>a+b,0))}원입니다. 중앙의 보조 지표는 전체 카드·현금 기준을 유지합니다.`;}
  setTimeout(()=>{if(changed){renderMain();markDraft();}addMessage(response);state.pending=false;},reduced?0:330);
}
$('#chat-form').onsubmit=e=>{e.preventDefault();const input=$('#chat-input');send(input.value);input.value='';};
$('#chat-input').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('#chat-form').requestSubmit();}};
$$('[data-prompt]').forEach(b=>b.onclick=()=>send(b.dataset.prompt));
const files=[{id:'card',name:'카드매출_2026-09.csv',type:'csv',size:'846 B',date:'9월 8일 09:42',status:'ready',label:'분석 가능',detail:'카드 결제·취소 · 13행'}, {id:'cash',name:'현금장부_2026-09.csv',type:'csv',size:'408 B',date:'9월 8일 09:38',status:'ready',label:'분석 가능',detail:'현금 결제 · 7행'}, {id:'august',name:'카드매출_2026-08.csv',type:'csv',size:'182 KB',date:'9월 7일 16:20',status:'pending',label:'검토 필요',detail:'보관함 UI용 예시 항목'}, {id:'policy',name:'매장_취소규정.pdf',type:'pdf',size:'92 KB',date:'9월 6일 11:05',status:'stored',label:'보관 중',detail:'보관함 UI용 예시 항목'}];
function csvFor(id){const data=['발생일,종류,금액,결제수단'];rows.forEach((r,i)=>{const date=`2026-09-0${i+1}`;data.push(`${date},결제,${r[id]},${id==='card'?'카드':'현금'}`);if(id==='card'&&r.refund)data.push(`${date},취소,${-r.refund},카드`);});return '\uFEFF'+data.join('\r\n');}
files.filter(file=>['card','cash'].includes(file.id)).forEach(file=>file.size=`${new Blob([csvFor(file.id)]).size} B`);
function download(id){const file=files.find(f=>f.id===id);if(!['card','cash'].includes(id)){toast('이 항목은 파일 보관함의 상태를 보여주는 예시입니다.');return;}const blob=new Blob([csvFor(id)],{type:'text/csv;charset=utf-8'});const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=file.name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function renderFiles(){const query=$('#file-search').value.toLowerCase(),type=$('#file-filter').value;const selected=files.filter(f=>f.name.toLowerCase().includes(query)&&(type==='all'||type===f.type));$('#file-rows').replaceChildren();selected.forEach(file=>{const tr=document.createElement('tr');const name=document.createElement('td');const nameButton=document.createElement('button');nameButton.className='file-name-button';const badge=document.createElement('span');badge.className=`file-icon ${file.type==='pdf'?'pdf':''}`;badge.textContent=file.type.toUpperCase();const copy=document.createElement('span'),strong=document.createElement('strong'),small=document.createElement('small');strong.textContent=file.name;small.textContent=file.detail;copy.append(strong,small);nameButton.append(badge,copy);nameButton.onclick=()=>previewFile(file.id);name.append(nameButton);tr.append(name);const status=document.createElement('td');const statusBadge=document.createElement('span');statusBadge.className=`badge ${file.status}`;statusBadge.textContent=file.label;status.append(statusBadge);tr.append(status);[file.size,file.date].forEach(text=>{const td=document.createElement('td');td.textContent=text;tr.append(td);});const actions=document.createElement('td');actions.className='row-actions';const view=document.createElement('button');view.textContent='미리보기';view.onclick=()=>previewFile(file.id);actions.append(view);if(['card','cash'].includes(file.id)){const dl=document.createElement('button');dl.setAttribute('aria-label',`${file.name} 다운로드`);dl.innerHTML='<span data-icon="download"></span>';dl.onclick=()=>download(file.id);actions.append(dl);}tr.append(actions);$('#file-rows').append(tr);});icons($('#file-rows'));$('#no-files').hidden=selected.length>0;$('#library-count').textContent=`파일 ${selected.length}개`;$('.nav-count').textContent=String(files.length);$('[data-tab="files"] span').textContent=String(files.length);}
$('#file-search').oninput=renderFiles;$('#file-filter').onchange=renderFiles;
$$('[data-tab]').forEach(b=>b.onclick=()=>{$$('[data-tab]').forEach(t=>{t.classList.toggle('selected',t===b);t.setAttribute('aria-pressed',String(t===b));});$('#file-library').hidden=b.dataset.tab!=='files';$('#ledger-library').hidden=b.dataset.tab!=='ledgers';});
function openDialog(title,content){$('#detail-title').textContent=title;$('#detail-content').replaceChildren();if(typeof content==='string')$('#detail-content').innerHTML=content;else $('#detail-content').append(content);$('#detail-dialog').showModal();}
$('#close-dialog').onclick=()=>$('#detail-dialog').close();$('#detail-dialog').onclick=e=>{if(e.target===$('#detail-dialog')){const rect=e.target.getBoundingClientRect();if(e.clientX<rect.left||e.clientX>rect.right||e.clientY<rect.top||e.clientY>rect.bottom)e.target.close();}};
function analyzeFile(id){state.scope=id;showView('workspace');setChat(true);renderMain();markDraft();if($('#detail-dialog').open)$('#detail-dialog').close();addMessage(`${files.find(f=>f.id===id).name}을 선택했어요. 중앙에 일별 ${scopeLabel()}을 표시했습니다.`);}
function previewFile(id){const file=files.find(f=>f.id===id);if(!['card','cash'].includes(id)){const p=document.createElement('p');p.textContent='보관함 상태를 보여주기 위한 예시 항목입니다. 실제 원본이 있는 카드·현금 CSV에서 미리보기와 다운로드를 체험해보세요.';openDialog(file.name,p);return;}const content=document.createElement('div');const p=document.createElement('p');p.textContent='원본 데이터 · 시안용 합성 파일. 다운로드한 CSV와 표시한 집계의 금액이 일치합니다.';content.append(p);const pre=document.createElement('pre');pre.textContent=csvFor(id).replace('\uFEFF','');content.append(pre);const button=document.createElement('button');button.className='primary';button.textContent='이 파일로 분석';button.onclick=()=>analyzeFile(id);content.append(button);openDialog(file.name,content);}
$$('[data-analyze]').forEach(b=>b.onclick=()=>analyzeFile(b.dataset.analyze));
$('#evidence-button').onclick=()=>{const values=currentValues();openDialog('집계표와 계산 기준',`<p>강남점 · 2026. 9. 1. – 9. 7. · ${scopeLabel()}<br>${state.scope==='cash'?'현금 결제액을 발생일별로 합산합니다.':'결제액에서 카드 취소금액을 발생일 기준으로 차감합니다.'} 수수료는 차감하지 않습니다.<br>시안용 합성 데이터이며 실제 SQL 실행 결과는 아닙니다.</p><table class="file-table"><thead><tr><th>날짜</th><th>${scopeLabel()}</th></tr></thead><tbody>${rows.map((r,i)=>`<tr><td>2026. ${r.date.replace('/','. ')}.</td><td>${money(values[i])}원</td></tr>`).join('')}<tr><td>합계</td><td>${money(values.reduce((a,b)=>a+b,0))}원</td></tr></tbody></table>`);};
function filePicker(){showView('files');setChat(false);$('[data-tab="files"]').click();toast('분석할 파일의 미리보기를 열어 “이 파일로 분석”을 선택하세요.');}
$('#sources-button').onclick=$('#chat-files').onclick=$('#attach-file').onclick=filePicker;
$('#upload-file').onclick=()=>$('#file-input').click();$('#file-input').onchange=e=>{const file=e.target.files[0];if(!file)return;files.unshift({id:`local-${Date.now()}`,name:file.name,type:file.name.split('.').pop().toLowerCase(),size:`${Math.max(1,Math.ceil(file.size/1024))} KB`,date:'방금 선택',status:'stored',label:'로컬 선택',detail:'현재 화면의 목록만 추가 · 서버 업로드 없음'});renderFiles();toast('파일 이름을 시안 목록에 추가했습니다. 파일 내용은 업로드하지 않았습니다.');e.target.value='';};
$('#store-select').onclick=()=>openDialog('가게 선택','<p>이 시안은 모닝테이블 강남점의 샘플 데이터로 구성했습니다. 실제 연결 단계에서는 소유한 가게 목록과 명시적인 비교 대상 선택을 제공합니다.</p>');
$('#settings').onclick=()=>openDialog('시안 정보','<p>DATA:EZ 분석 작업 공간 · OpenAI Platform 화면 참고<br>차콜 배경, 얇은 경계선, 간결한 왼쪽 메뉴와 오른쪽 접이식 채팅을 적용했습니다.<br><br>그래프: Apache ECharts 6.0.0 · SVG 렌더러<br>데이터: 2026년 9월 1일–7일 합성 데이터<br>이 페이지는 실제 계정·LLM·Supabase에 연결되지 않은 디자인 시안입니다.</p>');
$('#account').onclick=()=>openDialog('샘플 계정','<p>김사장님 · 모닝테이블 강남점<br>화면 구성을 확인하기 위한 샘플 계정입니다.</p>');
document.addEventListener('keydown',e=>{if(e.key.toLowerCase()==='n'&&!e.ctrlKey&&!e.metaKey&&!e.altKey&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)&&!$('#detail-dialog').open)$('#new-analysis').click();});
$('#theme-select').value=DataezTheme.preference;
$('#theme-select').onchange=event=>DataezTheme.setPreference(event.target.value);
document.addEventListener('dataez-theme-change',()=>{
  $('#theme-select').value=DataezTheme.preference;
  syncChartTheme();
  renderCharts();
});
async function refreshTypography(){
  const chosen=DataezType.read();
  if(!chosen)return;
  DataezType.applyTo(document.documentElement,chosen);
  try { await document.fonts.load(`${chosen.weight} 16px "${DataezType.fonts[chosen.font].face}"`); } catch {}
  syncChartTheme();renderCharts();resizeCharts();
}
document.addEventListener('dataez-type-change',refreshTypography);
renderFiles();showView('workspace');renderCharts();
refreshTypography();
window.designPrototype = {state,rows,charts,totals:{gross:sum('card')+sum('cash'),refund:sum('refund'),net:rows.reduce((n,r)=>n+net(r),0)}};
