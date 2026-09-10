# ASCII Video — Animated ASCII

Convert video/audio files to colored ASCII animations (MP4/GIF).

## Prerequisites
```bash
pip install pillow numpy
# ffmpeg for frame extraction
```

## Basic Conversion

```python
from PIL import Image
import numpy as np

def image_to_ascii(img, cols=100):
    """Convert a PIL Image to ASCII string."""
    # Gray pixel values → ASCII characters
    chars = "@%#*+=-:. "
    img = img.resize((cols, int(img.height * cols / img.width * 0.5)))
    img = img.convert('L')  # grayscale
    pixels = np.array(img)
    result = ''
    for row in pixels:
        for pixel in row:
            idx = int(pixel / 255 * (len(chars) - 1))
            result += chars[idx]
        result += '\n'
    return result
```

## Color Modes

1. **Grayscale** — `img.convert('L')`, classic ASCII look
2. **ANSI color** — Use escape codes `\033[38;2;R;G;Bm` for terminal colors
3. **HTML color** — `<span style="color: rgb(R,G,B)">` for web output

## Frame Rate Tuning

- Standard: 10-15 FPS
- Slow scenes: 8-10 FPS
- Fast action: 15-24 FPS

## Output Formats

| Format | Use Case |
|--------|----------|
| MP4 | Social media, embedding |
| GIF | Quick sharing, lightweight |
| Terminal | Live playback in TTY |

## Pitfalls
1. Large frames = large files — keep `--width 80-120` range
2. Complex videos lose detail in ASCII — high contrast scenes work best
3. Black/white pixel-to-char mapping subjective — adjust thresholds per video
