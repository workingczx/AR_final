"""Inspect geometry alignment and anterior coverage in the public NasalSeg archive."""
import argparse
import gzip
import json
import re
from zipfile import ZipFile

import numpy as np


def read_volume(archive, name):
    header, payload = archive.read(name).split(b'\n\n', 1)
    fields = dict(line.split(': ', 1) for line in header.decode().splitlines() if ': ' in line)
    if (fields['type'], fields['encoding'], fields['endian'], fields['space']) != (
            'int16', 'gzip', 'little', 'left-posterior-superior'):
        raise ValueError(f'Unexpected NRRD format in {name}')
    shape = tuple(map(int, fields['sizes'].split()))
    volume = np.frombuffer(gzip.decompress(payload), dtype='<i2').reshape(shape, order='F')
    return volume, fields


def numbers(value):
    return np.array(re.findall(r'[-+.0-9eE]+', value), dtype=float)


def audit(path):
    rows = []
    with ZipFile(path) as archive:
        for index in range(1, 131):
            case = f'P{index:03d}'
            image, header = read_volume(archive, f'images/{case}_img.nrrd')
            seg, seg_header = read_volume(archive, f'labels/{case}_seg.nrrd')
            matched = image.shape == seg.shape and all(
                np.allclose(numbers(header[key]), numbers(seg_header[key]), rtol=0, atol=1e-5)
                for key in ('space directions', 'space origin'))

            label_ids = np.unique(seg)
            # LPS axis 1 increases toward the posterior for these axis-aligned files.
            directions = numbers(seg_header['space directions']).reshape(3, 3)
            if not np.allclose(directions, np.diag(np.diag(directions))) or directions[1, 1] <= 0:
                raise ValueError(f'Unexpected orientation in {case}')
            foreground = np.where(seg != 0)
            anterior_index = int(foreground[1].min())
            rows.append({'case': case, 'ct_label_grid_matches': matched, 'shape': list(image.shape),
                         'spacing_mm': np.diag(directions).tolist(),
                         'label_ids': label_ids.tolist(),
                         'anterior_margin_before_any_label_mm': round(anterior_index * directions[1, 1], 3)})
    aligned = [row for row in rows if row['ct_label_grid_matches']]
    return {'ct_label_pairs': len(rows),
            'matched_ct_label_grids': len(aligned),
            'anterior_ct_margin_in_grid_matched_cases_mm': {
                'min': min(row['anterior_margin_before_any_label_mm'] for row in aligned),
                'max': max(row['anterior_margin_before_any_label_mm'] for row in aligned)},
            'notes': ['Margin describes image coverage in front of annotations.',
                      'Anatomical nostril landmarks and a swept entry trajectory require separate verification.'],
            'cases': rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive')
    args = parser.parse_args()
    print(json.dumps(audit(args.archive), indent=2))
