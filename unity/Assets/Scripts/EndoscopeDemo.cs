using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.Controls;
using UnityEngine.InputSystem.XR;
using CommonUsages = UnityEngine.XR.CommonUsages;
using UnityEngine.XR;
using UnityEngine.XR.ARFoundation;

public sealed class EndoscopeDemo : MonoBehaviour
{
    const int InternalLayer = 8;
    ScopeMotion motion;
    PatientGeometry patient;
    Camera mainCamera, tipCamera;
    Transform patientRoot, shaft, marker, xrPanel;
    MeshFilter exteriorMesh, interiorMesh;
    MeshRenderer difference;
    Material anatomyMaterial, differenceMaterial;
    RenderTexture tipImage;
    bool modified, placed, previousModel, previousReset;
    float opacity = .22f;
    string status = "Ready";
    bool xrMode;

    void Start()
    {
#if UNITY_ANDROID && !UNITY_EDITOR
        xrMode = true;
#endif
        patient = new PatientGeometry(Resources.Load<TextAsset>("P002").bytes);
        motion = new ScopeMotion(patient);
        Setup();
        UpdatePose();
    }

    Material Material(string name, Color color, float mode, int queue = 3000)
    {
        var material = new Material(Resources.Load<Shader>("EndoscopeSurface")) { name = name, renderQueue = queue };
        material.SetColor("_Color", color);
        material.SetFloat("_Mode", mode);
        return material;
    }

    MeshFilter DisplayMesh(string name, Mesh mesh, Material material, int layer = 0)
    {
        var obj = new GameObject(name);
        obj.layer = layer;
        obj.transform.SetParent(patientRoot, false);
        var filter = obj.AddComponent<MeshFilter>();
        filter.sharedMesh = mesh;
        obj.AddComponent<MeshRenderer>().sharedMaterial = material;
        return filter;
    }

    Transform Primitive(PrimitiveType type, string name, Material material)
    {
        var obj = GameObject.CreatePrimitive(type);
        obj.name = name;
        Destroy(obj.GetComponent<Collider>());
        obj.transform.SetParent(patientRoot, false);
        obj.GetComponent<Renderer>().sharedMaterial = material;
        return obj.transform;
    }

    void Setup()
    {
        patientRoot = new GameObject("P002 patient").transform;
        patientRoot.SetParent(transform, false);
        anatomyMaterial = Material("Local transparency", new Color(.46f, .72f, .88f), 0);
        differenceMaterial = Material("Red synthetic difference", new Color(1, .07f, .035f, .94f), 1, 3010);
        exteriorMesh = DisplayMesh("CT anatomy", patient.Baseline, anatomyMaterial);
        difference = DisplayMesh("Synthetic difference", patient.Difference, differenceMaterial)
            .GetComponent<MeshRenderer>();
        var internalMaterial = Material("Endoscope tissue", new Color(.88f,.66f,.48f), 2, 2000);
        internalMaterial.SetFloat("_DepthWrite", 1);
        interiorMesh = DisplayMesh("Internal camera anatomy", patient.Baseline, internalMaterial, InternalLayer);

        var scope = Material("Scope", new Color(.2f, .94f, 1), 3, 3020);
        shaft = Primitive(PrimitiveType.Cylinder, "Rigid shaft", scope);
        shaft.localScale = new Vector3(.0016f, ScopeMotion.ShaftLength / 2, .0016f);
        marker = Primitive(PrimitiveType.Sphere, "Scope tip", scope);
        marker.localScale = Vector3.one * .0022f;

        tipImage = new RenderTexture(640, 480, 24) { name = "Tip camera", antiAliasing = 1 };
        tipCamera = new GameObject("Tip camera").AddComponent<Camera>();
        tipCamera.transform.SetParent(patientRoot, false);
        tipCamera.cullingMask = 1 << InternalLayer;
        tipCamera.clearFlags = CameraClearFlags.SolidColor;
        tipCamera.backgroundColor = new Color(.04f, .025f, .025f, 1);
        tipCamera.nearClipPlane = .00015f;
        tipCamera.farClipPlane = .22f;
        tipCamera.fieldOfView = 2 * Mathf.Atan(Mathf.Tan(39 * Mathf.Deg2Rad) * .75f) * Mathf.Rad2Deg;
        tipCamera.targetTexture = tipImage;
        tipCamera.stereoTargetEye = StereoTargetEyeMask.None;

        mainCamera = new GameObject("Viewer").AddComponent<Camera>();
        mainCamera.tag = "MainCamera";
        mainCamera.cullingMask = ~(1 << InternalLayer);
        mainCamera.clearFlags = CameraClearFlags.SolidColor;
        mainCamera.nearClipPlane = .015f;
        mainCamera.farClipPlane = 20;
        if (xrMode)
        {
            mainCamera.backgroundColor = Color.clear;
            mainCamera.gameObject.AddComponent<ARCameraManager>();
            var session = new GameObject("AR Session");
            session.transform.SetParent(transform, false);
            session.AddComponent<ARSession>();
            var panelMat = Material("Tip screen", Color.white, 4, 3030);
            panelMat.mainTexture = tipImage;
            xrPanel = Primitive(PrimitiveType.Quad, "Tip screen", panelMat);
            xrPanel.SetParent(transform, false);
            xrPanel.localScale = new Vector3(.23f, .1725f, 1);
            patientRoot.gameObject.SetActive(false);
            xrPanel.gameObject.SetActive(false);
            Application.onBeforeRender += TrackHead;
        }
        else
        {
            var background = new GameObject("Desktop background").AddComponent<Camera>();
            background.transform.SetParent(transform, false);
            background.cullingMask = 0;
            background.depth = -10;
            background.clearFlags = CameraClearFlags.SolidColor;
            background.backgroundColor = Color.black;
            mainCamera.backgroundColor = new Color(.055f,.085f,.12f);
            mainCamera.rect = new Rect(.035f,.2f,.54f,.62f);
            mainCamera.orthographic = true;
            Bounds bounds = patient.Baseline.bounds;
            mainCamera.orthographicSize = bounds.size.magnitude * .52f;
            mainCamera.transform.position = bounds.center + new Vector3(.21f,.045f,-.035f);
            mainCamera.transform.LookAt(bounds.center, Vector3.up);
        }
    }

    void TrackHead()
    {
        Vector3 position;
        Quaternion orientation;
        if (InputSystem.GetDevice<XRHMD>() is XRHMD hmd && hmd.isTracked.isPressed)
        {
            position = hmd.centerEyePosition.ReadValue();
            orientation = hmd.centerEyeRotation.ReadValue();
        }
        else
        {
            var head = InputDevices.GetDeviceAtXRNode(XRNode.CenterEye);
            if (!head.TryGetFeatureValue(CommonUsages.devicePosition, out position) ||
                !head.TryGetFeatureValue(CommonUsages.deviceRotation, out orientation))
                return;
        }
        mainCamera.transform.SetPositionAndRotation(position, orientation);
        if (placed) return;
        Vector3 forward = Vector3.ProjectOnPlane(orientation * Vector3.forward, Vector3.up).normalized;
        if (forward.sqrMagnitude < .5f) return;
        var anchorRotation = Quaternion.LookRotation(forward, Vector3.up);
        patientRoot.SetPositionAndRotation(position + anchorRotation * new Vector3(-.095f,-.06f,.48f),
            anchorRotation * Quaternion.Euler(0,-70,0));
        xrPanel.SetPositionAndRotation(position + anchorRotation * new Vector3(.15f,-.035f,.58f), anchorRotation);
        patientRoot.gameObject.SetActive(true);
        xrPanel.gameObject.SetActive(true);
        placed = true;
    }

    void Update()
    {
        if (motion == null) return;
        if (xrMode)
        {
            var right = XRController.rightHand;
            var left = XRController.leftHand;
            Vector2 stick = right?.TryGetChildControl<Vector2Control>("thumbstick")?.ReadValue() ?? Vector2.zero;
            Vector2 transparency = left?.TryGetChildControl<Vector2Control>("thumbstick")?.ReadValue() ?? Vector2.zero;
            bool aim = right?.TryGetChildControl<ButtonControl>("triggerPressed")?.isPressed ?? false;
            bool swap = right?.TryGetChildControl<ButtonControl>("primaryButton")?.isPressed ?? false;
            bool reset = right?.TryGetChildControl<ButtonControl>("secondaryButton")?.isPressed ?? false;
            if (Mathf.Abs(transparency.y) > .2f) opacity = Mathf.Clamp(opacity + transparency.y * Time.deltaTime * .6f, 0,.9f);
            if (swap && !previousModel) modified = !modified;
            if (reset && !previousReset) { motion.Reset(); placed = false; }
            previousModel = swap;
            previousReset = reset;
            Move(stick, aim);
        }
        else if (Keyboard.current is Keyboard keyboard)
        {
            if (keyboard.mKey.wasPressedThisFrame) modified = !modified;
            if (keyboard.spaceKey.wasPressedThisFrame) { motion.Reset(); status = "Reset"; }
            if (keyboard.equalsKey.wasPressedThisFrame || keyboard.numpadPlusKey.wasPressedThisFrame)
                opacity = Mathf.Min(.9f, opacity + .06f);
            if (keyboard.minusKey.wasPressedThisFrame || keyboard.numpadMinusKey.wasPressedThisFrame)
                opacity = Mathf.Max(0, opacity - .06f);
            var aiming = new Vector2(Axis(keyboard.dKey.isPressed, keyboard.aKey.isPressed),
                Axis(keyboard.fKey.isPressed, keyboard.rKey.isPressed));
            if (aiming != Vector2.zero) Move(aiming, true);
            else Move(new Vector2(0, Axis(keyboard.wKey.isPressed, keyboard.sKey.isPressed)), false);
        }
        UpdatePose();
    }

    static float Axis(bool positive, bool negative) => (positive ? 1 : 0) - (negative ? 1 : 0);

    void Move(Vector2 stick, bool aim)
    {
        if (stick.sqrMagnitude <= .15f * .15f || (!aim && Mathf.Abs(stick.y) <= .15f)) return;
        status = motion.Input(stick, aim, Time.deltaTime) ? "Moving" : "Motion blocked";
    }

    void UpdatePose()
    {
        tipCamera.transform.localPosition = motion.CameraPosition;
        tipCamera.transform.localRotation = motion.Rotation;
        shaft.localPosition = (motion.Tail + motion.Tip) / 2;
        shaft.localRotation = Quaternion.FromToRotation(Vector3.up, motion.Forward);
        marker.localPosition = motion.Tip;
        Vector3 window = patientRoot.TransformPoint(motion.Tip);
        anatomyMaterial.SetVector("_Tip", window);
        anatomyMaterial.SetFloat("_WindowOpacity", opacity);
        differenceMaterial.SetVector("_Tip", window);
        exteriorMesh.sharedMesh = modified ? patient.Modified : patient.Baseline;
        interiorMesh.sharedMesh = exteriorMesh.sharedMesh;
        difference.enabled = modified;
    }

    void OnDestroy()
    {
        Application.onBeforeRender -= TrackHead;
        if (tipImage != null) { tipImage.Release(); Destroy(tipImage); }
    }

    void OnGUI()
    {
        if (xrMode || tipImage == null) return;
        float width = Screen.width, height = Screen.height;
        var heading = new GUIStyle(GUI.skin.label) {fontSize = 20, fontStyle = FontStyle.Bold};
        GUI.Label(new Rect(.035f*width, .055f*height, .9f*width, 30), "Virtual endoscope   /   NasalSeg P002", heading);
        GUI.Label(new Rect(.035f*width, .135f*height, .5f*width, 22), "CT anatomy and local transparency");
        GUI.Label(new Rect(.60f*width, .135f*height, .37f*width, 22), "Internal tip camera");
        var panel = new Rect(.60f*width,.18f*height,.365f*width,.62f*height);
        GUI.DrawTexture(panel, tipImage, ScaleMode.ScaleToFit);
        var mode = modified ? "Synthetic modification" : "Baseline";
        GUI.Label(new Rect(.035f*width,.825f*height,.93f*width,25),
            $"{mode}   •   Opacity {opacity:0.00}   •   {status}   •   Distance from entry {motion.Tip.magnitude*1000:0.0} mm");
        GUI.Label(new Rect(.035f*width,.885f*height,.93f*width,25),
            "W / S   insert and retract     A / D / R / F   aim     M   model     + / -   opacity     Space   reset");
    }
}
