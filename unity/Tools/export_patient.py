"""Pack the P002 Python demo assets and prebuild collision acceleration trees."""
import argparse
import json
from pathlib import Path
import struct

import numpy as np
import open3d as o3d


def export(source, output):
    manifest = json.loads((source / 'manifest.json').read_text())
    entry = manifest['entry_pose']
    basis = np.array(entry['camera_to_world_rotation']) @ np.diag([1, -1, 1])
    origin = np.array(entry['tip_mm'])

    def read(name):
        mesh = o3d.io.read_triangle_mesh(str(source / f'{name}.ply'))
        vertices = (np.asarray(mesh.vertices) - origin) @ basis * .001
        faces = np.asarray(mesh.triangles)[:, [0, 2, 1]]
        return vertices, faces

    with np.load(source / 'geometry.npz') as data:
        changed = data['changed_faces']

    with output.open('wb') as stream:
        def integer(*values):
            stream.write(struct.pack('<' + 'i' * len(values), *values))

        def floats(values):
            stream.write(np.asarray(values, dtype='<f4').tobytes())

        def mesh(vertices, faces):
            integer(len(vertices), len(faces) * 3)
            floats(vertices)
            stream.write(faces.astype('<i4').tobytes())

        stream.write(b'P002')
        mesh(*read('baseline'))
        vertices, faces = read('modified')
        mesh(vertices, faces)
        used, patch = np.unique(faces[changed], return_inverse=True)
        mesh(vertices[used], patch.reshape(-1, 3))
        for name in ('collision-baseline', 'collision-modified'):
            vertices, faces = read(name)
            triangles = vertices[faces]
            lo, hi = triangles.min(1), triangles.max(1)
            mid = (lo + hi) / 2
            nodes, order = [], []

            def build(ids):
                lower, upper = lo[ids].min(0), hi[ids].max(0)
                node = len(nodes)
                nodes.append(None)
                if len(ids) <= 8:
                    start = len(order)
                    order.extend(ids)
                    children = (-1, -1, start, len(ids))
                else:
                    axis = np.argmax(np.ptp(mid[ids], axis=0))
                    ids = ids[np.argsort(mid[ids, axis], kind='stable')]
                    split = len(ids) // 2
                    children = (build(ids[:split]), build(ids[split:]), 0, 0)
                nodes[node] = (lower, upper, children)
                return node

            build(np.arange(len(triangles)))
            integer(len(nodes), len(triangles))
            for lower, upper, children in nodes:
                floats(lower - 1e-7)
                floats(upper + 1e-7)
                integer(*children)
            floats(triangles[order])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    export(args.source, args.output)
