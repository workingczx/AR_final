Shader "Endoscope/Surface"
{
    Properties
    {
        _Color ("Color", Color) = (1,1,1,1)
        _MainTex ("Image", 2D) = "white" {}
        _Tip ("Tip", Vector) = (0,0,0,0)
        _WindowRadius ("Window radius", Float) = .012
        _WindowOpacity ("Window opacity", Range(0,1)) = .22
        _Mode ("Mode", Float) = 0
        _DepthWrite ("Depth write", Float) = 0
        _DepthTest ("Depth test", Float) = 4
    }
    SubShader
    {
        Tags { "Queue"="Transparent" "RenderType"="Transparent" }
        Pass
        {
            Cull Off
            ZWrite [_DepthWrite]
            ZTest [_DepthTest]
            Blend SrcAlpha OneMinusSrcAlpha, One OneMinusSrcAlpha
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_instancing
            #include "UnityCG.cginc"
            sampler2D _MainTex;
            float4 _Color, _Tip;
            float _WindowRadius, _WindowOpacity, _Mode;
            struct Input { float4 vertex : POSITION; float3 normal : NORMAL;
                float2 uv : TEXCOORD0; UNITY_VERTEX_INPUT_INSTANCE_ID };
            struct Output { float4 clip : SV_POSITION; float3 world : TEXCOORD0;
                float3 normal : TEXCOORD1; float2 uv : TEXCOORD2;
                UNITY_VERTEX_OUTPUT_STEREO };
            Output vert(Input input)
            {
                Output o;
                UNITY_SETUP_INSTANCE_ID(input);
                UNITY_INITIALIZE_OUTPUT(Output, o);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);
                o.clip = UnityObjectToClipPos(input.vertex);
                o.world = mul(unity_ObjectToWorld, input.vertex).xyz;
                o.normal = UnityObjectToWorldNormal(input.normal);
                o.uv = input.uv;
                return o;
            }
            float4 frag(Output input) : SV_Target
            {
                UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(input);
                if (_Mode > 3.5) return tex2D(_MainTex, input.uv);
                if (_Mode > 2.5) return _Color;
                float distanceToWindow = length(input.world - _Tip.xyz);
                float weight = saturate((_WindowRadius - distanceToWindow) / .002);
                if (_Mode > .5 && _Mode < 1.5)
                {
                    clip(weight - .001);
                    return float4(_Color.rgb, _Color.a * weight);
                }
                float3 direction = _WorldSpaceCameraPos.xyz - input.world;
                float diffuse = abs(dot(normalize(input.normal), normalize(direction)));
                if (_Mode > 1.5)
                {
                    float radius = length(direction) / .012;
                    return float4(_Color.rgb * (.15 + .85 * diffuse / (1 + radius*radius)), 1);
                }
                return float4(_Color.rgb * (.42 + .58 * diffuse), lerp(.9, _WindowOpacity, weight));
            }
            ENDCG
        }
    }
}
