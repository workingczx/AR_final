"""Replay and verify the p04_left course demo using its existing motion code."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from demo import Demo, HERE, load_assets


def red_pixels(demo):
    image = demo.overview_image(draw_scope=False).astype(float)
    return int(np.count_nonzero(image[..., 2] > np.maximum(image[..., 0], image[..., 1]) + 50))


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def verify_routes(assets):
    config, meshes, changed = assets
    routes = {}
    for label, x, y in [('straight', 0, 0), ('left', -1, 0), ('right', 1, 0),
                        ('up', 0, -1), ('down', 0, 1)]:
        scope = Demo(config, meshes, changed)
        origin = scope.tip.copy()
        for _ in range(15):
            require(scope.joystick(0, 1, 0.1)[0], f'{label}: approach rejected')
        if x or y:
            require(scope.joystick(x, y, 0.1, aiming=True)[0], f'{label}: aiming rejected')
        for step in range(45):
            previous = scope.state()
            accepted, _ = scope.joystick(0, 1, 0.1)
            if not accepted:
                require(scope.state() == previous, f'{label}: rejection changed state')
                break
        else:
            raise RuntimeError(f'{label}: expected a blocked motion')
        require(step > 0, f'{label}: no motion accepted after approach')
        displacement = float(np.linalg.norm(scope.tip - origin))
        require(scope.joystick(0, -1, 0.1)[0], f'{label}: withdrawal rejected')
        routes[label] = {'accepted_forward_steps_after_approach': step,
                         'displacement_before_block_mm': round(displacement, 3),
                         'blocked_state_unchanged': True, 'withdrawal_accepted': True}
    return routes


def playback(demo, show=None):
    trace = []

    def record(label, request=None):
        prior = demo.state()
        accepted, clearance = demo.joystick(*request[:3], aiming=request[3]) if request else (None, None)
        state = demo.state()
        if accepted is False:
            require(state == prior, 'A rejected request changed the output pose')
        require(state['tip_mm'] == state['window_center_mm'], 'Window and tip diverged')
        request_fields = dict(zip(('x', 'y', 'dt_s', 'aiming'), request)) if request else None
        trace.append({'event': label, 'request': request_fields, 'accepted': accepted,
                      'sweep_clearance_bound_mm': clearance, **state})
        if show:
            show(label, demo)
        return accepted

    record('Entry')
    demo.mod = True
    record('Modified model at entry')
    outside = red_pixels(demo)
    require(outside == 0, 'Red difference visible at entry')
    for _ in range(34):
        require(record('Insert', (0, 1, 0.1, False)), 'Insertion rejected on the demo route')
    inside = red_pixels(demo)
    require(inside > 0, 'Red difference missing inside window')
    demo.mod = False
    record('Baseline at the same pose')
    baseline_pixels = red_pixels(demo)
    require(baseline_pixels == 0, 'Difference displayed in baseline mode')
    demo.mod = True
    record('Modified model at the same pose')
    require(record('Aim right', (1, 0, 0.1, True)), 'Aim rejected')
    for _ in range(20):
        if not record('Advance toward wall', (0, 1, 0.1, False)):
            break
    else:
        raise RuntimeError('Expected wall rejection')
    blocked_tip = demo.tip.copy()
    # Retrace the accepted straight path at the same orientation before undoing the turn.
    advances = sum(r['event'] == 'Advance toward wall' and r['accepted'] for r in trace)
    for _ in range(advances):
        require(record('Withdraw', (0, -1, 0.1, False)), 'Withdrawal rejected')
    require(np.linalg.norm(blocked_tip - demo.tip) > 0, 'Withdrawal did not move the tip')
    require(record('Restore entry heading', (-1, 0, 0.1, True)), 'Return turn rejected')
    for _ in range(34):
        require(record('Withdraw toward entry', (0, -1, 0.1, False)), 'Return path rejected')
    after = red_pixels(demo)
    require(after == 0 and np.allclose(demo.tip, trace[0]['tip_mm']),
            'Return to entry or red-region exit failed')
    return {'red_pixel_counts': {'entry': outside, 'inside': inside,
                                 'baseline_at_same_pose': baseline_pixels, 'after_withdrawal': after},
            'trace': trace}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, default=HERE / 'assets')
    parser.add_argument('--output', type=Path, help='Write a JSON replay trace and route report')
    parser.add_argument('--play', action='store_true', help='Show an animated replay on the desktop')
    args = parser.parse_args()
    assets = load_assets(args.assets)

    def show(label, demo):
        cv2.imshow('Virtual endoscope replay', demo.panel(label))
        key = cv2.waitKeyEx(450 if label in {'Entry', 'Modified model at the same pose',
                                             'Baseline at the same pose', 'Aim right'} else 72)
        if key in (27, ord('q')):
            raise KeyboardInterrupt

    try:
        report = playback(Demo(*assets), show if args.play else None)
    except KeyboardInterrupt:
        print('Replay stopped.')
        return
    finally:
        if args.play:
            cv2.destroyAllWindows()
    report['routes'] = verify_routes(assets)
    report['result'] = 'pass'
    if args.output:
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    summary = {key: value for key, value in report.items() if key != 'trace'}
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
