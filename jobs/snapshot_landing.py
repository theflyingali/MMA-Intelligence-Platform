"""Databricks job entry point: zip the UFCalendar landing folder into one dated archive.

Writes /Volumes/mma/raw/landing/_snapshots/ufcalendar_<UTC timestamp>.zip so the raw data can be
downloaded as a single file for an offline backup. Read-only on the landing folder; skips the run lock.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime, timezone

SKIP = {"_lock.json"}


def snapshot(source: str, dest_dir: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"{os.path.basename(source.rstrip('/'))}_{stamp}.zip"
    files = 0
    with tempfile.TemporaryDirectory() as tmp:
        local = os.path.join(tmp, name)  # build locally: zip needs seekable output
        with zipfile.ZipFile(local, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for root, dirs, names in os.walk(source):
                dirs.sort()
                for n in sorted(names):
                    if n in SKIP:
                        continue
                    path = os.path.join(root, n)
                    zf.write(path, os.path.relpath(path, os.path.dirname(source.rstrip("/"))))
                    files += 1
        size_mb = os.path.getsize(local) / 1e6
        os.makedirs(dest_dir, exist_ok=True)
        target = os.path.join(dest_dir, name)
        shutil.copyfile(local, target)
    print(f"snapshot {target}: {files} files, {size_mb:.1f} MB")
    return target


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--source", default="/Volumes/mma/raw/landing/ufcalendar")
    p.add_argument("--dest-dir", default="/Volumes/mma/raw/landing/_snapshots")
    a = p.parse_args(argv)
    snapshot(a.source, a.dest_dir)
    return 0


rc = main(sys.argv[1:])
if rc:
    sys.exit(rc)
