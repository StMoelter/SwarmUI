This folder is for Google-Colab related files.

View the notebook on Google Colab: https://colab.research.google.com/github/StMoelter/SwarmUI/blob/fix/colab-existing-packages/colab/colab-notebook.ipynb

## Keeping Colab's preinstalled packages

Start with a fresh Colab GPU runtime and run either the temporary-install cell or the Google Drive cell, then the setup and launch cells. A Python-session restart does not undo previous pip installations; delete the runtime if its packages have already been changed.

Before installing Python requirements, the launch cell runs `prepare-colab.py` in the notebook interpreter. It checks PyTorch/torchvision and CUDA access, records the preinstalled GPU and numerical package versions in `/content/swarm-colab/constraints.txt`, and saves the original `pip check` output alongside it as `pip-check-before.txt`. These files belong to the temporary runtime, even when SwarmUI is stored on Drive. Repeating the launch cell keeps the original baseline and rejects changed or missing protected packages.

The preparation sets `SWARM_COLAB_MODE=true`, `SWARM_COLAB_PYTHON` to the notebook interpreter, `SWARM_NO_VENV=true`, and `PIP_CONSTRAINT` to the absolute constraints path. The installer and backend use that interpreter, ignore old backend virtual environments, and preserve Colab's existing PyTorch/CUDA stack. Other dependencies are installed only as needed. Normal installations without Colab mode retain their existing Python and PyTorch selection.

If a requirement cannot be satisfied without replacing a protected package, installation stops and pip reports the conflicting requirements. Automated package uninstalls are also blocked in Colab. Do not remove the constraints or use `--no-deps` to bypass a conflict; the requested backend or optional feature may need versions incompatible with that runtime.

The notebook selects `StMoelter/SwarmUI` and the `fix/colab-existing-packages` branch. To use another fork or branch, change `url` and `branch` in the setup cell. The launch cell fetches that repository and branch explicitly, including for existing Drive installations, and resets the checkout to the fetched commit. Local changes in that Colab checkout will be replaced.

## Verification

Offline regression checks (no downloads or GPU required):

```sh
python3 -m unittest discover -s colab -p 'test_*.py'
bash -n launchtools/comfy-install-linux.sh
```

In Colab, verify that the backend starts and generates an image, then repeat the launch cell. Protected package versions should stay unchanged and satisfied packages should not be downloaded again. Compare `python -m pip check` with `/content/swarm-colab/pip-check-before.txt`; Colab's initial environment may already contain unrelated conflicts. Measure package preparation and backend startup separately from model downloads and the existing SwarmUI rebuild.
