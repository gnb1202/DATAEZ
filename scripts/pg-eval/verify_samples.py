"""Read-only QA of saved XLSX types/values and CSV checksums; no authoring."""
import csv
from datetime import datetime
import hashlib
import json

from openpyxl import load_workbook

from oracle import ROOT, SAMPLES


def main():
    manifest = json.loads((SAMPLES / 'manifest.json').read_text(encoding='utf-8'))
    for item in manifest['files']:
        data = (SAMPLES / item['name']).read_bytes()
        assert hashlib.sha256(data).hexdigest() == item['sha256']
        with (SAMPLES / item['name']).open(encoding='utf-8-sig', newline='') as f:
            assert len(list(csv.reader(f))) - 1 == item['rows']
    with (SAMPLES / '01_gangnam_pg.csv').open(encoding='utf-8-sig', newline='') as f:
        reference = list(csv.reader(f))
    book_path = ROOT / manifest['workbook']
    book = load_workbook(book_path, data_only=False)
    assert book.sheetnames == ['가상PG_강남']
    sheet = book.active
    assert (sheet.max_row, sheet.max_column) == (41, 13)
    for r, row in enumerate(sheet.iter_rows()):
        for c, cell in enumerate(row):
            assert cell.data_type not in {'e', 'f'}, (cell.coordinate, cell.value)
            wanted = reference[r][c]
            if r and c in {1, 2, 7, 8} and wanted:
                assert cell.data_type == 's' and cell.value == wanted, cell.coordinate
            elif r and c == 0:
                assert isinstance(cell.value, datetime) and cell.value.isoformat() == wanted[:19], cell.coordinate
            elif r and c == 11:
                assert isinstance(cell.value, datetime) and cell.value.date().isoformat() == wanted
            elif r and c in {4, 10, 12}:
                assert cell.data_type == 'n' and cell.value == int(wanted), cell.coordinate
            else:
                assert ('' if cell.value is None else str(cell.value)) == wanted, cell.coordinate
    report = {'passed': True, 'csv_files': len(manifest['files']), 'workbook': manifest['workbook'],
              'workbook_sha256': hashlib.sha256(book_path.read_bytes()).hexdigest(),
              'worksheets': 1, 'cells_compared': 41 * 13, 'formulas_or_error_cells': 0,
              'id_policy': 'Exact text values, including leading zeros; no apostrophe stored.',
              'date_policy': 'Native Excel wall-clock dates; import applies Asia/Seoul.',
              'render_note': 'Artifact renderer preview formats numeric text IDs as scientific notation despite XLSX text types and @ formats. Saved XML/cell values and all canonical imported rows were verified exactly; do not use the preview to inspect ID precision.'}
    (SAMPLES / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
