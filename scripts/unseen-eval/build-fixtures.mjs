import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const dir=path.join(root,'samples/unseen-v1');
const previews=path.join(root,'.local-test/unseen-fixture-previews');
const spec=JSON.parse(await fs.readFile(path.join(dir,'source.json'),'utf8'));
await fs.mkdir(previews,{recursive:true});
const quote=v=>{const s=v==null?'':String(v);return /[",\n\r]/.test(s)?'"'+s.replaceAll('"','""')+'"':s;};
for(const [key,f] of Object.entries(spec.files)){
  const wb=Workbook.create(),sheet=wb.worksheets.add('거래');
  sheet.showGridLines=false;
  const rows=f.rows.map(row=>row.map((v,i)=>{
    if(v===null)return null;
    if(f.excel&&f.columns[i]===f.date)return new Date(v+'T00:00:00Z');
    if(f.columns[i]===f.amount||f.columns[i]==='fee')return Number(v);
    return v;
  }));
  const data=[f.columns,...rows];
  const range=sheet.getRangeByIndexes(0,0,data.length,f.columns.length);
  f.columns.forEach((column,i)=>{if(column==='주문번호'||column==='receipt_code'||column==='접수ID')sheet.getRangeByIndexes(0,i,data.length,1).setNumberFormat('@');});
  range.values=data;range.format.font={name:'Arial',size:11};range.format.rowHeight=25;range.format.columnWidth=24;
  const header=sheet.getRangeByIndexes(0,0,1,f.columns.length);
  header.format={fill:'#242A34',font:{name:'Arial',size:11,bold:true,color:'#FFFFFF'}};
  f.columns.forEach((column,i)=>{
    const values=sheet.getRangeByIndexes(1,i,rows.length,1);
    if(column===f.amount||column==='fee')values.setNumberFormat('#,##0.00;[Red]-#,##0.00;0.00');
    if(f.excel&&column===f.date)values.setNumberFormat('yyyy-mm-dd');
    if(column==='주문번호'||column==='비고'||column==='메모')sheet.getRangeByIndexes(0,i,data.length,1).format.columnWidth=column==='주문번호'?34:140;
  });
  wb.recalculate();
  const check=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!',options:{useRegex:true,maxResults:10}});
  await fs.writeFile(path.join(previews,key+'-inspect.json'),JSON.stringify(check));
  const preview=await wb.render({sheetName:'거래',range:`A1:${String.fromCharCode(64+f.columns.length)}${Math.min(data.length,7)}`,scale:1,format:'png'});
  await fs.writeFile(path.join(previews,key+'.png'),new Uint8Array(await preview.arrayBuffer()));
  const target=path.join(dir,key);await fs.mkdir(target,{recursive:true});
  if(f.excel){await (await SpreadsheetFile.exportXlsx(wb)).save(path.join(target,f.filename));}
  else{
    // CSV is the raw import fixture. Serializing the populated cells preserves
    // intentional nulls, identifiers and differing date-text formats.
    await fs.writeFile(path.join(target,f.filename),'\uFEFF'+range.values.map(r=>r.map(quote).join(',')).join('\r\n')+'\r\n');
  }
}
await fs.mkdir(path.join(dir,'document'),{recursive:true});
await fs.writeFile(path.join(dir,'document/업무메모.md'),spec.document);
console.log('Created eight import fixtures and one untrusted-content document.');
