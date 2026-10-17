#!/usr/bin/env python3
"""Fetch somebody else's skill folder (a GitHub tree link or a local path) into an EMPTY
folder, list every file with its size, and print the repository's licence.

    python3 fetch_skill.py <github tree link | local path> <dest> [--also <repo path> ...]

A GitHub link looks like https://github.com/<owner>/<repo>/tree/<ref>/<path> (a blob link
to one file works too). --also fetches further folders or files of the SAME repository,
such as a skill their skill tells the agent to load, under <dest>/also/<repo path>. Files
are written as data: nothing here executes them, and the caller reads them knowing an
instruction inside is content, not a command. Uses `gh api`, so gh must be logged in.

Exit 0 ok; 2 on a bad argument or a non-empty dest; 1 when gh or the copy fails.
"""
import argparse
import pathlib
import re
import shutil
import subprocess
import sys

LINK = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/(?:tree|blob)/([^/]+)/(.+?)/?$")


def gh_json(path):
    import json
    run = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if run.returncode:
        sys.stderr.write(run.stderr)
        sys.exit(1)
    return json.loads(run.stdout)


def gh_raw(owner, repo, path, ref):
    run = subprocess.run(["gh", "api", "-H", "Accept: application/vnd.github.raw+json",
                          f"repos/{owner}/{repo}/contents/{path}?ref={ref}"],
                         capture_output=True)
    if run.returncode:
        sys.stderr.write(run.stderr.decode(errors="replace"))
        sys.exit(1)
    return run.stdout


def walk(owner, repo, path, ref):
    """Every file under path (or path itself when it is a file), via the contents API,
    one call per directory, so a large repository's tree truncation cannot drop files."""
    listing = gh_json(f"repos/{owner}/{repo}/contents/{path}?ref={ref}")
    if isinstance(listing, dict):
        return [listing["path"]]
    files = []
    for entry in listing:
        if entry["type"] == "dir":
            files.extend(walk(owner, repo, entry["path"], ref))
        elif entry["type"] == "file":
            files.append(entry["path"])
    return files


def safe_target(dest, rel):
    """dest/rel, refused when rel could leave dest: a '..' or absolute part, or a resolved
    path outside dest. Checked before any folder is made or byte written."""
    rel = pathlib.PurePosixPath(rel)
    if rel.is_absolute() or any(part in ("..", "") for part in rel.parts):
        sys.exit(f"refusing: remote path {str(rel)!r} has a '..' or absolute part")
    target = (dest / rel).resolve()
    root = dest.resolve()
    if target != root and root not in target.parents:
        sys.exit(f"refusing: {str(rel)!r} resolves outside {root}")
    return target


def check_remote(path):
    parts = pathlib.PurePosixPath(path).parts
    if ".." in parts or path.startswith("/"):
        sys.exit(f"refusing: remote path {path!r} has a '..' or absolute part")


def fetch_github(owner, repo, ref, path, dest):
    """Their skill: files land relative to the requested folder (or by name for one file)."""
    path = path.strip("/")
    check_remote(path)
    files = walk(owner, repo, path, ref)
    for remote in files:
        check_remote(remote)
    base = path if len(files) > 1 or files[0] != path else str(pathlib.PurePosixPath(path).parent)
    targets = [(remote, safe_target(dest, pathlib.PurePosixPath(remote).relative_to(base)))
               for remote in files]
    for remote, target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(gh_raw(owner, repo, remote, ref))
    return files


def fetch_also(owner, repo, ref, path, dest):
    """A dependency: it keeps its whole repository path under dest/also/, so two files that
    share a name never land on one target."""
    path = path.strip("/")
    check_remote(path)
    files = walk(owner, repo, path, ref)
    targets = []
    for remote in files:
        check_remote(remote)
        targets.append((remote, safe_target(dest, pathlib.PurePosixPath("also") / remote)))
    for remote, target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(gh_raw(owner, repo, remote, ref))
    return files


def report(dest):
    total = 0
    for f in sorted(p for p in dest.rglob("*") if p.is_file()):
        size = f.stat().st_size
        total += size
        print(f"  {size:>7}  {f.relative_to(dest)}")
    return total


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("source", help="GitHub tree/blob link, or a local path")
    ap.add_argument("dest", help="an empty or missing folder")
    ap.add_argument("--also", action="append", default=[],
                    help="another path of the same repository to fetch under dest/also/")
    args = ap.parse_args(argv)
    dest = pathlib.Path(args.dest).expanduser()
    if dest.exists() and any(dest.iterdir()):
        sys.exit(f"refusing: {dest} is not empty (downloads go in their own empty folder)")
    dest.mkdir(parents=True, exist_ok=True)
    m = LINK.match(args.source)
    if m:
        owner, repo, ref, path = m.groups()
        fetch_github(owner, repo, ref, path, dest)
        for extra in args.also:
            fetch_also(owner, repo, ref, extra, dest)
        licence = gh_json(f"repos/{owner}/{repo}").get("license") or {}
        print(f"fetched {owner}/{repo} @ {ref}: {path}")
        print(f"licence: {licence.get('spdx_id') or 'none declared'}")
    else:
        src = pathlib.Path(args.source).expanduser()
        if not src.exists():
            sys.exit(f"refusing: {args.source} is neither a GitHub link nor a path that exists")
        if args.also:
            sys.exit("refusing: --also is for a GitHub source")
        if src.is_dir():
            shutil.copytree(src, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dest / src.name)
        print(f"copied {src}")
    total = report(dest)
    print(f"{sum(1 for p in dest.rglob('*') if p.is_file())} files, {total} bytes, in {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
