"""Promote a manually sanitized candidate with an independently authored test contract.

Never copies production traces/data. Writes a NEW question set; never runs a model.
"""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from catalog import DEFAULT, load_catalog


def promote(candidate_path, contract_path, output_path, source=DEFAULT):
    candidate = json.loads(Path(candidate_path).read_text(encoding='utf-8'))
    keys = {'schema_version','kind','question','expected_behavior','synthetic_confirmed'}
    if set(candidate) != keys or candidate['schema_version'] != 1 or candidate['kind'] != 'synthetic_regression_candidate' or candidate['synthetic_confirmed'] is not True:
        raise ValueError('Only the reviewed synthetic candidate export is supported')
    if not all(isinstance(candidate[k],str) and len(candidate[k].strip()) >= 5 for k in ('question','expected_behavior')):
        raise ValueError('Question and expected behavior are required')
    contract = json.loads(Path(contract_path).read_text(encoding='utf-8'))
    if contract.get('question') != candidate['question']:
        raise ValueError('Contract question must exactly match the reviewed synthetic question')
    if contract.get('review') != candidate['expected_behavior']:
        raise ValueError('Contract review must preserve the candidate expected behavior')
    catalog = load_catalog(source)
    catalog['cases'].append(contract)
    # Validates all IDs, source scopes and frozen values with the existing
    # independent Decimal fixture oracle before writing anything persistent.
    with TemporaryDirectory(prefix='dataez-candidate-') as temp:
        path = Path(temp)/'questions.json'
        path.write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf-8')
        load_catalog(path)
    with Path(output_path).open('x',encoding='utf-8') as output:
        json.dump(catalog,output,ensure_ascii=False,indent=2)
        output.write('\n')
    return contract['id']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--contract',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--questions',type=Path,default=DEFAULT)
    args = parser.parse_args()
    try:
        case_id = promote(args.candidate,args.contract,args.output,args.questions)
        print(f'Validated {case_id}. New question set: {args.output}. No model calls made.')
    except (ValueError,KeyError,OSError) as error:
        parser.exit(1,f'Candidate not promoted: {error}\n')
