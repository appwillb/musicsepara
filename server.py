import asyncio
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional

# On Windows, use SelectorEventLoop to prevent WinError 64 / socket disconnection issues
if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

from fastapi import FastAPI, UploadFile, File, Form, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, Response

from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
STATIC_DIR = BASE_DIR / "static"

UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)

app = FastAPI(title="tunemusic Pro Authentic Reconstructed Engine")

def silence_windows_socket_closed(loop, context):
    exception = context.get('exception')
    if isinstance(exception, OSError) and getattr(exception, 'winerror', None) in (64, 121, 10054):
        return  # Suppress harmless Windows client disconnect noise
    try:
        loop.default_exception_handler(context)
    except Exception:
        pass

@app.on_event("startup")
async def startup_event():
    try:
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(silence_windows_socket_closed)
    except Exception:
        pass

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from stageprompter_engine import router as stageprompter_router
app.include_router(stageprompter_router)

from license_engine import (
    get_system_hwid,
    load_installed_license,
    save_license,
    remove_license,
    verify_license_key
)

# =============================================================================
# 0. CRYPTOGRAPHIC HARDWARE LICENSING & ANTI-PIRACY GATEKEEPER
# =============================================================================
@app.middleware("http")
async def license_gatekeeper_middleware(request, call_next):
    path = request.url.path
    
    # Allow license management endpoints, static assets, media, and UI shells
    if (
        path.startswith("/api/license")
        or path.startswith("/stageprompter")
        or path.startswith("/assets")
        or path.startswith("/fonts")
        or path.startswith("/img")
        or path.startswith("/uploads")
        or path.startswith("/output")
        or path in ("/", "/tunemusic", "/tunemusic/", "/pt", "/pt/", "/presentation", "/favicon.ico", "/LOGO.png")
    ):
        return await call_next(request)
    
    # Enforce license for heavy processing & data operations
    if path.startswith("/split/tracks") or path.startswith("/api/stageprompter/video") or (path.startswith("/api/stageprompter/") and request.method in ("POST", "PUT", "DELETE")):
        is_licensed, info = load_installed_license()
        if not is_licensed:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "Acesso Bloqueado: Este computador não possui licença ativa do tunemusic Pro.",
                    "hwid": get_system_hwid(),
                    "message": info.get("message", "Licença necessária para executar esta ação.")
                }
            )

    return await call_next(request)


@app.get("/api/license/status")
async def get_license_status():
    is_licensed, info = load_installed_license()
    return info


@app.get("/api/license/hwid")
async def get_license_hwid():
    return {
        "hwid": get_system_hwid()
    }


@app.post("/api/license/activate")
async def activate_license(data: dict):
    key = data.get("key", "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="Chave de licença não fornecida.")
    
    success, message, payload = save_license(key)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {
        "ok": True,
        "message": message,
        "payload": payload
    }


@app.post("/api/license/reset")
async def reset_license(data: Optional[dict] = None):
    remove_license()
    return {
        "ok": True,
        "message": "Licença desinstalada com sucesso."
    }

tasks: Dict[str, Dict[str, Any]] = {}
active_connections: Dict[str, List[tuple]] = {}

# 1. Server Discovery API
@app.get("/split/get_server")
async def get_server():
    return {
        "server": "1",
        "statusCode": 200,
        "data": {
            "server": "1"
        }
    }


# 2. Upload and split initiation
@app.post("/split/tracks")
async def upload_split_tracks(file: UploadFile = File(...), model: int = Form(1)):
    task_id = str(uuid.uuid4())
    task_key = str(uuid.uuid4())[:8]
    ext = Path(file.filename).suffix or ".mp3"
    input_file_path = UPLOAD_DIR / f"{task_id}{ext}"

    with open(input_file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    task_info = {
        "id": task_id,
        "key": task_key,
        "filename": file.filename,
        "status": "process",
        "progress": 0,
        "model": model,
        "s": "",
        "tonality": "C",
        "bpm": 120
    }
    tasks[task_id] = task_info

    # Start background task
    asyncio.create_task(run_demucs_task(task_id, input_file_path, model))

    return task_info


@app.get("/split/status/{task_id}")
async def get_task_status(task_id: str):
    if task_id in tasks:
        return tasks[task_id]
    task_out_dir = OUTPUT_DIR / task_id
    if task_out_dir.exists() and (task_out_dir / "vocal.wav").exists() and (task_out_dir / "music.wav").exists():
        task_info = {
            "id": task_id,
            "key": "stem",
            "filename": "Audio",
            "status": "ready",
            "progress": 100,
            "tonality": "C",
            "bpm": 120
        }
        tasks[task_id] = task_info
        return task_info
    raise HTTPException(status_code=404, detail="Tarefa não encontrada")

async def broadcast_ws(task_id: str, message: dict):
    if task_id in active_connections:
        for ws, ident_raw in active_connections[task_id]:
            try:
                await ws.send_json({
                    "identifier": ident_raw,
                    "message": message
                })
            except Exception:
                pass


MODAL_GPU_URL = os.getenv("MODAL_GPU_URL", "")
MODAL_TUNE_URL = os.getenv("MODAL_TUNE_URL", "")


async def run_demucs_task(task_id: str, input_path: Path, model: int):
    task_out_dir = OUTPUT_DIR / task_id
    task_out_dir.mkdir(exist_ok=True)

    tasks[task_id]["status"] = "processing"
    tasks[task_id]["progress"] = 10
    await broadcast_ws(task_id, {"status": "processing", "progress": 10})

    # Optional remote Modal GPU only if explicitly specified by user via environment
    if MODAL_GPU_URL:
        try:
            import httpx
            import base64

            await broadcast_ws(task_id, {"status": "processing", "progress": 30})
            print(f"[{task_id}] Enviando audio para Modal GPU...")

            audio_data = input_path.read_bytes()
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    MODAL_GPU_URL,
                    content=audio_data,
                    headers={"Content-Type": "application/octet-stream"}
                )

            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    vocal_bytes = base64.b64decode(data["vocals_b64"])
                    music_bytes = base64.b64decode(data["no_vocals_b64"])

                    (task_out_dir / "vocal.wav").write_bytes(vocal_bytes)
                    (task_out_dir / "music.wav").write_bytes(music_bytes)

                    tasks[task_id]["status"] = "ready"
                    tasks[task_id]["progress"] = 100
                    await broadcast_ws(task_id, {
                        "status": "ready",
                        "id": task_id,
                        "key": tasks[task_id]["key"],
                        "tonality": "C",
                        "bpm": 120
                    })
                    print(f"[{task_id}] Processamento concluído via Modal GPU com sucesso!")
                    return
        except Exception as e:
            print(f"[{task_id}] Modal ignorado, executando localmente:", e)

    # Execução 100% Local (com aceleração NVIDIA RTX CUDA se disponível)
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    device_name = torch.cuda.get_device_name(0) if device == "cuda" else "CPU Multi-Core"
    print(f"[{task_id}] Processamento LOCAL com Demucs v4 em tempo real (Hardware: {device.upper()} - {device_name})...")

    cores = "1" if device == "cuda" else str(max(1, (os.cpu_count() or 2)))
    cmd = [
        sys.executable,
        "-m",
        "demucs.separate",
        "-n", "htdemucs",
        "-d", device,
        "--shifts", "0",
        "--overlap", "0.1",
        "-j", cores,
        "--clip-mode", "clamp",
        "--filename", "{stem}.{ext}",
        "-o", str(task_out_dir),
        str(input_path),
    ]

    if model == 1:
        cmd.extend(["--two-stems", "vocals"])

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Background progress ticker while Demucs is computing
        async def progress_ticker():
            current_p = 15
            while process.returncode is None:
                await asyncio.sleep(2)
                if current_p < 90:
                    current_p += 15
                    tasks[task_id]["progress"] = current_p
                    await broadcast_ws(task_id, {"status": "processing", "progress": current_p})

        ticker_task = asyncio.create_task(progress_ticker())

        stdout, stderr = await process.communicate()
        ticker_task.cancel()

        if process.returncode != 0:
            err_msg = stderr.decode(errors="ignore")
            print("Demucs error:", err_msg)
            await broadcast_ws(task_id, {"status": "error", "message": "Falha na separação: " + err_msg[:100]})
            return

        # Map stems
        for root, _, files in os.walk(task_out_dir):
            for f in files:
                p = Path(root) / f
                if f.startswith("vocals."):
                    shutil.copy2(p, task_out_dir / "vocal.wav")
                elif f.startswith("no_vocals."):
                    shutil.copy2(p, task_out_dir / "music.wav")
                elif f.startswith("bass."):
                    shutil.copy2(p, task_out_dir / "bass.wav")
                elif f.startswith("drums."):
                    shutil.copy2(p, task_out_dir / "drums.wav")
                elif f.startswith("other."):
                    shutil.copy2(p, task_out_dir / "other.wav")
                    if not (task_out_dir / "music.wav").exists():
                        shutil.copy2(p, task_out_dir / "music.wav")

        tasks[task_id]["status"] = "ready"
        tasks[task_id]["progress"] = 100
        await broadcast_ws(task_id, {
            "status": "ready",
            "id": task_id,
            "key": tasks[task_id]["key"],
            "tonality": "C",
            "bpm": 120
        })
        print(f"[{task_id}] Processamento concluído com sucesso!")

    except Exception as e:
        print("Task error:", e)
        await broadcast_ws(task_id, {"status": "error", "message": str(e)})

# 3. ActionCable WebSocket Endpoint
@app.websocket("/cable")
async def websocket_cable(websocket: WebSocket):
    requested_subprotocols = websocket.headers.get("sec-websocket-protocol", "").split(",")
    subprotocol = "actioncable-v1-json" if any("actioncable-v1-json" in s for s in requested_subprotocols) else None
    await websocket.accept(subprotocol=subprotocol)
    await websocket.send_json({"type": "welcome"})
    subscribed_task_id = None

    async def ping_loop():
        import time
        try:
            while True:
                await asyncio.sleep(3)
                await websocket.send_json({"type": "ping", "message": int(time.time())})
        except Exception:
            pass

    ping_task = asyncio.create_task(ping_loop())

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            cmd = msg.get("command")

            if cmd == "subscribe":
                ident_raw = msg.get("identifier", "{}")
                try:
                    ident = json.loads(ident_raw)
                    subscribed_task_id = ident.get("id")
                    if subscribed_task_id not in active_connections:
                        active_connections[subscribed_task_id] = []
                    active_connections[subscribed_task_id].append((websocket, ident_raw))

                    await websocket.send_json({
                        "type": "confirm_subscription",
                        "identifier": ident_raw
                    })

                    # If task already finished, emit ready immediately
                    if subscribed_task_id in tasks and tasks[subscribed_task_id]["status"] == "ready":
                        await websocket.send_json({
                            "identifier": ident_raw,
                            "message": {
                                "status": "ready",
                                "id": subscribed_task_id,
                                "key": tasks[subscribed_task_id]["key"],
                                "tonality": "C",
                                "bpm": 120
                            }
                        })
                except Exception as e:
                    print("Subscribe parse error:", e)

            elif cmd == "message":
                pass

    except WebSocketDisconnect:
        pass
    finally:
        ping_task.cancel()
        if subscribed_task_id and subscribed_task_id in active_connections:
            active_connections[subscribed_task_id] = [
                conn for conn in active_connections[subscribed_task_id] if conn[0] != websocket
            ]


# 4. Audio Stem Delivery API & Helpers
def ensure_mp3_converted(wav_path: Path, mp3_path: Path):
    if mp3_path.exists():
        return
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        bundled = BASE_DIR / "bin" / "ffmpeg.exe"
        if bundled.exists():
            ffmpeg_bin = str(bundled)
    if ffmpeg_bin:
        try:
            subprocess.run(
                [ffmpeg_bin, "-y", "-i", str(wav_path), "-codec:a", "libmp3lame", "-b:a", "320k", str(mp3_path)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            if mp3_path.exists():
                return
        except Exception:
            pass

    try:
        import lameenc
        import numpy as np
        import soundfile as sf
        data, sr = sf.read(str(wav_path), dtype="int16")
        if data.ndim == 1:
            data = np.column_stack([data, data])
        encoder = lameenc.Encoder()
        encoder.set_bit_rate(320)
        encoder.set_in_sample_rate(sr)
        encoder.set_channels(data.shape[1])
        encoder.set_quality(2)
        mp3_bytes = encoder.encode(data.tobytes()) + encoder.flush()
        with open(mp3_path, "wb") as f:
            f.write(mp3_bytes)
    except Exception as e:
        print(f"Error encoding MP3 for {wav_path}: {e}")

def ensure_mix_created(task_out_dir: Path) -> Path:
    mix_wav = task_out_dir / "mix.wav"
    if mix_wav.exists():
        return mix_wav
    vocal_wav = task_out_dir / "vocal.wav"
    if not vocal_wav.exists():
        vocal_wav = task_out_dir / "vocals.wav"
    music_wav = task_out_dir / "music.wav"
    if not music_wav.exists():
        music_wav = task_out_dir / "instrumental.wav"

    if vocal_wav.exists() and music_wav.exists():
        try:
            import numpy as np
            import soundfile as sf
            v_data, sr_v = sf.read(str(vocal_wav), dtype="float32")
            m_data, sr_m = sf.read(str(music_wav), dtype="float32")
            max_len = max(len(v_data), len(m_data))
            if len(v_data) < max_len:
                v_data = np.pad(v_data, ((0, max_len - len(v_data)), (0, 0)) if v_data.ndim > 1 else (0, max_len - len(v_data)))
            if len(m_data) < max_len:
                m_data = np.pad(m_data, ((0, max_len - len(m_data)), (0, 0)) if m_data.ndim > 1 else (0, max_len - len(m_data)))
            mix_data = v_data + m_data
            peak = float(np.max(np.abs(mix_data)))
            if peak > 1.0:
                mix_data = mix_data / peak
            sf.write(str(mix_wav), mix_data, sr_v, subtype="PCM_16")
            return mix_wav
        except Exception as e:
            print("Mix error:", e)
    return vocal_wav if vocal_wav.exists() else music_wav

@app.get("/split/listen/{stem}/{task_id}/{key}")
async def listen_stem(
    stem: str,
    task_id: str,
    key: str,
    codec: Optional[str] = None,
    download: Optional[int] = None
):
    task_out_dir = OUTPUT_DIR / task_id

    if stem == "mix":
        stem_file = ensure_mix_created(task_out_dir)
    else:
        stem_file = task_out_dir / f"{stem}.wav"
        if not stem_file.exists():
            if stem == "vocal":
                alt = task_out_dir / "vocals.wav"
                if alt.exists():
                    stem_file = alt
            elif stem == "music":
                alt = task_out_dir / "instrumental.wav"
                if alt.exists():
                    stem_file = alt

    if not stem_file or not stem_file.exists():
        raise HTTPException(status_code=404, detail="Faixa não encontrada")

    # If MP3 requested
    if codec == "mp3":
        mp3_file = task_out_dir / f"{stem}.mp3"
        ensure_mp3_converted(stem_file, mp3_file)
        if mp3_file.exists():
            headers = {"Content-Disposition": f'attachment; filename="{stem}.mp3"'}
            return FileResponse(
                mp3_file,
                media_type="audio/mpeg",
                filename=f"{stem}.mp3",
                headers=headers
            )

    # If explicit download requested for WAV
    if download == 1 or codec == "wav":
        headers = {"Content-Disposition": f'attachment; filename="{stem}.wav"'}
        return FileResponse(
            stem_file,
            media_type="audio/wav",
            filename=f"{stem}.wav",
            headers=headers
        )

    # Default: inline stream for Web Audio player preview/playback
    return FileResponse(stem_file, media_type="audio/wav")

# 5. Geolocation / User Mock Endpoints
@app.get("/geo")
async def get_geo():
    return {"ip": "127.0.0.1", "country": "BR"}

@app.get("/user/get")
async def get_user():
    return {
        "data": {
            "isMembership": True,
            "isAdmin": False
        },
        "statusCode": 200
    }

# 5.2 tunemusic & StagePrompter Routes & Integration Bridge
@app.get("/tunemusic")
@app.get("/tunemusic/")
@app.get("/pt/tunemusic")
@app.get("/pt/tunemusic/")
@app.get("/stageprompter")
@app.get("/stageprompter/")
@app.get("/pt/stageprompter")
@app.get("/pt/stageprompter/")
async def serve_stageprompter_page():
    stageprompter_file = STATIC_DIR / "stageprompter" / "index.html"
    if stageprompter_file.exists():
        return FileResponse(stageprompter_file)
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/stageprompter/presentation")
@app.get("/stageprompter/presentation/")
@app.get("/pt/stageprompter/presentation")
@app.get("/pt/stageprompter/presentation/")
async def serve_stageprompter_presentation():
    presentation_file = STATIC_DIR / "stageprompter" / "presentation.html"
    if presentation_file.exists():
        return FileResponse(presentation_file)
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/api/stageprompter/vocal-tasks")
async def list_vocal_remover_tasks():
    """
    Retorna tarefas de separação do Vocal Remover para importação 1-click no StagePrompter.
    """
    result = []
    for task_id, t in tasks.items():
        if t.get("status") == "ready":
            key = t.get("key", "stem")
            result.append({
                "id": task_id,
                "filename": t.get("filename", "audio"),
                "instrumental_url": f"/split/listen/music/{task_id}/{key}",
                "vocal_url": f"/split/listen/vocal/{task_id}/{key}",
                "mix_url": f"/split/listen/mix/{task_id}/{key}",
                "bpm": t.get("bpm", 120),
                "tonality": t.get("tonality", "C")
            })
    try:
        for d in OUTPUT_DIR.iterdir():
            if d.is_dir() and d.name not in tasks:
                if (d / "music.wav").exists() or (d / "vocal.wav").exists():
                    tid = d.name
                    result.append({
                        "id": tid,
                        "filename": f"Música {tid[:8]}",
                        "instrumental_url": f"/split/listen/music/{tid}/local",
                        "vocal_url": f"/split/listen/vocal/{tid}/local",
                        "mix_url": f"/split/listen/mix/{tid}/local",
                        "bpm": 120,
                        "tonality": "C"
                    })
    except Exception:
        pass
    return result

# 6. Serve static assets
STAGEPROMPTER_DIR = STATIC_DIR / "stageprompter"
app.mount("/stageprompter", StaticFiles(directory=str(STAGEPROMPTER_DIR)), name="stageprompter")
if (STAGEPROMPTER_DIR / "fonts").exists():
    app.mount("/fonts", StaticFiles(directory=str(STAGEPROMPTER_DIR / "fonts")), name="fonts")
app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")
app.mount("/img", StaticFiles(directory=str(STATIC_DIR / "img")), name="img")
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")

# 7. Unified Desktop Workstation Entry Points
@app.get("/")
@app.get("/tunemusic")
@app.get("/tunemusic/")
@app.get("/pt/tunemusic")
@app.get("/pt/tunemusic/")
@app.get("/stageprompter")
@app.get("/stageprompter/")
@app.get("/pt/stageprompter")
@app.get("/pt/stageprompter/")
async def serve_main_app():
    return FileResponse(STAGEPROMPTER_DIR / "index.html")

VOCAL_TOOLS_FILE = STATIC_DIR / "vocal_tools.html"
VOCAL_TOOL_PATHS = (
    "pitch", "cutter", "joiner", "key-bpm-finder", "voice-recorder", "karaoke", "splitter-ai",
    "pt", "pt/pitch", "pt/cutter", "pt/joiner", "pt/key-bpm-finder", "pt/voice-recorder", "pt/karaoke", "pt/splitter-ai"
)

@app.get("/pt")
@app.get("/pt/")
@app.get("/vocal-tools")
@app.get("/vocal-tools/{tool_subpath:path}")
async def serve_vocal_tools(tool_subpath: str = ""):
    return FileResponse(VOCAL_TOOLS_FILE)

@app.get("/presentation")
@app.get("/stageprompter/presentation")
@app.get("/stageprompter/presentation/")
@app.get("/pt/stageprompter/presentation")
@app.get("/pt/stageprompter/presentation/")
async def serve_presentation_app():
    return FileResponse(STAGEPROMPTER_DIR / "presentation.html")

@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    if full_path.startswith("api/") or full_path.startswith("split/") or full_path.startswith("uploads/") or full_path.startswith("output/"):
        raise HTTPException(status_code=404)
    clean_path = full_path.strip("/")
    if clean_path.startswith("pt/stageprompter") or clean_path == "stageprompter" or clean_path.startswith("pt/tunemusic") or clean_path == "tunemusic":
        return FileResponse(STAGEPROMPTER_DIR / "index.html")
    if clean_path == "pt" or clean_path.startswith("pt/") or clean_path in VOCAL_TOOL_PATHS or any(clean_path.startswith(p) for p in ("vocal-tools", "pitch", "cutter", "joiner", "key-bpm-finder", "voice-recorder", "karaoke", "splitter-ai")):
        return FileResponse(VOCAL_TOOLS_FILE)
    if full_path in ("index.html",):
        return FileResponse(STAGEPROMPTER_DIR / "index.html")
    # Check in stageprompter dir first (e.g. LOGO.png, styles.css)
    sp_file = STAGEPROMPTER_DIR / full_path
    if sp_file.is_file():
        return FileResponse(sp_file)
    if "presentation" in clean_path:
        return FileResponse(STAGEPROMPTER_DIR / "presentation.html")
    # Prevent serving the legacy web app
    if full_path.startswith("assets/") or full_path.startswith("img/"):
        file_path = STATIC_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
    return FileResponse(STAGEPROMPTER_DIR / "index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
