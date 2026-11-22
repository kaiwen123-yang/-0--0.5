"""Reproduce a fitted wrist candidate from the published observations, without robot I/O.

Run python3 reproduce.py PATH_TO_RESULT_DIR --fix-k3 or omit the flag for Brown5.
The original training/development/final split and exclusions come from the manifest.
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--fix-k3', action='store_true')
    args = parser.parse_args()
    rows = [json.loads(s) for s in (args.directory / 'observations.jsonl').read_text().splitlines()]
    train = [r for r in rows if r['split'] == 'train' and r['in_fit_or_score']]
    objects = np.zeros((88, 3), dtype=np.float32)
    objects[:, :2] = np.mgrid[:11, :8].T.reshape(-1, 2) * .020
    xy = [np.array(r['corners'], np.float32).reshape(-1, 1, 2) for r in train]
    flag = cv2.CALIB_FIX_K3 if args.fix_k3 else 0
    rms, K, D, *_ = cv2.calibrateCameraExtended([objects] * len(train), xy, (640, 480), None, None, flags=flag)
    G = [np.asarray(r['G']) for r in train]
    rotations, translations = [], []
    for corners in xy:
        success, r, t = cv2.solvePnP(objects, corners, K, D, flags=cv2.SOLVEPNP_ITERATIVE)
        if not success:
            raise ValueError('Training view failed PnP')
        rotations.append(cv2.Rodrigues(r)[0])
        translations.append(t)
    rotation, translation = cv2.calibrateHandEye([g[:3,:3] for g in G], [g[:3,3:4] for g in G],
                                                 rotations, translations, method=cv2.CALIB_HAND_EYE_PARK)
    transform = np.eye(4)
    transform[:3, :3], transform[:3, 3] = rotation, translation.ravel()
    print(json.dumps(dict(opencv=cv2.__version__, train_views=len(train), rms_px=rms, K=K.tolist(),
                          D=D.ravel().tolist(), T_flange_camera=transform.tolist()), indent=2))

if __name__ == '__main__':
    main()
