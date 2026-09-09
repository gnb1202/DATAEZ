const roles=[['bg','작업 배경'],['side','사이드바'],['panel','그래프 패널'],['text','주요 텍스트'],['muted','보조 텍스트'],['accent','주요 강조'],['chart-secondary','비교 데이터'],['chart-cancel','취소 데이터'],['action-bg','주요 버튼'],['success-text','분석 가능']];
document.querySelectorAll('.theme-sample').forEach(sample=>{
  const style=getComputedStyle(sample);
  roles.forEach(([token,label])=>{
    const value=style.getPropertyValue(`--${token}`).trim();
    const row=document.createElement('div');row.className='swatch';
    const color=document.createElement('span');color.className='swatch-color';color.style.backgroundColor=value;
    const copy=document.createElement('span'),title=document.createElement('strong'),code=document.createElement('code');
    title.textContent=label;code.textContent=value.toUpperCase();copy.append(title,code);row.append(color,copy);sample.querySelector('.swatches').append(row);
  });
});
document.querySelectorAll('[data-apply]').forEach(button=>button.addEventListener('click',()=>{
  DataezTheme.setPreference(button.dataset.apply);location.href='index.html';
}));
