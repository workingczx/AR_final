"""Build an experimental P002 entry scene from the public NasalSeg release."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from scipy.ndimage import label, map_coordinates
from skimage.measure import marching_cubes

from check_nasalseg import numbers, read_volume
from demo import CAMERA_OFFSET, HERE, LENGTH, RADIUS, WINDOW, scene, tensor
from prepare import mesh_of, write_mesh


def prepare(archive_path, output):
    with ZipFile(archive_path) as archive:
        ct, ct_header = read_volume(archive, 'images/P002_img.nrrd')
        seg, seg_header = read_volume(archive, 'labels/P002_seg.nrrd')
    for key in ('space directions', 'space origin'):
        if not np.allclose(numbers(ct_header[key]), numbers(seg_header[key]), rtol=0, atol=1e-5):
            raise ValueError(f'P002 CT and segmentation disagree on {key}')
    if ct.shape != seg.shape:
        raise ValueError('P002 CT and segmentation shapes differ')

    directions = numbers(ct_header['space directions']).reshape(3, 3)
    spacing = np.diag(directions)
    if not np.array_equal(directions, np.diag(spacing)) or np.any(spacing <= 0):
        raise ValueError('Unexpected P002 orientation')
    origin = numbers(ct_header['space origin'])
    inward = np.array([0.6, 1., 0.85])
    inward /= np.linalg.norm(inward)
    inside_reference = np.array([61, 30, 9]) * spacing
    entry = inside_reference - 8 * inward
    right = np.cross(inward, [0, 0, 1])
    right /= np.linalg.norm(right)
    rotation = np.column_stack((right, np.cross(inward, right), inward))

    # The CT supplies all passage and exterior air. The segmentation and
    # bounded exterior region restrict the demo to the selected passage.
    grid = np.moveaxis(np.indices(ct.shape), 0, -1) * spacing - inside_reference
    longitudinal = grid @ inward
    radius_squared = np.sum(grid**2, axis=-1) - longitudinal**2
    entry_roi = (longitudinal >= -25) & (longitudinal <= 10) & (radius_squared <= 6.5**2)
    airway = ct < -470
    permitted = airway & ((seg == 3) | entry_roi)
    components, _ = label(permitted)
    component = components[61, 30, 9]
    if component == 0:
        raise ValueError('The reference point is outside permitted air')
    mask = components == component
    padded = np.pad(mask, 1)
    local_vertices, faces, _, _ = marching_cubes(padded.astype(np.float32), level=0.5,
                                                 allow_degenerate=False)
    voxel_vertices = local_vertices - 1
    vertices = voxel_vertices * spacing + origin
    baseline = mesh_of(vertices, faces)
    if not baseline.is_edge_manifold(False) or not baseline.is_vertex_manifold():
        raise ValueError('Permitted air must have a closed manifold boundary')
    if not baseline.orient_triangles():
        raise ValueError('Permitted air mesh must be orientable')
    faces = np.asarray(baseline.triangles).copy()

    # Air/tissue midpoint surfaces are the visible geometry. Surfaces produced
    # by cropping the simulated volume are used only for collision.
    centres = voxel_vertices[faces].mean(axis=1)
    mean_ct = map_coordinates(ct.astype(float), centres.T, order=1, prefilter=False,
                              mode='constant', cval=-1024)
    visible = mean_ct > -790
    query = origin + inside_reference + 5 * inward
    points = scene(baseline).compute_closest_points(tensor(query[None]))['points'].numpy()
    center = points[0].astype(float)
    direction = center - query
    direction /= np.linalg.norm(direction)
    weight = np.maximum(0, 1 - (np.linalg.norm(vertices - center, axis=1) / 3.8)**2)**2
    modified_vertices = vertices + 0.6 * weight[:, None] * direction
    changed_faces = np.any(weight[faces[visible]] > 0, axis=1)
    if not changed_faces.any():
        raise ValueError('Difference does not intersect visible surfaces')

    output.mkdir(parents=True, exist_ok=True)
    write_mesh(output / 'baseline.ply', mesh_of(vertices, faces[visible]))
    write_mesh(output / 'modified.ply', mesh_of(modified_vertices, faces[visible]))
    write_mesh(output / 'collision-baseline.ply', baseline)
    write_mesh(output / 'collision-modified.ply', mesh_of(modified_vertices, faces))
    np.savez_compressed(output / 'geometry.npz', changed_faces=changed_faces)
    digest = hashlib.md5()
    with archive_path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    manifest = {
        'dataset': 'NasalSeg v2 / P002',
        'source': 'https://zenodo.org/records/13893419',
        'source_archive_md5': digest.hexdigest(),
        'source_space': 'DICOM LPS in millimetres',
        'ct_spacing_mm': spacing.tolist(),
        'air_threshold_hu': -470,
        'segmentation_label': 3,
        'separate_collision_meshes': True,
        'entry_pose': {'tip_mm': (origin + entry).tolist(),
                       'camera_to_world_rotation': rotation.tolist()},
        'entry_reference_mm': (origin + inside_reference).tolist(),
        'entry_roi': {'range_from_reference_mm': [-25, 10], 'radius_mm': 6.5},
        'shaft': {'tip_to_tail_mm': LENGTH, 'capsule_radius_mm': RADIUS},
        'camera_offset_mm': CAMERA_OFFSET,
        'window_radius_mm': WINDOW,
        'difference': {'center_mm': center.tolist(), 'peak_displacement_mm': 0.6,
                       'support_radius_mm': 3.8, 'changed_face_count': int(changed_faces.sum())},
    }
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--output', type=Path, default=HERE / 'assets-p002')
    args = parser.parse_args()
    prepare(args.archive, args.output)
