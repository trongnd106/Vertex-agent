# ASCII Art — Static Art Generation

Generate ASCII art from text, images, or via classic terminal utilities.

## pyfiglet — Text Banners

```python
import pyfiglet

# List available fonts
print(pyfiglet.FigletFont.getFonts())

# Generate with a specific font
print(pyfiglet.figlet_format("Hello", font="slant"))
```

Popular fonts: `slant`, `standard`, `banner`, `big`, `block`, `doom`, `epic`, `graffiti`, `isometric1`, `letters`, `ogre`, `peaks`, `puffy`, `rectangles`, `rounded`, `shadow`, `smscript`, `speed`, `stop`, `sub-zero`, `swampland`, `tinker-toy`, `train`, `whimsy`

## cowsay — Animal Messages

```bash
cowsay "Hello from Hermes"
# -f dragon, -f tux, -f ghostbusters, -f stegosaurus

# Combine with fortune
fortune | cowsay

# Export to file
cowsay "Hello" > output.txt
```

## boxes — Text in Decorative Borders

```bash
echo "Hello" | boxes -d shell
echo "Hello" | boxes -d c   # C-style comments
echo "Hello" | boxes -d html  # HTML comments
echo "Hello" | boxes -d cc   # C++ style
# -d list for all available designs
```

## jp2a — Image to ASCII

```bash
# Install
# apt-get install jp2a  # or brew install jp2a

# Convert image
jp2a --width=80 image.jpg
jp2a --colors --width=100 image.jpg  # with ANSI colors
```

## CLI Utility Availability

| Tool | Install |
|------|---------|
| pyfiglet | `pip install pyfiglet` |
| cowsay | `apt install cowsay` / `brew install cowsay` |
| boxes | `apt install boxes` / `brew install boxes` |
| jp2a | `apt install jp2a` / `brew install jp2a` |
