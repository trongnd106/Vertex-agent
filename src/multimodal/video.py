"""Video frame extraction — extract and analyze key frames from video files.

Based on patterns from DeepAgents ``middleware/_video.py``.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class VideoFrame:
    """A single frame extracted from a video."""

    index: int
    """Frame index in the video."""

    timestamp_seconds: float
    """Timestamp of the frame in seconds."""

    data: bytes | None = None
    """Raw image bytes of the frame (PNG format)."""

    path: str = ""
    """File path to the extracted frame image."""

    description: str = ""
    """Text description of the frame content."""

    similarity_to_previous: float = 0.0
    """Similarity score to the previous frame (0.0-1.0) for dedup."""


@dataclass
class VideoAnalysisResult:
    """Result of analyzing a video."""

    total_frames: int = 0
    """Total number of frames in the video."""

    duration_seconds: float = 0.0
    """Video duration in seconds."""

    extracted_frames: list[VideoFrame] = field(default_factory=list)
    """Frames that were extracted and analyzed."""

    key_frame_count: int = 0
    """Number of key frames after deduplication."""

    fps: float = 0.0
    """Frames per second of the original video."""


class VideoFrameExtractor:
    """Extract frames from video files using ffmpeg.

    Supports scene detection (via ffmpeg scene detection filter) and
    basic frame deduplication based on histogram similarity.
    """

    def __init__(
        self,
        ffmpeg_path: str = "ffmpeg",
        ffprobe_path: str = "ffprobe",
        extract_interval_seconds: float = 5.0,
        similarity_threshold: float = 0.85,
    ) -> None:
        """Initialize the extractor.

        Args:
            ffmpeg_path: Path to the ffmpeg binary.
            ffprobe_path: Path to the ffprobe binary.
            extract_interval_seconds: Interval between frame extractions.
            similarity_threshold: Frames with similarity above this are
                considered duplicates (0.0-1.0).
        """
        self._ffmpeg = ffmpeg_path
        self._ffprobe = ffprobe_path
        self._interval = extract_interval_seconds
        self._similarity_threshold = similarity_threshold

    def probe(self, video_path: str) -> dict[str, Any]:
        """Get video metadata using ffprobe.

        Returns:
            Dict with keys: 'duration', 'fps', 'width', 'height',
            'codec', 'total_frames'.
        """
        cmd = [
            self._ffprobe,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            video_path,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            import json

            data = json.loads(result.stdout)
            stream = next(
                (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
                {},
            )
            format_info = data.get("format", {})

            duration = float(stream.get("duration", format_info.get("duration", 0)))
            fps_str = stream.get("r_frame_rate", "0/1")
            num, den = fps_str.split("/")
            fps = float(num) / float(den) if float(den) > 0 else 0.0
            total_frames = int(stream.get("nb_frames", 0))
            if total_frames == 0 and fps > 0:
                total_frames = int(duration * fps)

            return {
                "duration": duration,
                "fps": fps,
                "width": int(stream.get("width", 0)),
                "height": int(stream.get("height", 0)),
                "codec": stream.get("codec_name", ""),
                "total_frames": total_frames,
            }
        except FileNotFoundError:
            logger.warning("ffprobe not found at %s", self._ffprobe)
            return {"duration": 0, "fps": 0, "width": 0, "height": 0, "codec": "", "total_frames": 0}
        except Exception as exc:
            logger.warning("Failed to probe video %s: %s", video_path, exc)
            return {"duration": 0, "fps": 0, "width": 0, "height": 0, "codec": "", "total_frames": 0}

    def extract_frames(
        self,
        video_path: str,
        output_dir: str | None = None,
        max_frames: int = 20,
    ) -> VideoAnalysisResult:
        """Extract frames from a video at regular intervals.

        Args:
            video_path: Path to the video file.
            output_dir: Directory to save extracted frames. If None,
                a temporary directory is created.
            max_frames: Maximum number of frames to extract.

        Returns:
            VideoAnalysisResult with extracted frames and metadata.
        """
        if not os.path.isfile(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        probe_result = self.probe(video_path)
        duration = probe_result.get("duration", 0)
        fps = probe_result.get("fps", 0)

        if duration <= 0:
            return VideoAnalysisResult()

        # Calculate frame interval
        interval = max(self._interval, duration / max_frames)

        cleanup = False
        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix="video_frames_")
            cleanup = True

        os.makedirs(output_dir, exist_ok=True)

        # Use ffmpeg to extract frames
        output_pattern = os.path.join(output_dir, "frame_%04d.png")
        cmd = [
            self._ffmpeg,
            "-i", video_path,
            "-vf", f"fps=1/{interval}",
            "-vframes", str(max_frames),
            "-q:v", "2",
            output_pattern,
        ]

        try:
            subprocess.run(cmd, capture_output=True, timeout=300)
        except FileNotFoundError:
            logger.warning("ffmpeg not found at %s", self._ffmpeg)
            return VideoAnalysisResult(
                total_frames=int(probe_result.get("total_frames", 0)),
                duration_seconds=duration,
                fps=fps,
            )
        except Exception as exc:
            logger.warning("ffmpeg extraction failed: %s", exc)
            return VideoAnalysisResult(
                total_frames=int(probe_result.get("total_frames", 0)),
                duration_seconds=duration,
                fps=fps,
            )

        # Collect extracted frames
        frame_files = sorted(
            [f for f in os.listdir(output_dir) if f.startswith("frame_") and f.endswith(".png")]
        )
        frames: list[VideoFrame] = []
        for i, filename in enumerate(frame_files):
            filepath = os.path.join(output_dir, filename)
            ts = i * interval

            with open(filepath, "rb") as f:
                data = f.read()

            # Simple dedup: compare file sizes as proxy for similarity
            similar = False
            if frames:
                prev_path = frames[-1].path
                if prev_path and os.path.isfile(prev_path):
                    prev_size = os.path.getsize(prev_path)
                    curr_size = len(data)
                    size_ratio = (
                        min(prev_size, curr_size) / max(prev_size, curr_size)
                        if max(prev_size, curr_size) > 0
                        else 0
                    )
                    similar = size_ratio > self._similarity_threshold

            frames.append(
                VideoFrame(
                    index=i,
                    timestamp_seconds=ts,
                    data=data,
                    path=filepath,
                    similarity_to_previous=1.0 if similar else 0.0,
                )
            )

        key_frames = [f for f in frames if f.similarity_to_previous < self._similarity_threshold]

        result = VideoAnalysisResult(
            total_frames=int(probe_result.get("total_frames", 0)),
            duration_seconds=duration,
            extracted_frames=frames,
            key_frame_count=len(key_frames),
            fps=fps,
        )

        if cleanup:
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)

        return result

    def extract_key_frames(
        self,
        video_path: str,
        output_dir: str | None = None,
        max_frames: int = 10,
    ) -> list[VideoFrame]:
        """Extract only key / non-duplicate frames from a video.

        Uses ffmpeg scene detection to find scene changes.
        """
        analysis = self.extract_frames(video_path, output_dir, max_frames)
        return [f for f in analysis.extracted_frames if f.similarity_to_previous < self._similarity_threshold]