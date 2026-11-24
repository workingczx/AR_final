using System;
using System.IO;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEditor.XR.Management;
using UnityEditor.XR.Management.Metadata;
using UnityEditor.XR.OpenXR.Features;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.XR.Management;
using UnityEngine.XR.OpenXR;
using UnityEngine.XR.OpenXR.Features.Interactions;
using UnityEngine.XR.OpenXR.Features.Meta;
using UnityEngine.XR.OpenXR.Features.MetaQuestSupport;

public static class EndoscopeBuild
{
    const string ScenePath = "Assets/Endoscope.unity";

    [MenuItem("Endoscope/Prepare project")]
    public static void Prepare()
    {
        if (!File.Exists(ScenePath))
        {
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            new GameObject("Endoscope demo").AddComponent<EndoscopeDemo>();
            EditorSceneManager.SaveScene(scene, ScenePath);
        }
        EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(ScenePath, true) };
        PlayerSettings.productName = "Virtual Endoscope";
        PlayerSettings.companyName = "Course Demo";
        PlayerSettings.defaultScreenWidth = 1152;
        PlayerSettings.defaultScreenHeight = 720;
        PlayerSettings.SetApplicationIdentifier(NamedBuildTarget.Android, "org.coursedemo.virtualendoscope");
        PlayerSettings.SetUseDefaultGraphicsAPIs(BuildTarget.Android, false);
        PlayerSettings.SetGraphicsAPIs(BuildTarget.Android, new[] { GraphicsDeviceType.Vulkan });
        PlayerSettings.SetScriptingBackend(NamedBuildTarget.Android, ScriptingImplementation.IL2CPP);
        PlayerSettings.Android.targetArchitectures = AndroidArchitecture.ARM64;
        PlayerSettings.Android.minSdkVersion = AndroidSdkVersions.AndroidApiLevel32;
        PlayerSettings.Android.targetSdkVersion = AndroidSdkVersions.AndroidApiLevel34;

        const BuildTargetGroup target = BuildTargetGroup.Android;
        if (!EditorBuildSettings.TryGetConfigObject(XRGeneralSettings.settingsKey,
                out XRGeneralSettingsPerBuildTarget settings))
        {
            settings = ScriptableObject.CreateInstance<XRGeneralSettingsPerBuildTarget>();
            AssetDatabase.CreateAsset(settings, "Assets/XRSettings.asset");
            EditorBuildSettings.AddConfigObject(XRGeneralSettings.settingsKey, settings, true);
        }
        if (!settings.HasSettingsForBuildTarget(target)) settings.CreateDefaultSettingsForBuildTarget(target);
        if (!settings.HasManagerSettingsForBuildTarget(target)) settings.CreateDefaultManagerSettingsForBuildTarget(target);
        var platform = settings.SettingsForBuildTarget(target);
        platform.InitManagerOnStart = true;
        if (!XRPackageMetadataStore.AssignLoader(platform.Manager, typeof(OpenXRLoader).FullName, target))
            throw new InvalidOperationException("Unable to configure the Android OpenXR loader");
        FeatureHelpers.RefreshFeatures(target);
        var xr = OpenXRSettings.GetSettingsForBuildTargetGroup(target);
        Enable(xr.GetFeature<MetaQuestFeature>());
        Enable(xr.GetFeature<OculusTouchControllerProfile>());
        Enable(xr.GetFeature<MetaQuestTouchPlusControllerProfile>());
        Enable(xr.GetFeature<ARSessionFeature>());
        Enable(xr.GetFeature<ARCameraFeature>());
        EditorUtility.SetDirty(platform);
        EditorUtility.SetDirty(platform.Manager);
        EditorUtility.SetDirty(xr);
        AssetDatabase.SaveAssets();
    }

    static void Enable(UnityEngine.XR.OpenXR.Features.OpenXRFeature feature)
    {
        if (feature == null) throw new InvalidOperationException("Required OpenXR feature missing");
        feature.enabled = true;
        EditorUtility.SetDirty(feature);
    }

    [MenuItem("Endoscope/Validate P002 motion")]
    public static void Validate()
    {
        var geometry = new PatientGeometry(Resources.Load<TextAsset>("P002").bytes);
        var motion = new ScopeMotion(geometry);
        for (int i = 0; i < 28; i++)
            Assert(motion.Input(Vector2.up, false, .1f), $"Unexpected block on insertion {i + 1}");
        Assert(Mathf.Abs(motion.Tip.z - .0168f) < .00001f, "Python path mismatch");
        var blocked = motion.Tip;
        Assert(!motion.Input(Vector2.up, false, .1f) && motion.Tip == blocked, "Endpoint state after collision");
        Assert(Vector3.Distance(motion.CameraPosition, motion.Tip) > .00049f, "Tip camera offset");
        for (int i = 0; i < 28; i++)
            Assert(motion.Input(Vector2.down, false, .1f), $"Unexpected block on withdrawal {i + 1}");
        Assert(motion.Tip.magnitude < .00001f, "Return to entry");
        for (int i = 0; i < 3; i++) Assert(motion.Input(Vector2.up, false, .1f), "Aim setup");
        for (int i = 0; i < 9; i++) Assert(motion.Input(Vector2.right, true, .1f), "Unexpected yaw block");
        var prior = motion.Rotation;
        Assert(!motion.Input(Vector2.right, true, .1f) && motion.Rotation == prior, "Shaft yaw rejection");
        Debug.Log("P002 validation passed: 28 insertions (16.8 mm), next step blocked, 28 withdrawals, 9 yaw steps then blocked.");
    }

    static void Assert(bool success, string message)
    {
        if (!success) throw new InvalidOperationException(message);
    }

    public static void PrepareAndValidate()
    {
        Prepare();
        Validate();
    }

    [MenuItem("Endoscope/Build Quest 3 APK")]
    public static void BuildQuest()
    {
        PrepareAndValidate();
        Build(BuildTarget.Android, "Builds/VirtualEndoscope-Quest.apk");
    }

    [MenuItem("Endoscope/Build Mac app")]
    public static void BuildMac()
    {
        PrepareAndValidate();
        Build(BuildTarget.StandaloneOSX, "Builds/VirtualEndoscope.app");
    }

    static void Build(BuildTarget target, string path)
    {
        Directory.CreateDirectory("Builds");
        var result = BuildPipeline.BuildPlayer(new[] { ScenePath }, path, target, BuildOptions.None);
        if (result.summary.result != BuildResult.Succeeded)
            throw new InvalidOperationException($"Build failed: {result.summary.result}");
        Debug.Log($"Built {path}");
    }
}
