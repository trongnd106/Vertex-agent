"""Image processing — read, analyze, and handle images in conversations."""

from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Image format detection via magic bytes (replaces deprecated imghdr)
_IMAGE_MAGIC: dict[bytes, str] = {
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpeg",
    b"GIF87a": "gif",
    b"GIF89a": "gif",
    b"RIFF": "webp",  # WebP starts with RIFF....WEBP
    b"\x00\x00\x01\x00": "ico",
}


def _detect_image_format(data: bytes) -> str | None:
    """Detect image format from raw bytes using magic byte signatures."""
    for magic, fmt in _IMAGE_MAGIC.items():
        if data.startswith(magic):
            if fmt == "webp":
                # Verify it's actually WebP (RIFF container, WEBP at offset 8)
                if data[8:12] == b"WEBP":
                    return "webp"
                continue  # RIFF but not WebP
            return fmt
    return None


@dataclass
class ImageAnalysis:
    """Result of analyzing an image."""

    description: str = ""
    """Text description of the image."""

    labels: list[str] = field(default_factory=list)
    """Detected labels / objects in the image."""

    text_extracted: str = ""
    """Text extracted from the image (OCR)."""

    width: int = 0
    """Image width in pixels."""

    height: int = 0
    """Image height in pixels."""

    format: str = ""
    """Image format e.g. 'png', 'jpeg', 'gif'."""

    size_bytes: int = 0
    """File size in bytes."""


class ImageProcessor:
    """Handle image loading, validation, and analysis.

    Supports base64-encoded images (inline in conversations) and
    file-path references from tool results.
    """

    SUPPORTED_FORMATS = {"png", "jpeg", "jpg", "gif", "webp"}

    @staticmethod
    def is_supported_format(data: bytes) -> bool:
        """Check if the given bytes represent a supported image format."""
        fmt = _detect_image_format(data[:32])
        return fmt in ImageProcessor.SUPPORTED_FORMATS

    @staticmethod
    def decode_base64(data: str) -> bytes:
        """Decode a base64-encoded image string.

        Handles both bare base64 and data URI format
        (e.g. ``data:image/png;base64,...``).
        """
        if data.startswith("data:image"):
            # data:image/png;base64,<actual_data>
            _, encoded = data.split(",", 1)
        else:
            encoded = data
        return base64.b64decode(encoded)

    @staticmethod
    def encode_base64(data: bytes, fmt: str = "png") -> str:
        """Encode image bytes to a data URI string."""
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:image/{fmt};base64,{encoded}"

    @staticmethod
    def load_image(source: str | bytes) -> tuple[bytes, str]:
        """Load image from a file path or bytes.

        Args:
            source: File path string or raw image bytes.

        Returns:
            Tuple of (image_bytes, format_string).

        Raises:
            FileNotFoundError: If the file path doesn't exist.
            ValueError: If the format is unsupported.
        """
        if isinstance(source, str):
            if not os.path.isfile(source):
                raise FileNotFoundError(f"Image file not found: {source}")
            with open(source, "rb") as f:
                data = f.read()
        else:
            data = source

        fmt = _detect_image_format(data[:32]) or "png"
        if fmt not in ImageProcessor.SUPPORTED_FORMATS:
            raise ValueError(
                f"Unsupported image format: {fmt}. "
                f"Supported: {', '.join(sorted(ImageProcessor.SUPPORTED_FORMATS))}"
            )
        return data, fmt

    @staticmethod
    def get_image_info(data: bytes) -> dict[str, Any]:
        """Extract basic image metadata without full decoding.

        Returns:
            Dict with 'format', 'size_bytes' keys.
        """
        fmt = _detect_image_format(data[:32]) or "unknown"
        return {
            "format": fmt,
            "size_bytes": len(data),
        }

    @staticmethod
    def is_base64_image(data: str) -> bool:
        """Check if a string looks like a base64-encoded image."""
        if data.startswith("data:image"):
            return True
        try:
            decoded = base64.b64decode(data, validate=True)
            return _detect_image_format(decoded[:32]) is not None
        except Exception:
            return False

    @staticmethod
    def extract_images_from_messages(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Extract image references from a list of conversation messages.

        Looks for:
        - ``data:image/...`` URIs in message content
        - ``image_url`` type content blocks (OpenAI/Anthropic format)
        - Tool results containing image file paths

        Returns:
            List of dicts with keys: 'source' (str), 'format' (str),
            'message_idx' (int), 'type' (str).
        """
        images: list[dict[str, Any]] = []
        for idx, msg in enumerate(messages):
            content = msg.get("content", "")
            if isinstance(content, str):
                if "data:image/" in content:
                    images.append({
                        "source": "base64",
                        "message_idx": idx,
                        "type": "inline",
                    })
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "image_url":
                            images.append({
                                "source": block.get("image_url", {}).get("url", ""),
                                "format": block.get("image_url", {}).get("detail", "auto"),
                                "message_idx": idx,
                                "type": "image_url",
                            })
                        elif block.get("type") == "tool_result":
                            result_data = str(block.get("content", ""))
                            for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                                if ext in result_data.lower():
                                    images.append({
                                        "source": result_data,
                                        "message_idx": idx,
                                        "type": "tool_result_image",
                                    })
                                    break
        return images