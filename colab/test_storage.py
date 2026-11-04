"""Offline Drive-storage checks using temporary directories, never user data."""

import importlib.util
import contextlib
import io
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = Path("src/BuiltinExtensions/ComfyUIBackend/CustomWorkflows")


class ColabStorageTests(unittest.TestCase):
    """Check storage preparation against real filesystem behavior."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.mount = self.root / "drive"
        (self.mount / "MyDrive").mkdir(parents=True)
        self.drive = self.mount / "MyDrive" / "Swarm UI"
        self.app = self.root / "local" / "SwarmUI"
        (self.app / WORKFLOW_PATH.parent).mkdir(parents=True)
        helper = ROOT / "colab/prepare-storage.py"
        self.assertTrue(helper.is_file(), "Drive storage preparation is missing")
        spec = importlib.util.spec_from_file_location("prepare_storage", helper)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.environment = patch.dict(os.environ)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def prepare(self):
        """Only the Drive mount itself is simulated; all file operations are real."""
        with patch.object(Path, "is_mount", return_value=True), contextlib.redirect_stdout(io.StringIO()):
            return self.module.prepare_storage(self.app, self.drive, self.mount)

    def test_creates_directories_links_and_local_temp(self):
        storage = self.prepare()
        for folder in ("Stable-Diffusion", "Lora", "VAE", "Embeddings", "controlnet",
                       "model_patches", "text_encoders", "clip", "clip_vision",
                       "diffusion_models", "unet", "upscale_models"):
            self.assertTrue((self.drive / "Models" / folder).is_dir(), folder)
        for local, remote in (("Models", "Models"), ("Output", "Output"),
                              (WORKFLOW_PATH, "Workflows")):
            self.assertTrue((self.app / local).is_symlink())
            self.assertEqual((self.app / local).resolve(), self.drive / remote)
        self.assertTrue((self.drive / "Output/ComfyUI").is_dir())
        self.assertEqual(storage["data"], self.drive / "Data")
        self.assertEqual(os.environ["SWARM_COLAB_DRIVE_ROOT"], str(self.drive))
        self.assertEqual(os.environ.get("PIP_CACHE_DIR"), str(self.drive / "Cache/pip"))
        self.assertTrue((self.drive / "Cache/pip").is_dir())
        self.assertTrue(Path(os.environ["TMPDIR"]).is_dir())
        self.assertFalse(Path(os.environ["TMPDIR"]).is_relative_to(self.mount))

    def test_existing_files_survive_and_repeat_does_not_copy_models(self):
        self.prepare()
        for relative, contents in (("Models/Lora/existing.safetensors", b"model"),
                                   ("Output/existing.png", b"image"),
                                   ("Data/Settings.fds", b"settings"),
                                   ("Workflows/example.json", b"workflow")):
            (self.drive / relative).write_bytes(contents)
        self.prepare()
        (self.app / "Models/Lora/new.safetensors").write_bytes(b"download")
        (self.app / "Output/new.png").write_bytes(b"generated")
        self.assertEqual((self.drive / "Models/Lora/existing.safetensors").read_bytes(), b"model")
        self.assertEqual((self.drive / "Data/Settings.fds").read_bytes(), b"settings")
        self.assertEqual((self.drive / "Workflows/example.json").read_bytes(), b"workflow")
        self.assertEqual((self.drive / "Models/Lora/new.safetensors").read_bytes(), b"download")
        self.assertEqual((self.drive / "Output/new.png").read_bytes(), b"generated")

    def test_new_runtime_reuses_persistent_storage(self):
        self.prepare()
        (self.drive / "Output/previous.png").write_bytes(b"previous session")
        self.app = self.root / "new-runtime/SwarmUI"
        (self.app / WORKFLOW_PATH.parent).mkdir(parents=True)
        self.prepare()
        self.assertEqual((self.app / "Output/previous.png").read_bytes(), b"previous session")

    def test_legacy_workflows_are_used_in_place(self):
        legacy = self.drive / WORKFLOW_PATH
        legacy.mkdir(parents=True)
        (legacy / "old.json").write_bytes(b"legacy workflow")
        storage = self.prepare()
        self.assertEqual(storage["workflows"], legacy)
        self.assertEqual((self.app / WORKFLOW_PATH / "old.json").read_bytes(), b"legacy workflow")
        self.assertFalse((self.drive / "Workflows").exists())

    def test_missing_mount_aborts_without_creating_drive_root(self):
        with patch.object(Path, "is_mount", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "mount"):
                self.module.prepare_storage(self.app, self.drive, self.mount)
        self.assertFalse(self.drive.exists())

    def test_local_conflicts_abort_before_touching_drive(self):
        for local in ("Models", "Output", WORKFLOW_PATH):
            with self.subTest(local=local):
                conflict = self.app / local
                conflict.mkdir()
                marker = conflict / "keep.txt"
                marker.write_bytes(b"keep")
                with self.assertRaisesRegex(RuntimeError, "existing"):
                    self.prepare()
                self.assertEqual(marker.read_bytes(), b"keep")
                self.assertFalse(self.drive.exists())
                marker.unlink()
                conflict.rmdir()

    def test_wrong_symlink_aborts_without_replacing_it(self):
        wrong = self.root / "other-models"
        wrong.mkdir()
        (self.app / "Models").symlink_to(wrong, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "existing"):
            self.prepare()
        self.assertEqual((self.app / "Models").resolve(), wrong)
        self.assertFalse(self.drive.exists())

    def test_storage_root_must_be_on_drive_and_program_must_be_local(self):
        for app, drive in ((self.app, self.root / "outside-drive"),
                           (self.mount / "MyDrive/local-program", self.drive)):
            with self.subTest(app=app, drive=drive):
                with patch.object(Path, "is_mount", return_value=True):
                    with self.assertRaises(RuntimeError):
                        self.module.prepare_storage(app, drive, self.mount)
        self.assertFalse(self.drive.exists())

    def test_write_failure_does_not_create_local_fallback(self):
        with patch.object(self.module.tempfile, "NamedTemporaryFile", side_effect=PermissionError("read-only")):
            with self.assertRaisesRegex(RuntimeError, "writ"):
                self.prepare()
        self.assertFalse((self.app / "Models").exists())
        self.assertFalse((self.app / "Output").exists())

    def test_existing_drive_file_is_not_replaced_with_a_directory(self):
        self.drive.mkdir(parents=True)
        (self.drive / "Data").write_bytes(b"existing file")
        with self.assertRaisesRegex(RuntimeError, "existing file"):
            self.prepare()
        self.assertEqual((self.drive / "Data").read_bytes(), b"existing file")
        self.assertFalse((self.drive / "Models").exists())

    def test_existing_drive_symlink_cannot_redirect_models_outside_root(self):
        self.drive.mkdir(parents=True)
        outside = self.root / "outside-models"
        outside.mkdir()
        (outside / "keep.txt").write_bytes(b"keep")
        (self.drive / "Models").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "escapes"):
            self.prepare()
        self.assertEqual((outside / "keep.txt").read_bytes(), b"keep")
        self.assertFalse((self.drive / "Output").exists())

    def test_fresh_runtime_installs_backend_even_with_persistent_settings(self):
        self.assertTrue(hasattr(self.module, "prepare_backend"), "Local backend preparation is missing")
        storage = self.prepare()
        (storage["data"] / "Settings.fds").write_text("IsInstalled: true\n")
        with patch.object(self.module, "run_logged") as run:
            self.module.prepare_backend(self.app)
        self.assertEqual(run.call_args.args[0], ["bash", "launchtools/comfy-install-linux.sh", "nv"])
        self.assertEqual(run.call_args.kwargs["cwd"], self.app)

    def test_existing_backend_restores_dependencies_and_propagates_failure(self):
        self.assertTrue(hasattr(self.module, "prepare_backend"), "Local backend preparation is missing")
        backend = self.app / "dlbackend/ComfyUI"
        backend.mkdir(parents=True)
        (backend / "main.py").write_text("")
        requirements = backend / "requirements.txt"
        requirements.write_text("")
        with patch.object(self.module, "run_logged", side_effect=subprocess.CalledProcessError(1, "pip")) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                self.module.prepare_backend(self.app)
        self.assertEqual(run.call_args.args[0], [sys.executable, "-s", "-m", "pip", "install", "-r", str(requirements)])
        self.assertEqual(run.call_args.kwargs["cwd"], self.app)


if __name__ == "__main__":
    unittest.main()
