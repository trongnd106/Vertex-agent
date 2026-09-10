# Songsee — Audio Feature Visualization

Generate spectrograms and multi-panel audio visualizations.

## Install
```bash
go install github.com/steipete/songsee/cmd/songsee@latest
```
Optional: `ffmpeg` for formats beyond WAV/MP3.

## Basic Usage
```bash
# Basic spectrogram
songsee track.mp3

# Save to file
songsee track.mp3 -o spectrogram.png

# Multi-panel visualization
songsee track.mp3 --viz spectrogram,mel,chroma,hpss,selfsim,loudness,tempogram,mfcc,flux

# Time slice
songsee track.mp3 --start 12.5 --duration 8 -o slice.jpg

# From stdin
cat track.mp3 | songsee - --format png -o out.png
```

## Visualization Types
`spectrogram`, `mel` (mel spectrogram), `chroma` (chromagram), `hpss` (harmonic-percussive), `selfsim` (self-similarity), `loudness`, `tempogram`, `mfcc`, `flux` (spectral flux)

## Output Formats
`png` (default), `jpg`, `svg`
