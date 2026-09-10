---
name: diagram-tools
description: "Create hand-drawn Excalidraw diagrams and dark-themed SVG architecture/cloud/infra diagrams. Two visual diagramming approaches for different needs."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [Diagrams, Architecture, Excalidraw, SVG, Cloud, Infrastructure, Design]
    related_skills: [web-design-prototyping]
---

# Diagram Tools — Visual Artifacts

Three complementary visual output approaches: hand-drawn diagrams (Excalidraw), clean SVG architecture diagrams, and terminal/ASCII art.

## Excalidraw — Hand-Drawn Diagrams

Use when you want informal, hand-drawn style diagrams for architecture, flow, sequence, or brainstorming.

**Key features:**
- JSON format (.excalidraw), hand-drawn sketch style
- Elements: rectangles, diamonds, arrows, text, images
- Upload script via `cryptography` pip package

**Quick start:**
See `references/excalidraw.md` for element types, upload workflow, and examples.

## Architecture Diagrams — SVG Cloud/Infra

Use when you need clean, dark-themed, professional SVG architecture diagrams as self-contained HTML.

**Key features:**
- Dark theme with JetBrains Mono font
- Color-coded component types (compute, storage, network, security, database)
- Self-contained HTML — works offline, no external assets

**Quick start:**
See `references/architecture-diagram.md` for component types, layout patterns, and templates.

## ASCII & Terminal Art

Use when you need text-based visual output: banner text, decorative borders, ASCII art from images, or animated ASCII video.

**Tools:**

### pyfiglet (banner text)
```bash
pip install pyfiglet
python3 -c "import pyfiglet; print(pyfiglet.figlet_format('Hello', font='slant'))"
```

### cowsay (terminal speech)
```bash
cowsay "Hello from Hermes"
```

### boxes (decorative borders)
```bash
echo "Hello" | boxes -d shell
```

### image-to-ascii
```bash
jp2a --width=80 image.jpg
```

### ASCII Video
Convert video/audio files to colored ASCII animations (MP4/GIF).
See `references/ascii-art.md` for fonts, box designs, and image options.
See `references/ascii-video.md` for conversion commands, color modes, and frame rate tuning.
