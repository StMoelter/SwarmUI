"""Connect a local Colab checkout to persistent SwarmUI storage on mounted Drive."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile


MODEL_FOLDERS = (
    "Stable-Diffusion", "Lora", "VAE", "Embeddings", "controlnet", "model_patches",
    "text_encoders", "clip", "clip_vision", "diffusion_models", "unet", "upscale_models",
)
WORKFLOW_PATH = Path("src/BuiltinExtensions/ComfyUIBackend/CustomWorkflows")


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
    for name, path in storage.items():
        print(f"Drive {name}: {path}", flush=True)
    print(f"Local program: {app_dir}\nLocal temporary files: {temporary}", flush=True)
    return storage


def prepare_backend(app_dir):
    """Provision local ComfyUI even when Drive settings say SwarmUI is already installed."""
    app_dir = Path(app_dir).resolve()
    backend = app_dir / "dlbackend/ComfyUI"
    if not (backend / "main.py").is_file():
        subprocess.run(["bash", "launchtools/comfy-install-linux.sh", "nv"], cwd=app_dir, check=True)
    else:
        subprocess.run([sys.executable, "-s", "-m", "pip", "install", "-r", str(backend / "requirements.txt")],
                       cwd=app_dir, check=True)
