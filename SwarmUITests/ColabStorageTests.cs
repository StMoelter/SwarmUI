using System;
using System.IO;
using NUnit.Framework;
using FreneticUtilities.FreneticDataSyntax;
using SwarmUI.Builtin_ComfyUIBackend;
using SwarmUI.Core;
using SwarmUI.Utils;

namespace SwarmUITests;

/// <summary>Tests persistent Colab paths without touching user storage or starting Python.</summary>
[TestFixture, NonParallelizable]
public class ColabStorageTests : SwarmUITest
{
    /// <summary>Prepares the test environment.</summary>
    [OneTimeSetUp]
    public static void PreInit()
    {
        Setup();
    }

    /// <summary>Drive paths override old settings only in explicitly enabled Colab mode.</summary>
    [TestCase(true)]
    [TestCase(false)]
    public static void TestStoragePaths(bool colab)
    {
        string root = Path.Combine(Path.GetTempPath(), $"swarm-drive-test-{Guid.NewGuid()}");
        string oldMode = Environment.GetEnvironmentVariable("SWARM_COLAB_MODE");
        string oldRoot = Environment.GetEnvironmentVariable("SWARM_COLAB_DRIVE_ROOT");
        try
        {
            foreach (string folder in new string[] { "Models", "Output", "Data", "Output/ComfyUI" })
            {
                Directory.CreateDirectory(Path.Combine(root, folder));
            }
            Environment.SetEnvironmentVariable("SWARM_COLAB_MODE", colab ? "true" : null);
            Environment.SetEnvironmentVariable("SWARM_COLAB_DRIVE_ROOT", root);
            Settings settings = new();
            settings.Paths.ModelRoot = "old-models";
            settings.Paths.OutputPath = "old-output";
            settings.Paths.DownloadToRootID = 5;
            ColabPathsHelper.ApplyStoragePaths(settings);
            Assert.That(settings.Paths.ModelRoot, Is.EqualTo(colab ? Path.Combine(root, "Models") : "old-models"));
            Assert.That(settings.Paths.OutputPath, Is.EqualTo(colab ? Path.Combine(root, "Output") : "old-output"));
            Assert.That(settings.Paths.DataPath, Is.EqualTo(colab ? Path.Combine(root, "Data") : "Data"));
            Assert.That(settings.Paths.DownloadToRootID, Is.EqualTo(colab ? 0 : 5));
            Assert.That(ColabPathsHelper.GetComfyOutputDirectory(), Is.EqualTo(colab ? Path.GetFullPath(Path.Combine(root, "Output/ComfyUI")) : null));
            string legacyScript = Path.Combine(root, "dlbackend/ComfyUI/main.py");
            string localScript = Path.GetFullPath("dlbackend/ComfyUI/main.py");
            Assert.That(ColabPathsHelper.GetComfyStartScript(legacyScript), Is.EqualTo(colab ? localScript : legacyScript));
            Assert.That(ColabPathsHelper.GetComfyStartScript("custom/backend/main.py"), Is.EqualTo("custom/backend/main.py"));
            if (colab)
            {
                settings.Paths.SDLoraFolder = Path.Combine(root, "outside-model-root");
                Assert.Throws<SwarmReadableErrorException>(new Action(() => ColabPathsHelper.ApplyStoragePaths(settings)));
                settings.Paths.SDLoraFolder = "../outside-model-root";
                Assert.Throws<SwarmReadableErrorException>(new Action(() => ColabPathsHelper.ApplyStoragePaths(settings)));
                settings.Paths.SDLoraFolder = $"Lora;{Path.Combine(root, "outside-model-root")}";
                Assert.Throws<SwarmReadableErrorException>(new Action(() => ColabPathsHelper.ApplyStoragePaths(settings)));
                settings.Paths.SDLoraFolder = Path.Combine(root, "Models", "Lora");
                Assert.DoesNotThrow(new Action(() => ColabPathsHelper.ApplyStoragePaths(settings)));
                Assert.That(settings.Paths.SDLoraFolder, Is.EqualTo(Path.Combine(root, "Models", "Lora")));
            }
        }
        finally
        {
            Environment.SetEnvironmentVariable("SWARM_COLAB_MODE", oldMode);
            Environment.SetEnvironmentVariable("SWARM_COLAB_DRIVE_ROOT", oldRoot);
            Directory.Delete(root, true);
        }
    }

    /// <summary>A missing Drive directory must not fall back to local storage.</summary>
    [Test]
    public static void TestMissingDrive()
    {
        string oldMode = Environment.GetEnvironmentVariable("SWARM_COLAB_MODE");
        string oldRoot = Environment.GetEnvironmentVariable("SWARM_COLAB_DRIVE_ROOT");
        try
        {
            Environment.SetEnvironmentVariable("SWARM_COLAB_MODE", "true");
            Environment.SetEnvironmentVariable("SWARM_COLAB_DRIVE_ROOT", Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString()));
            Assert.Throws<SwarmReadableErrorException>(new Action(() => ColabPathsHelper.ApplyStoragePaths(new Settings())));
            Environment.SetEnvironmentVariable("SWARM_COLAB_DRIVE_ROOT", "relative-drive-root");
            Assert.Throws<SwarmReadableErrorException>(new Action(() => ColabPathsHelper.ApplyStoragePaths(new Settings())));
            Environment.SetEnvironmentVariable("SWARM_COLAB_DRIVE_ROOT", null);
            Assert.DoesNotThrow(new Action(() => ColabPathsHelper.ApplyStoragePaths(new Settings())));
        }
        finally
        {
            Environment.SetEnvironmentVariable("SWARM_COLAB_MODE", oldMode);
            Environment.SetEnvironmentVariable("SWARM_COLAB_DRIVE_ROOT", oldRoot);
        }
    }

    /// <summary>Notebook preparation completes first-run configuration without opening the UI installer.</summary>
    [Test]
    public static void TestFirstRunConfiguration()
    {
        string root = Path.Combine(Path.GetTempPath(), $"swarm-first-run-test-{Guid.NewGuid()}");
        string oldMode = Environment.GetEnvironmentVariable("SWARM_COLAB_MODE");
        string oldRoot = Environment.GetEnvironmentVariable("SWARM_COLAB_DRIVE_ROOT");
        try
        {
            foreach (string folder in new string[] { "Models", "Output", "Data", "backend" })
            {
                Directory.CreateDirectory(Path.Combine(root, folder));
            }
            Environment.SetEnvironmentVariable("SWARM_COLAB_MODE", "true");
            Environment.SetEnvironmentVariable("SWARM_COLAB_DRIVE_ROOT", root);
            string backendFile = Path.Combine(root, "Data/Backends.fds");
            string script = Path.Combine(root, "backend/main.py");
            Settings settings = new();
            Assert.Throws<SwarmReadableErrorException>(new Action(() => ColabPathsHelper.CompleteSetup(settings, backendFile, script)));
            Assert.That(settings.IsInstalled, Is.False);
            Assert.That(File.Exists(backendFile), Is.False);
            File.WriteAllText(script, "");
            File.WriteAllText(Path.Combine(root, "backend/requirements.txt"), "");
            Assert.That(ColabPathsHelper.CompleteSetup(settings, backendFile, script), Is.True);
            Assert.That(settings.IsInstalled, Is.True);
            Assert.That(settings.LaunchMode, Is.EqualTo("none"));
            Assert.That(settings.InstallDate, Is.Not.Empty);
            FDSSection saved = FDSUtility.ReadFile(backendFile);
            Assert.That(saved.GetSection("0").GetString("type"), Is.EqualTo("comfyui_selfstart"));
            ComfyUISelfStartBackend.ComfyUISelfStartSettings backend = new();
            backend.Load(saved.GetSection("0.settings"));
            Assert.That(backend.StartScript, Is.EqualTo(script));
            Assert.That(backend.FrontendVersion, Is.EqualTo("None"));
            byte[] original = File.ReadAllBytes(backendFile);
            Assert.That(ColabPathsHelper.CompleteSetup(settings, backendFile, script), Is.False);
            Assert.That(File.ReadAllBytes(backendFile), Is.EqualTo(original));
            Settings existing = new();
            Assert.That(ColabPathsHelper.CompleteSetup(existing, backendFile, script), Is.True);
            Assert.That(File.ReadAllBytes(backendFile), Is.EqualTo(original));
        }
        finally
        {
            Environment.SetEnvironmentVariable("SWARM_COLAB_MODE", oldMode);
            Environment.SetEnvironmentVariable("SWARM_COLAB_DRIVE_ROOT", oldRoot);
            Directory.Delete(root, true);
        }
    }
}
