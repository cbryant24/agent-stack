"""PySceneDetect ContentDetector wrapper — returns scene list as [(start, end), ...]."""

from __future__ import annotations

from pathlib import Path


def detect_scenes_pyscenedetect(video: Path) -> list[tuple[float, float]]:
    """Return the ContentDetector's scene list in seconds.

    Returns a list of (start_sec, end_sec) pairs. PySceneDetect's ContentDetector
    returns a list of (FrameTimecode, FrameTimecode) pairs; we convert to seconds.
    """
    from scenedetect import ContentDetector, SceneManager, open_video  # local import: heavy dep

    video_stream = open_video(str(video))
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector())
    scene_manager.detect_scenes(video_stream, show_progress=False)
    scenes = scene_manager.get_scene_list()
    return [(float(start.seconds), float(end.seconds)) for start, end in scenes]
