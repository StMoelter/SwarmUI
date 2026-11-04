This folder is for Google-Colab related files.

View the notebook on Google Colab: https://colab.research.google.com/github/StMoelter/SwarmUI/blob/fix/colab-existing-packages/colab/colab-notebook.ipynb

## Persistent Drive storage with a local application

Use a fresh GPU runtime and run the notebook's three cells in order:

1. Mount Google Drive and set `DRIVE_ROOT` (default `/content/drive/MyDrive/SwarmUI`). Keep `APP_ROOT` on local Colab storage (default `/content/SwarmUI`).
2. Prepare local tools and clone the selected repository and branch. Repeating this cell reuses the local checkout.
3. Update the local program, protect Colab's preinstalled packages, prepare Drive storage, provision local ComfyUI, and launch SwarmUI. The normal launcher decides whether a rebuild is needed.

The first Colab launch automatically completes SwarmUI's initial configuration and registers the prepared local backend before serving the UI. Open the Cloudflare URL to reach the generation interface directly. Existing installed configurations and backend records are retained. No model download is triggered automatically; select an existing Drive model or use SwarmUI's model downloader if the collection is empty. The Colab backend uses the frontend already installed with ComfyUI rather than downloading a second validated frontend version.

Backend installation and server output are streamed live into the notebook, including pip dependency conflicts, build messages and the Cloudflare access URL. After the Drive paths, expect an installation/dependency-check message, then `Local ComfyUI preparation finished.` and `Starting SwarmUI`. The start cell keeps running while SwarmUI serves the interface; that alone does not mean installation is still in progress. Stopping the cell terminates the process group started by the notebook.

Persistent storage is organized as follows:

```text
MyDrive/SwarmUI/
  Models/
    Stable-Diffusion/  Lora/  VAE/  Embeddings/
    controlnet/  model_patches/  text_encoders/  clip/  clip_vision/
    diffusion_models/  unet/  upscale_models/
  Output/
    ComfyUI/          # Images written directly by ComfyUI nodes
  Data/               # Settings, users, presets and metadata databases
  Workflows/          # Saved custom ComfyUI workflows
  Cache/pip/          # Reusable package downloads for later runtimes
```

Existing files remain in place; preparation only creates missing directories. If the old Drive installation already contains `src/BuiltinExtensions/ComfyUIBackend/CustomWorkflows`, that directory is reused instead of creating `Workflows`. Preparation prints the actual paths. The old Drive program, backend and Python environment are not updated or deleted.

Local `Models` and `Output` links point to Drive; the local custom-workflow directory links to its persistent counterpart. Settings use SwarmUI's existing `--data_dir` argument. `SWARM_COLAB_DRIVE_ROOT` makes the chosen Drive model and output roots authoritative in Colab, including for model downloads. An old standard absolute ComfyUI start path under that Drive root is mapped to this runtime's local backend; custom backend paths are left unchanged. New runtimes provision ComfyUI locally even if persistent settings already mark installation complete.

Existing per-model-type directory settings are preserved when they resolve inside the selected Drive `Models` directory. An absolute directory outside that root or a relative `../` escape stops startup with the setting name and offending path, rather than sending downloads to temporary storage. Correct those values to subfolder names such as `Stable-Diffusion` or `Lora` before starting again.

Temporary files stay on the Colab VM via `TMPDIR`. Models are read directly from Drive, without copying the full collection at startup. Model loading can therefore take longer than loading from local disk. Saved images use SwarmUI's existing user/date organization under `Output`; directly saved backend images use `Output/ComfyUI`. These files persist when the Colab runtime is deleted. No separate Drive upload or synchronization service is needed.

New Colab checkouts use shallow Git clones, and repeat setup reuses installed .NET and cloudflared. `PIP_CACHE_DIR` points to Drive's `Cache/pip`, so later runtimes can reuse package downloads. A fresh VM still has to install dependencies absent from Colab and build the server locally; this is not an instant startup guarantee. Tool preparation and ComfyUI preparation report their elapsed seconds; .NET prints its build/restore duration. Keep those lines when reporting slow startup so the costly stage can be identified.

Preparation stops if Drive is not mounted or writable, a storage destination is a file, or a local path already contains a real directory or a different symlink. It does not replace or delete that content and does not silently switch to temporary local storage. Start with a fresh runtime when switching from the old notebook's temporary installation.

## Keeping Colab's preinstalled packages

A Python-session restart does not undo previous pip installations; delete the runtime if its packages have already been changed.

Before installing Python requirements, the launch cell runs `prepare-colab.py` in the notebook interpreter. It checks PyTorch/torchvision and CUDA access, records the preinstalled GPU and numerical package versions in `/content/swarm-colab/constraints.txt`, and saves the original `pip check` output alongside it as `pip-check-before.txt`. These files belong to the temporary runtime, even when SwarmUI is stored on Drive. Repeating the launch cell keeps the original baseline and rejects changed or missing protected packages.

Inventory is collected in a fresh process using the same `sys.executable -s` as pip, rather than the notebook kernel's cached modules or extra paths. Duplicate metadata records retain the first visible distribution, and NumPy is checked by importing the actual module. This prevents stale NumPy 1.26 metadata from replacing an installed NumPy 2.x baseline. On Python 3.13 or newer, a NumPy baseline older than 2.1 is rejected before installation. If a previous run downgraded NumPy, reconnect with a fresh GPU runtime to restore Colab's original packages; keep the persistent Drive data and cache.

The preparation sets `SWARM_COLAB_MODE=true`, `SWARM_COLAB_PYTHON` to the notebook interpreter, `SWARM_NO_VENV=true`, and `PIP_CONSTRAINT` to the absolute constraints path. The installer and backend use that interpreter and preserve Colab's existing PyTorch/CUDA stack. Other dependencies are installed only as needed. Normal installations without Colab mode retain their existing Python, PyTorch and storage selection.

Colab also sets `PIP_ONLY_BINARY=:all:`. Packages from the package index must have compatible wheels; pip must fail instead of spending minutes compiling NumPy or another source distribution. Optional features whose dependencies have no compatible wheels may therefore require a different runtime. Standard ComfyUI workflow-template media and frontend packages remain installed, so their initial download cost is separate from a numerical-library source build.

If a requirement cannot be satisfied without replacing a protected package, installation stops and pip reports the conflicting requirements. Automated package uninstalls are also blocked in Colab. Do not remove the constraints or use `--no-deps` to bypass a conflict; the requested backend or optional feature may need versions incompatible with that runtime.

The notebook selects `StMoelter/SwarmUI` and the `fix/colab-existing-packages` branch. To use another fork or branch, change `url` and `branch` in the first cell. The launch cell fetches that repository and branch explicitly and resets only the local checkout to the fetched commit. Local program changes in that Colab checkout will be replaced; persistent Drive data remains separate.

## Verification

Offline regression checks (no downloads or GPU required):

```sh
python3 -m unittest discover -s colab -p 'test_*.py'
bash -n launchtools/comfy-install-linux.sh
```

In Colab, verify that an existing model and LoRA appear, a new model download lands on Drive, and a generated image is present under Drive's `Output`. Save a custom workflow and a user setting, then repeat the launch cell and finally reconnect with a fresh runtime. Models, images, workflows and settings should remain available; the program and ComfyUI backend should be local. Protected package versions should stay unchanged and satisfied packages should not be downloaded again. Compare `python -m pip check` with `/content/swarm-colab/pip-check-before.txt`; Colab's initial environment may already contain unrelated conflicts. Measure package preparation, backend startup and model loading separately.

The C# path-selection tests are part of `SwarmUITests`; run them using `launchtools/run_tests.sh` or `launchtools/run_tests.bat`.
