#!/usr/bin/env python3
"""Create before/after sheets only from matching, successful capture manifests.

Usage: python make-comparisons.py BASELINE_ARTIFACT CANDIDATE_ARTIFACT OUTPUT_DIR
Requires Pillow. Source captures are never changed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def load(root: Path):
    manifest = json.loads((root / 'capture-manifest.json').read_text())
    result = {}
    for capture in manifest['captures']:
        if capture['journey_result'] != 'passed':
            continue
        key = tuple(str(capture[k]) for k in (
            'screen_and_state', 'locale', 'font_scale', 'api_level', 'physical_size_px',
            'density_dpi', 'feature_flags',
        ))
        if key in result:
            raise ValueError(f'ambiguous capture: {key}')
        result[key] = capture
    return result


def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    baseline, candidate, output = map(Path, sys.argv[1:])
    before, after = load(baseline), load(candidate)
    common = sorted(before.keys() & after.keys())
    if not common:
        raise SystemExit('No matching captures from successful journeys; no comparisons produced.')
    output.mkdir(parents=True, exist_ok=True)
    font = ImageFont.load_default()
    index = []
    for key in common:
        a, b = before[key], after[key]
        with Image.open(baseline / a['file']) as left, Image.open(candidate / b['file']) as right:
            left, right = left.convert('RGB'), right.convert('RGB')
            if left.size != right.size:
                raise ValueError(f'image dimensions differ: {key}')
            width, height = left.size
            sheet = Image.new('RGB', (width * 2 + 24, height + 72), 'white')
            draw = ImageDraw.Draw(sheet)
            draw.text((8, 6), f"Baseline {a['commit_sha'][:12]}", fill='black', font=font)
            draw.text((width + 16, 6), f"Candidate {b['commit_sha'][:12]}", fill='black', font=font)
            draw.text((8, 28), f'{key[0]} | {key[1]} | font {key[2]}', fill='black', font=font)
            sheet.paste(left, (8, 60))
            sheet.paste(right, (width + 16, 60))
            filename = f'{key[0]}-{key[1]}-{key[2]}.png'
            sheet.save(output / filename, optimize=True)
            index.append({'comparison': filename, 'baseline': a['file'], 'candidate': b['file'],
                          'baseline_sha': a['commit_sha'], 'candidate_sha': b['commit_sha']})
    (output / 'comparison-manifest.json').write_text(json.dumps(index, indent=2) + '\n')
    print(f'Created {len(index)} comparisons; unmatched or failed captures were omitted.')


if __name__ == '__main__':
    main()
