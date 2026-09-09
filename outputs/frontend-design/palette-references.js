/* Reference-derived DATA:EZ proposals, not official brand palettes. Local preview only. */
(() => {
  const proposals = [
    { id:'blue', letter:'A', name:'차콜 + 블루', tag:'확정 · 9/9', description:'선택과 실행에 블루를 사용합니다. 그린 상태 표시와 역할이 분리됩니다.', rationale:'토스의 색상 단계 + Square의 분석 구성', tradeoff:'국내 금융 화면과 가까운 인상. 로고와 레이아웃으로 DATA:EZ의 개성을 더할 수 있습니다.',
      dark:{bg:'#191B1F',side:'#121417',panel:'#22252A',text:'#F2F4F7',muted:'#A8B0BB',line:'#3B414B',accent:'#82B4FF',action:'#316AC4',onAction:'#FFFFFF',success:'#8BCEAF',cancel:'#E3A0A8'},
      light:{bg:'#F5F7FA',side:'#EDF0F4',panel:'#FFFFFF',text:'#20262F',muted:'#5B6574',line:'#D7DFE8',accent:'#245BB5',action:'#245BB5',onAction:'#FFFFFF',success:'#28724F',cancel:'#A74659'} },
    { id:'indigo', letter:'B', name:'잉크 + 인디고', tag:'분석 도구의 인상', description:'약한 보랏빛이 도는 바탕과 인디고. 차트와 숫자에 시선을 모읍니다.', rationale:'Mercury의 다크 화면 + Stripe의 차트 구성', tradeoff:'사업자 분석 도구에 어울리는 방향. 보라색 면적은 버튼과 핵심 차트에 제한합니다.',
      dark:{bg:'#191920',side:'#131319',panel:'#23232D',text:'#F2F1F8',muted:'#ADABBF',line:'#42414F',accent:'#B1A9FF',action:'#655BBE',onAction:'#FFFFFF',success:'#8BCEAF',cancel:'#E3A0A8'},
      light:{bg:'#F6F6FA',side:'#EFEEF5',panel:'#FFFFFF',text:'#262336',muted:'#656078',line:'#DAD8E5',accent:'#6256B1',action:'#6256B1',onAction:'#FFFFFF',success:'#28724F',cancel:'#A74659'} },
    { id:'mint', letter:'C', name:'차콜 + 민트', tag:'이전 민트안', description:'기존 민트안을 그대로 비교합니다. 부드러운 녹색 계열의 화면입니다.', rationale:'이전 DATA:EZ 팔레트 기록', tradeoff:'기존 시안의 분위기를 유지합니다. 강조와 성공 상태가 비슷해 라벨·형태로 함께 구분합니다.',
      dark:{bg:'#202020',side:'#141414',panel:'#202020',text:'#EDEDEC',muted:'#A2ADA5',line:'#373D38',accent:'#78C8B0',action:'#E8EBE8',onAction:'#1C2A21',success:'#A8D0B9',cancel:'#D78D94'},
      light:{bg:'#F6F8F6',side:'#EEF2EE',panel:'#FFFFFF',text:'#202A23',muted:'#55685C',line:'#D5DFD7',accent:'#26775E',action:'#263C2E',onAction:'#FFFFFF',success:'#2E6243',cancel:'#AA5263'} }
  ];
  const rows = [
    {date:'9/1',gross:1850000,refund:50000},{date:'9/2',gross:2210000,refund:80000},
    {date:'9/3',gross:1940000,refund:0},{date:'9/4',gross:2630000,refund:120000},
    {date:'9/5',gross:2510000,refund:50000},{date:'9/6',gross:3290000,refund:110000},
    {date:'9/7',gross:2980000,refund:200000}
  ];
  const money = value => new Intl.NumberFormat('ko-KR').format(value);
  const totals = rows.reduce((t,r) => ({gross:t.gross+r.gross,refund:t.refund+r.refund}),{gross:0,refund:0});
  const font = '"Spoqa Han Sans Neo", "Noto Sans KR", sans-serif';
  const roles = [['bg','작업 배경'],['panel','그래프 패널'],['text','주요 텍스트'],['accent','강조·순결제'],['success','분석 가능'],['cancel','취소금액']];
  let mode = 'dark', type = 'line';
  const container = document.getElementById('candidates');
  const charts = new Map();
  proposals.forEach(p => {
    const card = document.createElement('article');
    card.className='candidate';card.id=`candidate-${p.id}`;card.setAttribute('aria-labelledby',`title-${p.id}`);
    card.innerHTML=`<div class="candidate-top"><div class="candidate-label"><span>DIRECTION ${p.letter}</span><b>${p.tag}</b></div><h3 id="title-${p.id}">${p.name}</h3><p>${p.description}</p></div><div class="preview"><div class="mini-nav"><span class="active">대시보드</span><span>데이터</span><span class="store">강남점</span></div><div class="preview-body"><div class="metric-label">이번 주 순결제액</div><div class="net-amount">${money(totals.gross-totals.refund)}<small>원</small></div><div class="mini-kpis"><span>총 결제액<b>${money(totals.gross)}원</b></span><span class="refund">취소금액<b>${money(totals.refund)}원</b></span></div><div class="chart" id="chart-${p.id}" role="img" aria-label="일별 순결제액과 취소금액. 상세 수치는 아래 샘플 데이터 표에서 확인할 수 있습니다."></div><div class="legend"><span><i></i>순결제액</span><span class="refund"><i></i>취소금액</span></div><div class="preview-bottom"><span class="status">✓ 분석 가능</span><span class="action-sample">강조 버튼 예시</span></div></div></div><div class="color-list"></div><div class="candidate-bottom"><strong>${p.rationale}</strong>${p.tradeoff}</div>`;
    container.append(card);
    charts.set(p.id,echarts.init(document.getElementById(`chart-${p.id}`),null,{renderer:'svg'}));
  });
  document.getElementById('sample-rows').innerHTML=rows.map(r=>`<tr><th scope="row">${r.date}</th><td>${money(r.gross)}</td><td>${money(r.refund)}</td><td>${money(r.gross-r.refund)}</td></tr>`).join('')+`<tr><th scope="row">합계</th><td>${money(totals.gross)}</td><td>${money(totals.refund)}</td><td>${money(totals.gross-totals.refund)}</td></tr>`;
  function render(){
    document.body.dataset.mode=mode;
    proposals.forEach(p=>{
      const c=p[mode],card=document.getElementById(`candidate-${p.id}`);
      Object.entries(c).forEach(([key,value])=>card.style.setProperty(`--c-${key}`,value));
      card.style.colorScheme=mode;
      card.querySelector('.color-list').innerHTML=roles.map(([key,label])=>`<div class="swatch"><i style="background:${c[key]}"></i><div><span>${label}</span><code>${c[key]}</code></div></div>`).join('');
      charts.get(p.id).setOption({animation:false,textStyle:{fontFamily:font},grid:{left:41,right:9,top:16,bottom:29},tooltip:{trigger:'axis',confine:true,backgroundColor:c.panel,borderColor:c.line,textStyle:{color:c.text,fontFamily:font,fontSize:12},valueFormatter:value=>`${money(value)}원`},xAxis:{type:'category',data:rows.map(r=>r.date),boundaryGap:type==='bar',axisLine:{show:false},axisTick:{show:false},axisLabel:{fontSize:10,color:c.muted}},yAxis:{type:'value',min:0,max:3500000,interval:1000000,axisLabel:{fontSize:10,color:c.muted,formatter:v=>`${v/10000}만`},splitLine:{lineStyle:{color:c.line,type:'dashed'}}},series:[{name:'순결제액',type,data:rows.map(r=>r.gross-r.refund),itemStyle:{color:c.accent,borderRadius:[3,3,0,0]},lineStyle:{width:2.5,color:c.accent},areaStyle:type==='line'?{color:c.accent,opacity:.08}:undefined,showSymbol:false,barMaxWidth:17},{name:'취소금액',type,data:rows.map(r=>r.refund),itemStyle:{color:c.cancel,borderRadius:[3,3,0,0]},lineStyle:{width:2,color:c.cancel,type:'dashed'},showSymbol:false,barMaxWidth:17}]},true);
    });
    document.querySelectorAll('button[data-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.mode===mode)));
    document.querySelectorAll('button[data-chart]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.chart===type)));
  }
  document.querySelectorAll('button[data-mode]').forEach(b=>b.addEventListener('click',()=>{mode=b.dataset.mode;render();}));
  document.querySelectorAll('button[data-chart]').forEach(b=>b.addEventListener('click',()=>{type=b.dataset.chart;render();}));
  const observer=new ResizeObserver(()=>charts.forEach(chart=>chart.resize()));
  document.querySelectorAll('.chart').forEach(el=>observer.observe(el));
  render();
  document.fonts.ready.then(()=>charts.forEach(chart=>chart.resize()));
})();
