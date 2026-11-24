using UnityEngine;

public sealed class ScopeMotion
{
    public const float ShaftLength = 0.014f;
    public const float Radius = 0.0008f;
    public const float CameraOffset = 0.0005f;
    public const float WindowRadius = 0.012f;
    const float SampleSpacing = 0.00025f;
    const float Margin = 0.00005f;
    readonly PatientGeometry.SurfaceTree[] walls;

    public Vector3 Tip { get; private set; }
    public Quaternion Rotation { get; private set; } = Quaternion.identity;
    public Vector3 Forward => Rotation * Vector3.forward;
    public Vector3 Tail => Tip - Forward * ShaftLength;
    public Vector3 CameraPosition => Tip + Forward * CameraOffset;

    public ScopeMotion(PatientGeometry geometry)
    {
        // The exported P002 origin is the Python-certified interior seed of
        // both permitted-space meshes. An accepted continuous sweep cannot
        // leave either volume without crossing its surface.
        walls = geometry.Walls;
        if (!Sweep(Tip, Rotation)) throw new System.InvalidOperationException("P002 entry clearance");
    }

    public void Reset()
    {
        Tip = Vector3.zero;
        Rotation = Quaternion.identity;
    }

    public bool Request(Vector3 destination, Quaternion orientation)
    {
        if (!Sweep(destination, orientation)) return false;
        Tip = destination;
        Rotation = orientation;
        return true;
    }

    public bool Input(Vector2 stick, bool aim, float seconds)
    {
        float strength = Mathf.Clamp01((stick.magnitude - .15f) / .85f);
        if (strength == 0) return true;
        stick = stick.normalized * strength * Mathf.Clamp(seconds, 0, .1f);
        if (aim)
        {
            var yaw = Quaternion.AngleAxis(stick.x * 24, Vector3.up);
            var pitch = Quaternion.AngleAxis(-stick.y * 24, Vector3.right);
            return Request(Tip, Rotation * yaw * pitch);
        }
        return Request(Tip + Forward * (stick.y * .006f), Rotation);
    }

    bool Sweep(Vector3 destination, Quaternion orientation)
    {
        float arc = Quaternion.Angle(Rotation, orientation) * Mathf.Deg2Rad;
        float bound = Vector3.Distance(Tip, destination) + ShaftLength * arc;
        int timeSteps = Mathf.Max(1, Mathf.CeilToInt(bound / SampleSpacing));
        int axisSteps = Mathf.CeilToInt(ShaftLength / SampleSpacing);
        float threshold = Radius + Margin + .5f * (bound / timeSteps + ShaftLength / axisSteps);

        for (int t = 0; t <= timeSteps; t++)
        {
            float fraction = (float)t / timeSteps;
            var center = Vector3.Lerp(Tip, destination, fraction);
            var shaft = Quaternion.Slerp(Rotation, orientation, fraction) * Vector3.back * ShaftLength;
            for (int i = 0; i <= axisSteps; i++)
            {
                var point = center + shaft * ((float)i / axisSteps);
                foreach (var wall in walls)
                    if (!wall.IsClear(point, threshold)) return false;
            }
        }
        return true;
    }
}
