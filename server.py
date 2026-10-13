import asyncio
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Dict, Any, List

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

app = FastAPI(title="VocalRemover Authentic Reconstructed Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


MODAL_GPU_URL = os.getenv("MODAL_GPU_URL", "https://appwillb--vocal-remover-ai-api.us-east.modal.run/separate")
MODAL_TUNE_URL = os.getenv("MODAL_TUNE_URL", "https://appwillb--vocal-remover-ai-api.us-east.modal.run/tune")


async def run_demucs_task(task_id: str, input_path: Path, model: int):
    task_out_dir = OUTPUT_DIR / task_id
    task_out_dir.mkdir(exist_ok=True)

    await broadcast_ws(task_id, {"status": "processing", "progress": 20})

    # 1. Tentar via Modal Serverless GPU (Gratuito, rápido e não pesa na VPS)
    if MODAL_GPU_URL:
        try:
            import httpx
            import base64

            await broadcast_ws(task_id, {"status": "processing", "progress": 40})
            print(f"[{task_id}] Enviando audio para Modal GPU...")

            audio_data = input_path.read_bytes()
            async with httpx.AsyncClient(timeout=180.0) as client:
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
                    await broadcast_ws(task_id, {
                        "status": "ready",
                        "id": task_id,
                        "key": tasks[task_id]["key"],
                        "tonality": "C",
                        "bpm": 120
                    })
                    print(f"[{task_id}] Processamento concluído via Modal GPU com sucesso!")
                    return
                else:
                    print(f"[{task_id}] Modal retornou erro interno:", data.get("error"))
            else:
                print(f"[{task_id}] Modal HTTP status:", resp.status_code)
        except Exception as e:
            print(f"[{task_id}] Erro na conexão com Modal GPU, tentando fallback:", e)

    # 2. Fallback: Processamento local
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"

    cores = "1" if device == "cuda" else str(max(1, (os.cpu_count() or 2)))
    cmd = [
        sys.executable,
        "-m",
        "demucs.separate",
        "-n", "htdemucs",
        "-d", device,
        "--shifts", "1",
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

        await broadcast_ws(task_id, {"status": "processing", "progress": 50})

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            print("Demucs error:", stderr.decode(errors="ignore"))
            await broadcast_ws(task_id, {"status": "error", "message": "Falha na separação"})
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

        tasks[task_id]["status"] = "ready"
        await broadcast_ws(task_id, {
            "status": "ready",
            "id": task_id,
            "key": tasks[task_id]["key"],
            "tonality": "C",
            "bpm": 120
        })

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


# 4. Audio Stem Delivery API
@app.get("/split/listen/{stem}/{task_id}/{key}")
async def listen_stem(stem: str, task_id: str, key: str):
    task_out_dir = OUTPUT_DIR / task_id
    stem_file = task_out_dir / f"{stem}.wav"

    if not stem_file.exists():
        # Fallback names
        if stem == "vocal":
            alt = task_out_dir / "vocals.wav"
            if alt.exists():
                return FileResponse(alt, media_type="audio/wav")
        elif stem == "music":
            alt = task_out_dir / "instrumental.wav"
            if alt.exists():
                return FileResponse(alt, media_type="audio/wav")
        raise HTTPException(status_code=404, detail="Faixa não encontrada")

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

# 5.1 Vocal Studio Pitch Corrector API
@app.post("/api/tune-vocal")
async def tune_vocal_endpoint(
    file: UploadFile = File(...),
    root: str = Form("C"),
    scale: str = Form("major"),
    strength: float = Form(0.85),
    retune_speed: float = Form(0.5),
    preserve_vibrato: bool = Form(True)
):
    """
    Endpoint para afinação vocal profissional:
    1. Tenta via Modal Serverless GPU na nuvem
    2. Fallback transparente local com vocal_tuner.py
    """
    import tempfile
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Arquivo de audio vazio")

    # 1. Tentar Modal GPU
    if MODAL_TUNE_URL:
        try:
            import httpx
            import base64
            params = {
                "root": root,
                "scale": scale,
                "strength": str(strength),
                "retune_speed": str(retune_speed),
                "preserve_vibrato": "true" if preserve_vibrato else "false"
            }
            async with httpx.AsyncClient(timeout=180.0) as client:
                resp = await client.post(
                    MODAL_TUNE_URL,
                    params=params,
                    content=audio_bytes,
                    headers={"Content-Type": "application/octet-stream"}
                )

            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    tuned_bytes = base64.b64decode(data["tuned_b64"])
                    print(f"[Tune] Áudio afinado com sucesso via Modal GPU ({root} {scale}, {strength*100:.0f}%)")
                    return Response(content=tuned_bytes, media_type="audio/wav")
                else:
                    print("[Tune] Modal retornou erro interno:", data.get("error"))
            else:
                print("[Tune] Modal HTTP status:", resp.status_code, resp.text[:150])
        except Exception as e:
            print("[Tune] Erro ao conectar com Modal GPU, usando fallback local:", e)

    # 2. Fallback Local via vocal_tuner.py
    try:
        from vocal_tuner import tune_vocal
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as in_f, \
             tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as out_f:
            in_path = in_f.name
            out_path = out_f.name
            in_f.write(audio_bytes)

        tune_vocal(
            in_path,
            out_path,
            root=root,
            scale=scale,
            strength=strength,
            retune_speed=retune_speed,
            preserve_vibrato=preserve_vibrato
        )

        with open(out_path, "rb") as f:
            tuned_bytes = f.read()

        try:
            os.remove(in_path)
            os.remove(out_path)
        except Exception:
            pass

        print(f"[Tune] Áudio afinado via processador local ({root} {scale})")
        return Response(content=tuned_bytes, media_type="audio/wav")
    except Exception as e:
        print("[Tune] Erro no fallback local:", e)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tuner")
@app.get("/pt/tuner")
async def serve_tuner_page():
    tuner_file = STATIC_DIR / "tuner.html"
    if tuner_file.exists():
        return FileResponse(tuner_file)
    return FileResponse(STATIC_DIR / "index.html")

# 6. Serve static assets

app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")
app.mount("/img", StaticFiles(directory=str(STATIC_DIR / "img")), name="img")

# 7. SPA catch-all route: any page serves index.html
@app.get("/")
async def root_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/pt/")

@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    if full_path.startswith("api/") or full_path.startswith("split/"):
        raise HTTPException(status_code=404)
    file_path = STATIC_DIR / full_path
    if file_path.is_file():
        return FileResponse(file_path)
    return FileResponse(STATIC_DIR / "index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=False)
