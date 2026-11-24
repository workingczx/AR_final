"""Build offline assets from the existing p04_left CT-derived segmentation."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import open3d as o3d
from scipy.spatial.transform import Rotation

from demo import BUFFER, CAMERA_OFFSET, LENGTH, RADIUS, STEP, WINDOW, scene, tensor


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def mesh_of(vertices, faces):
    mesh = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(vertices),
                                    o3d.utility.Vector3iVector(faces))
    mesh.compute_vertex_normals()
    return mesh


def write_mesh(path, mesh):
    if not o3d.io.write_triangle_mesh(str(path), mesh, write_triangle_uvs=False):
        raise OSError(f'Failed to write {path}')


def prepare(source, output):
    preop = source / 'input' / 'preop'
    stl, trajectory = preop / 'Sinus_Left.stl', preop / 'trajectories.npy'
    baseline = o3d.io.read_triangle_mesh(str(stl))
    baseline.remove_duplicated_vertices()
    baseline.remove_degenerate_triangles()
    baseline.remove_duplicated_triangles()
    if baseline.is_empty() or not baseline.is_edge_manifold(False) or not baseline.is_vertex_manifold():
        raise ValueError('Expected a nonempty closed manifold segmentation surface')
    if not baseline.orient_triangles():
        raise ValueError('Expected an orientable segmentation surface')
    baseline.compute_vertex_normals()
    v, f = np.asarray(baseline.vertices), np.asarray(baseline.triangles)
    pose = np.load(trajectory, allow_pickle=False)[0]
    rotation = Rotation.from_matrix(pose[:3, :3]).as_matrix()
    forward = rotation[:, 2]
    entry = pose[:3, 3] - 3 * forward
    query = pose[:3, 3] + 22 * forward
    world = scene(baseline)
    clearance = -world.compute_signed_distance(tensor(pose[None, :3, 3]), nsamples=5).numpy()[0]
    if clearance <= 0:
        raise ValueError('First camera pose is outside the segmented airway')
    center = world.compute_closest_points(tensor(query[None]))['points'].numpy()[0].astype(float)
    direction = (center - query) / np.linalg.norm(center - query)
    support_radius, peak = 4.2, 1.0
    weight = np.maximum(0, 1 - (np.linalg.norm(v - center, axis=1) / support_radius)**2)**2
    modified_v = v + peak * weight[:, None] * direction
    changed_faces = np.any(weight[f] > 0, axis=1)
    if not changed_faces.any():
        raise ValueError('Synthetic difference has no affected triangles')
    patch_indices, patch_faces = np.unique(f[changed_faces], return_inverse=True)
    modified = mesh_of(modified_v, f)
    patch = mesh_of(modified_v[patch_indices], patch_faces.reshape(-1, 3))
    patch.paint_uniform_color([0.99, 0.04, 0.03])

    output.mkdir(parents=True, exist_ok=True)
    for name, mesh in [('baseline', baseline), ('modified', modified), ('difference_patch', patch)]:
        write_mesh(output / f'{name}.ply', mesh)
        with (output / f'{name}.obj').open('w') as handle:
            # Keep source millimetres and winding. Apply the manifest transform in Unity.
            if name == 'difference_patch':
                handle.write('mtllib difference_patch.mtl\nusemtl SyntheticDifference\n')
            np.savetxt(handle, np.asarray(mesh.vertices), fmt='v %.8f %.8f %.8f')
            np.savetxt(handle, np.asarray(mesh.triangles) + 1, fmt='f %d %d %d')
    (output / 'difference_patch.mtl').write_text('newmtl SyntheticDifference\nKd 0.99 0.04 0.03\n')
    np.savez_compressed(output / 'geometry.npz', baseline_vertices=v, modified_vertices=modified_v,
                        triangles=f, changed_faces=changed_faces)

    source_to_unity = np.eye(4)
    source_to_unity[:3, :3] = np.diag([1, -1, 1]) @ rotation.T * 0.001
    source_to_unity[:3, 3] = -source_to_unity[:3, :3] @ entry
    manifest = {
        'dataset': 'p04_left / An Endoscopic Chisel sample',
        'source_files_sha256': {p.name: sha256(p) for p in (stl, trajectory)},
        'source_space': 'Original dataset world coordinates in mm. Camera axes right, down, forward.',
        'entry_pose': {'tip_mm': entry.tolist(), 'camera_to_world_rotation': rotation.tolist(),
                       'method': '3 mm back from preop frame 0; intra-nasal start, not external landmark'},
        'shaft': {'tip_to_tail_mm': LENGTH, 'capsule_radius_mm': RADIUS},
        'camera': {'offset_tip_local_mm': [0, 0, CAMERA_OFFSET],
                   'forward_tip_local': [0, 0, 1], 'horizontal_fov_deg': 78},
        'window': {'radius_mm': WINDOW, 'edge_blend_mm': 2,
                   'outer_opacity': 0.9, 'default_inner_opacity': 0.22},
        'collision': {'permitted_space': 'Intersection of enclosed baseline and modified airway volumes',
                      'sample_spacing_bound_mm': STEP, 'additional_margin_mm': BUFFER},
        'difference': {'type': 'synthetic wall displacement', 'center_mm': center.tolist(),
                       'direction_world_unit': direction.tolist(),
                       'support_radius_mm': support_radius, 'analytic_peak_mm': peak,
                       'actual_max_vertex_displacement_mm': float(np.max(weight) * peak),
                       'changed_vertex_count': int(np.count_nonzero(weight)),
                       'changed_face_count': int(changed_faces.sum()),
                       'formula': 'v_mod = v + direction * peak * max(0, 1 - (norm(v-center)/radius)^2)^2'},
        'mesh_counts': {'vertices': len(v), 'triangles': len(f)},
        'source_to_unity_metres_row_major': source_to_unity.tolist(),
        'unity_conversion': 'Multiply column points by the 4x4 matrix. Reflecting transform: reverse triangle winding once when baking. Convert camera basis with diag(1,-1,1) on the right of the rotation.',
    }
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Existing data/p04_left directory')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent / 'assets')
    args = parser.parse_args()
    prepare(args.source, args.output)
