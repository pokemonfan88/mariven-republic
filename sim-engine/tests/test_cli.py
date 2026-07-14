import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

import engine as engine_module


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def directory_digests(path):
    return {
        item.relative_to(path): digest(item)
        for item in path.rglob("*")
        if item.is_file()
    }


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "sim-engine"
        shutil.copytree(ROOT / "engine", self.root / "engine")
        shutil.copytree(ROOT / "data", self.root / "data")
        shutil.copytree(ROOT / "output", self.root / "output")

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_cli(self, *args):
        return subprocess.run(
            [
                sys.executable,
                "-X",
                "utf8",
                str(self.root / "engine" / "engine.py"),
                *args,
            ],
            cwd=self.root,
            text=True,
            capture_output=True,
            encoding="utf-8",
        )

    def run_cli_with_host_encoding(self, *args):
        return subprocess.run(
            [
                sys.executable,
                str(self.root / "engine" / "engine.py"),
                *args,
            ],
            cwd=self.root,
            text=True,
            capture_output=True,
        )

    def test_dry_run_does_not_modify_runtime_files(self):
        state = self.root / "data" / "state.json"
        database = self.root / "output" / "events.db"
        archive = self.root / "output" / "archive"
        before = (digest(state), digest(database), directory_digests(archive))

        result = self.run_cli("--days", "2", "--dry-run")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            before,
            (digest(state), digest(database), directory_digests(archive)),
        )
        self.assertEqual(result.stdout.count("## "), 2)

    def test_run_days_returns_each_daily_state(self):
        state = json.loads(
            (self.root / "data" / "state.json").read_text(encoding="utf-8")
        )
        original = copy.deepcopy(state)
        resources = engine_module.EngineResources.load(self.root / "data")

        final_state, daily_states = engine_module.run_days(
            state, 2, resources
        )
        repeated = engine_module.run_days(state, 2, resources)

        self.assertEqual(state, original)
        self.assertEqual((final_state, daily_states), repeated)
        self.assertEqual(
            [daily["date"] for daily in daily_states],
            ["2026-08-12", "2026-08-13"],
        )
        self.assertEqual(final_state, daily_states[-1])

    def test_main_does_not_archive_when_run_days_fails(self):
        copied_engine = self.root / "engine" / "engine.py"
        with (
            patch.object(engine_module, "__file__", str(copied_engine)),
            patch.object(
                engine_module,
                "run_days",
                side_effect=RuntimeError("forced model failure"),
            ),
            patch.object(engine_module, "archive_day") as archive,
        ):
            with self.assertRaisesRegex(RuntimeError, "forced model failure"):
                engine_module.main(["--days", "2"])

        archive.assert_not_called()

    def test_dry_run_uses_host_encoding_and_preserves_runtime_files(self):
        state = self.root / "data" / "state.json"
        database = self.root / "output" / "events.db"
        archive = self.root / "output" / "archive"
        before = (digest(state), digest(database), directory_digests(archive))

        result = self.run_cli_with_host_encoding("--dry-run")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("## 2026-08-12 周三", result.stdout)
        self.assertEqual(
            before,
            (digest(state), digest(database), directory_digests(archive)),
        )

    def test_days_defaults_to_one_and_must_be_positive(self):
        default = self.run_cli("--dry-run")
        invalid = self.run_cli("--days", "0", "--dry-run")

        self.assertEqual(default.returncode, 0, default.stderr)
        self.assertEqual(default.stdout.count("## "), 1)
        self.assertNotEqual(invalid.returncode, 0)
        self.assertIn("positive", invalid.stderr)


if __name__ == "__main__":
    unittest.main()
