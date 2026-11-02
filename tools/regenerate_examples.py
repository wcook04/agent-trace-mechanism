#!/usr/bin/env python3
"""Build all current public projections and indexes; --check compares without edits."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from trace_mechanism.parser import parse_codex_session, parse_claude_session
from trace_mechanism.views import render, structured

ROOT = Path(__file__).resolve().parents[1]


def generate():
    outputs = {}

    def save(path, value):
        outputs[path] = value.encode() if isinstance(value, str) else value

    def view(source, stem, parser):
        turns = parser(ROOT / source)
        save(stem + '.compact.txt', render(turns) + '\n')
        save(stem + '.detailed.txt', render(turns, True) + '\n')
        save(stem + '.expected.json', json.dumps(structured(turns), ensure_ascii=False, indent=2) + '\n')

    for provider, parser in [('codex', parse_codex_session), ('claude', parse_claude_session)]:
        base = 'examples' if provider == 'codex' else 'tests/fixtures'
        view(f'{base}/{provider}.jsonl', f'{base}/{provider}', parser)
    for phase in ('before', 'after'):
        view(f'examples/codex-retrieval/source-{phase}.jsonl',
             f'examples/codex-retrieval/{phase}', parse_codex_session)

    def index(source_name, output_name, single=False):
        source = outputs.get(source_name, (ROOT / source_name).read_bytes() if (ROOT / source_name).exists() else None)
        if source is None:
            raise ValueError(source_name)
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            src, dst = temp / Path(source_name).name, temp / Path(output_name).name
            src.write_bytes(source)
            subprocess.run(['node', str(ROOT / 'tools/build_index.mjs'), str(src), str(dst)] +
                           (['--single'] if single else []), check=True)
            save(output_name, dst.read_bytes())
            clip = json.loads(dst.read_text())
            if clip['carrier_mode'] == 'raw_sidecar_plus_index':
                raw = clip['raw_sidecar']['filename']
                save(str(Path(output_name).parent / raw), (temp / raw).read_bytes())

    index('examples/codex.detailed.txt', 'examples/production-structured-clip.json', single=True)
    index('examples/codex-retrieval/after.detailed.txt', 'examples/codex-retrieval/after.index.json', single=True)
    index('examples/controlled-run/assembled.detailed.txt', 'examples/controlled-run/structured-attachment.json')

    clip_provenance = {
        'source_file': 'src/trace_mechanism/structurer.mjs',
        'source_sha256': hashlib.sha256((ROOT / 'src/trace_mechanism/structurer.mjs').read_bytes()).hexdigest(),
        'fixture': 'examples/codex.detailed.txt',
        'fixture_sha256': hashlib.sha256(outputs['examples/codex.detailed.txt']).hexdigest(),
        'output': 'examples/production-structured-clip.json',
        'output_sha256': hashlib.sha256(outputs['examples/production-structured-clip.json']).hexdigest(),
        'invocation': 'node tools/build_index.mjs examples/codex.detailed.txt examples/production-structured-clip.json --single',
        'validation': 'Reproduction, exact source reconstruction and semantic action regressions are separate checks.',
    }
    save('docs/structured-clip-provenance.json', json.dumps(clip_provenance, indent=2) + '\n')
    historical = json.loads((ROOT / 'examples/controlled-run/provenance.json').read_text())
    historical['structured_index_rebuilt'] = {
        'builder': 'src/trace_mechanism/structurer.mjs', 'source_sha256': clip_provenance['source_sha256'],
        'command': 'node tools/build_index.mjs examples/controlled-run/assembled.detailed.txt examples/controlled-run/structured-attachment.json',
        'boundary': 'Historical native rendered text is frozen. Only the interpretation index is rebuilt.',
    }
    for name in historical['files']:
        path = 'examples/controlled-run/' + name
        data = outputs.get(path, (ROOT / path).read_bytes())
        historical['files'][name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    save('examples/controlled-run/provenance.json', json.dumps(historical, indent=2) + '\n')
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    stale = []
    for name, data in generate().items():
        target = ROOT / name
        if args.check:
            if not target.exists() or target.read_bytes() != data:
                stale.append(name)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    if stale:
        raise SystemExit('Stale generated examples: ' + ', '.join(stale))
    print('Generated examples ' + ('verified.' if args.check else 'updated.'))


if __name__ == '__main__':
    main()
