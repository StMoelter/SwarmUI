"""Keep Colab's working GPU and numerical packages during SwarmUI installation."""

import importlib.metadata
import os
from pathlib import Path
import re
import subprocess
import sys


PROTECTED_PACKAGES = {
    "torch", "torchvision", "torchaudio", "numpy", "numba", "llvmlite", "pillow",
    "opencv-python", "opencv-contrib-python", "opencv-python-headless", "triton",
}


def protect_packages(constraints_path):
    """Capture preinstalled versions once, and reject changes to that baseline."""
    installed = {}
    for distribution in importlib.metadata.distributions():
        name = re.sub(r"[-_.]+", "-", distribution.metadata["Name"]).lower()
        if name in PROTECTED_PACKAGES or name.startswith(("nvidia-", "pytorch-triton")):
            installed[name] = distribution.version
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


def prepare_environment():
    """Validate notebook Python and configure inherited protection for all pip calls."""
    print(f"Colab Python: {sys.executable} ({sys.version.split()[0]})", flush=True)
    subprocess.run([
        sys.executable, "-s", "-c",
        "import torch, torchvision; "
        "print('PyTorch:', torch.__version__, 'CUDA:', torch.version.cuda); "
        "assert torch.cuda.is_available(), "
        "'No usable CUDA GPU. Select a GPU runtime in Colab before starting SwarmUI.'",
    ], check=True)
    constraints_path = Path("/content/swarm-colab/constraints.txt")
    protect_packages(constraints_path)
    baseline_check = constraints_path.with_name("pip-check-before.txt")
    if not baseline_check.exists():
        check = subprocess.run([sys.executable, "-s", "-m", "pip", "check"],
                               text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        baseline_check.write_text(check.stdout, encoding="utf-8")
    os.environ["SWARM_COLAB_MODE"] = "true"
    os.environ["SWARM_COLAB_PYTHON"] = sys.executable
    os.environ["SWARM_NO_VENV"] = "true"
    os.environ["PIP_CONSTRAINT"] = str(constraints_path)
    print(f"Protected Colab packages ({constraints_path}):\n"
          f"{constraints_path.read_text(encoding='utf-8')}", flush=True)


if __name__ == "__main__":
    prepare_environment()
