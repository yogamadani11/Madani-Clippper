from __future__ import annotations
import os, uuid, json, shutil, subprocess, math, re
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

BASE = Path(__file__).resolve().parent.parent
WORK = Path(os.getenv("WORK_DIR", str(BASE / "work"))).resolve()
WORK.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "250"))
MAX_VIDEO_SECONDS = int(os.getenv("MAX_VIDEO_SECONDS", "600"))
ALLOWED = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
JOBS: dict[str, dict] = {}

app = FastAPI(title="Madani Clipper", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"]
)
app.mount("/static", StaticFiles(directory=str(BASE / "app" / "static")), name="static")


def run(cmd: list[str]) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return p.stdout.strip()
    except FileNotFoundError:
        raise HTTPException(500, "FFmpeg/FFprobe belum tersedia di server.")
    except subprocess.CalledProcessError as e:
        raise HTTPException(422, "Pemrosesan video gagal: " + (e.stderr[-600:] or "format video tidak didukung"))


def probe(path: Path) -> dict:
    raw = run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", str(path)])
    data = json.loads(raw)
    duration = float(data.get("format", {}).get("duration", 0))
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    if duration <= 0:
        raise HTTPException(422, "Durasi video tidak terbaca.")
    if duration > MAX_VIDEO_SECONDS:
        raise HTTPException(413, f"Video terlalu panjang. Batas saat ini {MAX_VIDEO_SECONDS} detik.")
    return {"duration": duration, "width": video.get("width", 0), "height": video.get("height", 0)}


def transcribe(path: Path) -> list[dict]:
    if os.getenv("ENABLE_WHISPER", "0") != "1":
        return []
    try:
        from faster_whisper import WhisperModel
        model_name = os.getenv("WHISPER_MODEL", "tiny")
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(path), vad_filter=True)
        return [{"start": float(s.start), "end": float(s.end), "text": s.text.strip()} for s in segments]
    except Exception as exc:
        return [{"error": str(exc)[:200]}]


def make_suggestions(duration: float, transcript: list[dict], count: int, clip_len: int) -> list[dict]:
    # Split into overlapping candidate windows; favor speech-rich windows when transcription exists.
    clip_len = max(10, min(clip_len, 90))
    if duration <= clip_len:
        starts = [0.0]
    else:
        step = max(8, clip_len // 2)
        starts = [float(x) for x in range(0, max(1, int(duration - clip_len) + 1), step)]
        last = max(0.0, duration - clip_len)
        if not starts or abs(starts[-1] - last) > 2:
            starts.append(last)
    candidates = []
    for start in starts:
        end = min(duration, start + clip_len)
        words = [s for s in transcript if isinstance(s, dict) and s.get("start", 0) < end and s.get("end", 0) > start and s.get("text")]
        text = " ".join(s["text"] for s in words)
        # Score is a transparent heuristic, not a claim of semantic/viral prediction.
        speech = min(1.0, sum(max(0, min(end, s["end"]) - max(start, s["start"])) for s in words) / max(1, end-start))
        length_bonus = min(1.0, len(text.split()) / 35) if text else 0.25
        score = round(0.45 * speech + 0.35 * length_bonus + 0.20 * (0.5 if not text else 0.7), 3)
        candidates.append({"start": round(start, 2), "end": round(end, 2), "score": score, "transcript": text[:420]})
    candidates.sort(key=lambda x: x["score"], reverse=True)
    chosen = []
    for item in candidates:
        if all(abs(item["start"] - c["start"]) >= clip_len * 0.65 for c in chosen):
            chosen.append(item)
        if len(chosen) >= max(1, min(count, 20)):
            break
    return sorted(chosen, key=lambda x: x["start"])


@app.get("/", response_class=HTMLResponse)
def home():
    return (BASE / "app" / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/api/health")
def health():
    return {"ok": True, "app": "Madani Clipper", "ffmpeg": shutil.which("ffmpeg") is not None}


@app.post("/api/upload")
async def upload(video: UploadFile = File(...)):
    suffix = Path(video.filename or "video.mp4").suffix.lower()
    if suffix not in ALLOWED:
        raise HTTPException(415, "Format belum didukung. Gunakan MP4, MOV, MKV, atau WebM.")
    job_id = uuid.uuid4().hex[:12]
    folder = WORK / job_id
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / ("source" + suffix)
    size = 0
    try:
        with target.open("wb") as out:
            while chunk := await video.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_MB * 1024 * 1024:
                    raise HTTPException(413, f"Ukuran maksimal {MAX_UPLOAD_MB} MB.")
                out.write(chunk)
        meta = probe(target)
        JOBS[job_id] = {"id": job_id, "folder": str(folder), "source": str(target), "filename": video.filename, **meta, "suggestions": [], "clips": []}
        return {"job_id": job_id, "filename": video.filename, "duration": round(meta["duration"], 1), "width": meta["width"], "height": meta["height"]}
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise


@app.post("/api/analyze/{job_id}")
def analyze(job_id: str, mode: str = Form("auto"), count: int = Form(5), clip_seconds: int = Form(45)):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Proyek tidak ditemukan. Upload ulang video.")
    transcript = transcribe(Path(job["source"]))
    suggestions = make_suggestions(job["duration"], transcript, count, clip_seconds)
    job["suggestions"] = suggestions
    job["transcript"] = transcript
    job["mode"] = mode
    return {"mode": mode, "suggestions": suggestions, "transcription_enabled": os.getenv("ENABLE_WHISPER", "0") == "1"}


@app.post("/api/render/{job_id}")
def render(job_id: str, payload: dict):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Proyek tidak ditemukan. Upload ulang video.")
    selected = payload.get("clips", [])
    if not selected:
        selected = job.get("suggestions", [])
    if not selected:
        raise HTTPException(400, "Belum ada klip yang dipilih.")
    folder = Path(job["folder"])
    outputs = []
    for i, clip in enumerate(selected[:20], 1):
        start = max(0.0, float(clip["start"]))
        end = min(float(job["duration"]), float(clip["end"]))
        if end - start < 2:
            continue
        out = folder / f"madani_clip_{i:02d}.mp4"
        # Vertical crop: scale to fill 1080x1920, then center crop. Audio is retained.
        vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
        run(["ffmpeg", "-y", "-ss", str(start), "-i", job["source"], "-t", str(end-start),
             "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
             "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)])
        outputs.append({"name": out.name, "url": f"/api/download/{job_id}/{out.name}", "start": start, "end": end})
    job["clips"] = outputs
    return {"clips": outputs}


@app.get("/api/download/{job_id}/{filename}")
def download(job_id: str, filename: str):
    job = JOBS.get(job_id)
    if not job or not re.fullmatch(r"madani_clip_\d{2}\.mp4", filename):
        raise HTTPException(404, "File tidak ditemukan.")
    path = Path(job["folder"]) / filename
    if not path.exists():
        raise HTTPException(404, "File sudah tidak tersedia.")
    return FileResponse(path, media_type="video/mp4", filename=filename)


@app.delete("/api/job/{job_id}")
def delete_job(job_id: str):
    job = JOBS.pop(job_id, None)
    if job:
        shutil.rmtree(job["folder"], ignore_errors=True)
    return {"deleted": bool(job)}
