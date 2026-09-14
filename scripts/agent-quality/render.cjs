// ECharts engine smoke test of real backend output, not the React dashboard UI.
const fs = require('node:fs');
const path = require('node:path');
const echarts = require('../../web/node_modules/echarts');
const dir = path.resolve(process.argv[2]);
const input = JSON.parse(fs.readFileSync(path.join(dir, 'render-input.json'), 'utf8'));
const results = [];
fs.mkdirSync(path.join(dir, 'charts'), { recursive: true });
for (const row of input) {
  for (let index = 0; index < row.charts.length; index++) {
    const chart = row.charts[index];
    const record = { id: row.id, index, passed: false, engine: echarts.version, kind: 'ECharts SVG SSR', react_ui_tested: false };
    let engine;
    try {
      if (!/^[A-Za-z0-9_-]+$/.test(row.id)) throw Error('Invalid case ID');
      if (!['line', 'bar', 'pie'].includes(chart.chart_type)) throw Error('Invalid chart type');
      const points = chart.data.map(item => {
        if (!(chart.x_key in item) || !(chart.y_key in item)) throw Error('Missing axis');
        const value = item[chart.y_key];
        if (value !== null && (typeof value === 'boolean' || value === '' || !Number.isFinite(Number(value)))) throw Error('Invalid number');
        return { name: String(item[chart.x_key] ?? '(분류 미제공)'), value: value === null ? null : Number(value) };
      });
      engine = echarts.init(null, null, { renderer: 'svg', ssr: true, width: 900, height: 420 });
      engine.setOption({ animation: false, backgroundColor: '#fff', color: ['#3975da','#7e9bbd','#759f8f','#b59173'],
        title: { text: row.id + ' · ' + chart.chart_type, left: 24, top: 12 },
        ...(chart.chart_type === 'pie' ? { series: [{ type:'pie', radius:['35%','65%'], data:points }] } : {
          grid: { left:85, right:35, top:70, bottom:75 },
          xAxis:{ type:'category',data:points.map(p=>p.name),axisLabel:{hideOverlap:true} },
          yAxis:{type:'value'}, series:[{type:chart.chart_type,data:points,connectNulls:false}]
        }) });
      const svg = engine.renderToSVGString();
      if (!svg.includes('<svg') || /(?:NaN|Infinity)/.test(svg)) throw Error('Invalid SVG geometry');
      if (points.some(p=>p.value!==null) && !svg.includes('<path')) throw Error('No chart geometry');
      const filename = `charts/${row.id}-${index}.svg`;
      fs.writeFileSync(path.join(dir,filename),svg);
      Object.assign(record,{passed:true,file:filename,point_count:points.length,empty_dataset:points.length===0});
    } catch (error) { record.error = error.message; }
    finally { engine?.dispose(); }
    results.push(record);
  }
}
fs.writeFileSync(path.join(dir,'render-results.json'),JSON.stringify(results,null,2));
process.exit(results.every(r=>r.passed)?0:1);
