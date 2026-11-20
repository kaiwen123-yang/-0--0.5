"""Collect actual per-pose capture records. Join optional individual reviews by ID."""
import argparse
import csv
import json
from pathlib import Path

REVIEWS = ('corner_order', 'pose_verified', 'static_capture_verified', 'board_orientation_verified')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cal', type=Path, required=True)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--write-review', type=Path)
    group.add_argument('--review', type=Path)
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text())
    rows = []
    for path in sorted((args.cal / 'poses').glob('*/capture.json')):
        row = json.loads(path.read_text())
        if (row.get('kind') != 'calibration_capture' or row['pose_group'] != path.parent.name
                or row['sample_id'] != row['pose_group'] or row['split'] not in ('train', 'heldout')
                or not Path(row['image_path']).is_file()):
            raise ValueError(f'Invalid capture: {path}')
        for actual, required in [('camera_mount', spec['mount_mode']), ('camera_id', spec['camera_id']),
                                 ('camera_role', spec['camera_role']), ('camera_frame', spec['camera_frame']),
                                 ('image_size', spec['image_size']), ('base_frame', spec['robot']['base_frame']),
                                 ('gripper_frame', spec['robot']['gripper_frame']),
                                 ('pose_source', spec['robot']['pose_source'])]:
            if row[actual] != required:
                raise ValueError(f'{path}: inconsistent {actual}')
        rows.append(row)
    if not rows:
        parser.error('No actual pose captures')
    if args.review:
        with args.review.open(newline='') as source:
            reviews = list(csv.DictReader(source))
        by_id = {r['sample_id']: r for r in reviews}
        if len(by_id) != len(reviews) or set(by_id) != {r['sample_id'] for r in rows}:
            raise ValueError('Review IDs must match distinct capture IDs exactly')
        for row in rows:
            reviewed = by_id[row['sample_id']]
            row['corner_order'] = reviewed['corner_order']
            for field in REVIEWS[1:]:
                if reviewed[field] not in ('0', '1'):
                    raise ValueError(f'{row["sample_id"]}: enter 0 or 1 for {field}')
                row[field] = reviewed[field] == '1'
    if args.write_review:
        with args.write_review.open('x', newline='') as destination:
            writer = csv.writer(destination)
            writer.writerow(('sample_id', *REVIEWS))
            writer.writerows((r['sample_id'], r['corner_order'], 0, 0, 0) for r in rows)
    with args.output.open('x') as destination:
        for row in rows:
            destination.write(json.dumps(row, allow_nan=False) + '\n')


if __name__ == '__main__':
    main()
