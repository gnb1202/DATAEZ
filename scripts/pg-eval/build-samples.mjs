// Synthetic fixtures only: no merchant/customer data or actual PG export contract.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const author = process.env.DATAEZ_AUTHOR_DIR || path.join(root, '.local-test/e-author');
const require = createRequire(path.join(author, 'package.json'));
const { Workbook, SpreadsheetFile, FileBlob } = await import(pathToFileURL(require.resolve('@oai/artifact-tool')));
const out = path.join(root, 'samples/pg-evaluation');
const workbookDir = path.join(root, 'outputs/01a07df0-dba6-7841-8cde-f4505b7e6614');
await fs.mkdir(out, { recursive: true });
await fs.mkdir(workbookDir, { recursive: true });
const headers = ['거래일시', '거래번호', '원거래번호', '거래구분', '거래금액', '통화', '결제수단', '주문번호', '가맹점ID', '판매채널', 'PG수수료', '정산예정일', '정산예정금액'];
const pgMapping = { amount_column: '거래금액', occurred_at_column: '거래일시', event_id_column: '거래번호', original_event_id_column: '원거래번호', currency_column: '통화', currency: 'KRW', timezone: 'Asia/Seoul', event_kind: 'signed' };
const cashMapping = { amount_column: '금액', occurred_at_column: '발생일시', currency: 'KRW', timezone: 'Asia/Seoul', event_kind: 'signed' };
const id = n => '0000202609' + String(n).padStart(12, '0');
const event = (n, date, amount, original = '', store = '강남') => {
  const fee = Math.round(amount * 0.03); // Fictional flat 3%; no tax/fee accuracy claim.
  const settled = new Date(date.slice(0, 10) + 'T00:00:00Z');
  settled.setUTCDate(settled.getUTCDate() + 3);
  return [date, id(n), original, amount < 0 ? '부분취소' : '승인', amount, 'KRW', n % 3 === 0 ? '간편결제' : '카드', 'ORDER-' + id(n), store === '강남' ? '000001001' : '000002001', n % 2 ? '예약웹' : '매장', fee, settled.toISOString().slice(0, 10), amount - fee];
};
const base = [event(1, '2026-08-31T23:55:00+09:00', 100000), event(2, '2026-09-01T00:05:00+09:00', 24000)];
for (let d = 1; d <= 6; d++) {
  for (let k = 0; k < 6; k++) base.push(event(d * 100 + k, `2026-09-0${d}T${String(10 + k).padStart(2, '0')}:15:00+09:00`, 12000 + ((d * 3 + k) % 8) * 4000));
}
base.push(event(88001, '2026-09-02T18:30:00+09:00', -20000, id(1)));
base.push(event(88002, '2026-09-03T18:30:00+09:00', -30000, id(1)));
const added = [];
for (let d = 7; d <= 8; d++) {
  for (let k = 0; k < 6; k++) added.push(event(d * 100 + k, `2026-09-0${d}T${String(10 + k).padStart(2, '0')}:15:00+09:00`, 16000 + ((d + k) % 7) * 4000));
}
added.push(event(99001, '2026-09-08T16:00:00+09:00', -8000, id(700)));
added.push(event(99002, '2026-09-08T16:05:00+09:00', -4000, id(700)));
const hongdae = [event(1, '2026-08-31T23:58:00+09:00', 70000, '', '홍대')];
for (let d = 1; d <= 8; d++) for (let k = 0; k < 3; k++) hongdae.push(event(d * 100 + k, `2026-09-0${d}T${12 + k}:00:00+09:00`, 22000 + k * 6000 + d * 1000, '', '홍대'));
hongdae.push(event(901, '2026-09-08T18:00:00+09:00', -15000, id(100), '홍대'));
const cashHeaders = ['발생일시', '금액', '분류', '메모'];
const cash = [['2026-08-31T20:00:00+09:00', 18000, '현금', '월말 현금 장부']];
for (let d = 1; d <= 6; d++) cash.push([`2026-09-0${d}T18:00:00+09:00`, 10000 + d * 1000, '현금', '마감 장부']);
const cashReview = [[...cash[1].slice(0, 3), '기존 행 재기록 — 제외할 예제'], ['2026-09-02T19:00:00+09:00', cash[2][1], '현금', '같은 금액의 별도 실제 거래 — 포함할 예제'], ['2026-09-07T18:00:00+09:00', 17000, '현금', '신규'], ['2026-09-08T18:00:00+09:00', 18000, '현금', '신규']];
const files = [];
function csv(columns, rows) {
  const quote = x => '"' + String(x ?? '').replaceAll('"', '""') + '"';
  return '\uFEFF' + [columns, ...rows].map(r => r.map(quote).join(',')).join('\r\n') + '\r\n';
}
async function write(name, columns, rows, purpose) {
  const data = Buffer.from(csv(columns, rows), 'utf8');
  await fs.writeFile(path.join(out, name), data);
  files.push({ name, rows: rows.length, sha256: createHash('sha256').update(data).digest('hex'), purpose });
}
await write('01_gangnam_pg.csv', headers, base, '강남 PG 최초 업로드');
await write('02_gangnam_pg_renamed.csv', headers, base, '01과 바이트까지 동일; 같은 출처에 재업로드');
await write('03_gangnam_pg_overlap.csv', headers, [...base.slice(-12), ...added], '기존 12건 + 신규 14건; 신규만 반영');
await write('04_partial_refunds_repeat.csv', headers, added.slice(-2), '이미 반영된 부분 취소 2건의 재업로드');
const changed = [...base[2]]; changed[4] += 1000; changed[10] = Math.round(changed[4] * 0.03); changed[12] = changed[4] - changed[10];
await write('05_conflict.csv', headers, [changed, event(9991, '2026-09-08T20:00:00+09:00', 50000)], '같은 거래번호의 금액 변경; 전체 파일 반영 금지');
const badAmount = event(9992, '2026-09-08T20:00:00+09:00', 50000); badAmount[4] = '';
const badCurrency = event(9993, '2026-09-08T20:00:00+09:00', 50000); badCurrency[5] = 'USD';
const badDate = event(9994, '2026-09-08T20:00:00+09:00', 50000); badDate[0] = '2026-02-30';
await write('06_invalid.csv', headers, [event(9995, '2026-09-08T20:00:00+09:00', 50000), badAmount, badCurrency, badDate], '빈 금액·다른 통화·불가능한 날짜; 전체 검증 실패');
await write('07_hongdae_pg.csv', headers, hongdae, '다른 가게; 강남과 겹치는 거래번호도 별개로 인정');
await write('08_cash_first.csv', cashHeaders, cash, '거래번호 없는 별도 현금 출처');
await write('09_cash_review.csv', cashHeaders, cashReview, '후보 2건 중 파일 행 2 제외·행 3 포함, 신규 2건');
await write('10_settlement_reference.csv', ['정산기준일', '정산입금액', '수수료', '설명'], [['2026-09-04', 242500, 7500, '합성 정산 참고자료; 결제 매출과 합산 금지'], ['2026-09-05', 194000, 6000, '매출 원장의 대체값이 아님']], '일반 테이블로 업로드하는 정산 참고자료');
const precision = event(9999, '2026-09-08T23:59:59+09:00', 0); precision[4] = '9007199254740993.01'; precision[10] = '0'; precision[12] = precision[4];
await write('11_precision_boundary.csv', headers, [precision], '별도 테스트 전용; 매출 데모에 합산하지 않음');
await write('12_cash_pending.csv', cashHeaders, [[...cash[1].slice(0, 3), '판단을 남겨 둘 후보 A'], [...cash[2].slice(0, 3), '판단을 남겨 둘 후보 B'], ['2026-09-08T21:00:00+09:00', 20000, '현금', '후보 결정 전에는 함께 미반영']], '챗봇의 검토 안내 검증용; 후보 2건을 미결정 상태로 유지');

const wb = Workbook.create();
const sheet = wb.worksheets.add('가상PG_강남');
// Excel date cells store wall-clock values. The import mapping applies Seoul time.
const excelRows = base.map(r => r.map((v, i) => i === 0 ? new Date(String(v).slice(0, 19) + 'Z') : i === 11 ? new Date(v + 'T00:00:00Z') : v));
const range = sheet.getRange(`A1:M${base.length + 1}`);
sheet.getRange(`B2:C${base.length + 1}`).setNumberFormat('@');
sheet.getRange(`H2:I${base.length + 1}`).setNumberFormat('@');
range.values = [headers, ...excelRows];
range.format.font = { name: 'Arial', size: 10 };
range.format.rowHeight = 24;
range.format.verticalAlignment = 'center';
sheet.getRange(`B2:C${base.length + 1}`).setNumberFormat('@');
sheet.getRange(`H2:I${base.length + 1}`).setNumberFormat('@');
sheet.getRange(`A2:A${base.length + 1}`).setNumberFormat('yyyy-mm-dd hh:mm:ss');
sheet.getRange(`L2:L${base.length + 1}`).setNumberFormat('yyyy-mm-dd');
for (const col of ['E', 'K', 'M']) sheet.getRange(`${col}2:${col}${base.length + 1}`).setNumberFormat('#,##0;[Red](#,##0);–');
const widths = [24, 28, 28, 10, 13, 8, 11, 35, 14, 11, 13, 15, 17];
widths.forEach((width, i) => { sheet.getRange(`${String.fromCharCode(65 + i)}:${String.fromCharCode(65 + i)}`).format.columnWidth = width; });
sheet.tables.add(`A1:M${base.length + 1}`, true, 'SyntheticPgEvents');
sheet.getRange('A1:M1').format = { fill: '#163D48', font: { name: 'Arial', color: '#FFFFFF', bold: true, size: 10 }, rowHeight: 32 };
sheet.showGridLines = false;
sheet.freezePanes.freezeRows(1);
sheet.freezePanes.freezeColumns(2);
wb.recalculate();
console.log(JSON.stringify(await wb.inspect({ kind: 'table', range: '가상PG_강남!A1:G5', include: 'values,formulas', tableMaxRows: 5, tableMaxCols: 7 })));
console.log(JSON.stringify(await wb.inspect({ kind: 'match', searchTerm: '#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!', options: { useRegex: true, maxResults: 20 } })));
const workbookPath = path.join(workbookDir, 'DATAEZ_가상PG_강남.xlsx');
await (await SpreadsheetFile.exportXlsx(wb)).save(workbookPath);
// Render the saved workbook, so validation covers the delivered file.
const saved = await SpreadsheetFile.importXlsx(await FileBlob.load(workbookPath));
const png = await saved.render({ sheetName: '가상PG_강남', range: 'A1:M10', scale: 1, format: 'png' });
await fs.writeFile(path.join(author, 'pg-preview.png'), new Uint8Array(await png.arrayBuffer()));
await fs.writeFile(path.join(out, 'manifest.json'), JSON.stringify({ synthetic: true, as_of: '2026-09-08', timezone: 'Asia/Seoul', currency: 'KRW', pg_mapping: pgMapping, cash_mapping: cashMapping, files, workbook: path.relative(root, workbookPath).replaceAll('\\', '/'), cash_decisions: { '2': 'exclude', '3': 'include' } }, null, 2) + '\n');
console.log(JSON.stringify({ csvFiles: files.length, workbookPath, baseEvents: base.length }));
