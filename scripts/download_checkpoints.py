#!/home/fanyuan/miniconda3/envs/kaiwen-learn/bin/python
"""Fetch generation-pinned official openpi weights, without importing ML runtimes.

Uses the standard library and a local C helper for GCS CRC32C checksums.  Nothing
is installed into the Python environment.  Re-run the same command to resume.
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import ctypes
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
CHECKPOINTS = ("pi05_libero", "pi0_libero", "pi05_base", "pi0_base")
STOP = threading.Event()
PRINT_LOCK = threading.Lock()
NATIVE_SOURCE = r'''
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#if defined(__x86_64__)
#include <nmmintrin.h>
__attribute__((target("sse4.2")))
static uint32_t accelerated(uint32_t crc, const unsigned char *data, size_t n) {
    uint64_t c = ~crc;
    while (n >= 8) { uint64_t v; memcpy(&v, data, 8); c = _mm_crc32_u64(c, v); data += 8; n -= 8; }
    while (n--) c = _mm_crc32_u8(c, *data++);
    return ~(uint32_t)c;
}
#endif
uint32_t update(uint32_t crc, const unsigned char *data, size_t n) {
#if defined(__x86_64__)
    if (__builtin_cpu_supports("sse4.2")) return accelerated(crc, data, n);
#endif
    uint32_t c = ~crc;
    while (n--) { c ^= *data++; for (int i=0; i<8; ++i) c = (c >> 1) ^ (0x82f63b78U & (-(c & 1))); }
    return ~c;
}
'''


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def log(message):
    with PRINT_LOCK:
        print(f"[{now()}] {message}", flush=True)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def load_crc32c():
    build = ROOT / "cache" / "checksum-helper"
    build.mkdir(parents=True, exist_ok=True)
    source = build / "crc32c.c"
    library = build / "crc32c.so"
    if not library.exists() or not source.exists() or source.read_text() != NATIVE_SOURCE:
        source.write_text(NATIVE_SOURCE)
        compiler = shutil.which("cc") or shutil.which("gcc")
        if not compiler:
            raise RuntimeError("A C compiler is required to verify GCS composite-object CRC32C checksums")
        subprocess.run([compiler, "-O3", "-shared", "-fPIC", str(source), "-o", str(library)], check=True)
    native = ctypes.CDLL(str(library))
    update = native.update
    update.argtypes = (ctypes.c_uint32, ctypes.c_char_p, ctypes.c_size_t)
    update.restype = ctypes.c_uint32
    if update(0, b"123456789", 9) != 0xE3069283:
        raise RuntimeError("CRC32C known-vector check failed")
    return update


def request_json(url, args):
    for attempt in range(args.attempts):
        try:
            with urllib.request.urlopen(url, timeout=args.timeout) as response:
                return json.load(response)
        except Exception:
            if attempt + 1 == args.attempts:
                raise
            STOP.wait(min(2 ** attempt, 10))


def make_manifest(name, args):
    destination = ROOT / "results" / f"checkpoints-manifest-{name}.json"
    if destination.exists():
        return json.loads(destination.read_text())
    if name == "tokenizer":
        bucket, prefix = "big_vision", "paligemma_tokenizer.model"
    else:
        bucket, prefix = "openpi-assets", f"checkpoints/{name}/"
    objects, token = [], None
    if name == "tokenizer":
        objects = [request_json(f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/" + urllib.parse.quote(prefix, safe=""), args)]
    while name != "tokenizer":
        query = {"prefix": prefix}
        if token:
            query["pageToken"] = token
        listing = request_json(f"https://storage.googleapis.com/storage/v1/b/{bucket}/o?" + urllib.parse.urlencode(query), args)
        objects.extend(item for item in listing.get("items", []) if not item["name"].endswith("/"))
        token = listing.get("nextPageToken")
        if not token:
            break
    if name == "tokenizer":
        objects = [item for item in objects if item["name"] == prefix]
    if not objects:
        raise RuntimeError(f"Official prefix is empty: gs://{bucket}/{prefix}")
    for item in objects:
        local = (ROOT / "cache" / "openpi" / bucket / item["name"] if name == "tokenizer"
                 else ROOT / item["name"])
        item["local_path"] = str(local)
        item["download_url"] = (f"https://storage.googleapis.com/{bucket}/"
                                + urllib.parse.quote(item["name"], safe="/")
                                + "?generation=" + item["generation"])
        if not item.get("crc32c"):
            raise RuntimeError(f"Missing GCS checksum: {item['name']}")
    manifest = {"schema_version": 1, "created_at": now(), "name": name,
                "source": f"gs://{bucket}/{prefix}", "generation_pinned": True,
                "total_bytes": sum(int(item["size"]) for item in objects), "objects": objects}
    write_json(destination, manifest)
    return manifest


def hashes(path, update_crc32c):
    md5, crc = hashlib.md5(), 0
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            md5.update(chunk)
            crc = update_crc32c(crc, chunk, len(chunk))
    return {"md5Hash": base64.b64encode(md5.digest()).decode(),
            "crc32c": base64.b64encode(crc.to_bytes(4, "big")).decode()}


def verify(path, item, update_crc32c):
    if not path.exists() or path.stat().st_size != int(item["size"]):
        return None
    observed = hashes(path, update_crc32c)
    if any(observed[key] != item[key] for key in observed if item.get(key)):
        return None
    return observed


def download(item, args, update_crc32c, deadline):
    path, expected = Path(item["local_path"]), int(item["size"])
    partial = path.with_name(path.name + ".partial")
    path.parent.mkdir(parents=True, exist_ok=True)
    if STOP.is_set() or time.monotonic() >= deadline:
        return {"state": "pending"}
    if observed := verify(path, item, update_crc32c):
        log(f"verified existing {item['name']}")
        return {"state": "verified", "verified_at": now(), **observed}
    if path.exists():
        path.rename(path.with_name(path.name + f".invalid-{int(time.time())}"))
    if expected == 0 and not partial.exists():
        partial.touch()
    last_error = None
    urls = list(dict.fromkeys([item.get("mediaLink", item["download_url"]), item["download_url"]]))
    proxy_opener = urllib.request.build_opener()
    direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    routes = [(url, proxy_opener, "proxy") for url in urls] + [(url, direct_opener, "direct") for url in urls]
    endpoint = len(urls) if getattr(args, "prefer_direct", False) else 0
    for attempt in range(1, args.attempts + 1):
        if STOP.is_set() or time.monotonic() >= deadline:
            return {"state": "partial" if partial.exists() else "pending", "error": last_error}
        try:
            offset = partial.stat().st_size if partial.exists() else 0
            if offset > expected:
                raise ValueError(f"Partial file exceeds expected size: {offset}>{expected}")
            while offset < expected:
                if STOP.is_set() or time.monotonic() >= deadline:
                    return {"state": "partial" if partial.exists() else "pending"}
                end = min(offset + args.chunk_mib * 1024 * 1024, expected) - 1
                headers = {"Accept-Encoding": "identity", "Range": f"bytes={offset}-{end}"}
                url, opener, route_name = routes[endpoint % len(routes)]
                request = urllib.request.Request(url, headers=headers)
                request_started = time.monotonic()
                received = 0
                slow = False
                with opener.open(request, timeout=args.timeout) as response:
                    if response.status != 206 or response.headers.get("Content-Range") != f"bytes {offset}-{end}/{expected}":
                        raise RuntimeError("Server did not honor the requested resume range")
                    remote_generation = response.headers.get("x-goog-generation")
                    if remote_generation and remote_generation != item["generation"]:
                        raise RuntimeError("Server returned an unexpected GCS object generation")
                    with partial.open("ab") as stream:
                        while chunk := response.read(1024 * 1024):
                            stream.write(chunk)
                            received += len(chunk)
                            if STOP.is_set() or time.monotonic() >= deadline:
                                stream.flush()
                                return {"state": "partial"}
                            elapsed = time.monotonic() - request_started
                            if elapsed >= 15 and received / 2**20 / elapsed < 0.5:
                                slow = True
                                break
                        stream.flush()
                        os.fsync(stream.fileno())
                if not received:
                    raise RuntimeError("Server made no progress on the requested range")
                offset = partial.stat().st_size
                if offset > expected:
                    raise RuntimeError("Server returned more bytes than expected")
                if slow:
                    endpoint += 1
                    log(f"reconnect slow {route_name} stream {item['name']} at {offset / 2**20:.0f} MiB")
            observed = verify(partial, item, update_crc32c)
            if observed is None:
                if partial.stat().st_size == expected:
                    partial.rename(partial.with_name(partial.name + f".corrupt-{int(time.time())}"))
                raise RuntimeError(f"Size/checksum verification failed: {item['name']}")
            partial.replace(path)
            log(f"verified {item['name']} ({expected / 2**20:.1f} MiB)")
            return {"state": "verified", "verified_at": now(), **observed}
        except Exception as error:
            last_error = f"{type(error).__name__}: {error}"
            endpoint += 1
            log(f"retry {attempt}/{args.attempts} {item['name']}: {last_error}")
            STOP.wait(min(2 ** (attempt - 1), 10))
    return {"state": "failed", "error": last_error}


def summary(manifests, states, started, finished=False):
    groups = {}
    for manifest in manifests:
        present, verified, partial_bytes = 0, 0, 0
        objects = []
        for item in manifest["objects"]:
            path = Path(item["local_path"])
            partial = path.with_name(path.name + ".partial")
            state = states.get(item["name"], {"state": "pending"})
            if path.exists():
                present += path.stat().st_size
            if partial.exists():
                partial_bytes += partial.stat().st_size
            for segment in path.with_name(path.name + ".ranges").glob("*.segment*"):
                try:
                    partial_bytes += segment.stat().st_size
                except FileNotFoundError:
                    pass
            if state["state"] == "verified":
                verified += 1
            objects.append({"name": item["name"], "expected_bytes": int(item["size"]), **state})
        groups[manifest["name"]] = {"total_bytes": manifest["total_bytes"], "present_bytes": present,
                                    "partial_bytes": partial_bytes, "verified_files": verified,
                                    "total_files": len(objects), "complete": verified == len(objects), "objects": objects}
    status_path = ROOT / "results" / "checkpoints-status.json"
    # Preserve other checkpoints' verification records when, for example, the
    # user downloads a base model after finishing both LIBERO models.
    previous_groups = {}
    if status_path.exists():
        previous_groups = json.loads(status_path.read_text()).get("checkpoints", {})
    status = {"updated_at": now(), "started_at": started, "finished": finished,
              "requested_checkpoints": [manifest["name"] for manifest in manifests],
              "complete": all(group["complete"] for group in groups.values()),
              "checkpoints": {**previous_groups, **groups}}
    write_json(status_path, status)
    return status


def download_segment(job, args, deadline):
    """Own one disjoint remote interval; only promote exact-length segments."""
    item, low, high, path = job
    length = high - low + 1
    if path.exists() and path.stat().st_size == length:
        return {"state": "downloaded"}
    partial = path.with_name(path.name + ".partial")
    urls = list(dict.fromkeys([item.get("mediaLink", item["download_url"]), item["download_url"]]))
    proxy = urllib.request.build_opener()
    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    routes = [(url, proxy) for url in urls] + [(url, direct) for url in urls]
    route_index = len(urls) if args.prefer_direct else 0
    last_error = None
    for attempt in range(args.attempts):
        try:
            offset = partial.stat().st_size if partial.exists() else 0
            if offset > length:
                raise RuntimeError("Saved segment exceeds its pinned remote interval")
            while offset < length:
                if STOP.is_set() or time.monotonic() >= deadline:
                    return {"state": "partial"}
                start = low + offset
                url, opener = routes[route_index % len(routes)]
                request = urllib.request.Request(url, headers={
                    "Accept-Encoding": "identity", "Range": f"bytes={start}-{high}"})
                began, received, slow = time.monotonic(), 0, False
                with opener.open(request, timeout=args.timeout) as response:
                    if response.status != 206 or response.headers.get("Content-Range") != f"bytes {start}-{high}/{item['size']}":
                        raise RuntimeError("Server returned an unexpected segment range")
                    generation = response.headers.get("x-goog-generation")
                    if generation and generation != item["generation"]:
                        raise RuntimeError("Server returned an unexpected object generation")
                    with partial.open("ab") as stream:
                        while chunk := response.read(256 * 1024):
                            stream.write(chunk)
                            received += len(chunk)
                            if offset + received > length:
                                raise RuntimeError("Server returned an oversized segment")
                            if STOP.is_set() or time.monotonic() >= deadline:
                                return {"state": "partial"}
                            elapsed = time.monotonic() - began
                            if elapsed >= 15 and received / 2**20 / elapsed < 0.5:
                                slow = True
                                break
                        stream.flush()
                        os.fsync(stream.fileno())
                if not received:
                    raise RuntimeError("Server made no progress on a segment")
                offset = partial.stat().st_size
                if slow:
                    route_index += 1
            partial.replace(path)
            return {"state": "downloaded"}
        except Exception as error:
            last_error = f"{type(error).__name__}: {error}"
            route_index += 1
            log(f"segment retry {attempt + 1}/{args.attempts} {item['name']} bytes {low}-{high}: {last_error}")
            STOP.wait(min(2 ** attempt, 10))
    return {"state": "failed", "error": last_error}


def merge_segments(item, chunk_bytes, update_crc32c):
    """The main thread alone appends contiguous intervals and verifies the file."""
    path = Path(item["local_path"])
    partial = path.with_name(path.name + ".partial")
    directory = path.with_name(path.name + ".ranges")
    expected = int(item["size"])
    # GCS checkpoints include zero-byte commit markers. No HTTP interval exists
    # for these objects, but they still require a real file and hash validation.
    if expected == 0 and not partial.exists():
        partial.touch()
    offset = partial.stat().st_size if partial.exists() else 0
    while offset < expected:
        high = min((offset // chunk_bytes + 1) * chunk_bytes, expected) - 1
        segment = directory / f"{offset:020}-{high:020}.segment"
        if not segment.exists():
            return None
        if segment.stat().st_size != high - offset + 1:
            raise RuntimeError("Completed segment has an invalid length")
        with partial.open("ab") as destination, segment.open("rb") as source:
            shutil.copyfileobj(source, destination, 1024 * 1024)
            destination.flush()
            os.fsync(destination.fileno())
        segment.unlink()
        offset = high + 1
    if observed := verify(partial, item, update_crc32c):
        partial.replace(path)
        plan_path = directory / "plan.json"
        if plan_path.exists() and set(directory.iterdir()) == {plan_path}:
            plan_path.unlink()
            directory.rmdir()
        log(f"verified segmented {item['name']} ({expected / 2**20:.1f} MiB)")
        return {"state": "verified", "verified_at": now(), **observed}
    partial.rename(partial.with_name(partial.name + f".corrupt-{int(time.time())}"))
    return {"state": "failed", "error": "Final full-object size/checksum verification failed"}


def download_parallel_ranges(manifests, args, update_crc32c, deadline, started):
    states, jobs, chunk_sizes = {}, [], {}
    for manifest in manifests:
        for item in manifest["objects"]:
            path = Path(item["local_path"])
            if observed := verify(path, item, update_crc32c):
                states[item["name"]] = {"state": "verified", "verified_at": now(), **observed}
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                path.rename(path.with_name(path.name + f".invalid-{int(time.time())}"))
            directory = path.with_name(path.name + ".ranges")
            directory.mkdir(exist_ok=True)
            plan_path = directory / "plan.json"
            if plan_path.exists():
                plan = json.loads(plan_path.read_text())
                if plan["generation"] != item["generation"] or plan["size"] != item["size"]:
                    raise RuntimeError(f"Segment plan generation mismatch: {plan_path}")
                chunk_bytes = plan["chunk_bytes"]
            else:
                chunk_bytes = args.chunk_mib * 1024 * 1024
                write_json(plan_path, {"generation": item["generation"], "size": item["size"], "chunk_bytes": chunk_bytes})
            chunk_sizes[item["name"]] = chunk_bytes
            states[item["name"]] = merge_segments(item, chunk_bytes, update_crc32c) or {"state": "partial"}
            if states[item["name"]]["state"] == "verified":
                continue
            partial = path.with_name(path.name + ".partial")
            low = partial.stat().st_size if partial.exists() else 0
            while low < int(item["size"]):
                high = min((low // chunk_bytes + 1) * chunk_bytes, int(item["size"])) - 1
                jobs.append((item, low, high, directory / f"{low:020}-{high:020}.segment"))
                low = high + 1
    log(f"parallel ranges: {len(jobs)} disjoint segments, at most {args.workers} connections")
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(download_segment, job, args, deadline): job for job in jobs}
        last_log = 0
        while futures:
            done, _ = concurrent.futures.wait(futures, timeout=5, return_when=concurrent.futures.FIRST_COMPLETED)
            touched = {}
            for future in done:
                job = futures.pop(future)
                item = job[0]
                try:
                    result = future.result()
                except Exception as error:
                    result = {"state": "failed", "error": repr(error)}
                if result["state"] == "failed":
                    states[item["name"]] = result
                touched[item["name"]] = item
            for name, item in touched.items():
                if states[name]["state"] != "verified":
                    if result := merge_segments(item, chunk_sizes[name], update_crc32c):
                        states[name] = result
            status = summary(manifests, states, started)
            if time.monotonic() - last_log >= 30:
                for name in (manifest["name"] for manifest in manifests):
                    group = status["checkpoints"][name]
                    log(f"progress {name}: {(group['present_bytes'] + group['partial_bytes']) / 2**30:.2f}/{group['total_bytes'] / 2**30:.2f} GiB; {group['verified_files']}/{group['total_files']} verified")
                last_log = time.monotonic()
    return states


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", action="append", choices=CHECKPOINTS)
    parser.add_argument("--all", action="store_true", help="Download both LIBERO and both base checkpoints")
    parser.add_argument("--workers", type=int, choices=range(1, 17), default=4)
    parser.add_argument("--timeout", type=float, default=30, help="Per-request idle timeout in seconds")
    parser.add_argument("--attempts", type=int, default=5)
    parser.add_argument("--chunk-mib", type=int, default=32, help="Bound each HTTP Range request and reconnect slow streams")
    parser.add_argument("--prefer-direct", action="store_true", help="Try scoped proxy bypass first, falling back on slow/error responses")
    parser.add_argument("--parallel-ranges", action="store_true", help="Share workers across disjoint file segments; useful for slow large objects")
    parser.add_argument("--max-seconds", type=float, default=3600, help="Bounded run; re-run to resume")
    parser.add_argument("--manifest-only", action="store_true")
    args = parser.parse_args()
    if args.timeout <= 0 or not 1 <= args.attempts <= 10 or args.max_seconds <= 0 or not 1 <= args.chunk_mib <= 256:
        parser.error("Require timeout/max-seconds >0, attempts in [1,10], chunk-mib in [1,256]")
    (ROOT / "logs").mkdir(exist_ok=True)
    lock = (ROOT / "logs" / "checkpoints-download.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    names = CHECKPOINTS if args.all else tuple(dict.fromkeys(args.checkpoint or CHECKPOINTS[:2]))
    manifests = [make_manifest(name, args) for name in ("tokenizer", *names)]
    if args.manifest_only:
        for manifest in manifests:
            log(f"{manifest['name']}: {len(manifest['objects'])} files, {manifest['total_bytes'] / 2**30:.3f} GiB")
        return 0
    crc = load_crc32c()
    started, deadline, states = now(), time.monotonic() + args.max_seconds, {}
    for manifest in manifests:
        log(f"queued {manifest['name']}: {manifest['total_bytes'] / 2**30:.3f} GiB")
    if args.parallel_ranges:
        states = download_parallel_ranges(manifests, args, crc, deadline, started)
        status = summary(manifests, states, started, finished=True)
        log("All requested objects verified" if status["complete"] else "Download incomplete; re-run the same command to resume")
        return 0 if status["complete"] else 2
    # A shared queue keeps the requested priority order while using spare workers
    # when a checkpoint has fewer remaining objects than available connections.
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(download, item, args, crc, deadline): item
                   for manifest in manifests for item in manifest["objects"]}
        last_log = 0
        while futures:
            done, _ = concurrent.futures.wait(futures, timeout=5, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                item = futures.pop(future)
                try:
                    states[item["name"]] = future.result()
                except Exception as error:
                    states[item["name"]] = {"state": "failed", "error": repr(error)}
            status = summary(manifests, states, started)
            if time.monotonic() - last_log >= 30:
                for name, group in status["checkpoints"].items():
                    log(f"progress {name}: {(group['present_bytes'] + group['partial_bytes']) / 2**30:.2f}/{group['total_bytes'] / 2**30:.2f} GiB; {group['verified_files']}/{group['total_files']} verified")
                last_log = time.monotonic()
    status = summary(manifests, states, started, finished=True)
    log("All requested objects verified" if status["complete"] else "Download incomplete; re-run the same command to resume")
    return 0 if status["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
