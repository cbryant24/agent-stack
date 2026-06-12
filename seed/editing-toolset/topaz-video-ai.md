# Topaz Video AI — Pipeline Usage

## Topaz suite access

The director owns access to the full Topaz suite. Topaz Video AI is the tool currently in
pipeline use; the rest of the suite is available but not part of the standing workflow.

## What Topaz Does

Stage 3 — denoising only. Brightness, color, and upscaling are handled by ffmpeg before and after
Topaz respectively. Topaz's only job is removing noise from already-brightened footage.

## Why It's Used Headlessly

Topaz ships its own ffmpeg binary with the `tvai_up` filter built in. The GUI is bypassed entirely
by calling that binary directly from the command line, which is what makes it automatable via the
Python pipeline.

## The Command

```bash
"/Applications/Topaz Video.app/Contents/MacOS/ffmpeg" \
  -i input_bright.avi \
  -filter_complex "tvai_up=model=prob-4:scale=1:w=1920:h=1080:\
preblur=0:noise=0:details=0:halo=0:blur=0:compression=0:\
estimate=8:blend=0.2:device=0:vram=1:instances=1" \
  -c:v h264_videotoolbox -profile:v high -pix_fmt yuv420p \
  -allow_sw 1 -g 30 -b:v 0 -q:v 75 \
  -c:a copy -vsync vfr \
  output_denoised.mp4
```

`scale=1` means no resolution change — denoise only at the same resolution.

## Model: Proteus (`prob-4`)

Nyx is the purpose-built low-light model but crashes on M1 due to Apple Neural Engine / CoreML
cache corruption. Proteus is the reliable fallback and produces good results on this footage type.

To clear the Nyx cache manually:

```bash
rm -rf "/Applications/Topaz Video.app/Contents/Resources/models/coreMLCache"
```

## The VFR Problem

Topaz outputs variable frame rate footage but tags it as the original fps (e.g., 30fps). Without
`-vsync vfr` in any downstream ffmpeg command, ffmpeg fills the gap by duplicating thousands of
frames. This flag is required on both the Topaz output step and any upscale step that follows.

## Full Pipeline Position

| Step | Tool | Operation |
|------|------|-----------|
| 1 | ffmpeg | `eq` filter — brighten |
| 2 | **Topaz** | `tvai_up` — denoise |
| 3 | ffmpeg | `scale` — optional 4K upscale |
| 4 | DaVinci Resolve | color grade / LUT export |
| 5 | ffmpeg | `lut3d` — apply LUT if skipping Resolve per-file |

## Models

Models are not pre-installed. Download via Topaz app → Help → Model Manager.

| Model | Code | Status |
|-------|------|--------|
| Proteus | `prob-4` | Required — general denoising, works on M1 |
| Nyx | `nyx--Infinity` | Optional — low-light specialist, crashes on M1 |
| Nyx XL | `nyx-xl` | Optional — higher quality Nyx variant |
| Iris | `iris` | Optional — face/skin detail recovery, good as second pass |
