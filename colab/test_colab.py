"""Offline regression checks: python3 -m unittest discover -s colab -p 'test_*.py'."""

import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]


class ColabEnvironmentTests(unittest.TestCase):
    """Check baseline preservation without installing packages or using a GPU."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        helper = ROOT / "colab" / "prepare-colab.py"
        self.assertTrue(helper.is_file(), "Colab environment preparation is missing")
        spec = importlib.util.spec_from_file_location("prepare_colab", helper)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def distributions(self, packages):
        """Use real distribution metadata with controlled installed versions."""
        result = []
        for name, version in packages.items():
            directory = self.directory / f"{name}-{version}.dist-info"
            directory.mkdir(exist_ok=True)
            (directory / "METADATA").write_text(
                f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
                encoding="utf-8",
            )
            result.append(importlib.metadata.Distribution.at(directory))
        return result

    def test_capture_protects_base_packages_but_not_unrelated_packages(self):
        packages = self.distributions({
            "torch": "2.8.0+cu126", "torchvision": "0.23.0+cu126",
            "NumPy": "2.4.6", "numba": "0.60.0", "llvmlite": "0.43.0",
            "Pillow": "11.3.0", "opencv_python": "4.12.0.88",
            "opencv-contrib-python": "4.12.0.88",
            "opencv-python-headless": "4.12.0.88", "torchaudio": "2.8.0",
            "nvidia_cublas_cu12": "12.6.4.1", "triton": "3.4.0",
            "requests": "2.32.5",
        })
        constraints = self.directory / "constraints.txt"
        with patch.object(self.module.importlib.metadata, "distributions", return_value=packages):
            self.module.protect_packages(constraints)
        self.assertEqual(set(constraints.read_text().splitlines()), {
            "torch==2.8.0+cu126", "torchvision==0.23.0+cu126",
            "numpy==2.4.6", "numba==0.60.0", "llvmlite==0.43.0",
            "pillow==11.3.0", "opencv-python==4.12.0.88",
            "opencv-contrib-python==4.12.0.88", "opencv-python-headless==4.12.0.88",
            "torchaudio==2.8.0", "nvidia-cublas-cu12==12.6.4.1", "triton==3.4.0",
        })

    def test_repeated_preparation_keeps_original_baseline(self):
        constraints = self.directory / "constraints.txt"
        packages = self.distributions({"numpy": "2.4.6"})
        with patch.object(self.module.importlib.metadata, "distributions", return_value=packages):
            self.module.protect_packages(constraints)
            self.module.protect_packages(constraints)
        baseline = constraints.read_bytes()
        for installed in ({"numpy": "2.5.0"}, {}):
            with self.subTest(installed=installed):
                changed = self.distributions(installed)
                with patch.object(self.module.importlib.metadata, "distributions", return_value=changed):
                    with self.assertRaisesRegex(RuntimeError, "numpy"):
                        self.module.protect_packages(constraints)
                self.assertEqual(constraints.read_bytes(), baseline)

    def test_duplicate_metadata_does_not_pin_shadowed_numpy(self):
        current = self.distributions({"numpy": "2.4.6"})
        shadowed = self.distributions({"numpy": "1.26.4"})
        constraints = self.directory / "constraints.txt"
        with patch.object(self.module.importlib.metadata, "distributions", return_value=current + shadowed):
            self.module.protect_packages(constraints)
        self.assertEqual(constraints.read_text(), "numpy==2.4.6\n")

    def test_numpy_126_is_rejected_on_python313_before_installing(self):
        packages = self.distributions({"numpy": "1.26.4"})
        constraints = self.directory / "constraints.txt"
        with patch.object(self.module.importlib.metadata, "distributions", return_value=packages), \
                patch.object(self.module.sys, "version_info", (3, 13, 16)):
            with self.assertRaisesRegex(RuntimeError, "fresh"):
                self.module.protect_packages(constraints)
        self.assertFalse(constraints.exists())

    def test_numpy_126_remains_supported_on_python312(self):
        packages = self.distributions({"numpy": "1.26.4"})
        constraints = self.directory / "constraints.txt"
        with patch.object(self.module.importlib.metadata, "distributions", return_value=packages), \
                patch.object(self.module.sys, "version_info", (3, 12, 10)):
            self.module.protect_packages(constraints)
        self.assertEqual(constraints.read_text(), "numpy==1.26.4\n")

    def test_inventory_uses_fresh_python_and_actual_numpy_not_stale_metadata(self):
        """Reproduce stale metadata with a real subprocess and a tiny importable package."""
        self.distributions({"numpy": "1.26.4"})
        numpy = self.directory / "numpy"
        numpy.mkdir()
        (numpy / "__init__.py").write_text("__version__ = '2.4.6'\n")
        environment = dict(os.environ, PYTHONPATH=str(self.directory))
        result = subprocess.run([sys.executable, "-s", str(ROOT / "colab/prepare-colab.py"), "--inventory"],
                                env=environment, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["numpy"], "2.4.6")

    def test_preparation_exports_protection_and_preserves_diagnostics(self):
        constraints = self.directory / "constraints.txt"
        packages = self.distributions({"torch": "2.8.0", "numpy": "2.4.6"})
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(self.module.importlib.metadata, "distributions", return_value=packages), \
                    patch.object(self.module.subprocess, "run", side_effect=[
                        subprocess.CompletedProcess([], 0),
                        subprocess.CompletedProcess([], 0),
                        subprocess.CompletedProcess([], 0, stdout='{"torch":"2.8.0","numpy":"2.4.6"}'),
                        subprocess.CompletedProcess([], 1, stdout="Existing unrelated conflict\n"),
                        subprocess.CompletedProcess([], 0),
                        subprocess.CompletedProcess([], 0),
                        subprocess.CompletedProcess([], 0, stdout='{"torch":"2.8.0","numpy":"2.4.6"}'),
                    ]):
                self.module.prepare_environment(constraints)
                self.module.prepare_environment(constraints)
            self.assertEqual(os.environ["SWARM_COLAB_MODE"], "true")
            self.assertEqual(os.environ["SWARM_COLAB_PYTHON"], sys.executable)
            self.assertEqual(os.environ["PIP_CONSTRAINT"], str(constraints))
            self.assertEqual(os.environ["SWARM_NO_VENV"], "true")
            self.assertEqual(os.environ["PIP_ONLY_BINARY"], ":all:")
            self.assertEqual(constraints.with_name("pip-check-before.txt").read_text(),
                             "Existing unrelated conflict\n")

    def test_gpu_failure_does_not_capture_an_unusable_baseline(self):
        constraints = self.directory / "constraints.txt"
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(self.module.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "GPU check")):
                with self.assertRaises(subprocess.CalledProcessError):
                    self.module.prepare_environment(constraints)
            self.assertNotIn("SWARM_COLAB_MODE", os.environ)
        self.assertFalse(constraints.exists())

    def test_missing_notebook_pip_fails_before_baseline_is_captured(self):
        constraints = self.directory / "constraints.txt"
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(self.module.subprocess, "run", side_effect=[
                        subprocess.CompletedProcess([], 0),
                        subprocess.CalledProcessError(1, "notebook pip check"),
                    ]):
                with self.assertRaises(subprocess.CalledProcessError):
                    self.module.prepare_environment(constraints)
            self.assertNotIn("SWARM_COLAB_MODE", os.environ)
        self.assertFalse(constraints.exists())

    def test_real_pip_rejects_dependency_that_would_replace_protected_numpy(self):
        """Resolve local wheels only; never install packages or access the network."""
        for name, version, requires in (
            ("numpy", "2.4.6", ""), ("numpy", "2.5.0", ""),
            ("swarm_colab_probe", "1.0.0", "Requires-Dist: numpy>=2.5\n"),
        ):
            dist_info = f"{name}-{version}.dist-info"
            with zipfile.ZipFile(self.directory / f"{name}-{version}-py3-none-any.whl", "w") as wheel:
                wheel.writestr(f"{dist_info}/METADATA",
                              f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n{requires}")
                wheel.writestr(f"{dist_info}/WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
                wheel.writestr(f"{dist_info}/RECORD", "")
        constraints = self.directory / "constraints.txt"
        packages = self.distributions({"numpy": "2.4.6"})
        with patch.object(self.module.importlib.metadata, "distributions", return_value=packages):
            self.module.protect_packages(constraints)
        command = [sys.executable, "-m", "pip", "install", "--dry-run", "--ignore-installed",
                   "--no-index", "--find-links", str(self.directory), "--target",
                   str(self.directory / "unused-target"), "swarm-colab-probe"]
        env = dict(os.environ)
        env.pop("PIP_CONSTRAINT", None)
        env.pop("PIP_REQUIREMENT", None)
        unconstrained = subprocess.run(command, env=env, text=True, capture_output=True)
        self.assertEqual(unconstrained.returncode, 0, unconstrained.stderr)
        env["PIP_CONSTRAINT"] = str(constraints)
        constrained = subprocess.run(command, env=env, text=True, capture_output=True)
        self.assertNotEqual(constrained.returncode, 0)
        self.assertIn("ResolutionImpossible", constrained.stderr)
        self.assertEqual(constraints.read_text(), "numpy==2.4.6\n")
        self.assertFalse((self.directory / "unused-target").exists())


class ColabInstallerTests(unittest.TestCase):
    """Exercise the real installer with network and Python execution replaced."""

    def run_installer(self, colab=True, gpu_ok=True, pip_ok=True, constraints=True, preexisting=False):
        """Return the exit status and calls without downloading or installing anything."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            calls = root / "calls"
            fake_python = bin_dir / "notebook-python"
            fake_python.write_text(
                '#!/bin/bash\nprintf "%s\\n" "$*" >> "$CALLS"\n'
                'if [[ "$*" == *"-m pip"* ]]; then exit "$PIP_STATUS"; fi\n'
                'exit "$GPU_STATUS"\n'
            )
            fake_python.chmod(0o755)
            (bin_dir / "python3.11").symlink_to(fake_python)
            (bin_dir / "git").write_text('#!/bin/bash\nif [ -d ComfyUI ]; then exit 128; fi\nmkdir -p ComfyUI/.git\ntouch ComfyUI/requirements.txt\n')
            (bin_dir / "git").chmod(0o755)
            if preexisting:
                (root / "dlbackend/ComfyUI/.git").mkdir(parents=True)
                (root / "dlbackend/ComfyUI/requirements.txt").write_text("")
            constraint_file = root / "constraints.txt"
            if constraints:
                constraint_file.write_text("torch==2.8.0\n")
            env = dict(os.environ)
            for name in ("SWARM_COLAB_MODE", "SWARM_COLAB_PYTHON", "PIP_CONSTRAINT"):
                env.pop(name, None)
            env.update(PATH=f"{bin_dir}{os.pathsep}{env['PATH']}", SWARM_NO_VENV="true",
                       CALLS=str(calls), GPU_STATUS="0" if gpu_ok else "1",
                       PIP_STATUS="0" if pip_ok else "1")
            if colab:
                env.update(SWARM_COLAB_MODE="true", SWARM_COLAB_PYTHON=str(fake_python),
                           PIP_CONSTRAINT=str(constraint_file))
            result = subprocess.run(["bash", str(ROOT / "launchtools/comfy-install-linux.sh"), "nv"],
                                    cwd=root, env=env, text=True, capture_output=True)
            return result, calls.read_text().splitlines() if calls.exists() else []

    def test_colab_keeps_torch_and_installs_requirements(self):
        result, calls = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any("-m pip install -r requirements.txt" in call for call in calls))
        self.assertFalse(any("--index-url" in call for call in calls), calls)

    def test_colab_gpu_failure_stops_before_pip(self):
        result, calls = self.run_installer(gpu_ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("-m pip" in call for call in calls), calls)

    def test_colab_missing_constraints_stops_before_pip(self):
        result, calls = self.run_installer(constraints=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("-m pip" in call for call in calls), calls)

    def test_colab_pip_failure_is_not_reported_as_success(self):
        result, calls = self.run_installer(pip_ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Installation completed", result.stdout)

    def test_colab_reuses_backend_checkout_after_a_failed_install(self):
        result, calls = self.run_installer(preexisting=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any("-m pip install -r requirements.txt" in call for call in calls))

    def test_normal_install_keeps_existing_torch_installation_behavior(self):
        result, calls = self.run_installer(colab=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any("--index-url https://download.pytorch.org/whl/cu130" in call for call in calls))


if __name__ == "__main__":
    unittest.main()
