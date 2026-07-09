"""Validate the constructed FLF2V graph end-to-end on the live pod (no Qdrant needed).

Uploads two distinct solid-colour frames, wires them into the graph's first/last frame
slots via the real slot inference, submits, polls /history, and confirms a video output.
Proves the agent can drive the FLF2V graph — the Phase-0 exit criterion.
"""
import asyncio
import json
import pathlib
import struct
import sys
import zlib

from visual_generation.comfyui_client import ComfyUIClient
from visual_generation.graph_build import apply_source_filenames, write_slot
from visual_generation.slot_inference import infer_slots

ENDPOINT = sys.argv[1]
GRAPH = pathlib.Path("packages/visual-generation/workflows/wan2.2-flf2v-14B-lightx2v-api.json")


def _png(color: tuple[int, int, int], w: int = 512, h: int = 512) -> bytes:
    """A valid solid-colour RGB PNG, pure-stdlib (no Pillow dependency)."""
    r, g, b = color
    row = bytes([0]) + bytes([r, g, b] * w)  # filter byte 0 + pixels
    raw = row * h

    def chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)  # 8-bit, colour type 2 (RGB)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


async def main() -> int:
    client = ComfyUIClient(ENDPOINT, timeout=60.0)
    graph = json.loads(GRAPH.read_text())
    slots = infer_slots(graph).slot_map

    first = await client.upload_image(_png((30, 60, 120)), "flf2v_first.png")
    last = await client.upload_image(_png((160, 90, 40)), "flf2v_last.png")
    print(f"uploaded: first={first} last={last}")

    unmapped = apply_source_filenames(graph, slots, first_frame=first, last_frame=last)
    assert not unmapped, f"unmapped slots: {unmapped}"
    # Keep it cheap: 33 frames (4n+1) is enough to prove the pipeline.
    write_slot(graph, slots, "length", 33)

    prompt_id = await client.submit(graph)
    print(f"submitted prompt_id={prompt_id}; polling /history (video render takes minutes)...")

    for i in range(120):  # up to ~20 min at 10s interval
        record = await client.history(prompt_id)
        if record and record.get("outputs"):
            vids = client.videos_from_history(record)
            imgs = client.images_from_history(record)
            print(f"DONE: videos={vids} images={imgs}")
            status = record.get("status", {})
            print(f"status={status.get('status_str')} completed={status.get('completed')}")
            if vids:
                print("VALIDATION PASS: FLF2V graph produced a video output.")
                return 0
            print("VALIDATION FAIL: run completed but no video output found.")
            return 2
        await asyncio.sleep(10)
    print("VALIDATION TIMEOUT: no outputs after ~20 min.")
    return 3


sys.exit(asyncio.run(main()))
