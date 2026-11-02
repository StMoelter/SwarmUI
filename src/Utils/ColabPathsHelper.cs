using System;
using System.IO;
using SwarmUI.Core;

namespace SwarmUI.Utils;

/// <summary>Applies notebook-selected persistent paths only in explicitly enabled Colab mode.</summary>
public static class ColabPathsHelper
{
    /// <summary>Returns the prepared Drive root, or null when persistent Colab storage is not enabled.</summary>
    public static string GetDriveRoot()
    {
        string root = Environment.GetEnvironmentVariable("SWARM_COLAB_DRIVE_ROOT");
        if (Environment.GetEnvironmentVariable("SWARM_COLAB_MODE") != "true" || string.IsNullOrWhiteSpace(root))
        {
            return null;
        }
        if (!Path.IsPathFullyQualified(root))
        {
            throw new SwarmReadableErrorException("Colab Drive storage must use an absolute path. Run the notebook storage preparation first.");
        }
        root = Path.GetFullPath(root);
        foreach (string folder in new string[] { "Models", "Output", "Data" })
        {
            if (!Directory.Exists(Path.Combine(root, folder)))
            {
                throw new SwarmReadableErrorException($"Colab Drive storage is unavailable at '{root}'. Mount Google Drive and run the storage preparation before starting SwarmUI.");
            }
        }
        return root;
    }

    /// <summary>Directs configured models, new downloads, user data and saved images to Drive.</summary>
    public static void ApplyStoragePaths(Settings settings)
    {
        string root = GetDriveRoot();
        if (root is null)
        {
            return;
        }
        string modelRoot = Path.Combine(root, "Models");
        (string, string)[] modelFolders =
        [
            ("SDModelFolder", settings.Paths.SDModelFolder),
            ("SDLoraFolder", settings.Paths.SDLoraFolder),
            ("SDVAEFolder", settings.Paths.SDVAEFolder),
            ("SDEmbeddingFolder", settings.Paths.SDEmbeddingFolder),
            ("SDControlNetsFolder", settings.Paths.SDControlNetsFolder),
            ("SDClipFolder", settings.Paths.SDClipFolder),
            ("SDClipVisionFolder", settings.Paths.SDClipVisionFolder)
        ];
        foreach ((string name, string folders) in modelFolders)
        {
            foreach (string folder in folders.Split(';', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
            {
                string resolved = Path.GetFullPath(Utilities.CombinePathWithAbsolute(modelRoot, folder));
                string relative = Path.GetRelativePath(modelRoot, resolved);
                if (Path.IsPathRooted(relative) || relative == ".." || relative.StartsWith($"..{Path.DirectorySeparatorChar}"))
                {
                    throw new SwarmReadableErrorException($"Colab setting Paths.{name} points outside the Drive Models directory: '{folder}'. Use a subfolder within '{modelRoot}'.");
                }
            }
        }
        settings.Paths.ModelRoot = modelRoot;
        settings.Paths.OutputPath = Path.Combine(root, "Output");
        settings.Paths.DataPath = Path.Combine(root, "Data");
        settings.Paths.DownloadToRootID = 0;
    }

    /// <summary>Remaps the old standard Drive backend path to this runtime's local backend.</summary>
    public static string GetComfyStartScript(string configured)
    {
        string root = GetDriveRoot();
        if (root is not null && !string.IsNullOrWhiteSpace(configured)
            && Path.GetFullPath(configured) == Path.GetFullPath(Path.Combine(root, "dlbackend/ComfyUI/main.py")))
        {
            return Path.GetFullPath("dlbackend/ComfyUI/main.py");
        }
        return configured;
    }

    /// <summary>Returns the Drive directory for images saved directly by ComfyUI nodes.</summary>
    public static string GetComfyOutputDirectory()
    {
        string root = GetDriveRoot();
        return root is null ? null : Path.GetFullPath(Path.Combine(root, "Output/ComfyUI"));
    }
}
