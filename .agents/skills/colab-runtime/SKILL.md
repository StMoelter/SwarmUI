---
name: colab-runtime
description: Maintain Colab startup, dependency protection and persistent Drive storage without changing desktop installations.
---

# Colab Runtime

## When to Use

- Use when changing the notebook, its preparation helpers, or Colab-specific server behavior.
- Use when debugging lost settings or repeated package installation in Colab.

## Instructions

- Keep the program and backend local; persist models, output, workflows and native SwarmUI data through the paths selected by `colab/prepare-storage.py` and `ColabPathsHelper`.
- Check the notebook's `--data_dir` argument: server settings and backend files use that directory, while credentials and user preferences live in `Users.ldb`. Do not create a separate credentials file.
- Gate server behavior on explicitly enabled Colab mode and validated Drive storage. Preserve normal desktop behavior.
- A successful database write can still reside in a journal. Test persistence before shutdown as well as after reopening. Colab uses LiteDB shared connections to close/checkpoint each operation.
- When stopping a notebook subprocess, allow its entire process group to finish; a launcher exiting does not mean its server has finished saving. Keep a bounded fallback for unresponsive descendants.
- Drive has an upload queue. Use Colab's public `drive.flush_and_unmount` after stopping writers, and require remounting before restart. Forced runtime deletion can bypass cleanup.
- Preserve the runtime's imported numerical and GPU package versions. Reuse the existing constraints/inventory helper; never hard-code an old Colab baseline or silently permit source builds.
- Run Python tests with `python -m unittest discover -s colab -p 'test_*.py'` and C# tests with `launchtools/run_tests.sh`. Use temporary storage and dummy credentials only; never inspect actual user data or API keys.
- Validate notebook syntax through IPython's input transformer, since `%` and `!` statements are valid notebook syntax.
- Distinguish local regression tests from live Colab/Drive verification in the result.
