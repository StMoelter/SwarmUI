using System;
using System.Diagnostics;
using System.IO;
using NUnit.Framework;
using SwarmUI.Backends;
using SwarmUI.Builtin_ComfyUIBackend;
using SwarmUI.Utils;
using SwarmUI.Core;
using System.Threading.Tasks;
using System.Runtime.Versioning;

namespace SwarmUITests;

/// <summary>Checks Colab interpreter selection and protection without launching Python.</summary>
[TestFixture, NonParallelizable]
public class ColabPythonTests : SwarmUITest
{
    /// <summary>The installer checks pip with the notebook interpreter, without requiring a separate venv.</summary>
    [Test, Platform(Exclude = "Win"), UnsupportedOSPlatform("windows")]
    public static async Task TestColabInstallerPipCheck()
    {
        string python = Path.GetTempFileName();
        string oldMode = Environment.GetEnvironmentVariable("SWARM_COLAB_MODE");
        string oldPython = Environment.GetEnvironmentVariable("SWARM_COLAB_PYTHON");
        bool wasInstalled = Program.ServerSettings.IsInstalled;
        try
        {
            File.WriteAllText(python, "#!/bin/sh\nif [ \"$*\" = \"-s -m pip --version\" ]; then echo 'pip 25.0'; exit 0; fi\nexit 9\n");
            File.SetUnixFileMode(python, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
            Program.ServerSettings.IsInstalled = false;
            Environment.SetEnvironmentVariable("SWARM_COLAB_MODE", "true");
            Environment.SetEnvironmentVariable("SWARM_COLAB_PYTHON", python);
            Assert.That(await WebUtil.NeedLinuxPythonWarn(), Is.Null);
            File.WriteAllText(python, "#!/bin/sh\necho 'No module named pip'\nexit 1\n");
            Assert.That(await WebUtil.NeedLinuxPythonWarn(), Does.Contain("notebook"));
        }
        finally
        {
            Program.ServerSettings.IsInstalled = wasInstalled;
            Environment.SetEnvironmentVariable("SWARM_COLAB_MODE", oldMode);
            Environment.SetEnvironmentVariable("SWARM_COLAB_PYTHON", oldPython);
            File.Delete(python);
        }
    }

    /// <summary>Prepares the test environment.</summary>
    [OneTimeSetUp]
    public static void PreInit()
    {
        Setup();
    }

    /// <summary>Colab must use notebook Python even when an old backend venv is present.</summary>
    [TestCase(true)]
    [TestCase(false)]
    public static void TestPythonSelection(bool colab)
    {
        string root = Path.Combine(Path.GetTempPath(), $"swarm-colab-test-{Guid.NewGuid()}");
        string oldMode = Environment.GetEnvironmentVariable("SWARM_COLAB_MODE");
        string oldPython = Environment.GetEnvironmentVariable("SWARM_COLAB_PYTHON");
        try
        {
            string venvPython = Path.GetFullPath(Path.Combine(root, OperatingSystem.IsWindows() ? "venv/Scripts/python.exe" : "venv/bin/python3"));
            Directory.CreateDirectory(Path.GetDirectoryName(venvPython));
            File.WriteAllText(venvPython, "");
            string notebookPython = Path.Combine(root, "notebook-python");
            File.WriteAllText(notebookPython, "");
            Environment.SetEnvironmentVariable("SWARM_COLAB_MODE", colab ? "true" : null);
            Environment.SetEnvironmentVariable("SWARM_COLAB_PYTHON", notebookPython);
            ProcessStartInfo start = new();
            NetworkBackendUtils.ConfigurePythonExeFor(Path.Combine(root, "main.py"), "test", start, out string preArgs, out string forcePrior);
            Assert.That(start.FileName, Is.EqualTo(colab ? notebookPython : venvPython));
            Assert.That(preArgs, Is.EqualTo("-s main.py"));
            Assert.That(forcePrior, Is.Empty);
        }
        finally
        {
            Environment.SetEnvironmentVariable("SWARM_COLAB_MODE", oldMode);
            Environment.SetEnvironmentVariable("SWARM_COLAB_PYTHON", oldPython);
            if (Directory.Exists(root))
            {
                Directory.Delete(root, true);
            }
        }
    }

    /// <summary>Colab must reject a missing notebook interpreter instead of using a different Python.</summary>
    [Test]
    public static void TestMissingNotebookPython()
    {
        string oldMode = Environment.GetEnvironmentVariable("SWARM_COLAB_MODE");
        string oldPython = Environment.GetEnvironmentVariable("SWARM_COLAB_PYTHON");
        try
        {
            Environment.SetEnvironmentVariable("SWARM_COLAB_MODE", "true");
            Environment.SetEnvironmentVariable("SWARM_COLAB_PYTHON", null);
            Assert.Throws<InvalidOperationException>(new Action(() => NetworkBackendUtils.ConfigurePythonExeFor(
                Path.Combine(Path.GetTempPath(), "main.py"), "test", new ProcessStartInfo(), out _, out _)));
            Assert.Throws<InvalidOperationException>(new Action(() => PythonLaunchHelper.LaunchGeneric(
                Path.Combine(Path.GetTempPath(), "main.py"), false, [])));
        }
        finally
        {
            Environment.SetEnvironmentVariable("SWARM_COLAB_MODE", oldMode);
            Environment.SetEnvironmentVariable("SWARM_COLAB_PYTHON", oldPython);
        }
    }

    /// <summary>Generic helpers must use notebook Python instead of a stale Drive venv.</summary>
    [Test, Platform(Exclude = "Win"), UnsupportedOSPlatform("windows")]
    public static void TestGenericUsesNotebookPython()
    {
        string root = Path.Combine(Path.GetTempPath(), $"swarm-colab-test-{Guid.NewGuid()}");
        string oldMode = Environment.GetEnvironmentVariable("SWARM_COLAB_MODE");
        string oldPython = Environment.GetEnvironmentVariable("SWARM_COLAB_PYTHON");
        string oldDirectory = Environment.CurrentDirectory;
        try
        {
            string stalePython = Path.Combine(root, "dlbackend/ComfyUI/venv/bin/python");
            Directory.CreateDirectory(Path.GetDirectoryName(stalePython));
            File.WriteAllText(stalePython, "#!/bin/sh\nprintf stale");
            File.SetUnixFileMode(stalePython, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
            string notebookPython = Path.Combine(root, "notebook-python");
            File.WriteAllText(notebookPython, "#!/bin/sh\nprintf notebook");
            File.SetUnixFileMode(notebookPython, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
            Environment.CurrentDirectory = root;
            Environment.SetEnvironmentVariable("SWARM_COLAB_MODE", "true");
            Environment.SetEnvironmentVariable("SWARM_COLAB_PYTHON", notebookPython);
            using Process process = PythonLaunchHelper.LaunchGeneric("probe.py", false, []);
            Assert.That(process.StandardOutput.ReadToEnd(), Is.EqualTo("notebook"));
            process.WaitForExit();
            Assert.That(process.ExitCode, Is.Zero);
        }
        finally
        {
            Environment.CurrentDirectory = oldDirectory;
            Environment.SetEnvironmentVariable("SWARM_COLAB_MODE", oldMode);
            Environment.SetEnvironmentVariable("SWARM_COLAB_PYTHON", oldPython);
            if (Directory.Exists(root))
            {
                Directory.Delete(root, true);
            }
        }
    }

    /// <summary>Automated pip removals must not bypass the constraints file in Colab.</summary>
    [Test]
    public static void TestColabBlocksUninstallAndMissingConstraints()
    {
        string oldMode = Environment.GetEnvironmentVariable("SWARM_COLAB_MODE");
        string oldConstraints = Environment.GetEnvironmentVariable("PIP_CONSTRAINT");
        string constraints = Path.GetTempFileName();
        try
        {
            Environment.SetEnvironmentVariable("SWARM_COLAB_MODE", "true");
            Environment.SetEnvironmentVariable("PIP_CONSTRAINT", constraints);
            ComfyUISelfStartBackend backend = new();
            Assert.Throws<SwarmReadableErrorException>(new Action(() => backend.DoPythonCall("-s -m pip install numpy")));
            File.WriteAllText(constraints, "numpy==2.0.2\n");
            Assert.Throws<SwarmReadableErrorException>(new Action(() => backend.DoPythonCall("-s -m pip uninstall -y numpy")));
        }
        finally
        {
            Environment.SetEnvironmentVariable("SWARM_COLAB_MODE", oldMode);
            Environment.SetEnvironmentVariable("PIP_CONSTRAINT", oldConstraints);
            File.Delete(constraints);
        }
    }
}
