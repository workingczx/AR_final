using System.IO;
using UnityEngine;
using UnityEngine.Rendering;

public sealed class PatientGeometry
{
    public readonly Mesh Baseline, Modified, Difference;
    public readonly SurfaceTree[] Walls;

    public PatientGeometry(byte[] bytes)
    {
        using var reader = new BinaryReader(new MemoryStream(bytes));
        if (new string(reader.ReadChars(4)) != "P002")
            throw new InvalidDataException("Expected P002 geometry");
        Baseline = ReadMesh(reader, "Baseline");
        Modified = ReadMesh(reader, "Modified");
        Difference = ReadMesh(reader, "Synthetic difference");
        Walls = new[] { new SurfaceTree(reader), new SurfaceTree(reader) };
        if (reader.BaseStream.Position != reader.BaseStream.Length)
            throw new InvalidDataException("Unexpected patient geometry data");
    }

    static Mesh ReadMesh(BinaryReader reader, string name)
    {
        var vertices = new Vector3[reader.ReadInt32()];
        var indices = new int[reader.ReadInt32()];
        for (int i = 0; i < vertices.Length; i++) vertices[i] = ReadVector(reader);
        for (int i = 0; i < indices.Length; i++) indices[i] = reader.ReadInt32();
        var mesh = new Mesh { name = name, indexFormat = IndexFormat.UInt32 };
        mesh.vertices = vertices;
        mesh.triangles = indices;
        mesh.RecalculateNormals();
        return mesh;
    }

    static Vector3 ReadVector(BinaryReader r) =>
        new Vector3(r.ReadSingle(), r.ReadSingle(), r.ReadSingle());

    public sealed class SurfaceTree
    {
        struct Node
        {
            public Vector3 Lower, Upper;
            public int Left, Right, Start, Count;
        }

        readonly Node[] nodes;
        readonly Vector3[] triangleVertices;

        public SurfaceTree(BinaryReader reader)
        {
            nodes = new Node[reader.ReadInt32()];
            triangleVertices = new Vector3[3 * reader.ReadInt32()];
            for (int i = 0; i < nodes.Length; i++)
            {
                nodes[i] = new Node {
                    Lower = ReadVector(reader), Upper = ReadVector(reader),
                    Left = reader.ReadInt32(), Right = reader.ReadInt32(),
                    Start = reader.ReadInt32(), Count = reader.ReadInt32()
                };
            }
            for (int i = 0; i < triangleVertices.Length; i++)
                triangleVertices[i] = ReadVector(reader);
        }

        public bool IsClear(Vector3 point, float distance) =>
            !WithinDistance(0, point, distance * distance);

        bool WithinDistance(int index, Vector3 point, float squaredDistance)
        {
            var node = nodes[index];
            var offset = Vector3.Max(Vector3.zero, Vector3.Max(node.Lower - point, point - node.Upper));
            if (offset.sqrMagnitude > squaredDistance) return false;
            if (node.Count == 0)
                return WithinDistance(node.Left, point, squaredDistance) ||
                       WithinDistance(node.Right, point, squaredDistance);
            for (int i = 3 * node.Start; i < 3 * (node.Start + node.Count); i += 3)
            {
                if (DistanceToTriangle(point, triangleVertices[i], triangleVertices[i + 1],
                        triangleVertices[i + 2]) <= squaredDistance)
                    return true;
            }
            return false;
        }

        static float DistanceToEdge(Vector3 point, Vector3 a, Vector3 b)
        {
            var edge = b - a;
            float t = Mathf.Clamp01(Vector3.Dot(point - a, edge) / edge.sqrMagnitude);
            return (point - a - t * edge).sqrMagnitude;
        }

        static float DistanceToTriangle(Vector3 point, Vector3 a, Vector3 b, Vector3 c)
        {
            var normal = Vector3.Cross(b - a, c - a);
            if (Vector3.Dot(Vector3.Cross(b - a, point - a), normal) >= 0 &&
                Vector3.Dot(Vector3.Cross(c - b, point - b), normal) >= 0 &&
                Vector3.Dot(Vector3.Cross(a - c, point - c), normal) >= 0)
            {
                float projection = Vector3.Dot(point - a, normal);
                return projection * projection / normal.sqrMagnitude;
            }
            return Mathf.Min(DistanceToEdge(point, a, b),
                Mathf.Min(DistanceToEdge(point, b, c), DistanceToEdge(point, c, a)));
        }
    }
}
