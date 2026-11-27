shader_type canvas_item;
// F8 R1 retro post-process (GAME_SPEC §4.6 "global pixelation/quantization post-process"; ASSETFABRIC_SPEC §3 R1).
// One full-screen pass on a CanvasLayer between the world (layer 0) and the HUD (layer 2):
//   1. pixelate — sample the screen once per logical pixel (cell centre) of the profile's logical resolution; the base
//      viewport is an integer multiple (Retro autoload + integer stretch), so every logical pixel is an exact N×N block;
//   2. colour-blind remap — the active G-A11Y-01 variant (exact PatternVault colour → colour table, same as
//      palette_remap.gdshader) is applied *before* quantisation, so variants survive every profile;
//   3. quantise — 8-bit RGB → profile palette through the forge-built 64³ LUT (index = value >> 2, texelFetch, no
//      filtering): bit-identical to forge/retro/colour.py apply_lut, which the V1 harness uses to check frames;
//   4. optional scanlines — the lower half of every logical row darkened by `scanline` (0 = off, the default).
uniform sampler2D screen_tex : hint_screen_texture, filter_nearest;
uniform sampler2D lut : filter_nearest;
uniform vec2 logical = vec2(320.0, 180.0);
uniform float scanline = 0.0;
uniform vec3 src[24];
uniform vec3 dst[24];
uniform int count = 0;
uniform float tolerance = 0.012;

void fragment() {
	vec2 cell = floor(SCREEN_UV * logical);
	// textureLod 0: the uv is constant per cell, so screen-space derivatives jump at cell edges that fall inside a 2×2
	// pixel quad (odd scales); plain texture() would then pick a blurred mip there.
	vec3 c = textureLod(screen_tex, (cell + 0.5) / logical, 0.0).rgb;
	for (int i = 0; i < 24; i++) {
		if (i >= count) {
			break;
		}
		vec3 d = abs(c - src[i]);
		if (max(d.r, max(d.g, d.b)) < tolerance) {
			c = dst[i];
			break;
		}
	}
	ivec3 q = ivec3(floor(c * 255.0 + 0.5)) / 4;
	ivec2 t = ivec2((q.b % 8) * 64 + q.r, (q.b / 8) * 64 + q.g);
	vec3 o = texelFetch(lut, t, 0).rgb;
	if (scanline > 0.0 && fract(SCREEN_UV.y * logical.y) >= 0.5) {
		o *= 1.0 - scanline;
	}
	COLOR = vec4(o, 1.0);
}
