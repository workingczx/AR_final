"""Offline CT-derived virtual endoscope. Coordinates are source-world millimetres."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import open3d as o3d
from scipy.spatial.transform import Rotation, Slerp

HERE = Path(__file__).resolve().parent
LENGTH = 14.0
RADIUS = 0.8
CAMERA_OFFSET = 0.5
WINDOW = 12.0
STEP = 0.25
BUFFER = 0.05
WIDTH, HEIGHT = 360, 280


def scene(mesh):
    result = o3d.t.geometry.RaycastingScene(nthreads=2)
    result.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(mesh))
    return result


def tensor(a):
    return o3d.core.Tensor(np.ascontiguousarray(a, dtype=np.float32))


def load_assets(folder):
    config = json.loads((folder / 'manifest.json').read_text())
    meshes = [o3d.io.read_triangle_mesh(str(folder / name))
              for name in ('baseline.ply', 'modified.ply')]
    with np.load(folder / 'geometry.npz') as data:
        changed_faces = data['changed_faces']
    if config.get('separate_collision_meshes', False):
        collision_meshes = [o3d.io.read_triangle_mesh(str(folder / name)) for name in
                            ('collision-baseline.ply', 'collision-modified.ply')]
        if any(mesh.is_empty() for mesh in collision_meshes):
            raise ValueError('Missing or empty collision mesh')
        return config, meshes, changed_faces, collision_meshes
    return config, meshes, changed_faces


class Demo:
    def __init__(self, config, meshes, changed_faces, collision_meshes=None):
        self.config = config
        self.scenes = [scene(mesh) for mesh in meshes]
        self.collision_scenes = (None if collision_meshes is None else
                                 [scene(mesh) for mesh in collision_meshes])
        self.changed_faces = changed_faces
        self.tip = np.array(config['entry_pose']['tip_mm'])
        self.rotation = Rotation.from_matrix(config['entry_pose']['camera_to_world_rotation'])
        self.mod = False
        self.alpha = 0.22
        y, x = np.indices((HEIGHT, WIDTH))
        focal = WIDTH / (2 * np.tan(np.deg2rad(78 / 2)))
        self.camera_dirs = np.stack(((x - (WIDTH-1)/2) / focal,
                                     (y - (HEIGHT-1)/2) / focal,
                                     np.ones_like(x)), axis=-1)
        self.prepare_overview(meshes)
        accepted, _ = self.sweep(self.tip, self.rotation)
        if not accepted:
            raise ValueError('Entry pose fails clearance validation')

    def sweep(self, tip, rotation):
        """Certify the capsule along linear tip motion and shortest-arc SLERP."""
        rot_angle = (self.rotation.inv() * rotation).magnitude()
        path_bound = np.linalg.norm(tip - self.tip) + LENGTH * rot_angle
        time_steps = max(1, int(np.ceil(path_bound / STEP)))
        axis_steps = int(np.ceil(LENGTH / STEP))
        axis = np.linspace(0, LENGTH, axis_steps + 1)
        # At each time and shaft coordinate, a nearest sample is within
        # half a time interval's travel plus half an axial interval.
        allowance = path_bound / (2 * time_steps) + LENGTH / (2 * axis_steps)
        threshold = RADIUS + BUFFER + allowance
        interpolate = Slerp([0, 1], Rotation.from_quat(
            np.stack([self.rotation.as_quat(), rotation.as_quat()])))
        min_clearance = np.inf
        for start in range(0, time_steps + 1, 64):
            t = np.arange(start, min(start + 64, time_steps + 1)) / time_steps
            tips = self.tip + t[:, None] * (tip - self.tip)
            forward = interpolate(t).as_matrix()[:, :, 2]
            points = tips[:, None, :] - axis[None, :, None] * forward[:, None, :]
            for world in self.collision_scenes or self.scenes:
                signed = world.compute_signed_distance(tensor(points), nsamples=5).numpy()
                min_clearance = min(min_clearance, float(-signed.max()))
            if min_clearance < threshold:
                return False, min_clearance - allowance - RADIUS
        return True, min_clearance - allowance - RADIUS

    def joystick(self, x, y, dt, aiming=False):
        """One stick. Drive mode uses Y, aim mode uses X/Y for yaw/pitch."""
        if not np.isfinite([x, y, dt]).all():
            raise ValueError('Joystick values and dt must be finite')
        x, y = np.clip([x, y], -1, 1)
        dt = np.clip(dt, 0, 0.1)
        xy = np.array([x, y], dtype=float)
        xy *= max(0, 1 - 0.15 / max(np.linalg.norm(xy), 1e-12)) / 0.85
        x, y = xy / max(1, np.linalg.norm(xy))
        tip, rotation = self.tip, self.rotation
        if aiming:
            rotation = rotation * Rotation.from_euler('yx', [x * 24 * dt, y * 24 * dt],
                                                       degrees=True)
        else:
            tip = tip + rotation.as_matrix()[:, 2] * (y * 6 * dt)
        accepted, clearance = self.sweep(tip, rotation)
        if accepted:
            self.tip, self.rotation = tip, rotation
        return accepted, clearance

    def state(self):
        rotation = self.rotation.as_matrix()
        return {
            'tip_mm': self.tip.tolist(),
            'shaft_tail_mm': (self.tip - LENGTH * rotation[:, 2]).tolist(),
            'camera_mm': (self.tip + CAMERA_OFFSET * rotation[:, 2]).tolist(),
            'camera_to_world_rotation': rotation.tolist(),
            'window_center_mm': self.tip.tolist(),
            'modified': self.mod,
            'window_opacity': self.alpha,
        }

    @staticmethod
    def cast(world, origins, dirs):
        rays = np.concatenate([np.broadcast_to(origins, dirs.shape), dirs], axis=-1)
        hit = world.cast_rays(tensor(rays))
        depth = hit['t_hit'].numpy()
        valid = np.isfinite(depth)
        hit_points = origins + dirs * np.where(valid, depth, 0)[..., None]
        return valid, depth, hit_points, hit['primitive_ids'].numpy(), hit['primitive_normals'].numpy()

    def prepare_overview(self, meshes):
        lo, hi = meshes[0].get_min_bound(), meshes[0].get_max_bound()
        self.overview_center = (lo + hi) / 2
        self.px_per_mm = min((WIDTH - 32) / (hi[1] - lo[1]),
                             (HEIGHT - 40) / (hi[2] - lo[2]))
        y, x = np.indices((HEIGHT, WIDTH))
        origins = np.empty((HEIGHT, WIDTH, 3))
        origins[:, :, 0] = lo[0] - 12
        origins[:, :, 1] = self.overview_center[1] + (x - WIDTH/2) / self.px_per_mm
        origins[:, :, 2] = self.overview_center[2] - (y - HEIGHT/2) / self.px_per_mm
        dirs = np.zeros_like(origins)
        dirs[:, :, 0] = 1
        self.overview = [self.cast(world, origins, dirs) for world in self.scenes]
        # Locate the changed patch independently so nearer surfaces can partly
        # occlude it slightly in the semi-transparent overview.
        vertices = np.asarray(meshes[1].vertices)
        faces = np.asarray(meshes[1].triangles)[self.changed_faces]
        indices, compact = np.unique(faces, return_inverse=True)
        patch = o3d.geometry.TriangleMesh(
            o3d.utility.Vector3dVector(vertices[indices]),
            o3d.utility.Vector3iVector(compact.reshape(-1, 3)))
        self.patch = self.cast(scene(patch), origins, dirs)

    def window_weight(self, points):
        radius = np.linalg.norm(points - self.tip, axis=-1)
        return np.clip((WINDOW - radius) / 2, 0, 1)

    def overview_image(self, draw_scope=True):
        valid, surface_depth, points, _, normals = self.overview[self.mod]
        weight = self.window_weight(points)
        opacity = 0.90 * (1 - weight) + self.alpha * weight
        background = np.array([26, 19, 15])
        lighting = (0.32 + 0.68 * np.abs(normals[..., 0]))[..., None]
        color = lighting * [193, 172, 149]
        opacity *= valid
        image = background + opacity[..., None] * (color - background)
        if self.mod:
            patch_valid, depth, patch_points, _, _ = self.patch
            red = (patch_valid * self.window_weight(patch_points) *
                   np.where(depth <= surface_depth + 0.05, 0.95, 0.83))
            image += red[..., None] * (np.array([43, 48, 252]) - image)
        image = image.astype(np.uint8)
        state = self.state()

        def pixel(point):
            delta = np.asarray(point) - self.overview_center
            return tuple(np.rint([WIDTH/2 + self.px_per_mm * delta[1],
                                  HEIGHT/2 - self.px_per_mm * delta[2]]).astype(int))

        tip = pixel(state['tip_mm'])
        if draw_scope:
            cv2.circle(image, tip, round(WINDOW * self.px_per_mm), (149, 116, 54), 1, cv2.LINE_AA)
            cv2.line(image, pixel(state['shaft_tail_mm']), tip, (250, 205, 81), 3, cv2.LINE_AA)
            cv2.circle(image, tip, 5, (255, 238, 151), -1, cv2.LINE_AA)
        return image

    def camera_image(self):
        state = self.state()
        dirs = self.camera_dirs @ self.rotation.as_matrix().T
        valid, depth, _, ids, normals = self.cast(
            self.scenes[self.mod], np.asarray(state['camera_mm']), dirs)
        unit_dirs = dirs / np.linalg.norm(dirs, axis=-1, keepdims=True)
        diffuse = np.abs(np.sum(normals * unit_dirs, axis=-1))
        lighting = np.where(valid, 0.15 + 0.85 * diffuse / (1 + (depth/12)**2), 0)
        # Use neutral simulated materials. Difference color belongs to the external overlay.
        image = (lighting[..., None] * [154, 185, 230]).astype(np.uint8)
        return image, depth, ids

    def panel(self, status):
        canvas = np.full((HEIGHT + 78, WIDTH * 2 + 12, 3), (26, 19, 15), dtype=np.uint8)
        canvas[34:34+HEIGHT, :WIDTH] = self.overview_image()
        canvas[34:34+HEIGHT, WIDTH+12:] = self.camera_image()[0]
        for x, y, label in [(12, 24, 'CT anatomy / moving window'),
                            (WIDTH+24, 24, 'Virtual tip camera'),
                            (12, HEIGHT+53, status),
                            (12, HEIGHT+70, 'W/S drive   A/D/R/F aim   M model   +/- opacity   Q quit')]:
            cv2.putText(canvas, label, (x,y), cv2.FONT_HERSHEY_SIMPLEX, 0.46,
                        (226, 222, 215), 1, cv2.LINE_AA)
        return canvas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, default=HERE / 'assets-p002')
    args = parser.parse_args()
    demo = Demo(*load_assets(args.assets))
    keys = {'w': (0, 1, False), 's': (0, -1, False), 'a': (-1, 0, True),
            'd': (1, 0, True), 'r': (0, -1, True), 'f': (0, 1, True)}
    status = 'Entry pose'
    try:
        while True:
            model = 'modified' if demo.mod else 'baseline'
            cv2.imshow('Virtual endoscope', demo.panel(
                f'{model} | local opacity {demo.alpha:.2f} | {status}'))
            key = cv2.waitKeyEx(0)
            if key in (-1, 27, ord('q')):
                break
            key = chr(key & 255)
            if key in keys:
                x, y, aim = keys[key]
                accepted, _ = demo.joystick(x, y, 0.10, aiming=aim)
                status = 'Motion accepted' if accepted else 'Motion blocked'
            elif key == 'm':
                demo.mod = not demo.mod
            elif key in '+-=':
                demo.alpha = float(np.clip(demo.alpha + (0.06 if key != '-' else -0.06), 0, 0.9))
    finally:
        cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
