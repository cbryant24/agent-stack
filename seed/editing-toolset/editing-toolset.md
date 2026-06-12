# Editing Toolset

First-party facts about the director's editing toolset. Each `##` section below becomes one
`user_knowledge` candidate entry (`domain=editing_toolset`) at ingest time — heading hierarchy
becomes `topic_tags`, body becomes the `statement`. Edit freely before ingesting: correct
versions, add constraints, delete anything wrong, add tools.

## DaVinci Resolve — free version

The director edits in DaVinci Resolve (free version), not Studio. Technique recommendations
must be achievable in the free version by default; where a technique is Studio-only or
materially faster in Studio, flag it as an upgrade note rather than assuming availability.
Version: 20.3.1 Build 6.

### Free-version constraint — no noise reduction (Color page)

The free tier doesn't include the Noise Reduction panel on the Color page; Studio gets
motion-estimated temporal NR that is genuinely competitive with Topaz for some footage. The
director works around this with a headless Topaz Video AI preprocessing step (see the Topaz
doc in this folder) rather than Resolve's built-in temporal/spatial NR.

### Free-version constraint — no blur/mist effects

The Blur and Mist tools on the Color page are Studio-only, so a diffusion glow / "lo-fi
softness" look can't be added natively in the free version. Workarounds the director uses:
a Fusion-based blur approach (free but complex), or baking softness into an exported LUT
applied via ffmpeg.

### Free-version constraint — export codec restrictions

The free tier doesn't export ProRes, DNxHR, or H.265/HEVC. The director's workaround is
H.264 via the Deliver page with a bitrate cap; 4K HEVC source footage cannot be matched
codec-for-codec on export without Studio.

### Free-version constraint — most Resolve FX are Studio-only

The majority of effects in the Effects Library on the Color page (film grain, lens flares,
vignette-via-effects) are locked in the free version — notably there is no Film Grain
effect. The director's workaround for grain is a Fusion composition node, which is free but
not the straightforward tool.

## ffmpeg

ffmpeg is installed and used from the command line (macOS, iTerm2/zsh). It is the preferred
tool for scriptable media operations: frame extraction, transcoding, trims, concatenation,
speed changes, and format conversion. Terminal-based, scriptable solutions using ffmpeg are
preferred over GUI alternatives where quality is equivalent.
Version: 8.1.1.

## mpv

mpv is the playback and review tool for footage and renders, used from the command line.
Version: 0.41.0.

## Platform

Editing happens on a Mac (Apple Silicon M1). A Raspberry Pi exists in the environment but is
not part of the editing workflow.
