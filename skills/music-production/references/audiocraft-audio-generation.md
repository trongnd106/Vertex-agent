-
2|name: audiocraft-audio-generation
3|description: "AudioCraft: MusicGen text-to-music, AudioGen text-to-sound."
4|version: 1.0.0
5|author: Orchestra Research
6|license: MIT
7|dependencies: [audiocraft, torch>=2.0.0, transformers>=4.30.0]
8|platforms: [linux, macos]
9|metadata:
10|  hermes:
11|    tags: [Multimodal, Audio Generation, Text-to-Music, Text-to-Audio, MusicGen]
12|
13|---
14|
15|# AudioCraft: Audio Generation
16|
17|Comprehensive guide to using Meta's AudioCraft for text-to-music and text-to-audio generation with MusicGen, AudioGen, and EnCodec.
18|
19|## When to use AudioCraft
20|
21|**Use AudioCraft when:**
22|- Need to generate music from text descriptions
23|- Creating sound effects and environmental audio
24|- Building music generation applications
25|- Need melody-conditioned music generation
26|- Want stereo audio output
27|- Require controllable music generation with style transfer
28|
29|**Key features:**
30|- **MusicGen**: Text-to-music generation with melody conditioning
31|- **AudioGen**: Text-to-sound effects generation
32|- **EnCodec**: High-fidelity neural audio codec
33|- **Multiple model sizes**: Small (300M) to Large (3.3B)
34|- **Stereo support**: Full stereo audio generation
35|- **Style conditioning**: MusicGen-Style for reference-based generation
36|
37|**Use alternatives instead:**
38|- **Stable Audio**: For longer commercial music generation
39|- **Bark**: For text-to-speech with music/sound effects
40|- **Riffusion**: For spectogram-based music generation
41|- **OpenAI Jukebox**: For raw audio generation with lyrics
42|
43|## Quick start
44|
45|### Installation
46|
47|```bash
48|# From PyPI
49|pip install audiocraft
50|
51|# From GitHub (latest)
52|pip install git+https://github.com/facebookresearch/audiocraft.git
53|
54|# Or use HuggingFace Transformers
55|pip install transformers torch torchaudio
56|```
57|
58|### Basic text-to-music (AudioCraft)
59|
60|```python
61|import torchaudio
62|from audiocraft.models import MusicGen
63|
64|# Load model
65|model = MusicGen.get_pretrained('facebook/musicgen-small')
66|
67|# Set generation parameters
68|model.set_generation_params(
69|    duration=8,  # seconds
70|    top_k=250,
71|    temperature=1.0
72|)
73|
74|# Generate from text
75|descriptions = ["happy upbeat electronic dance music with synths"]
76|wav = model.generate(descriptions)
77|
78|# Save audio
79|torchaudio.save("output.wav", wav[0].cpu(), sample_rate=32000)
80|```
81|
82|### Using HuggingFace Transformers
83|
84|```python
85|from transformers import AutoProcessor, MusicgenForConditionalGeneration
86|import scipy
87|
88|# Load model and processor
89|processor = AutoProcessor.from_pretrained("facebook/musicgen-small")
90|model = MusicgenForConditionalGeneration.from_pretrained("facebook/musicgen-small")
91|model.to("cuda")
92|
93|# Generate music
94|inputs = processor(
95|    text=["80s pop track with bassy drums and synth"],
96|    padding=True,
97|    return_tensors="pt"
98|).to("cuda")
99|
100|audio_values = model.generate(
101|    **inputs,
102|    do_sample=True,
103|    guidance_scale=3,
104|    max_new_tokens=256
105|)
106|
107|# Save
108|sampling_rate = model.config.audio_encoder.sampling_rate
109|scipy.io.wavfile.write("output.wav", rate=sampling_rate, data=audio_values[0, 0].cpu().numpy())
110|```
111|
112|### Text-to-sound with AudioGen
113|
114|```python
115|from audiocraft.models import AudioGen
116|
117|# Load AudioGen
118|model = AudioGen.get_pretrained('facebook/audiogen-medium')
119|
120|model.set_generation_params(duration=5)
121|
122|# Generate sound effects
123|descriptions = ["dog barking in a park with birds chirping"]
124|wav = model.generate(descriptions)
125|
126|torchaudio.save("sound.wav", wav[0].cpu(), sample_rate=16000)
127|```
128|
129|## Core concepts
130|
131|### Architecture overview
132|
133|```
134|AudioCraft Architecture:
135|┌──────────────────────────────────────────────────────────────┐
136|│                    Text Encoder (T5)                          │
137|│                         │                                     │
138|│                    Text Embeddings                            │
139|└────────────────────────┬─────────────────────────────────────┘
140|                         │
141|┌────────────────────────▼─────────────────────────────────────┐
142|│              Transformer Decoder (LM)                         │
143|│     Auto-regressively generates audio tokens                  │
144|│     Using efficient token interleaving patterns               │
145|└────────────────────────┬─────────────────────────────────────┘
146|                         │
147|┌────────────────────────▼─────────────────────────────────────┐
148|│                EnCodec Audio Decoder                          │
149|│        Converts tokens back to audio waveform                 │
150|└──────────────────────────────────────────────────────────────┘
151|```
152|
153|### Model variants
154|
155|| Model | Size | Description | Use Case |
156||-------|------|-------------|----------|
157|| `musicgen-small` | 300M | Text-to-music | Quick generation |
158|| `musicgen-medium` | 1.5B | Text-to-music | Balanced |
159|| `musicgen-large` | 3.3B | Text-to-music | Best quality |
160|| `musicgen-melody` | 1.5B | Text + melody | Melody conditioning |
161|| `musicgen-melody-large` | 3.3B | Text + melody | Best melody |
162|| `musicgen-stereo-*` | Varies | Stereo output | Stereo generation |
163|| `musicgen-style` | 1.5B | Style transfer | Reference-based |
164|| `audiogen-medium` | 1.5B | Text-to-sound | Sound effects |
165|
166|### Generation parameters
167|
168|| Parameter | Default | Description |
169||-----------|---------|-------------|
170|| `duration` | 8.0 | Length in seconds (1-120) |
171|| `top_k` | 250 | Top-k sampling |
172|| `top_p` | 0.0 | Nucleus sampling (0 = disabled) |
173|| `temperature` | 1.0 | Sampling temperature |
174|| `cfg_coef` | 3.0 | Classifier-free guidance |
175|
176|## MusicGen usage
177|
178|### Text-to-music generation
179|
180|```python
181|from audiocraft.models import MusicGen
182|import torchaudio
183|
184|model = MusicGen.get_pretrained('facebook/musicgen-medium')
185|
186|# Configure generation
187|model.set_generation_params(
188|    duration=30,          # Up to 30 seconds
189|    top_k=250,            # Sampling diversity
190|    top_p=0.0,            # 0 = use top_k only
191|    temperature=1.0,      # Creativity (higher = more varied)
192|    cfg_coef=3.0          # Text adherence (higher = stricter)
193|)
194|
195|# Generate multiple samples
196|descriptions = [
197|    "epic orchestral soundtrack with strings and brass",
198|    "chill lo-fi hip hop beat with jazzy piano",
199|    "energetic rock song with electric guitar"
200|]
201|
202|# Generate (returns [batch, channels, samples])
203|wav = model.generate(descriptions)
204|
205|# Save each
206|for i, audio in enumerate(wav):
207|    torchaudio.save(f"music_{i}.wav", audio.cpu(), sample_rate=32000)
208|```
209|
210|### Melody-conditioned generation
211|
212|```python
213|from audiocraft.models import MusicGen
214|import torchaudio
215|
216|# Load melody model
217|model = MusicGen.get_pretrained('facebook/musicgen-melody')
218|model.set_generation_params(duration=30)
219|
220|# Load melody audio
221|melody, sr = torchaudio.load("melody.wav")
222|
223|# Generate with melody conditioning
224|descriptions = ["acoustic guitar folk song"]
225|wav = model.generate_with_chroma(descriptions, melody, sr)
226|
227|torchaudio.save("melody_conditioned.wav", wav[0].cpu(), sample_rate=32000)
228|```
229|
230|### Stereo generation
231|
232|```python
233|from audiocraft.models import MusicGen
234|
235|# Load stereo model
236|model = MusicGen.get_pretrained('facebook/musicgen-stereo-medium')
237|model.set_generation_params(duration=15)
238|
239|descriptions = ["ambient electronic music with wide stereo panning"]
240|wav = model.generate(descriptions)
241|
242|# wav shape: [batch, 2, samples] for stereo
243|print(f"Stereo shape: {wav.shape}")  # [1, 2, 480000]
244|torchaudio.save("stereo.wav", wav[0].cpu(), sample_rate=32000)
245|```
246|
247|### Audio continuation
248|
249|```python
250|from transformers import AutoProcessor, MusicgenForConditionalGeneration
251|
252|processor = AutoProcessor.from_pretrained("facebook/musicgen-medium")
253|model = MusicgenForConditionalGeneration.from_pretrained("facebook/musicgen-medium")
254|
255|# Load audio to continue
256|import torchaudio
257|audio, sr = torchaudio.load("intro.wav")
258|
259|# Process with text and audio
260|inputs = processor(
261|    audio=audio.squeeze().numpy(),
262|    sampling_rate=sr,
263|    text=["continue with a epic chorus"],
264|    padding=True,
265|    return_tensors="pt"
266|)
267|
268|# Generate continuation
269|audio_values = model.generate(**inputs, do_sample=True, guidance_scale=3, max_new_tokens=512)
270|```
271|
272|## MusicGen-Style usage
273|
274|### Style-conditioned generation
275|
276|```python
277|from audiocraft.models import MusicGen
278|
279|# Load style model
280|model = MusicGen.get_pretrained('facebook/musicgen-style')
281|
282|# Configure generation with style
283|model.set_generation_params(
284|    duration=30,
285|    cfg_coef=3.0,
286|    cfg_coef_beta=5.0  # Style influence
287|)
288|
289|# Configure style conditioner
290|model.set_style_conditioner_params(
291|    eval_q=3,          # RVQ quantizers (1-6)
292|    excerpt_length=3.0  # Style excerpt length
293|)
294|
295|# Load style reference
296|style_audio, sr = torchaudio.load("reference_style.wav")
297|
298|# Generate with text + style
299|descriptions = ["upbeat dance track"]
300|wav = model.generate_with_style(descriptions, style_audio, sr)
301|```
302|
303|### Style-only generation (no text)
304|
305|```python
306|# Generate matching style without text prompt
307|model.set_generation_params(
308|    duration=30,
309|    cfg_coef=3.0,
310|    cfg_coef_beta=None  # Disable double CFG for style-only
311|)
312|
313|wav = model.generate_with_style([None], style_audio, sr)
314|```
315|
316|## AudioGen usage
317|
318|### Sound effect generation
319|
320|```python
321|from audiocraft.models import AudioGen
322|import torchaudio
323|
324|model = AudioGen.get_pretrained('facebook/audiogen-medium')
325|model.set_generation_params(duration=10)
326|
327|# Generate various sounds
328|descriptions = [
329|    "thunderstorm with heavy rain and lightning",
330|    "busy city traffic with car horns",
331|    "ocean waves crashing on rocks",
332|    "crackling campfire in forest"
333|]
334|
335|wav = model.generate(descriptions)
336|
337|for i, audio in enumerate(wav):
338|    torchaudio.save(f"sound_{i}.wav", audio.cpu(), sample_rate=16000)
339|```
340|
341|## EnCodec usage
342|
343|### Audio compression
344|
345|```python
346|from audiocraft.models import CompressionModel
347|import torch
348|import torchaudio
349|
350|# Load EnCodec
351|model = CompressionModel.get_pretrained('facebook/encodec_32khz')
352|
353|# Load audio
354|wav, sr = torchaudio.load("audio.wav")
355|
356|# Ensure correct sample rate
357|if sr != 32000:
358|    resampler = torchaudio.transforms.Resample(sr, 32000)
359|    wav = resampler(wav)
360|
361|# Encode to tokens
362|with torch.no_grad():
363|    encoded = model.encode(wav.unsqueeze(0))
364|    codes = encoded[0]  # Audio codes
365|
366|# Decode back to audio
367|with torch.no_grad():
368|    decoded = model.decode(codes)
369|
370|torchaudio.save("reconstructed.wav", decoded[0].cpu(), sample_rate=32000)
371|```
372|
373|## Common workflows
374|
375|### Workflow 1: Music generation pipeline
376|
377|```python
378|import torch
379|import torchaudio
380|from audiocraft.models import MusicGen
381|
382|class MusicGenerator:
383|    def __init__(self, model_name="facebook/musicgen-medium"):
384|        self.model = MusicGen.get_pretrained(model_name)
385|        self.sample_rate = 32000
386|
387|    def generate(self, prompt, duration=30, temperature=1.0, cfg=3.0):
388|        self.model.set_generation_params(
389|            duration=duration,
390|            top_k=250,
391|            temperature=temperature,
392|            cfg_coef=cfg
393|        )
394|
395|        with torch.no_grad():
396|            wav = self.model.generate([prompt])
397|
398|        return wav[0].cpu()
399|
400|    def generate_batch(self, prompts, duration=30):
401|        self.model.set_generation_params(duration=duration)
402|
403|        with torch.no_grad():
404|            wav = self.model.generate(prompts)
405|
406|        return wav.cpu()
407|
408|    def save(self, audio, path):
409|        torchaudio.save(path, audio, sample_rate=self.sample_rate)
410|
411|# Usage
412|generator = MusicGenerator()
413|audio = generator.generate(
414|    "epic cinematic orchestral music",
415|    duration=30,
416|    temperature=1.0
417|)
418|generator.save(audio, "epic_music.wav")
419|```
420|
421|### Workflow 2: Sound design batch processing
422|
423|```python
424|import json
425|from pathlib import Path
426|from audiocraft.models import AudioGen
427|import torchaudio
428|
429|def batch_generate_sounds(sound_specs, output_dir):
430|    """
431|    Generate multiple sounds from specifications.
432|
433|    Args:
434|        sound_specs: list of {"name": str, "description": str, "duration": float}
435|        output_dir: output directory path
436|    """
437|    model = AudioGen.get_pretrained('facebook/audiogen-medium')
438|    output_dir = Path(output_dir)
439|    output_dir.mkdir(exist_ok=True)
440|
441|    results = []
442|
443|    for spec in sound_specs:
444|        model.set_generation_params(duration=spec.get("duration", 5))
445|
446|        wav = model.generate([spec["description"]])
447|
448|        output_path = output_dir / f"{spec['name']}.wav"
449|        torchaudio.save(str(output_path), wav[0].cpu(), sample_rate=16000)
450|
451|        results.append({
452|            "name": spec["name"],
453|            "path": str(output_path),
454|            "description": spec["description"]
455|        })
456|
457|    return results
458|
459|# Usage
460|sounds = [
461|    {"name": "explosion", "description": "massive explosion with debris", "duration": 3},
462|    {"name": "footsteps", "description": "footsteps on wooden floor", "duration": 5},
463|    {"name": "door", "description": "wooden door creaking and closing", "duration": 2}
464|]
465|
466|results = batch_generate_sounds(sounds, "sound_effects/")
467|```
468|
469|### Workflow 3: Gradio demo
470|
471|```python
472|import gradio as gr
473|import torch
474|import torchaudio
475|from audiocraft.models import MusicGen
476|
477|model = MusicGen.get_pretrained('facebook/musicgen-small')
478|
479|def generate_music(prompt, duration, temperature, cfg_coef):
480|    model.set_generation_params(
481|        duration=duration,
482|        temperature=temperature,
483|        cfg_coef=cfg_coef
484|    )
485|
486|    with torch.no_grad():
487|        wav = model.generate([prompt])
488|
489|    # Save to temp file
490|    path = "temp_output.wav"
491|    torchaudio.save(path, wav[0].cpu(), sample_rate=32000)
492|    return path
493|
494|demo = gr.Interface(
495|    fn=generate_music,
496|    inputs=[
497|        gr.Textbox(label="Music Description", placeholder="upbeat electronic dance music"),
498|        gr.Slider(1, 30, value=8, label="Duration (seconds)"),
499|        gr.Slider(0.5, 2.0, value=1.0, label="Temperature"),
500|        gr.Slider(1.0, 10.0, value=3.0, label="CFG Coefficient")
501|