"""Export an existing run; this command never calls a model or sends a message."""
import argparse
import json
from pathlib import Path
import sys
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab_model_monitor.animation import projection
from lab_model_monitor.config import ROOT, STATE
from lab_model_monitor.store import RunStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run_id', type=UUID)
    parser.add_argument('--site', action='store_true', help='Prepare this run as the Site animation snapshot')
    args = parser.parse_args()
    payload = projection(RunStore().get(str(args.run_id)))
    directory = STATE / 'artifacts' / str(args.run_id)
    directory.mkdir(parents=True, exist_ok=True)
    for index, sample in enumerate(payload['samples']):
        if sample['html']:
            (directory / f'model-{index + 1}.html').write_text(sample['html'], encoding='utf-8', newline='')
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    (directory / 'display.json').write_text(serialized, encoding='utf-8')
    if args.site:
        (ROOT / 'lib' / 'animation-results.json').write_text(serialized, encoding='utf-8')
    print(json.dumps({'run_id': payload['run_id'], 'directory': str(directory),
                      'samples': [{k: s[k] for k in ('requested_model', 'status', 'sha256')} for s in payload['samples']]}))


if __name__ == '__main__':
    main()
