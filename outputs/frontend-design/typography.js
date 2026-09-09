(() => {
  const $ = selector => document.querySelector(selector);
  const controls = {'body-size': 'size', 'body-weight': 'weight', 'body-tracking': 'tracking', 'body-leading': 'leading', 'amount-size': 'amount'};
  let settings = DataezType.read() || {...DataezType.defaults};
  let fontsReady = false;
  const defaultSentence = $('#custom-preview').textContent;
  const chart = echarts.init($('#type-chart'), null, {renderer: 'svg'});
  const data = [1800000, 2130000, 1940000, 2510000, 2460000, 3180000, 2780000];
  const labels = ['9/1', '9/2', '9/3', '9/4', '9/5', '9/6', '9/7'];
  const money = new Intl.NumberFormat('ko-KR');
  function drawChart() {
    const style = getComputedStyle(document.documentElement);
    const token = name => style.getPropertyValue(`--${name}`).trim();
    const font = DataezType.fonts[settings.font].family;
    chart.setOption({
      animation: false,
      textStyle: {fontFamily: font, fontSize: settings.size - 2, fontWeight: settings.weight},
      grid: {left: 62, right: 28, top: 24, bottom: 36},
      tooltip: {
        trigger: 'axis', backgroundColor: token('tooltip-bg'), borderColor: token('tooltip-line'), padding: [10, 13],
        textStyle: {fontFamily: font, fontSize: settings.size - 1, color: token('text')},
        extraCssText: `border-radius:6px;font-kerning:none;font-variant-numeric:${settings.tabular ? 'tabular-nums' : 'proportional-nums'};`,
        formatter: p => `${p[0].axisValue}<br>순결제액 <b style="margin-left:16px">${money.format(p[0].value)}원</b>`
      },
      xAxis: {type: 'category', data: labels, boundaryGap: false, axisTick: {show: false}, axisLine: {show: false}, axisLabel: {color: token('muted'), fontFamily: font, fontSize: settings.size - 2, fontWeight: settings.weight, margin: 15}},
      yAxis: {type: 'value', min: 0, max: 4000000, interval: 1000000, axisLabel: {color: token('muted'), fontFamily: font, fontSize: settings.size - 3, fontWeight: settings.weight, formatter: v => v === 0 ? '0' : `${v / 10000}만`}, splitLine: {lineStyle: {color: token('chart-grid'), type: 'dashed', opacity: .7}}},
      series: [{name: '순결제액', type: 'line', data, smooth: false, showSymbol: false, symbolSize: 7,
        lineStyle: {color: token('chart-primary'), width: 2}, itemStyle: {color: token('chart-primary')},
        areaStyle: {color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{offset: 0, color: token('chart-area-start')}, {offset: 1, color: token('chart-area-end')}])}}]
    }, true);
  }
  function render() {
    settings = DataezType.normalize(settings);
    DataezType.applyTo($('#type-sample'), settings);
    DataezType.applyTo($('#number-sample'), settings);
    $('#chosen-font').textContent = DataezType.fonts[settings.font].name;
    const selected = DataezType.fonts[settings.font];
    const weightSlider = $('#body-weight');
    weightSlider.min = selected.weights ? '0' : '400';
    weightSlider.max = selected.weights ? String(selected.weights.length - 1) : '600';
    weightSlider.step = selected.weights ? '1' : '50';
    $('#weight-note').textContent = selected.weights ? '이 글꼴은 400 · 500 · 700 굵기로 조절해요.' : '굵기를 조금씩 조절할 수 있어요.';
    document.querySelectorAll('input[name="font"]').forEach(input => {input.checked = input.value === settings.font;});
    for (const [id, key] of Object.entries(controls)) {
      $(`#${id}`).value = key === 'weight' && selected.weights ? selected.weights.indexOf(settings.weight) : settings[key];
      $(`#${id}-value`).textContent = key === 'tracking' ? `${settings[key].toFixed(3)}em` : key === 'leading' ? settings[key].toFixed(2) : `${settings[key]}${['size', 'amount'].includes(key) ? 'px' : ''}`;
    }
    weightSlider.setAttribute('aria-valuetext', String(settings.weight));
    $('#tabular').checked = settings.tabular;
    $('#tabular').disabled = Boolean(selected.fixedDigits);
    $('.checkbox-control small').textContent = selected.fixedDigits ? '이 글꼴은 숫자 폭이 기본으로 같아요' : '자리마다 같은 폭으로 정렬';
    $('#numeric-mode').textContent = selected.fixedDigits ? `기본 숫자 폭 동일 · ${selected.name}` : settings.tabular ? '숫자 너비 맞춤' : '글자 모양에 따른 숫자 너비';
    $('#css-output').textContent = DataezType.css(settings);
    drawChart();
  }
  document.querySelectorAll('input[name="font"]').forEach(input => input.addEventListener('change', () => {
    settings.font = input.value; render(); $('#action-status').textContent = '';
  }));
  Object.entries(controls).forEach(([id, key]) => $(`#${id}`).addEventListener('input', event => {
    const weights = DataezType.fonts[settings.font].weights;
    settings[key] = key === 'weight' && weights ? weights[Number(event.target.value)] : Number(event.target.value);
    render(); $('#action-status').textContent = '';
  }));
  $('#tabular').addEventListener('change', event => {settings.tabular = event.target.checked; render();});
  $('#sample-text').addEventListener('input', event => {$('#custom-preview').textContent = event.target.value || defaultSentence;});
  $('#reset').addEventListener('click', () => {
    settings = {...DataezType.defaults}; $('#sample-text').value = ''; $('#custom-preview').textContent = defaultSentence;
    render(); $('#action-status').textContent = '확정한 Spoqa 기본 설정으로 되돌렸어요.';
  });
  $('#theme-select').value = DataezTheme.preference;
  $('#theme-select').addEventListener('change', event => DataezTheme.setPreference(event.target.value));
  document.addEventListener('dataez-theme-change', () => {$('#theme-select').value = DataezTheme.preference; drawChart();});
  $('#apply-font').addEventListener('click', () => {
    const result = DataezType.save(settings);
    const params = new URLSearchParams();
    // Carry a URL fallback only when the browser cannot persist the settings.
    if (!result.persisted) {
      params.set('type', JSON.stringify(result.settings));
      params.set('theme', DataezTheme.preference);
    }
    location.href = `index.html${params.size ? '?' + params : ''}`;
  });
  $('#download-settings').addEventListener('click', () => {
    const blob = new Blob([JSON.stringify({product: 'DATA:EZ', scope: 'design-prototype', version: 1, theme: DataezTheme.preference, typography: settings}, null, 2) + '\n'], {type: 'application/json'});
    const href = URL.createObjectURL(blob), link = document.createElement('a');
    link.href = href; link.download = `dataez-typography-${settings.font}.json`; document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(href), 1000);
    $('#action-status').textContent = `${DataezType.fonts[settings.font].name} 설정 파일을 저장했어요.`;
  });
  $('#copy-css').addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(DataezType.css(settings));
      $('#action-status').textContent = 'CSS를 복사했어요. 글꼴 파일은 fonts 폴더에 있어요.';
    } catch {
      $('.css-details').open = true;
      const range = document.createRange(); range.selectNodeContents($('#css-output'));
      const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range); $('#css-output').focus();
      $('#action-status').textContent = '자동 복사를 사용할 수 없어 CSS를 펼쳤어요. 선택한 내용을 복사해주세요.';
    }
  });
  new ResizeObserver(() => chart.resize()).observe($('#type-chart'));
  render();
  const sampleText = '우리 가게 결제 취소 정산 기록 0123456789₩−%';
  Promise.allSettled(Object.values(DataezType.fonts).map(async font => {
    const loaded = await Promise.all((font.weights || [400]).map(weight => document.fonts.load(`${weight} 16px "${font.face}"`, sampleText)));
    if (loaded.some(faces => !faces.length)) throw new Error(font.face);
    return font.face;
  })).then(results => {
    const failed = results.filter(r => r.status === 'rejected');
    fontsReady = failed.length === 0;
    $('#font-status').classList.toggle('error', !fontsReady);
    $('#font-status').textContent = fontsReady ? `${Object.keys(DataezType.fonts).length}개 글꼴 준비 완료 · 위 카드는 고정된 조건, 아래 화면은 선택한 설정으로 비교합니다.` : '일부 글꼴을 불러오지 못했어요. 페이지를 새로고침한 뒤 다시 비교해주세요.';
    drawChart();
  });
  window.typographyLab = {chart, get settings() {return {...settings};}, get fontsReady() {return fontsReady;}};
})();
