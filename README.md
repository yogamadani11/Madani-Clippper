# Madani Clipper

A private, no-login AI-assisted video clipping web app prototype.

## What works
- Upload MP4/MOV/MKV/WebM video.
- Choose **Full Auto** (automatically select suggested moments) or **Semi AI** (review and select suggested moments).
- Generate short clips with FFmpeg.
- Optional speech transcription with faster-whisper (CPU mode).
- Download generated MP4 clips.
- No account/login required in this starter project.

## Important limitations
This is a working starter, not a hosted service. It must be deployed to a hosting account before it has a public URL.
Free hosting has limits: services may sleep, storage may be temporary, and video processing may time out or run out of memory. Keep initial uploads short (for example, under 5–10 minutes) until tested.
The default clip ranking is a practical heuristic (speech density + scene changes + audio energy). It is not a guarantee that every selected moment is funny, meaningful, or viral. Transcription is optional and can improve segment context, but does not magically understand every video.
Do not upload private, confidential, or copyrighted content unless you have permission.

## Run locally
Requirements:
- Python 3.11+
- FFmpeg and FFprobe installed and available on PATH

Then:
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Open http://localhost:8000

Optional better transcription:
```bash
pip install faster-whisper
```
Set `ENABLE_WHISPER=1`. The first run downloads a model and needs internet. On free CPU hosting, use `WHISPER_MODEL=tiny` or leave Whisper disabled.

## Deploy on Render (free tier, subject to current plan availability)
1. Create a GitHub repository and upload this project.
2. In Render, create **New > Web Service** and connect the repository.
3. Choose Docker runtime (the included `Dockerfile`).
4. Set environment variables:
   - `MAX_UPLOAD_MB=250`
   - `MAX_VIDEO_SECONDS=600`
   - `ENABLE_WHISPER=0`
5. Deploy. Render may sleep when idle and local generated files can be lost after restart/redeploy. This app stores jobs locally in `work/`, so treat downloads as temporary.
6. Use the Render-provided HTTPS URL on your Android phone.

For a private service, do not share the URL. This starter deliberately has no login, so anyone who obtains the URL can use it. For stronger privacy, add authentication before sharing it.

## Android
Open the deployed URL in Chrome. Use the browser menu > **Add to Home screen** to create an app-like shortcut. This starter is a responsive web app; it is not yet a native APK.

## Environment variables
- `MAX_UPLOAD_MB`: upload limit, default 250
- `MAX_VIDEO_SECONDS`: maximum video length, default 600
- `ENABLE_WHISPER`: `1` to enable optional faster-whisper, default `0`
- `WHISPER_MODEL`: `tiny`, `base`, etc., default `tiny`
- `WORK_DIR`: working directory, default `work`

## Next production steps
- Add authentication/password protection (recommended for a private app).
- Add persistent object storage for video and output files.
- Add queue/worker processing for long videos.
- Add real semantic highlight ranking with a configured AI provider if desired.
- Add automatic subject tracking for vertical crop.
