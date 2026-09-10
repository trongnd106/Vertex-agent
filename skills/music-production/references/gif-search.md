# GIF Search (Tenor API)

Search and download GIFs directly via the Tenor API using curl.

## Setup

Requires `TENOR_API_KEY` env var. Get a free key at https://developers.google.com/tenor/guides/quickstart.

Prerequisites: `curl` and `jq`.

## Search

```bash
curl -s "https://tenor.googleapis.com/v2/search?q=thumbs+up&limit=5&key=${TENOR_API_KEY}" | jq -r '.results[].media_formats.gif.url'
```

## Download top result

```bash
URL=$(curl -s "https://tenor.googleapis.com/v2/search?q=celebration&limit=1&key=${TENOR_API_KEY}" | jq -r '.results[0].media_formats.gif.url')
curl -sL "$URL" -o celebration.gif
```

## API Parameters

| Parameter | Description |
|-----------|-------------|
| `q` | Search query (URL-encode spaces as `+`) |
| `limit` | Max results (1-50, default 20) |
| `media_filter` | Filter: `gif`, `tinygif`, `mp4`, `tinymp4`, `webm` |
| `contentfilter` | Safety: `off`, `low`, `medium`, `high` |
| `locale` | Language: `en_US`, `es`, `fr`, etc. |

## Media Formats

Each result has `.media_formats.gif` (full quality), `.media_formats.tinygif` (preview), `.media_formats.mp4` (video), `.media_formats.webm`.

## Notes

- URL-encode query: spaces as `+`
- Use `tinygif` URLs for lighter-weight chat sending
- GIF URLs work directly in markdown: `![alt](url)`, `MEDIA:url`
