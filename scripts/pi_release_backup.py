#!/usr/bin/env python3
"""Project-scoped, verified GitHub backup/restore. No source deletion before full verification."""
import argparse
import concurrent.futures as futures
import datetime
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import time

import zstandard as zstd

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
REPO = 'kaiwen123-yang/-0--0.5'
TAG = 'pi-complete-backup-20261101'
STAGE = ROOT / 'runtime' / TAG
PUB = ROOT / 'publication' / TAG
PART_LIMIT = 512 * 1024**2
ALLOWED = [ROOT/'outputs', ROOT/'results', ROOT/'archive-upload', ROOT/'docs/papers',
           WORKSPACE/'assets/openpi-assets/checkpoints/pi0_base',
           WORKSPACE/'assets/openpi-assets/checkpoints/pi05_base']


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    tmp.replace(path)


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(8 << 20), b''):
            h.update(block)
    return h.hexdigest()


def record(event, **values):
    row = {'at_utc': now(), 'event': event, **values}
    STAGE.mkdir(parents=True, exist_ok=True)
    with (STAGE/'events.jsonl').open('a') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
    print(json.dumps(row, ensure_ascii=False), flush=True)


def command(args, timeout=120):
    p = subprocess.run(list(map(str, args)), text=True, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, timeout=timeout)
    if p.returncode:
        raise RuntimeError(f'Command exit {p.returncode}: {args[:4]}: {p.stdout[-3000:]}')
    return p.stdout


def release(tag):
    # A draft may not resolve through /releases/tags. Match its exact tag in the authenticated list.
    page = 1
    while True:
        rows = json.loads(command(['gh', 'api', f'repos/{REPO}/releases?per_page=100&page={page}']))
        for item in rows:
            if item['tag_name'] == tag:
                return item
        if len(rows) < 100:
            return None
        page += 1


def assets(tag):
    r = release(tag)
    if r is None:
        raise RuntimeError(f'Release missing: {tag}')
    # The release response can truncate large asset sets. Always paginate the assets endpoint.
    result = {}
    page = 1
    while True:
        rows = json.loads(command(['gh', 'api', f'repos/{REPO}/releases/{r["id"]}/assets?per_page=100&page={page}']))
        for item in rows:
            result[item['name']] = item
        if len(rows) < 100:
            return result
        page += 1


def receipt(asset, expected):
    if (asset['state'] != 'uploaded' or asset['size'] != expected['bytes'] or
            asset.get('digest') != 'sha256:' + expected['sha256']):
        raise ValueError(f'Remote size/SHA256 mismatch: {asset["name"]}')
    return {k: asset[k] for k in ('id','name','size','digest','state','browser_download_url')}


def upload_file(path, expected=None):
    expected = expected or {'name': path.name, 'bytes': path.stat().st_size, 'sha256': sha(path)}
    for attempt in range(1, 4):
        remote = assets(TAG).get(path.name)
        if remote is not None:
            if remote['state'] == 'uploaded':
                return receipt(remote, expected)
            # Only this task's incomplete, uncommitted upload slot is removed for retry.
            command(['gh','api','--method','DELETE',f'repos/{REPO}/releases/assets/{remote["id"]}'])
            record('removed_incomplete_upload_slot', name=path.name, asset_id=remote['id'])
        t0 = time.monotonic()
        try:
            command(['gh','release','upload',TAG,'--repo',REPO,path], timeout=900)
            item = receipt(assets(TAG)[path.name], expected)
            record('uploaded', name=path.name, bytes=expected['bytes'], attempt=attempt,
                   seconds=time.monotonic()-t0)
            return item
        except Exception as exc:
            record('upload_attempt_failed', name=path.name, attempt=attempt, error=str(exc))
            if attempt == 3:
                raise
            time.sleep(2 * attempt)


def download_file(tag, item, directory):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory/item['name']
    if path.exists():
        if path.stat().st_size == item['bytes'] and sha(path) == item['sha256']:
            return path
        # Discard only our task-owned incomplete download, never a source file.
        path.unlink()
    for attempt in range(1, 4):
        t0 = time.monotonic()
        try:
            command(['gh','release','download',tag,'--repo',REPO,'--pattern',item['name'],
                     '--dir',directory], timeout=900)
            if path.stat().st_size != item['bytes'] or sha(path) != item['sha256']:
                raise ValueError(f'Downloaded size/SHA256 mismatch: {path.name}')
            record('downloaded_verified', tag=tag, name=path.name, bytes=item['bytes'],
                   attempt=attempt, seconds=time.monotonic()-t0)
            return path
        except Exception as exc:
            record('download_attempt_failed', tag=tag, name=item['name'], attempt=attempt, error=str(exc))
            if path.exists():
                path.unlink()
            if attempt == 3:
                raise
            time.sleep(2 * attempt)


class SplitWriter(io.RawIOBase):
    def __init__(self, directory, stem):
        self.directory, self.stem = directory, stem
        self.stream, self.size, self.total, self.h = None, 0, 0, None
        self.parts = []

    def writable(self): return True
    def tell(self): return self.total

    def finish_part(self):
        if self.stream is not None:
            self.stream.flush(); os.fsync(self.stream.fileno()); self.stream.close()
            self.parts.append({'name': self.path.name, 'bytes': self.size, 'sha256': self.h.hexdigest()})
            self.stream = None

    def write(self, data):
        view = memoryview(data)
        original = len(view)
        while view:
            if self.stream is None:
                self.path = self.directory/f'{self.stem}.part-{len(self.parts):03d}'
                self.stream = self.path.open('xb'); self.h = hashlib.sha256(); self.size = 0
            count = min(len(view), PART_LIMIT-self.size)
            self.stream.write(view[:count]); self.h.update(view[:count])
            self.size += count; self.total += count; view = view[count:]
            if self.size == PART_LIMIT: self.finish_part()
        return original

    def flush(self):
        if self.stream is not None: self.stream.flush()


class JoinedReader(io.RawIOBase):
    def __init__(self, paths):
        self.paths, self.index, self.stream = list(paths), 0, None

    def readable(self): return True

    def read(self, size=-1):
        if size < 0:
            raise ValueError('Unbounded archive read is disabled')
        pieces, remaining = [], size
        while remaining:
            if self.stream is None:
                if self.index >= len(self.paths): break
                self.stream = self.paths[self.index].open('rb'); self.index += 1
            block = self.stream.read(remaining)
            if not block:
                self.stream.close(); self.stream = None; continue
            pieces.append(block); remaining -= len(block)
        return b''.join(pieces)

    def readinto(self, buf):
        block = self.read(len(buf)); buf[:len(block)] = block; return len(block)

    def close(self):
        if self.stream is not None: self.stream.close()
        super().close()


def safe_destination(root, relative):
    p = PurePosixPath(relative)
    if p.is_absolute() or '..' in p.parts or not p.parts:
        raise ValueError(f'Unsafe archive path: {relative}')
    target = root.joinpath(*p.parts)
    current = root
    for part in p.parts[:-1]:
        current = current/part
        if current.is_symlink(): raise ValueError(f'Restore parent is a symlink: {current}')
    return target


def restore_group(group, archive_dir, destination):
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    expected = {r['archive_path']: r for r in group['entries']}
    seen, pending_links, pending_dirs = set(), [], []
    joined = JoinedReader([archive_dir/p['name'] for p in group['parts']])
    decompressed = zstd.ZstdDecompressor().stream_reader(joined) if group['format'] == 'tar.zst' else joined
    mode = 'r|' if group['format'] == 'tar.zst' else 'r|gz'
    with tarfile.open(fileobj=decompressed, mode=mode) as tar:
        for member in tar:
            name = member.name.removeprefix('./')
            if name not in expected:
                if group['external']:
                    continue
                raise ValueError(f'Unexpected member: {name}')
            if name in seen: raise ValueError(f'Duplicate archive member: {name}')
            row = expected[name]; seen.add(name)
            target = safe_destination(destination, row['path'])
            if row['type'] == 'directory':
                if not member.isdir(): raise ValueError('Directory type mismatch')
                target.mkdir(parents=True, exist_ok=True); pending_dirs.append((target,row)); continue
            if row['type'] == 'symlink':
                if not member.issym() or member.linkname != row['target']: raise ValueError('Symlink mismatch')
                pending_links.append((target,row)); continue
            if not member.isfile() or member.size != row['bytes']:
                raise ValueError(f'File metadata mismatch: {name}')
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink(): raise ValueError(f'Existing symlink at file destination: {target}')
            if target.exists():
                if target.stat().st_size != row['bytes'] or sha(target) != row['sha256']:
                    raise FileExistsError(f'Refusing to overwrite different file: {target}')
                continue
            tmp = target.with_name(target.name+'.restore-incomplete')
            h, count = hashlib.sha256(), 0
            with tar.extractfile(member) as src, tmp.open('xb') as out:
                for block in iter(lambda: src.read(8 << 20), b''):
                    out.write(block); h.update(block); count += len(block)
            if count != row['bytes'] or h.hexdigest() != row['sha256']:
                raise ValueError(f'Restored member SHA256 mismatch: {name}')
            tmp.chmod(row['mode']); os.utime(tmp, ns=(row['mtime_ns'],row['mtime_ns']))
            tmp.replace(target)
    decompressed.close(); joined.close()
    if set(expected) != seen:
        raise ValueError(f'Missing archive members: {sorted(set(expected)-seen)[:10]}')
    for target,row in pending_links:
        # Rebase only links originally pointing inside this recorded workspace.
        old_prefix = group['source_workspace'].rstrip('/')+'/'
        link = row['target']
        if link.startswith(old_prefix): link = str(destination/link[len(old_prefix):])
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            if os.readlink(target) != link: raise FileExistsError(target)
        elif target.exists(): raise FileExistsError(target)
        else: target.symlink_to(link)
    for target,row in reversed(pending_dirs): target.chmod(row['mode'])
    return {'members':len(seen),'files':sum(r['type']=='file' for r in expected.values()),
            'bytes':sum(r.get('bytes',0) for r in expected.values()),'every_file_sha256_matched':True,
            'verified_at_utc':now()}


def walk_entries(path):
    if path.is_symlink() or path.is_file():
        yield path; return
    for current, dirs, files in os.walk(path, followlinks=False):
        current = Path(current); yield current
        for d in list(dirs):
            p = current/d
            if p.is_symlink(): dirs.remove(d); yield p
        for f in files: yield current/f


def inventory():
    if (STAGE/'catalog-working.json').exists(): raise FileExistsError('Use resume for the existing snapshot')
    tracked = set(command(['git','-C',ROOT,'ls-files','-z']).split('\0'))
    old_members = json.loads((ROOT/'publication/fy5080-release-members.json').read_text())['new_files']
    old_map = {x['path']:x for x in old_members}
    old_package = json.loads((ROOT/'publication/fy5080-package-manifest.json').read_text())
    old_assets = assets('fy5080-pi-artifacts-20261031')
    checkpoint_dirs = sorted(p for p in (ROOT/'outputs').rglob('resume.json')
                             if '/checkpoints/' in str(p) and p.parent.name.isdigit())
    checkpoint_ids = {}
    for resume in checkpoint_dirs:
        p = resume.parent; relative = p.relative_to(ROOT/'outputs')
        if relative.parts[0].startswith('pi0-ab'):
            gid=f'ab-{relative.parts[1].lower()}-checkpoint-{p.name}'
        elif relative.parts[0].startswith('pi0-six'): gid=f'six-checkpoint-{p.name}'
        else: gid=f'v2-checkpoint-{p.name}'
        checkpoint_ids[p] = gid
    groups = {}
    retained, exclusions = [], []
    paths = []
    for root in ALLOWED:
        if root.exists(): paths += list(walk_entries(root))
    # Preserve the modified environment declarations, without uploading environment binaries or credentials.
    support = []
    for family in ('pi0','pi05'):
        support += [WORKSPACE/family/'activate.sh',WORKSPACE/family/'openpi/pyproject.toml',WORKSPACE/family/'openpi/uv.lock']
    paths += [p for p in support if p.exists()]
    for p in sorted(set(paths)):
        rel = p.relative_to(WORKSPACE).as_posix()
        repo_rel = p.relative_to(ROOT).as_posix() if p.is_relative_to(ROOT) else None
        if repo_rel in tracked and not p.is_dir():
            retained.append(rel); continue
        if p.name in ('.env','credentials','hosts.yml','id_ed25519','id_rsa') or p.name.endswith('.pem'):
            exclusions.append({'path':rel,'reason':'credential-like filename, retained and not published'}); continue
        info = p.lstat()
        if stat.S_ISLNK(info.st_mode): typ='symlink'
        elif stat.S_ISDIR(info.st_mode): typ='directory'
        elif stat.S_ISREG(info.st_mode): typ='file'
        else: raise ValueError(f'Unexpected special file: {p}')
        external = old_map.get(repo_rel)
        gid, fmt, tag = None, 'tar.zst', TAG
        if external and typ=='file' and info.st_size==external['bytes']:
            gid='existing-fy5080-'+external['group']; fmt='tar.gz'; tag='fy5080-pi-artifacts-20261031'
        if gid is None:
            for parent,name in checkpoint_ids.items():
                if p==parent or p.is_relative_to(parent): gid=name; break
        if gid is None:
            if p==ROOT/'outputs/pi0-120-demo-v2-20261101/dataset' or p.is_relative_to(ROOT/'outputs/pi0-120-demo-v2-20261101/dataset'):
                gid='v2-training-data'
            elif p.is_relative_to(ROOT/'outputs/pi0-ab-old2010-20261101'):gid='ab-records'
            elif p.is_relative_to(ROOT/'outputs/pi0-120-demo-v2-20261101'):gid='v2-records'
            elif p.is_relative_to(ROOT/'outputs/pi0-six-demo-20261031'):gid='six-records'
            elif p.is_relative_to(ROOT/'outputs/pi0-120-regression-diagnosis-20261101'):gid='regression-records'
            elif p.is_relative_to(WORKSPACE/'assets/openpi-assets/checkpoints/pi0_base'):gid='official-pi0-base'
            elif p.is_relative_to(WORKSPACE/'assets/openpi-assets/checkpoints/pi05_base'):gid='official-pi05-base'
            elif p.is_relative_to(ROOT/'results'):gid='remaining-results'
            else:gid='support-and-other-records'
        group = groups.setdefault(gid,{'id':gid,'tag':tag,'format':fmt,'external':tag!=TAG,
            'source_workspace':str(WORKSPACE),'entries':[],'parts':[]})
        row={'path':rel,'archive_path':repo_rel if group['external'] else rel,'type':typ,
             'mode':stat.S_IMODE(info.st_mode),'mtime_ns':info.st_mtime_ns,'inode':info.st_ino,
             'cleanup':p not in support}
        if typ=='file':row['bytes']=info.st_size
        if typ=='symlink':row['target']=os.readlink(p)
        group['entries'].append(row)
    all_files=[r for g in groups.values() for r in g['entries'] if r['type']=='file']
    total=sum(r['bytes'] for r in all_files); done=0; last=0
    record('inventory_hash_start', files=len(all_files), source_bytes=total)
    def hash_row(row):
        p=WORKSPACE/row['path']; digest=sha(p); st=p.stat()
        if st.st_size!=row['bytes'] or st.st_mtime_ns!=row['mtime_ns'] or st.st_ino!=row['inode']:
            raise ValueError(f'Source changed while inventorying: {p}')
        return row,digest
    with futures.ThreadPoolExecutor(max_workers=2) as pool:
        for future in futures.as_completed([pool.submit(hash_row,r) for r in all_files]):
            row,digest=future.result(); row['sha256']=digest; done+=row['bytes']
            if time.monotonic()-last>15:
                record('inventory_hash_progress',hashed_bytes=done,total_bytes=total);last=time.monotonic()
    for g in groups.values():
        if g['external']:
            key=g['id'].removeprefix('existing-fy5080-')
            for name in old_package['groups'][key]['parts']:
                a=old_assets[name]
                if not a.get('digest','').startswith('sha256:') or a['state']!='uploaded':raise ValueError(name)
                g['parts'].append({'name':name,'bytes':a['size'],'sha256':a['digest'].split(':',1)[1]})
        g['source_bytes']=sum(r.get('bytes',0) for r in g['entries'])
    order=['ab-b-checkpoint-2010','v2-training-data','ab-records','v2-records','regression-records',
           'official-pi0-base','six-checkpoint-2010']
    ordered=sorted(groups.values(),key=lambda g:(order.index(g['id']) if g['id'] in order else len(order),g['id']))
    catalog={'schema_version':1,'tag':TAG,'repository':REPO,'created_at_utc':now(),
        'source_workspace':str(WORKSPACE),'source_git_commit':command(['git','-C',ROOT,'rev-parse','HEAD']).strip(),
        'scope':'All selected pi research outputs, untracked raw results, historical staging records, papers, and both official base checkpoints',
        'software_retained':'Git checkout and history, pi0/pi05 source/isolated environments, runtime tools and caches; other projects not included',
        'official_base_copies':'Explicit user-authorized complete recovery copies; original Gemma/upstream licenses accompany the release',
        'allowed_cleanup_roots':[str(p) for p in ALLOWED], 'retained_git_files':retained,'exclusions':exclusions,
        'groups':ordered,'source_file_count':len(all_files),'source_bytes':total,
        'minimal_B_groups':['ab-b-checkpoint-2010','ab-records','v2-training-data','v2-records','regression-records','official-pi0-base']}
    save(STAGE/'catalog-working.json',catalog)
    save(STAGE/'state.json',{'phase':'inventoried','groups':{},'source_deleted':False,'created_at_utc':now()})
    record('inventory_complete',files=len(all_files),source_bytes=total,groups=len(ordered))
    return catalog


def make_archive(group):
    directory=STAGE/'archive'/group['id']; directory.mkdir(parents=True,exist_ok=False)
    writer=SplitWriter(directory,group['id']+'.tar.zst')
    with zstd.ZstdCompressor(level=1,threads=2).stream_writer(writer,closefd=False) as compressed:
        with tarfile.open(fileobj=compressed,mode='w|',format=tarfile.PAX_FORMAT) as tar:
            for r in group['entries']:
                p=WORKSPACE/r['path']; st=p.lstat()
                if st.st_mtime_ns!=r['mtime_ns'] or st.st_ino!=r['inode']:
                    raise ValueError(f'Source changed before archive: {p}')
                info=tarfile.TarInfo(r['archive_path']); info.mode=r['mode']; info.mtime=r['mtime_ns']/1e9
                if r['type']=='directory':info.type=tarfile.DIRTYPE;tar.addfile(info)
                elif r['type']=='symlink':info.type=tarfile.SYMTYPE;info.linkname=r['target'];tar.addfile(info)
                else:
                    if st.st_size!=r['bytes']:raise ValueError(p)
                    info.size=r['bytes']
                    with p.open('rb') as f:tar.addfile(info,f)
    writer.finish_part(); group['parts']=writer.parts
    record('archive_created',group=group['id'],parts=len(writer.parts),archive_bytes=sum(x['bytes'] for x in writer.parts))
    return directory


def remove_staging(path):
    path=path.resolve()
    if not path.is_relative_to(STAGE.resolve()) or path==STAGE.resolve():
        raise ValueError('Staging cleanup escaped task root')
    if path.exists():shutil.rmtree(path)


def write_index(catalog,state):
    value={'tag':TAG,'release_url':f'https://github.com/{REPO}/releases/tag/{TAG}',
        'phase':state['phase'],'source_file_count':catalog['source_file_count'],'source_bytes':catalog['source_bytes'],
        'source_deleted':state.get('source_deleted',False),'minimal_B_groups':catalog['minimal_B_groups'],
        'groups':[{'id':g['id'],'tag':g['tag'],'source_bytes':g['source_bytes'],'member_count':len(g['entries']),
                   'parts':g['parts'],'verification':state['groups'].get(g['id'])} for g in catalog['groups']],
        'catalog_sha256':state.get('catalog_sha256'),'updated_at_utc':now()}
    save(PUB/'index.json',value)


def publish_index(message):
    relative=str((PUB/'index.json').relative_to(ROOT))
    staged=command(['git','-C',ROOT,'diff','--cached','--name-only']).splitlines()
    if any(p!=relative for p in staged):raise RuntimeError('Unrelated staged changes; index push stopped')
    command(['git','-C',ROOT,'add','--',relative])
    if command(['git','-C',ROOT,'diff','--cached','--name-only']).strip():
        command(['git','-C',ROOT,'commit','-m',message])
    branch=command(['git','-C',ROOT,'branch','--show-current']).strip()
    if branch!='codex/pi0-b-coverage-correction-test-20261101':raise RuntimeError('Backup branch changed')
    for attempt in range(1,4):
        try:
            command(['git','-C',ROOT,'-c','http.version=HTTP/1.1','push','origin',f'HEAD:refs/heads/{branch}'],timeout=45)
            local=command(['git','-C',ROOT,'rev-parse','HEAD']).strip()
            remote=command(['git','-C',ROOT,'ls-remote','origin',f'refs/heads/{branch}']).split()[0]
            if local!=remote:raise ValueError('Remote Git index commit differs')
            record('recovery_index_pushed',commit=local,attempt=attempt)
            return
        except Exception as exc:
            record('index_push_failed',attempt=attempt,error=repr(exc))
            if attempt==3:raise
            time.sleep(2*attempt)


def run_backup():
    catalog=json.loads((STAGE/'catalog-working.json').read_text()) if (STAGE/'catalog-working.json').exists() else inventory()
    state=json.loads((STAGE/'state.json').read_text())
    if state.get('source_deleted'):
        record('already_complete_no_repeat');return
    if release(TAG) is None:
        notes=STAGE/'release-notes.md'
        notes.write_text('Complete pi-series research-data recovery snapshot. IN PROGRESS; source data is retained until every group passes remote digest and downloaded-file recovery verification.\n\nIncludes new full model/optimizer checkpoints, frozen datasets and raw evaluation evidence. Historical dataset/checkpoint groups reuse exact assets in fy5080-pi-artifacts-20261031. Original incomplete historical checkpoints remain incomplete; this is a faithful backup, not a repair.\n\nOfficial base weight recovery copies are covered by the accompanying upstream and Gemma license/notice files. No credentials, installed environments, or other projects are included.\n')
        command(['gh','release','create',TAG,'--repo',REPO,'--target',catalog['source_git_commit'],'--draft',
                 '--title','Pi-series complete recovery backup 2026-11-01','--notes-file',notes])
    for path in (ROOT/'third_party_licenses/GEMMA-LICENSE.txt',ROOT/'third_party_licenses/openpi-LICENSE'):
        upload_file(path)
    for group in catalog['groups']:
        gid=group['id']
        if state['groups'].get(gid,{}).get('every_file_sha256_matched'):
            gf=STAGE/f'group-{gid}.json'
            if not gf.exists():save(gf,{'group':group,'verification':state['groups'][gid]})
            upload_file(gf)
            for parent in ('archive','download','restore-verification'):
                if (STAGE/parent/gid).exists():remove_staging(STAGE/parent/gid)
            continue
        state.update(phase='backing_up',current_group=gid);save(STAGE/'state.json',state)
        record('group_start',group=gid,source_bytes=group['source_bytes'],external=group['external'])
        if shutil.disk_usage(STAGE).free < max(25*1024**3,group['source_bytes']*3+5*1024**3):
            raise RuntimeError(f'Not enough temporary space for {gid}')
        archive_dir=STAGE/'archive'/gid
        if not group['external']:
            if not group['parts']:
                if archive_dir.exists():remove_staging(archive_dir)
                archive_dir=make_archive(group);save(STAGE/'catalog-working.json',catalog)
            with futures.ThreadPoolExecutor(max_workers=2) as pool:
                receipts=list(pool.map(lambda part:upload_file(archive_dir/part['name'],part),group['parts']))
        remote=assets(group['tag'])
        receipts=[receipt(remote[p['name']],p) for p in group['parts']]
        downloaded=STAGE/'download'/gid
        with futures.ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda part:download_file(group['tag'],part,downloaded),group['parts']))
        restored=STAGE/'restore-verification'/gid
        if restored.exists():remove_staging(restored)
        report=restore_group(group,downloaded,restored)
        if gid=='ab-b-checkpoint-2010':
            # This restores the real 4020-step optimizer/model state without performing updates.
            ckpt=restored/'pi-reproduction/outputs/pi0-ab-old2010-20261101/B/checkpoints/pi0_piper_color_lora/ab_old2010/2010'
            verification_file=STAGE/'B-full-state-restore.json'
            command(['bash',ROOT/'scripts/verify_pi_backup_state.sh',ckpt,verification_file],timeout=900)
            report['model_optimizer_restore']=json.loads(verification_file.read_text())
        report.update(remote_assets=receipts,source_files_unchanged=True)
        state['groups'][gid]=report
        save(STAGE/'state.json',state);write_index(catalog,state)
        group_file=STAGE/f'group-{gid}.json';save(group_file,{'group':group,'verification':report})
        upload_file(group_file)
        record('group_verified',group=gid,files=report['files'],source_bytes=group['source_bytes'])
        remove_staging(downloaded);remove_staging(restored)
        if archive_dir.exists():remove_staging(archive_dir)
    state.update(phase='all_groups_verified',current_group=None)
    catalog.setdefault('recovery_tool_sha256',sha(Path(__file__)))
    catalog.setdefault('backup_tool_commit',command(['git','-C',ROOT,'rev-parse','HEAD']).strip())
    save(STAGE/'catalog-working.json',catalog)
    final=STAGE/'backup-catalog.json';save(final,catalog)
    state['catalog_sha256']=sha(final);save(STAGE/'state.json',state);write_index(catalog,state)
    upload_file(final)
    upload_file(STAGE/'B-full-state-restore.json')
    sums=STAGE/'SHA256SUMS'
    sums.write_text(''.join(f'{p["sha256"]}  {p["name"]}\n' for g in catalog['groups'] if not g['external'] for p in g['parts'])
                    +f'{sha(final)}  {final.name}\n')
    upload_file(sums)
    upload_file(Path(__file__))
    notes=STAGE/'release-notes-complete.md'
    notes.write_text(f'All {len(catalog["groups"])} groups verified by remote asset size/SHA256 and full re-download, extraction and every selected file SHA256. {catalog["source_file_count"]} regular files, {catalog["source_bytes"]} source bytes. The B final checkpoint was restored with its model and optimizer counters at 4020; zero updates were performed.\n\nUse backup-catalog.json and pi_release_backup.py restore. Each new tar.zst archive is split into <=512 MiB parts. Historical groups explicitly reference the immutable fy5080-pi-artifacts-20261031 Release. Details: docs/PI0_RELEASE_RESTORE_20261101.md in branch codex/pi0-b-coverage-correction-test-20261101.\n\nOriginal pi0/ pi05 base-weight upstream licenses accompany these user-authorized recovery copies. Historical incomplete checkpoints are preserved as-is. Credentials, installed environment binaries and other projects are excluded.\n')
    command(['gh','release','edit',TAG,'--repo',REPO,'--draft=false','--notes-file',notes])
    remote=assets(TAG);receipt(remote[final.name],{'bytes':final.stat().st_size,'sha256':sha(final)})
    state.update(phase='published_verified_ready_for_cleanup',published_at_utc=now())
    save(STAGE/'state.json',state);write_index(catalog,state)
    record('complete_backup_published',url=f'https://github.com/{REPO}/releases/tag/{TAG}')
    publish_index('Record fully downloaded and verified pi backup before source cleanup')


def cleanup_sources():
    catalog=json.loads((STAGE/'catalog-working.json').read_text());state=json.loads((STAGE/'state.json').read_text())
    if state.get('source_deleted'):return
    if state['phase']!='published_verified_ready_for_cleanup':raise RuntimeError('Full backup is not verified/published')
    if release(TAG)['draft']:raise RuntimeError('Release is still a draft')
    if any(not state['groups'].get(g['id'],{}).get('every_file_sha256_matched') for g in catalog['groups']):
        raise RuntimeError('Not all groups passed full recovery verification')
    for tag in sorted({g['tag'] for g in catalog['groups']}):
        remote=assets(tag)
        for group in catalog['groups']:
            if group['tag']==tag:
                for p in group['parts']:receipt(remote[p['name']],p)
    tracked=set(command(['git','-C',ROOT,'ls-files','-z']).split('\0'))
    rows=[r for g in catalog['groups'] for r in g['entries'] if r['cleanup']]
    plan_path=STAGE/'cleanup-plan.json'
    resuming=plan_path.exists()
    if resuming:
        plan=json.loads(plan_path.read_text())
        if plan['catalog_sha256']!=state['catalog_sha256']:raise ValueError('Cleanup plan catalog differs')
    def source_path(row):
        p=WORKSPACE/row['path']
        bases=[base for base in ALLOWED if p==base or p.is_relative_to(base)]
        if not bases:raise ValueError(f'Outside allowlist: {p}')
        base=bases[0]
        if base.is_symlink():raise ValueError(f'Cleanup root changed to a symlink: {base}')
        if p!=base and not p.parent.resolve().is_relative_to(base):
            raise ValueError(f'Physical parent escaped frozen allowed root: {p}')
        if p.is_relative_to(ROOT) and p.relative_to(ROOT).as_posix() in tracked:
            raise ValueError(f'Tracked file: {p}')
        return p
    # Verify every deletion target before deleting the first original file.
    for i,r in enumerate(rows):
        p=source_path(r)
        try:st=p.lstat()
        except FileNotFoundError:
            if resuming:continue
            raise
        if st.st_ino!=r['inode'] or (not(resuming and r['type']=='directory') and st.st_mtime_ns!=r['mtime_ns']):
            raise ValueError(f'Source changed: {p}')
        if r['type']=='file' and (st.st_size!=r['bytes'] or sha(p)!=r['sha256']):raise ValueError(f'Source content changed: {p}')
        if r['type']=='symlink' and os.readlink(p)!=r['target']:raise ValueError(f'Source link changed: {p}')
        if i%100==0:record('cleanup_precheck',checked=i,total=len(rows))
    if not resuming:
        plan={'catalog_sha256':state['catalog_sha256'],'created_at_utc':now(),
              'free_bytes_before':shutil.disk_usage(WORKSPACE).free,
              'planned_files':[{'path':r['path'],'bytes':r.get('bytes',0),'sha256':r.get('sha256'),'type':r['type']}
                               for r in rows if r['type']!='directory']}
        save(plan_path,plan)
    state.update(phase='deleting_verified_sources',free_bytes_before=plan['free_bytes_before'])
    save(STAGE/'state.json',state)
    journal=STAGE/'deletion-journal.jsonl'
    for r in rows:
        if r['type']=='directory':continue
        p=source_path(r)
        try:st=p.lstat()
        except FileNotFoundError:
            if resuming:continue
            raise
        if st.st_ino!=r['inode'] or st.st_mtime_ns!=r['mtime_ns']:raise ValueError(f'Changed during cleanup: {p}')
        p.unlink()
        with journal.open('a') as f:f.write(json.dumps({'path':r['path'],'at_utc':now()})+'\n')
    for r in sorted((r for r in rows if r['type']=='directory'),key=lambda r:len(PurePosixPath(r['path']).parts),reverse=True):
        p=WORKSPACE/r['path']
        try:p.rmdir()
        except OSError:
            if not p.is_dir() or any(p.iterdir()):continue
            raise
    receipt_path=STAGE/'cleanup-receipt.json'
    if receipt_path.exists():cleanup=json.loads(receipt_path.read_text())
    else:
        removed=plan['planned_files']
        cleanup={'completed_at_utc':now(),'files_and_links_deleted':len(removed),
            'source_bytes_deleted':sum(r['bytes'] for r in removed),
            'free_bytes_before':state['free_bytes_before'],'free_bytes_after':shutil.disk_usage(WORKSPACE).free,
            'free_space_note':'filesystem-wide free space can also change due to unrelated concurrent jobs',
            'allowed_roots':[str(p) for p in ALLOWED],'other_projects_touched':False,'deleted':removed,
            'deletion_journal_sha256':sha(journal),'resumed_cleanup':resuming}
        save(receipt_path,cleanup)
    upload_file(receipt_path)
    state.update(phase='complete',source_deleted=True,cleanup={k:v for k,v in cleanup.items() if k!='deleted'})
    save(STAGE/'state.json',state);write_index(catalog,state)
    record('cleanup_complete',**state['cleanup'])
    publish_index('Record completed verified pi data cleanup')


def finalize_documentation():
    state=json.loads((STAGE/'state.json').read_text())
    if state.get('phase')!='complete' or not state.get('source_deleted'):
        raise RuntimeError('Cleanup has not completed; final documentation cannot claim completion')
    done=PUB/'documentation-finalized.json'
    if done.exists():
        paths=['AGENTS.md','ARTIFACT_INDEX.json','README.md','docs/PI0_RELEASE_RESTORE_20261101.md',
               'docs/PI0_STORAGE_BACKUP_STATUS_20261101.md',
               'experiments/piper-color-v1/pi0-b-coverage-correction-test-20261101.json',str(done.relative_to(ROOT))]
        staged=command(['git','-C',ROOT,'diff','--cached','--name-only']).splitlines()
        if any(p not in paths for p in staged):raise RuntimeError('Unrelated staged changes during documentation resume')
        command(['git','-C',ROOT,'add','--',*paths])
        if command(['git','-C',ROOT,'diff','--cached','--name-only']).strip():
            command(['git','-C',ROOT,'commit','-m','Finish completed pi archive documentation'])
        publish_index('Confirm final pi archive documentation delivery')
        record('final_documentation_pushed',commit=command(['git','-C',ROOT,'rev-parse','HEAD']).strip())
        return
    index=json.loads((PUB/'index.json').read_text())
    cleanup=state['cleanup'];gib=cleanup['source_bytes_deleted']/1024**3
    meta=ROOT/'ARTIFACT_INDEX.json';data=json.loads(meta.read_text())
    data['pi_complete_backup_20261101'].update(status='published_downloaded_restored_and_source_cleaned',source_deleted=True,
        release_url=index['release_url'],source_file_count=index['source_file_count'],source_bytes=index['source_bytes'],
        cleanup=cleanup,catalog_sha256=index['catalog_sha256'])
    data['pi_b_coverage_restoration_required']=True
    save(meta,data)
    contract=ROOT/'experiments/piper-color-v1/pi0-b-coverage-correction-test-20261101.json'
    obj=json.loads(contract.read_text());obj['status']='ready_after_restore_not_started'
    obj['restoration'].update(source_storage_state='archived_source_removed_restore_required',
        release_url=index['release_url'],catalog_sha256=index['catalog_sha256'])
    save(contract,obj)
    doc=ROOT/'docs/PI0_RELEASE_RESTORE_20261101.md';text=doc.read_text()
    marker='## 备份的含义\n'
    text=text.replace(marker,f'**完成记录：** 全部 {len(index["groups"])} 组已通过远端大小/SHA256、全量回下载、解包逐文件校验；B 完整模型/优化器实际恢复到累计4020。原始数据已按白名单清理，涉及约 {gib:.2f} GiB 文件内容。详细回执在恢复索引和 Release 的 `cleanup-receipt.json`。新合并任务尚未执行，须先恢复数据。\n\n'+marker,1)
    doc.write_text(text)
    old=ROOT/'docs/PI0_STORAGE_BACKUP_STATUS_20261101.md';text=old.read_text();parts=text.split('\n',1)
    old.write_text(parts[0]+'\n\n**后续更新：用户已授权完整备份后清理，现已完成。** 原核对记录保留在下文；最新状态和恢复方法见 [Release 恢复说明](PI0_RELEASE_RESTORE_20261101.md)。\n'+parts[1])
    readme=ROOT/'README.md';text=readme.read_text()
    original='**存储核对：** π 项目尚未全量备份至 GitHub，未执行用户所述条件性删除；完整检查点、v2 数据和原始视频/轨迹仍需保留。[备份缺口与占用](docs/PI0_STORAGE_BACKUP_STATUS_20261101.md)。'
    updated=f'**存储归档已完成：** π 研究数据与两套基础权重已按清单上传/复用 Release，完成全量回下载和逐文件校验，B 完整状态恢复验证通过；已清理对应原始数据约 {gib:.2f} GiB。代码和环境保留，新任务执行前先恢复。[恢复步骤](docs/PI0_RELEASE_RESTORE_20261101.md) · [Release]({index["release_url"]})。'
    if original not in text:raise ValueError('README storage paragraph changed; review required')
    readme.write_text(text.replace(original,updated,1))
    agents=ROOT/'AGENTS.md';agents.write_text(agents.read_text()+f'\n\n## 完整归档与清理已完成\n- `{TAG}` 已完成全量回下载/逐文件校验，B 模型与优化器恢复计数4020验证通过。按授权清理的来源数据已经移除，其他项目未处理。\n- 代码、Git、隔离环境与恢复工具保留；新任务必须先读 docs/PI0_RELEASE_RESTORE_20261101.md 并恢复最小 B 集合，依实际恢复回执绑定路径。原 source_anchor 是历史摘要，不代表旧路径仍存在。\n')
    save(done,{'completed_at_utc':now(),'release_url':index['release_url'],'source_deleted':True,'new_task_started':False})
    paths=['AGENTS.md','ARTIFACT_INDEX.json','README.md','docs/PI0_RELEASE_RESTORE_20261101.md',
           'docs/PI0_STORAGE_BACKUP_STATUS_20261101.md',str(contract.relative_to(ROOT)),str(done.relative_to(ROOT))]
    staged=command(['git','-C',ROOT,'diff','--cached','--name-only']).splitlines()
    if any(p not in paths for p in staged):raise RuntimeError('Unrelated staged changes before final documentation')
    command(['git','-C',ROOT,'add','--',*paths]);command(['git','-C',ROOT,'diff','--cached','--check'])
    if command(['git','-C',ROOT,'diff','--cached','--name-only']).strip():
        command(['git','-C',ROOT,'commit','-m','Document completed pi archive cleanup and required data restoration'])
    publish_index('Record final pi archive documentation')
    record('final_documentation_pushed',commit=command(['git','-C',ROOT,'rev-parse','HEAD']).strip())


def restore_command(args):
    index=json.loads((PUB/'index.json').read_text())
    expected=index['catalog_sha256']
    if not expected or index['phase'] not in ('published_verified_ready_for_cleanup','complete'):
        raise RuntimeError('The complete verified recovery catalog has not been published yet')
    cache=args.cache.resolve(); cache.mkdir(parents=True,exist_ok=True)
    remote=assets(TAG);a=remote['backup-catalog.json']
    if a.get('digest')!='sha256:'+expected:raise ValueError('Catalog differs from committed trusted index')
    cp=download_file(TAG,{'name':a['name'],'bytes':a['size'],'sha256':expected},cache)
    catalog=json.loads(cp.read_text())
    ids=catalog['minimal_B_groups'] if args.minimal_b else (args.groups or [g['id'] for g in catalog['groups']])
    if not set(ids)<={g['id'] for g in catalog['groups']}:raise ValueError('Unknown group ID')
    destination=args.workspace_root.resolve();destination.mkdir(parents=True,exist_ok=True)
    results=[]
    for group in catalog['groups']:
        if group['id'] not in ids:continue
        remote=assets(group['tag']);folder=cache/group['id'];folder.mkdir(exist_ok=True)
        for part in group['parts']:
            receipt(remote[part['name']],part);download_file(group['tag'],part,folder)
        result=restore_group(group,folder,destination);results.append({'group':group['id'],**result})
        for part in group['parts']:(folder/part['name']).unlink()
        folder.rmdir()
    mapping={'workspace_root':str(destination),'original_workspace_root':catalog['source_workspace'],
        'restored_at_utc':now(),'groups':results,
        'B_checkpoint':str(destination/'pi-reproduction/outputs/pi0-ab-old2010-20261101/B/checkpoints/pi0_piper_color_lora/ab_old2010/2010'),
        'v2_dataset':str(destination/'pi-reproduction/outputs/pi0-120-demo-v2-20261101/dataset'),
        'pi0_base':str(destination/'assets/openpi-assets/checkpoints/pi0_base'),
        'path_rule':'regular-file contents are exact originals; internal absolute symlink targets rebase to destination workspace'}
    save(destination/'pi-restoration-receipt-20261101.json',mapping)
    print(json.dumps(mapping,indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('backup');sub.add_parser('cleanup');sub.add_parser('all');sub.add_parser('status');sub.add_parser('finalize')
    q=sub.add_parser('restore');q.add_argument('--workspace-root',type=Path,required=True)
    q.add_argument('--cache',type=Path,required=True);choice=q.add_mutually_exclusive_group()
    choice.add_argument('--minimal-b',action='store_true');choice.add_argument('--groups',nargs='+')
    args=p.parse_args()
    if args.command=='restore':restore_command(args);return
    STAGE.mkdir(parents=True,exist_ok=True);PUB.mkdir(parents=True,exist_ok=True)
    with (STAGE/'lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if args.command=='status':print((STAGE/'state.json').read_text());return
        try:
            if args.command in ('backup','all'):run_backup()
            if args.command in ('cleanup','all'):cleanup_sources()
            if args.command in ('finalize','all'):finalize_documentation()
        except BaseException as exc:
            record('operation_failed',error=repr(exc));raise


if __name__=='__main__':main()
