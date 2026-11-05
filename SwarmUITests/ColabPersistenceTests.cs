using System;
using System.IO;
using System.Threading.Tasks;
using LiteDB;
using FreneticUtilities.FreneticDataSyntax;
using NUnit.Framework;
using SwarmUI.Accounts;
using SwarmUI.Backends;
using SwarmUI.Builtin_ComfyUIBackend;
using SwarmUI.Core;
using SwarmUI.Text2Image;
using SwarmUI.WebAPI;

namespace SwarmUITests;

/// <summary>Checks acknowledged Colab writes using temporary storage and dummy credentials.</summary>
[TestFixture, NonParallelizable]
public class ColabPersistenceTests : SwarmUITest
{
    [OneTimeSetUp]
    public static void PreInit()
    {
        Setup();
    }

    /// <summary>Backend changes must reach Drive before a successful request returns.</summary>
    [Test]
    public static async Task TestBackendChangesSaveImmediately()
    {
        string root = Path.Combine(Path.GetTempPath(), $"swarm-backends-{Guid.NewGuid()}");
        string oldMode = Environment.GetEnvironmentVariable("SWARM_COLAB_MODE");
        string oldRoot = Environment.GetEnvironmentVariable("SWARM_COLAB_DRIVE_ROOT");
        BackendHandler oldBackends = Program.Backends;
        Action oldRefresh = Program.ModelRefreshEvent;
        bool hadModels = Program.T2IModelSets.TryGetValue("Stable-Diffusion", out T2IModelHandler oldModels);
        try
        {
            foreach (string folder in new string[] { "Models", "Output", "Data" })
            {
                Directory.CreateDirectory(Path.Combine(root, folder));
            }
            Environment.SetEnvironmentVariable("SWARM_COLAB_MODE", "true");
            Environment.SetEnvironmentVariable("SWARM_COLAB_DRIVE_ROOT", root);
            BackendHandler handler = new() { SaveFilePath = Path.Combine(root, "Data/Backends.fds") };
            Program.Backends = handler;
            Program.T2IModelSets["Stable-Diffusion"] = new();
            BackendHandler.BackendType type = handler.RegisterBackendType<ComfyUISelfStartBackend>("comfyui_selfstart", "test", "test");
            BackendHandler.BackendData backend = handler.AddNewOfType(type);
            Assert.That(File.Exists(handler.SaveFilePath), Is.True);
            await handler.EditById(backend.ID, backend.AbstractBackend.SettingsRaw.Save(true), "Saved title");
            Assert.That(FDSUtility.ReadFile(handler.SaveFilePath).GetString($"{backend.ID}.title"), Is.EqualTo("Saved title"));
            Assert.That(await handler.DeleteById(backend.ID), Is.True);
            Assert.That(FDSUtility.ReadFile(handler.SaveFilePath).GetRootKeys(), Is.Empty);
        }
        finally
        {
            Program.Backends = oldBackends;
            Program.ModelRefreshEvent = oldRefresh;
            if (hadModels)
            {
                Program.T2IModelSets["Stable-Diffusion"] = oldModels;
            }
            else
            {
                Program.T2IModelSets.Remove("Stable-Diffusion");
            }
            Environment.SetEnvironmentVariable("SWARM_COLAB_MODE", oldMode);
            Environment.SetEnvironmentVariable("SWARM_COLAB_DRIVE_ROOT", oldRoot);
            Directory.Delete(root, true);
        }
    }

    /// <summary>Drive must receive a self-contained database before the server shuts down.</summary>
    [Test]
    public static async Task TestAcknowledgedUserChangesReachMainDatabase()
    {
        string root = Path.Combine(Path.GetTempPath(), $"swarm-persistence-{Guid.NewGuid()}");
        string oldData = Program.DataDir;
        Settings oldSettings = Program.ServerSettings;
        bool oldNoPersist = Program.NoPersist;
        bool oldEmptyStringToNull = BsonMapper.Global.EmptyStringToNull;
        string oldMode = Environment.GetEnvironmentVariable("SWARM_COLAB_MODE");
        string oldRoot = Environment.GetEnvironmentVariable("SWARM_COLAB_DRIVE_ROOT");
        SessionHandler handler = null;
        try
        {
            foreach (string folder in new string[] { "Models", "Output", "Data" })
            {
                Directory.CreateDirectory(Path.Combine(root, folder));
            }
            Program.DataDir = Path.Combine(root, "Data");
            Program.ServerSettings = new();
            Program.ServerSettings.Maintenance.UserDBBackups = 0;
            Program.NoPersist = false;
            BsonMapper.Global.EmptyStringToNull = false;
            Environment.SetEnvironmentVariable("SWARM_COLAB_MODE", "true");
            Environment.SetEnvironmentVariable("SWARM_COLAB_DRIVE_ROOT", root);
            handler = new();
            Session session = handler.CreateSession("persistence-test");
            for (int i = 0; i < 3; i++)
            {
                handler.SessionDatabase.Upsert(new Session.DatabaseEntry() { ID = $"expired-{i}", LastActiveUnixTime = 0 });
            }
            handler.CleanOldSessions();
            Assert.That(handler.SessionDatabase.Count(), Is.EqualTo(1), "All expired sessions must be removed while the active session remains");
            await BasicAPIFeatures.SetAPIKey(session, "civitai_api", "dummy-key-for-test");
            session.User.Settings.Theme = "modern_light";
            session.User.Settings.TrySetFieldModified("Theme", true);
            session.User.Save();
            session.User.SavePreset(new T2IPreset() { Title = "Persistent preset", Author = "local", Description = "saved" });
            string snapshot = Path.Combine(root, "snapshot.ldb");
            File.Copy(Path.Combine(Program.DataDir, "Users.ldb"), snapshot);
            using (LiteDatabase reopened = new(snapshot))
            {
                Assert.That(reopened.GetCollection<SessionHandler.GenericDataStore>("generic_data")
                    .FindById("local///$civitai_api///key")?.Data, Is.EqualTo("dummy-key-for-test"));
                Assert.That(reopened.GetCollection<User.DatabaseEntry>("users").FindById("local").RawSettings, Does.Contain("modern_light"));
                Assert.That(reopened.GetCollection<T2IPreset>("t2i_presets").FindById("local///persistent preset")?.Description, Is.EqualTo("saved"));
            }
            handler.Shutdown();
            handler = new();
            session = handler.CreateSession("new-runtime-test");
            Assert.That(session.User.GetGenericData("civitai_api", "key"), Is.EqualTo("dummy-key-for-test"));
            Assert.That((string)(await BasicAPIFeatures.GetAPIKeyStatus(session, "civitai_api"))["status"], Does.StartWith("last updated"));
            Assert.That(session.User.Settings.Theme, Is.EqualTo("modern_light"));
            await BasicAPIFeatures.SetAPIKey(session, "civitai_api", "none");
            File.Copy(Path.Combine(Program.DataDir, "Users.ldb"), snapshot, true);
            using (LiteDatabase reopened = new(snapshot))
            {
                Assert.That(reopened.GetCollection<SessionHandler.GenericDataStore>("generic_data")
                    .FindById("local///$civitai_api///key"), Is.Null);
            }
        }
        finally
        {
            handler?.Shutdown();
            Program.DataDir = oldData;
            Program.ServerSettings = oldSettings;
            Program.NoPersist = oldNoPersist;
            BsonMapper.Global.EmptyStringToNull = oldEmptyStringToNull;
            Environment.SetEnvironmentVariable("SWARM_COLAB_MODE", oldMode);
            Environment.SetEnvironmentVariable("SWARM_COLAB_DRIVE_ROOT", oldRoot);
            Directory.Delete(root, true);
        }
    }
}
