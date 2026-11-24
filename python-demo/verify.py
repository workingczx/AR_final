"""Run the offline acceptance checks and optionally save a visual walkthrough."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import open3d as o3d

from demo import CAMERA_OFFSET, HERE, LENGTH, Demo, load_assets, scene


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def verify(folder, output):
    config, meshes, changed_faces = load_assets(folder)
    demo = Demo(config, meshes, changed_faces)
    first = demo.state()
    entry_panel = demo.panel('1 / Entry pose')
    before, first_depth, _ = demo.camera_image()
    require(np.isfinite(first_depth).sum() > first_depth.size // 2, 'Entry view has too few hits')
    center = np.array(config['difference']['center_mm'])
    require(demo.window_weight(center) == 0, 'Change should start outside the window')
    demo.mod = True
    entry_modified = demo.overview_image(False).astype(float)
    require(not np.any(entry_modified[..., 2] > entry_modified[..., 0] + 50),
            'Change visibly leaks outside the local window')
    demo.mod = False

    advanced = 0
    for _ in range(34):
        accepted, clearance = demo.joystick(0, 1, 0.1)
        require(accepted and clearance >= 0.05 - 1e-9, 'Expected safe insertion was rejected')
        advanced += 1
    near = demo.state()
    near_panel = demo.panel('2 / Inserted 20.4 mm')
    _, near_depth, _ = demo.camera_image()
    require(not np.array_equal(first_depth, near_depth) and
            not np.array_equal(before, demo.camera_image()[0]), 'Internal camera did not update')
    rot = np.array(near['camera_to_world_rotation'])
    tip = np.array(near['tip_mm'])
    require(np.allclose(near['camera_mm'], tip + CAMERA_OFFSET * rot[:, 2]) and
            np.allclose(near['shaft_tail_mm'], tip - LENGTH * rot[:, 2]) and
            near['window_center_mm'] == near['tip_mm'], 'Outputs use inconsistent transforms')
    require(demo.window_weight(center) > 0.9, 'Change should enter window')
    baseline_image = demo.overview_image(False)
    demo.mod = True
    modified_image = demo.overview_image(False)
    red_pixels = int(np.count_nonzero(modified_image[..., 2].astype(float)
                         > np.maximum(modified_image[..., 0], modified_image[..., 1]) + 50.0))
    require(red_pixels > 0 and not np.array_equal(baseline_image, modified_image),
            'Modified state should show red')
    modified_panel = demo.panel('3 / Synthetic difference')
    demo.alpha = 0.6
    require(not np.array_equal(modified_image, demo.overview_image(False)), 'Opacity did not update')
    demo.alpha = 0.22

    accepted_aim, _ = demo.joystick(1, 0, 0.1, aiming=True)
    aim = demo.state()
    require(accepted_aim and aim['tip_mm'] == near['tip_mm'] and
            aim['camera_to_world_rotation'] != near['camera_to_world_rotation'] and
            aim['camera_mm'] != near['camera_mm'], 'Aim did not update camera from accepted pose')
    accepted, _ = demo.joystick(0, -1, 0.1)
    require(accepted and np.linalg.norm(np.array(demo.tip) - first['tip_mm']) < 20.4,
            'Withdrawal did not move toward entry')
    for _ in range(30):
        previous = demo.state()
        accepted, _ = demo.joystick(0, 1, 0.1)
        if not accepted:
            require(demo.state() == previous, 'Rejected input changed a derived transform')
            break
    else:
        raise RuntimeError('Expected collision was not rejected')
    blocked_panel = demo.panel('4 / Swept collision blocked motion')

    # Two enclosed boxes give safe endpoints with an unsafe gap between them.
    toy = o3d.geometry.TriangleMesh.create_box(10, 10, 24).translate((-5, -5, -20))
    toy += o3d.geometry.TriangleMesh.create_box(10, 10, 24).translate((15, -5, -20))
    check = Demo(config, meshes, changed_faces)
    from scipy.spatial.transform import Rotation
    check.scenes = [scene(toy)]
    check.tip, check.rotation = np.zeros(3), Rotation.identity()
    goal = np.array([20., 0., 0.])
    require(check.sweep(check.tip, check.rotation)[0], 'Toy start should be safe')
    require(not check.sweep(goal, check.rotation)[0], 'Sweep tunneled across the gap')
    check.tip = goal
    require(check.sweep(goal, check.rotation)[0], 'Toy goal should be safe')
    # A 90 degree turn keeps the tip safe at the origin but drives the tail through a wall.
    check.tip = np.zeros(3)
    require(not check.sweep(check.tip, Rotation.from_euler('y', 90, degrees=True))[0],
            'Rotation ignored shaft clearance')

    with np.load(folder / 'geometry.npz') as data:
        distance = np.linalg.norm(data['modified_vertices'] - data['baseline_vertices'], axis=1)
        require(np.array_equal(np.any(distance[data['triangles']] > 0, axis=1), changed_faces)
                and np.isclose(distance.max(), config['difference']['actual_max_vertex_displacement_mm']),
                'Difference geometry and metadata disagree')
    transform = np.array(config['source_to_unity_metres_row_major'])
    require(np.allclose(transform @ np.r_[first['tip_mm'], 1], [0, 0, 0, 1]) and
            np.isclose(np.linalg.det(transform[:3, :3]), -1e-9, atol=1e-13),
            'Metre conversion mismatch')
    report = {
        'result': 'pass',
        'accepted_insertion_steps': advanced,
        'validated_insertion_mm': float(np.linalg.norm(tip - first['tip_mm'])),
        'red_pixels_when_within_window': red_pixels,
        'changed_faces': int(changed_faces.sum()),
        'checks': ['entry clearance', 'insertion', 'withdrawal', 'aiming', 'wall rejection with unchanged pose',
                   'swept path rejection with safe endpoints', 'shaft rotation rejection', 'camera transform',
                   'updated tip image', 'window center', 'opacity control', 'local synthetic difference',
                   'difference geometry correspondence', 'source-to-Unity scale and origin'],
    }
    if output:
        output.mkdir(parents=True, exist_ok=True)
        image = np.vstack([entry_panel, near_panel, modified_panel, blocked_panel])
        if not cv2.imwrite(str(output / 'demo-preview.png'), image):
            raise OSError('Could not write demo preview')
        (output / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, default=HERE / 'assets')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    verify(args.assets, args.output)
