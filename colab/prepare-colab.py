"""Keep Colab's working GPU and numerical packages during SwarmUI installation."""

import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys


PROTECTED_PACKAGES = {
    "torch", "torchvision", "torchaudio", "numpy", "numba", "llvmlite", "pillow",
    "opencv-python", "opencv-contrib-python", "opencv-python-headless", "triton",
}


def protected_versions():
    """Use the first visible metadata record rather than overwriting it with shadowed copies."""
    installed = {}
    for distribution in importlib.metadata.distributions():
        name = re.sub(r"[-_.]+", "-", distribution.metadata["Name"]).lower()
        if name in PROTECTED_PACKAGES or name.startswith(("nvidia-", "pytorch-triton")):
            installed.setdefault(name, distribution.version)
    return installed


def capture_inventory():
    """Read effective versions in a fresh notebook Python, including the actual NumPy module."""
    installed = protected_versions()
    installed["numpy"] = importlib.import_module("numpy").__version__
    return installed


def protect_packages(constraints_path, installed=None):
    """Capture preinstalled versions once, and reject changed or incompatible baselines."""
    if installed is None:
        installed = protected_versions()
    numpy_version = re.match(r"(\d+)\.(\d+)", installed.get("numpy", ""))
    if sys.version_info[:2] >= (3, 13) and numpy_version and tuple(map(int, numpy_version.groups())) < (2, 1):
        raise RuntimeError(
            f"NumPy {installed['numpy']} is incompatible with this Python version. "
            "Start a fresh Colab GPU runtime; the previous runtime's NumPy may have been downgraded. "
            "No package installation has been started."
        )
    if constraints_path.exists():
        for line in constraints_path.read_text(encoding="utf-8").splitlines():
            name, version = line.split("==", 1)
            if installed.get(name) != version:
                raise RuntimeError(
                    f"Colab baseline changed: {name} must remain {version}, "
                    f"but is now {installed.get(name, 'missing')}. "
                    "Start a fresh Colab runtime and run the notebook again."
                )
    else:
        constraints_path.parent.mkdir(parents=True, exist_ok=True)
        constraints_path.write_text(
            "".join(f"{name}=={installed[name]}\n" for name in sorted(installed)),
            encoding="utf-8",
        )


def prepare_environment(constraints_path=None):
    """Validate notebook Python and configure inherited protection for all pip calls."""
    print(f"Colab Python: {sys.executable} ({sys.version.split()[0]})", flush=True)
    subprocess.run([
        sys.executable, "-s", "-c",
        "import torch, torchvision; "
        "print('PyTorch:', torch.__version__, 'CUDA:', torch.version.cuda); "
        "assert torch.cuda.is_available(), "
        "'No usable CUDA GPU. Select a GPU runtime in Colab before starting SwarmUI.'",
    ], check=True)
    print("Checking pip with the notebook Python...", flush=True)
    subprocess.run([sys.executable, "-s", "-m", "pip", "--version"], check=True)
    inventory = subprocess.run([sys.executable, "-s", str(Path(__file__).resolve()), "--inventory"],
                               text=True, capture_output=True, check=True)
    if constraints_path is None:
        constraints_path = Path("/content/swarm-colab/constraints.txt")
    protect_packages(constraints_path, json.loads(inventory.stdout))
    baseline_check = constraints_path.with_name("pip-check-before.txt")
    if not baseline_check.exists():
        check = subprocess.run([sys.executable, "-s", "-m", "pip", "check"],
                               text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        baseline_check.write_text(check.stdout, encoding="utf-8")
    os.environ["SWARM_COLAB_MODE"] = "true"
    os.environ["SWARM_COLAB_PYTHON"] = sys.executable
    os.environ["SWARM_NO_VENV"] = "true"
    os.environ["PIP_CONSTRAINT"] = str(constraints_path)
    os.environ["PIP_ONLY_BINARY"] = ":all:"
    print(f"Protected Colab packages ({constraints_path}):\n"
          f"{constraints_path.read_text(encoding='utf-8')}", flush=True)


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--inventory":
        print(json.dumps(capture_inventory()))
    else:
        prepare_environment()
