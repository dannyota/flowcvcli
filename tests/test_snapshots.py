"""Auto-snapshot before destructive ops + `flowcv backups` listing. Offline:
snapshots write to a temp XDG_STATE_HOME; the destructive API calls are stubbed."""
import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from unittest import mock

from flowcvcli.cli import build_parser, cmd_rm_section, cmd_delete_resume, main
from flowcvcli.errors import ApiError
from flowcvcli.resume import ResumeMixin


class FakeFC(ResumeMixin):
    """Minimal ResumeMixin host: real snapshot/list_backups, stubbed API + auth."""

    def __init__(self, resume, resume_id="R1"):
        self._resume = resume        # a dict, or an Exception to raise on fetch
        self._rid = resume_id
        self.deleted = []            # records destructive API calls, in order

    @property
    def resume_id(self):
        return self._rid

    def get_resume(self):
        if isinstance(self._resume, Exception):
            raise self._resume
        return self._resume

    def delete_section(self, section):
        self.deleted.append(("section", section))
        return {"success": True}

    def delete_resume(self, resume_id=None):
        self.deleted.append(("resume", resume_id))
        return {"success": True}


@contextlib.contextmanager
def state_home(tmp, fc=None):
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.dict(os.environ, {"XDG_STATE_HOME": tmp}, clear=False))
        if fc is not None:
            stack.enter_context(mock.patch("flowcvcli.cli.FlowCV", return_value=fc))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        yield


def parse(argv):
    return build_parser().parse_args(argv)


class SnapshotWriteTest(unittest.TestCase):
    def test_snapshot_writes_content_and_0600(self):
        resume = {"id": "R1", "title": "CV", "content": {"work": {}}}
        fc = FakeFC(resume)
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"XDG_STATE_HOME": tmp}, clear=False):
                path = fc.snapshot()
            self.assertTrue(os.path.exists(path))
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            with open(path) as f:
                self.assertEqual(json.load(f), resume)
            self.assertIn(os.path.join("flowcvcli", "backups"), path)


class DestructiveOpTest(unittest.TestCase):
    def test_rm_section_snapshots_before_deleting(self):
        resume = {"id": "R1", "content": {"work": {}}}
        fc = FakeFC(resume)
        with tempfile.TemporaryDirectory() as tmp:
            with state_home(tmp, fc):
                cmd_rm_section(parse(["rm-section", "work", "--yes"]))
            files = os.listdir(os.path.join(tmp, "flowcvcli", "backups"))
        self.assertEqual(len(files), 1)                 # snapshot written
        self.assertEqual(fc.deleted, [("section", "work")])  # API called after

    def test_delete_resume_snapshots_before_deleting(self):
        fc = FakeFC({"id": "R1"})
        with tempfile.TemporaryDirectory() as tmp:
            with state_home(tmp, fc):
                cmd_delete_resume(parse(["delete-resume", "--yes"]))
            files = os.listdir(os.path.join(tmp, "flowcvcli", "backups"))
        self.assertEqual(len(files), 1)
        self.assertEqual(fc.deleted, [("resume", "R1")])

    def test_snapshot_failure_aborts_the_destructive_op(self):
        fc = FakeFC(ApiError("cannot fetch resume"))
        with tempfile.TemporaryDirectory() as tmp:
            with state_home(tmp, fc):
                with self.assertRaises(ApiError):
                    cmd_rm_section(parse(["rm-section", "work", "--yes"]))
        self.assertEqual(fc.deleted, [])                # API never reached

    def test_no_backup_skips_snapshot_and_still_deletes(self):
        fc = FakeFC(ApiError("would fail if fetched"))  # export must NOT be called
        with tempfile.TemporaryDirectory() as tmp:
            with state_home(tmp, fc):
                cmd_rm_section(parse(["rm-section", "work", "--yes", "--no-backup"]))
            self.assertFalse(os.path.isdir(os.path.join(tmp, "flowcvcli", "backups")))
        self.assertEqual(fc.deleted, [("section", "work")])


class RotationTest(unittest.TestCase):
    def test_keeps_newest_20(self):
        fc = FakeFC({"id": "R1"})
        with tempfile.TemporaryDirectory() as tmp:
            bdir = os.path.join(tmp, "flowcvcli", "backups")
            os.makedirs(bdir, mode=0o700)
            for i in range(1, 26):                      # 25 old snapshots, distinct ts
                open(os.path.join(bdir, f"R1-20200101-{i:06d}.json"), "w").close()
            with mock.patch.dict(os.environ, {"XDG_STATE_HOME": tmp}, clear=False):
                fc.snapshot()                            # writes #26 (current ts), prunes
            files = sorted(os.listdir(bdir))
            self.assertEqual(len(files), 20)
            self.assertNotIn("R1-20200101-000001.json", files)  # oldest pruned
            self.assertIn("R1-20200101-000025.json", files)     # newest old kept


class BackupsListingTest(unittest.TestCase):
    def _make(self, bdir, name):
        os.makedirs(bdir, exist_ok=True)
        with open(os.path.join(bdir, name), "w") as f:
            f.write("{}")

    def test_list_backups_current_vs_all(self):
        fc = FakeFC({"id": "R1"})
        with tempfile.TemporaryDirectory() as tmp:
            bdir = os.path.join(tmp, "flowcvcli", "backups")
            self._make(bdir, "R1-20200101-000001.json")
            self._make(bdir, "R2-20200101-000002.json")
            with mock.patch.dict(os.environ, {"XDG_STATE_HOME": tmp}, clear=False):
                mine = fc.list_backups()
                every = fc.list_backups(all_resumes=True)
        self.assertEqual([os.path.basename(b["path"]) for b in mine],
                         ["R1-20200101-000001.json"])
        self.assertEqual(len(every), 2)
        self.assertEqual(set(mine[0].keys()), {"path", "size", "mtime"})

    def test_backups_command_json_shape(self):
        fc = mock.Mock()
        fc.list_backups.return_value = [
            {"path": "/b/R1-x.json", "size": 12, "mtime": 1.0}]
        out = io.StringIO()
        with mock.patch("flowcvcli.cli.FlowCV", return_value=fc):
            with contextlib.redirect_stdout(out):
                main(["--json", "backups"])
        data = json.loads(out.getvalue().strip())
        self.assertEqual(data, [{"path": "/b/R1-x.json", "size": 12, "mtime": 1.0}])


if __name__ == "__main__":
    unittest.main()
