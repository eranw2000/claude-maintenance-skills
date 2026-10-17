#!/usr/bin/env python3
"""Offline tests for fetch_skill.py: where each remote file lands. gh is replaced by fakes,
so no network.

    python3 test_fetch_skill.py
"""
import importlib.util
import pathlib
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("fs", HERE / "fetch_skill.py")
fs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fs)


class FakeRepo:
    """A remote tree: {path: bytes}. walk() and gh_raw() read it."""

    def __init__(self, files):
        self.files = files

    def walk(self, owner, repo, path, ref):
        if path in self.files:
            return [path]
        return [p for p in self.files if p.startswith(path.rstrip("/") + "/")]

    def raw(self, owner, repo, path, ref):
        return self.files[path]


def run(files, path, dest, also=False):
    fake = FakeRepo(files)
    old = fs.walk, fs.gh_raw
    fs.walk, fs.gh_raw = fake.walk, fake.raw
    try:
        if also:
            return fs.fetch_also("o", "r", "main", path, dest)
        return fs.fetch_github("o", "r", "main", path, dest)
    finally:
        fs.walk, fs.gh_raw = old


class Targets(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.dest = self.tmp / "a" / "theirs"  # ../../ from here is still inside self.tmp
        self.dest.mkdir(parents=True)

    def test_folder_with_subfolders_keeps_its_layout(self):
        run({"skills/x/SKILL.md": b"a", "skills/x/agents/o.yaml": b"b"}, "skills/x", self.dest)
        self.assertEqual((self.dest / "SKILL.md").read_bytes(), b"a")
        self.assertEqual((self.dest / "agents/o.yaml").read_bytes(), b"b")

    def test_single_file_blob_lands_by_its_name(self):
        run({"skills/x/SKILL.md": b"a"}, "skills/x/SKILL.md", self.dest)
        self.assertEqual((self.dest / "SKILL.md").read_bytes(), b"a")

    def test_parent_traversal_is_refused_and_nothing_escapes(self):
        files = {"skills/x/SKILL.md": b"a", "skills/x/../../escape.md": b"evil"}
        with self.assertRaises(SystemExit) as ctx:
            run(files, "skills/x", self.dest)
        self.assertIn("..", str(ctx.exception))
        self.assertEqual([f for f in self.tmp.rglob("*") if f.is_file()], [])

    def test_control_a_dotted_name_is_not_traversal(self):
        run({"skills/x/a..b.md": b"ok"}, "skills/x", self.dest)
        self.assertEqual((self.dest / "a..b.md").read_bytes(), b"ok")

    def test_two_also_files_with_one_name_both_survive(self):
        files = {"skills/a/reference/checklist.md": b"A", "skills/b/reference/checklist.md": b"B"}
        run(files, "skills/a/reference/checklist.md", self.dest, also=True)
        run(files, "skills/b/reference/checklist.md", self.dest, also=True)
        self.assertEqual((self.dest / "also/skills/a/reference/checklist.md").read_bytes(), b"A")
        self.assertEqual((self.dest / "also/skills/b/reference/checklist.md").read_bytes(), b"B")

    def test_also_folder_with_trailing_slash_keeps_its_repo_path(self):
        files = {"skills/p/w/SKILL.md": b"w"}
        run(files, "skills/p/w/", self.dest, also=True)
        self.assertEqual((self.dest / "also/skills/p/w/SKILL.md").read_bytes(), b"w")

    def test_also_with_parent_traversal_is_refused(self):
        with self.assertRaises(SystemExit):
            run({"../x.md": b"evil"}, "../x.md", self.dest, also=True)
        self.assertFalse((self.dest / "x.md").exists())


if __name__ == "__main__":
    unittest.main(verbosity=1)
