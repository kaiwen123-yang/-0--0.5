"""Extract native-unit, single-wrist inspection data from one pinned official HDF5 episode.

A local --hdf5 path is optional. The network reader verifies byte ranges and retains
only the source blocks actually used. This is an inspection export, not a policy dataset.
"""
import argparse
from contextlib import ExitStack
import io
import json
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

import cv2
import h5py
import numpy as np
import requests


class RemoteHDF5(io.RawIOBase):
    block_size = 64 * 1024

    def __init__(self, source, cache):
        super().__init__()
        self.source = source
        self.size = source['source_size_bytes']
        self.cache = cache / source['revision'] / source['task'] / source['episode']
        self.cache.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.offset = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.offset

    def seek(self, offset, whence=0):
        position = (0, self.offset, self.size)[whence] + offset
        if position < 0:
            raise OSError('Negative HDF5 seek')
        self.offset = position
        return position

    def block(self, number):
        start = number * self.block_size
        end = min(start + self.block_size, self.size) - 1
        path = self.cache / str(number)
        if not path.exists():
            url = f"https://modelscope.cn/api/v1/datasets/{self.source['dataset']}/repo"
            params = dict(Revision=self.source['revision'], FilePath=self.source['path'],
                          range_start=start, range_end=end)
            headers = {'Range': f'bytes={start}-{end}', 'Accept-Encoding': 'identity'}
            with self.session.get(url, params=params, headers=headers, stream=True, timeout=(10, 30)) as response:
                expected = f'bytes {start}-{end}/{self.size}'
                if response.status_code != 206 or response.headers.get('Content-Range', '').lower() != expected:
                    raise OSError(f'Expected {expected}, HTTP {response.status_code}')
                data = response.raw.read(end - start + 2)
            if len(data) != end - start + 1:
                raise OSError('Incomplete remote HDF5 block')
            with NamedTemporaryFile(dir=self.cache, delete=False) as pending:
                pending.write(data)
            Path(pending.name).replace(path)
        data = path.read_bytes()
        if len(data) != end - start + 1:
            raise OSError(f'Incomplete cached block {path}')
        return data

    def readinto(self, buffer):
        length = min(len(buffer), max(0, self.size - self.offset))
        done = 0
        while done < length:
            number, offset = divmod(self.offset, self.block_size)
            block = self.block(number)
            count = min(len(block) - offset, length - done)
            buffer[done:done+count] = block[offset:offset+count]
            self.offset += count
            done += count
        return done

    def close(self):
        self.session.close()
        super().close()


def export(file, source, side, out):
    camera = f'camera_{side}'
    stamps = np.asarray(file['camera_observations/timestamp'])
    n = len(stamps)
    if n < 1 or np.any(np.diff(stamps) < 0):
        raise ValueError('Empty or non-monotonic camera time')
    data = {'camera_timestamp_source': stamps}
    for role in ('master', 'puppet'):
        for name, leaf, columns in (
            ('joints', f'arm_{side}_position_align', 6),
            ('gripper', f'end_effector_{side}_position_align', 1),
        ):
            node = file[f'{role}/{leaf}']
            values = np.asarray(node['data'])
            expected = (n, 6) if columns == 6 else (n,)
            if values.shape != expected or not np.isfinite(values).all():
                raise ValueError(f'Invalid source values {node.name}: {values.shape}')
            times = np.asarray(node['timestamp'])
            intervene = np.asarray(node['is_intervene'])
            if times.shape != (n,) or intervene.shape != (n,):
                raise ValueError(f'Metadata length differs in {node.name}')
            data[f'{role}_{name}'] = values
            data[f'{role}_{name}_timestamp_source'] = times
            data[f'{role}_{name}_is_intervene'] = intervene
    images = []
    for i in sorted({0, n//2, n-1}):
        original = np.asarray(file[f'camera_observations/color_images/{camera}'][i], dtype=np.uint8)
        im = cv2.imdecode(original, cv2.IMREAD_COLOR)
        if im is None or original[:2].tobytes() != bytes.fromhex('ffd8'):
            raise ValueError(f'Invalid source JPEG at row {i}')
        name = f'wrist_{side}_{i:04}.jpg'
        (out/name).write_bytes(original.tobytes())
        images.append(dict(index=i, image=name, width=im.shape[1], height=im.shape[0]))
    np.savez_compressed(out/'source_numeric.npz', **data)
    manifest = dict(source=source, native_side=side, source_camera=camera, source_rows=n,
                    source_images=images, proposed_model_slot='left_wrist_0_rgb',
                    training_eligible=False, numeric_units='source native',
                    pending=['joint axes and reference mapping', 'gripper scale and zero',
                             'subsecond policy alignment', 'leader-to-issued command mapping',
                             'task independence of omitted arm and base'])
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')


def main():
    sources = json.loads(Path(__file__).with_name('sources.json').read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sample', choices=sources)
    parser.add_argument('--side', required=True, choices=('left','right'))
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--hdf5', type=Path)
    parser.add_argument('--cache', type=Path, default=Path('range_cache'))
    args = parser.parse_args()
    source = sources[args.sample]
    if args.out.exists():
        raise FileExistsError(args.out)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        if args.hdf5:
            if args.hdf5.stat().st_size != source['source_size_bytes']:
                raise ValueError('File size differs from the selected episode')
            handle = args.hdf5
        else:
            handle = stack.enter_context(RemoteHDF5(source, args.cache))
        h5 = stack.enter_context(h5py.File(handle, 'r'))
        staging = Path(stack.enter_context(TemporaryDirectory(dir=args.out.parent)))
        output = staging/'preview'
        output.mkdir()
        export(h5, source, args.side, output)
        output.rename(args.out)
    print(args.out/'manifest.json')


if __name__ == '__main__':
    main()
