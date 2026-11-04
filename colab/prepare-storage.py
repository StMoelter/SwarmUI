"""Connect a local Colab checkout to persistent SwarmUI storage on mounted Drive."""

import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time


MODEL_FOLDERS = (
    "Stable-Diffusion", "Lora", "VAE", "Embeddings", "controlnet", "model_patches",
    "text_encoders", "clip", "clip_vision", "diffusion_models", "unet", "upscale_models",
)
WORKFLOW_PATH = Path("src/BuiltinExtensions/ComfyUIBackend/CustomWorkflows")


def run_logged(command, cwd=None):
    """Forward child stdout/stderr live through Python so notebook users can see them."""
    environment = dict(os.environ, PYTHONUNBUFFERED="1")
    process = subprocess.Popen(command, cwd=cwd, env=environment, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1,
                               start_new_session=os.name == "posix")
    try:
        for line in process.stdout:
            print(line, end="", flush=True)
        exit_code = process.wait()
    except BaseException:
        # Stopping a notebook cell must also stop its installer/server and child processes.
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        else:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            process.wait()
        if os.name == "posix":
            # The launcher may have exited before a descendant that ignored SIGTERM.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        raise
    finally:
        process.stdout.close()
    if exit_code != 0:
        raise subprocess.CalledProcessError(exit_code, command)


def prepare_storage(app_dir, drive_root, mountpoint):
    """Create missing directories and links, preserving all existing user content."""
    app_dir = Path(app_dir).resolve()
    mountpoint = Path(mountpoint).resolve()
    if not mountpoint.is_mount() or not (mountpoint / "MyDrive").is_dir():
        raise RuntimeError("Google Drive is not mounted. Run the Drive mount cell first.")
    drive_root = Path(drive_root).resolve()
    if not drive_root.is_relative_to(mountpoint) or drive_root == mountpoint:
        raise RuntimeError("The storage root must be inside mounted Google Drive.")
    if app_dir.is_relative_to(mountpoint):
        raise RuntimeError("The SwarmUI program must be installed locally, outside Google Drive.")
    legacy_workflows = drive_root / WORKFLOW_PATH
    workflows = legacy_workflows if legacy_workflows.is_dir() else drive_root / "Workflows"
    storage = {
        "models": drive_root / "Models",
        "output": drive_root / "Output",
        "data": drive_root / "Data",
        "workflows": workflows,
        "pip_cache": drive_root / "Cache/pip",
    }
    links = {app_dir / "Models": storage["models"],
             app_dir / "Output": storage["output"],
             app_dir / WORKFLOW_PATH: workflows}
    # Check all conflicts before creating anything on Drive or replacing local links.
    for local, target in links.items():
        if local.is_symlink() and local.resolve() == target.resolve():
            continue
        if local.exists() or local.is_symlink():
            raise RuntimeError(f"Refusing to replace existing local path: {local}. "
                               "Use a clean local checkout or resolve the path conflict first.")
    folders = list(storage.values()) + [storage["models"] / folder for folder in MODEL_FOLDERS]
    folders.append(storage["output"] / "ComfyUI")
    for folder in folders:
        if not folder.resolve().is_relative_to(drive_root):
            raise RuntimeError(f"Drive storage path escapes the selected root: {folder}")
        if folder.exists() and not folder.is_dir():
            raise RuntimeError(f"Expected a directory, but found an existing file: {folder}")
    try:
        for folder in folders:
            folder.mkdir(parents=True, exist_ok=True)
        # Probe each destination, not just the parent: existing subfolders may be read-only.
        for folder in storage.values():
            with tempfile.NamedTemporaryFile(prefix=".swarm-write-check-", dir=folder):
                pass
    except OSError as error:
        raise RuntimeError(f"Cannot write SwarmUI storage on Google Drive: {error}") from error
    for local, target in links.items():
        if not local.is_symlink():
            local.parent.mkdir(parents=True, exist_ok=True)
            local.symlink_to(target, target_is_directory=True)
    temporary = app_dir.parent / "swarm-colab" / "tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    os.environ["TMPDIR"] = str(temporary)
    os.environ["SWARM_COLAB_DRIVE_ROOT"] = str(drive_root)
    os.environ["PIP_CACHE_DIR"] = str(storage["pip_cache"])
    for name, path in storage.items():
        print(f"Drive {name}: {path}", flush=True)
    print(f"Local program: {app_dir}\nLocal temporary files: {temporary}", flush=True)
    return storage


def prepare_backend(app_dir):
    """Provision local ComfyUI even when Drive settings say SwarmUI is already installed."""
    app_dir = Path(app_dir).resolve()
    backend = app_dir / "dlbackend/ComfyUI"
    started = time.monotonic()
    if not (backend / "main.py").is_file():
        print("Installing the local ComfyUI backend (keeping Colab's PyTorch/CUDA)...", flush=True)
        run_logged(["bash", "launchtools/comfy-install-linux.sh", "nv"], cwd=app_dir)
    else:
        print("Checking local ComfyUI dependencies (reusing installed packages)...", flush=True)
        run_logged([sys.executable, "-s", "-m", "pip", "install", "-r", str(backend / "requirements.txt")],
                   cwd=app_dir)
    print(f"Local ComfyUI preparation finished in {time.monotonic() - started:.1f} seconds.", flush=True)
