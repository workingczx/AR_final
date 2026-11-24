"""Verify the P002 entry, collision, model toggle and return path."""
import argparse
import json
from pathlib import Path
from zipfile import ZipFile

import cv2
import numpy as np
from scipy.ndimage import map_coordinates

from check_nasalseg import numbers, read_volume
from demo import Demo, HERE, load_assets
from replay import red_pixels, require


def verify(folder, archive_path, output=None):
    demo = Demo(*load_assets(folder))
    start = demo.state()
    axis = demo.rotation.as_matrix()[:, 2]
    panels = [demo.panel('P002 / Exterior start')]
    initial_camera = demo.camera_image()[0]
    samples = []
    with ZipFile(archive_path) as archive:
        ct, header = read_volume(archive, 'images/P002_img.nrrd')
        labels, _ = read_volume(archive, 'labels/P002_seg.nrrd')
    origin = numbers(header['space origin'])
    spacing = numbers(header['space directions']).reshape(3, 3).diagonal()

    def sample():
        ijk = ((demo.tip - origin) / spacing).reshape(3, 1)
        value = int(map_coordinates(labels, ijk, order=0, prefilter=False)[0])
        intensity = float(map_coordinates(ct.astype(np.float32), ijk, order=1, prefilter=False)[0])
        return {'label': value, 'ct_hu': intensity, **demo.state()}

    exterior = sample()
    require(exterior['label'] == 0 and exterior['ct_hu'] < -470, 'Expected unlabelled CT air at entry')
    for step in range(45):
        previous = demo.state()
        accepted, margin = demo.joystick(0, 1, 0.1)
        if not accepted:
            require(demo.state() == previous, 'Rejected insertion changed pose')
            break
        samples.append({'sweep_clearance_bound_mm': margin, **sample()})
    else:
        raise RuntimeError('Expected travel limit')
    require(samples[-1]['label'] == demo.config['segmentation_label'],
            'Final accepted pose is outside the labelled nasal passage')
    first_inside = next(i + 1 for i, state in enumerate(samples)
                        if state['label'] == demo.config['segmentation_label'])
    require(not np.array_equal(initial_camera, demo.camera_image()[0]), 'Camera did not update')
    require(all(s['tip_mm'] == s['window_center_mm'] for s in samples), 'Window and tip diverged')
    panels.append(demo.panel('P002 / Insertion blocked'))
    require(red_pixels(demo) == 0, 'Baseline should have no red')
    demo.mod = True
    count = red_pixels(demo)
    require(count > 0, 'Modified model should show red near the wall')
    panels.append(demo.panel('P002 / Synthetic difference'))
    for _ in samples:
        require(demo.joystick(0, -1, 0.1)[0], 'Withdrawal rejected')
    require(np.allclose(demo.tip, start['tip_mm']) and sample()['label'] == 0,
            'Did not return to exterior start')
    panels.append(demo.panel('P002 / Returned to exterior start'))
    # Aim repeatedly from a partially inserted pose until the wall rejects
    # the pivot. The tip alone is static; the shaft is what sweeps the wall.
    for _ in range(first_inside):
        require(demo.joystick(0, 1, 0.1)[0], 'Approach for pivot test rejected')
    for i in range(36):
        previous = demo.state()
        if not demo.joystick(1, 0, 0.1, aiming=True)[0]:
            require(demo.state() == previous, 'Rejected pivot changed pose')
            break
    else:
        raise RuntimeError('Expected a blocked shaft pivot')

    report = {
        'result': 'pass', 'start': exterior, 'heading_lps': axis.tolist(),
        'first_label_entry_mm': round(first_inside * 0.6, 2),
        'accepted_insertion_mm': round(step * 0.6, 2),
        'accepted_insertion_steps': step, 'accepted_yaw_steps_before_block': i,
        'red_pixels_at_final_pose': count, 'withdrawal_to_start': True, 'trace': samples,
    }
    if output:
        output.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(output / 'p002-preview.png'), np.vstack(panels)):
            raise OSError('Could not save P002 preview')
        (output / 'p002-validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in {'trace', 'start'}}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--assets', type=Path, default=HERE / 'assets-p002')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    verify(args.assets, args.archive, args.output)
