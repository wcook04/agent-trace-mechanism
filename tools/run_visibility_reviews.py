#!/usr/bin/env python3
"""Ask a Codex model to review each copy in examples/reviewer-visibility.

Each review is one ``codex exec`` call in an empty folder with a read-only
sandbox, no saved session, no user configuration and no instruction files.
The prompt is the test's prompt.txt with one copy pasted in. Replies are saved
under <test>/replies/<model>/. This costs model usage and its output is not fixed, so
no check runs it.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parents[1] / 'examples/reviewer-visibility'
# told and not-told have the same text in these four copies, so that text is reviewed once.
TEXTS = [f'{history}.{name}' for name in ('before', 'markers', 'generic', 'counted')
         for history in ('told', 'wrongly-refused')] + \
        [f'{history}.{name}' for name in ('full', 'full.note') for history in ('told', 'not-told', 'wrongly-refused')]


# The second example: only the last of three turns is copied. agreed and forbidden share the three last-turn texts.
EARLIER = {'folder': 'earlier-turns',
           'texts': ['agreed.last', 'agreed.last.line-partial', 'agreed.last.line-earlier', 'agreed.last.line-count',
                     'agreed.last.generic', 'agreed.last.counted', 'agreed.whole', 'forbidden.whole']}
FOLDER = {name: 'tool-output' for name in TEXTS} | {name: EARLIER['folder'] for name in EARLIER['texts']}


def review(job):
    codex, model, name, run, out = job
    target = out / f'{name}.{run}.txt'
    if target.exists() and target.read_text().strip():
        return name, run, 'kept'
    folder = HERE / FOLDER[name]
    prompt = (folder / 'prompt.txt').read_text().replace('{copy}', (folder / f'copies/{name}.txt').read_text().rstrip('\n'))
    with tempfile.TemporaryDirectory() as empty:
        done = subprocess.run([codex, 'exec', '--skip-git-repo-check', '--ephemeral', '--ignore-user-config',
                               '--ignore-rules', '-s', 'read-only', '-m', model, '-C', empty, '-o', str(target), '-'],
                              input=prompt, text=True, capture_output=True, timeout=600)
    return name, run, 'ok' if done.returncode == 0 and target.exists() else done.stderr[-300:]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--codex', default='codex')
    parser.add_argument('--model', required=True)
    parser.add_argument('--runs', type=int, default=3)
    parser.add_argument('--parallel', type=int, default=4)
    parser.add_argument('--earlier-turns', action='store_true', help='review the second example')
    args = parser.parse_args()
    out = HERE / (EARLIER['folder'] if args.earlier_turns else 'tool-output') / 'replies' / args.model
    out.mkdir(parents=True, exist_ok=True)
    jobs = [(args.codex, args.model, name, run, out) for name in (EARLIER['texts'] if args.earlier_turns else TEXTS)
            for run in range(1, args.runs + 1)]
    with ThreadPoolExecutor(args.parallel) as pool:
        for name, run, state in pool.map(review, jobs):
            print(name, run, state, flush=True)


if __name__ == '__main__':
    main()
