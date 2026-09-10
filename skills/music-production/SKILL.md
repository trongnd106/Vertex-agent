---
name: music-production
description: "AI music generation, songwriting craft, audio visualization, and text-to-music generation. Covers HeartMuLa (local), Suno prompts, AudioCraft, songsee spectrograms."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [Music, Audio, Generation, Songwriting, Spectrogram, Suno, HeartMuLa]
    related_skills: []
---

# Music Production & Media Tools — Generation, Songwriting, Video, GIFs

Six media/audio/video subsections depending on what the user needs.

## 1. Songwriting & AI Music Prompts

For songwriting craft and Suno AI prompt generation. Detailed in `references/songwriting-and-ai-music.md`.

**Quick start:** Follow the song structure guide (ABABCB, AABA, AAA) and craft prompts with genre tags, mood descriptors, and vocal style hints.

## 2. HeartMuLa — Open-Source Music Generation

For running HeartMuLa locally (Suno-like music generation from lyrics + tags). Requires GPU.

**Install:**
```bash
git clone https://github.com/HeartMuLa/heartlib.git
cd heartlib
uv venv --python 3.10 .venv && . .venv/bin/activate && uv pip install -e .
```

**Generate:** See `references/heartmula.md` for generation commands, model selection (3B/7B), and hardware requirements (min 8GB VRAM).

## 3. Songsee — Audio Visualization

For generating spectrograms and multi-panel feature visualizations.

**Install:** `go install github.com/steipete/songsee/cmd/songsee@latest`
**Usage:** `songsee track.mp3 --viz spectrogram,mel,chroma,mfcc`

## 4. AudioCraft — Text-to-Music/Audio

For Meta's AudioCraft suite: MusicGen (text-to-music) and AudioGen (text-to-sound).

See `references/audiocraft-audio-generation.md` for installation and model details.

## 5. YouTube Transcript Extraction

For extracting and reformatting YouTube video transcripts into summaries, threads, blog posts, etc.

**Setup:** `pip install youtube-transcript-api`

**Usage:** The script `scripts/fetch_transcript.py` accepts any standard YouTube URL format, short links (youtu.be), shorts, embeds, live links, or a raw 11-character video ID. See `references/youtube-content.md` for full workflow and output formatting.

**Output format details:** `references/youtube-output-formats.md`

## 6. GIF Search (Tenor API)

Search and download reaction GIFs via the Tenor API. Requires `TENOR_API_KEY` env var.

**Quick start:**
```bash
curl -s "https://tenor.googleapis.com/v2/search?q=celebration&limit=1&key=${TENOR_API_KEY}" | jq -r '.results[0].media_formats.gif.url'
```

Full details in `references/gif-search.md`.

## Agent Selection

| User wants... | Use subsection |
|---------------|----------------|
| Write lyrics, craft Suno prompts | `references/songwriting-and-ai-music.md` |
| Generate local AI music | `references/heartmula.md` |
| Visualize audio features | `references/songsee.md` |
| Text-to-music with Meta AudioCraft | `references/audiocraft-audio-generation.md` |
| Extract/summarize YouTube video | `references/youtube-content.md` |
| Search/download a reaction GIF | `references/gif-search.md` |
