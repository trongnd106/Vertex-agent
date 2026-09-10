# HeartMuLa — Local Music Generation

Open-source music foundation model (Apache-2.0). Generates music from lyrics + tags.

## Components
- **HeartMuLa** (3B/7B) — Music language model
- **HeartCodec** (12.5Hz) — High-fidelity audio codec
- **HeartTranscriptor** — Whisper-based lyric transcription
- **HeartCLAP** — Audio-text alignment

## Hardware
- Min: 8GB VRAM (`--lazy_load true`)
- Recommended: 16GB+ VRAM
- Multi-GPU: `--mula_device cuda:0 --codec_device cuda:1`

## Installation
```bash
git clone https://github.com/HeartMuLa/heartlib.git
cd heartlib
uv venv --python 3.10 .venv
source .venv/bin/activate
uv pip install -e .
```

## Generation
```bash
source .venv/bin/activate
python3 -m heartmula.generate \
  --lyrics_path lyrics.txt \
  --tags "synthwave,retro,instrumental" \
  --model_size 3b \
  --lazy_load true \
  --output_dir ./output
```

## Pitfalls
1. Python 3.10 required — will fail with newer Python
2. First run downloads ~6GB of model weights
3. `--lazy_load` swaps models on/off GPU (slower but less VRAM)
4. Without GPU, generation is extremely slow
