#!/usr/bin/env node
// A reproducible entry point for the unchanged production builder.
import { readFileSync, writeFileSync } from 'node:fs';
import { basename, dirname, join } from 'node:path';
import { parseAgentTrace, buildAttachmentClip } from '../src/trace_mechanism/structurer.mjs';

const [input, output, mode] = process.argv.slice(2);
if (!input || !output || (mode && mode !== '--single')) {
  throw new Error('Usage: node tools/build_index.mjs INPUT.txt OUTPUT.json [--single]');
}
const source = readFileSync(input, 'utf8');
const rawName = basename(input).replace(/\.txt$/, '') + '.raw.txt';
const clip = buildAttachmentClip(parseAgentTrace(source, basename(input), '2026-11-02T00:00:00Z'), {
  index_filename: basename(output), raw_sidecar_filename: rawName,
  disable_raw_sidecar_fallback: mode === '--single',
});
writeFileSync(output, JSON.stringify(clip, null, 2) + '\n');
if (clip.carrier_mode === 'raw_sidecar_plus_index') {
  writeFileSync(join(dirname(output), clip.raw_sidecar.filename), source);
}
