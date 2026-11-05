"""Check notebook subprocess output with real local processes, without GPU/network."""

import contextlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import signal
import unittest


class NotebookProcessTests(unittest.TestCase):
    """Child-process messages must go through Python's notebook output stream."""

    def setUp(self):
        helper = Path(__file__).with_name("prepare-storage.py")
        spec = importlib.util.spec_from_file_location("prepare_storage", helper)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.assertTrue(hasattr(self.module, "run_logged"), "Notebook process output forwarding is missing")

    def test_forwards_stdout_and_stderr(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.module.run_logged([sys.executable, "-c",
                                    "import sys; print('installing package'); print('dependency details', file=sys.stderr)"])
        self.assertIn("installing package", output.getvalue())
        self.assertIn("dependency details", output.getvalue())

    def test_output_arrives_before_process_exits(self):
        with tempfile.TemporaryDirectory() as directory:
            ack = Path(directory) / "output-received"

            class NotebookOutput(io.StringIO):
                """Acknowledge progress exactly when Python forwards it to the notebook."""

                def write(self, text):
                    if "ready for notebook" in text:
                        ack.touch()
                    return super().write(text)

            script = ("import pathlib, sys, time; ack = pathlib.Path(sys.argv[1]); "
                      "print('ready for notebook', flush=True)\n"
                      "for attempt in range(100):\n"
                      "    if ack.exists(): break\n"
                      "    time.sleep(0.02)\n"
                      "sys.exit(0 if ack.exists() else 7)")
            with contextlib.redirect_stdout(NotebookOutput()):
                self.module.run_logged([sys.executable, "-c", script, str(ack)])
            self.assertTrue(ack.exists())

    def test_failure_shows_diagnostic_and_preserves_exit_code(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises(subprocess.CalledProcessError) as error:
                self.module.run_logged([sys.executable, "-c",
                                        "import sys; print('package conflict', file=sys.stderr); sys.exit(23)"])
        self.assertEqual(error.exception.returncode, 23)
        self.assertIn("package conflict", output.getvalue())

    @unittest.skipUnless(os.name == "posix", "Colab process groups require POSIX")
    def test_stopping_notebook_does_not_leave_child_running(self):
        child_pid = None

        class InterruptedNotebook(io.StringIO):
            """Simulate the user stopping the cell once its child starts."""

            def write(self, text):
                nonlocal child_pid
                child_pid = int(text.strip())
                raise KeyboardInterrupt()

        with contextlib.redirect_stdout(InterruptedNotebook()):
            with self.assertRaises(KeyboardInterrupt):
                self.module.run_logged([sys.executable, "-c",
                                        "import os,time; print(os.getpid(),flush=True); time.sleep(60)"])
        self.assertIsNotNone(child_pid)
        with self.assertRaises(ProcessLookupError):
            os.kill(child_pid, 0)

    @unittest.skipUnless(os.name == "posix", "Colab process groups require POSIX")
    def test_stopping_notebook_allows_descendant_to_save(self):
        class InterruptedNotebook(io.StringIO):
            def write(self, text):
                if "ready" in text:
                    raise KeyboardInterrupt()
                return super().write(text)

        with tempfile.TemporaryDirectory() as directory:
            saved = Path(directory) / "saved"
            child = ("import pathlib,signal,sys,time\n"
                     "def stop(*args):\n"
                     "    time.sleep(0.3)\n"
                     "    pathlib.Path(sys.argv[1]).write_text('saved')\n"
                     "    sys.exit(0)\n"
                     "signal.signal(signal.SIGTERM,stop)\n"
                     "print('ready',flush=True)\n"
                     "time.sleep(60)")
            parent = ("import subprocess,sys,time; "
                      "subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]); time.sleep(60)")
            with contextlib.redirect_stdout(InterruptedNotebook()):
                with self.assertRaises(KeyboardInterrupt):
                    self.module.run_logged([sys.executable, "-c", parent, child, str(saved)])
            self.assertTrue(saved.exists(), "Launcher exited before its server could finish saving")

    @unittest.skipUnless(os.name == "posix", "Colab process groups require POSIX")
    def test_stopping_notebook_kills_descendant_that_ignores_sigterm(self):
        descendant_pid = None

        class InterruptedNotebook(io.StringIO):
            """Stop once the nested installer has started."""

            def write(self, text):
                nonlocal descendant_pid
                if text.startswith("descendant:"):
                    descendant_pid = int(text.split(":", 1)[1])
                    raise KeyboardInterrupt()
                return super().write(text)

        with tempfile.TemporaryDirectory() as directory:
            heartbeat = Path(directory) / "heartbeat"
            child_script = ("import pathlib,signal,sys,time; "
                            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                            "path=pathlib.Path(sys.argv[1]); print('ready',flush=True)\n"
                            "while True:\n"
                            "    path.write_text(str(time.monotonic_ns()))\n"
                            "    time.sleep(0.02)")
            parent_script = ("import subprocess,sys,time; "
                             "child=subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]],stdout=subprocess.PIPE,text=True); "
                             "child.stdout.readline(); time.sleep(0.05); "
                             "print('descendant:'+str(child.pid),flush=True); time.sleep(60)")
            try:
                with contextlib.redirect_stdout(InterruptedNotebook()):
                    with self.assertRaises(KeyboardInterrupt):
                        self.module.run_logged([sys.executable, "-c", parent_script, child_script, str(heartbeat)])
                last_heartbeat = heartbeat.read_text()
                time.sleep(0.15)
                self.assertEqual(heartbeat.read_text(), last_heartbeat, "Nested installer is still running")
            finally:
                if descendant_pid is not None:
                    try:
                        os.kill(descendant_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass


if __name__ == "__main__":
    unittest.main()
