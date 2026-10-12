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
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
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
        "status": "processing",
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


async def run_demucs_task(task_id: str, input_path: Path, model: int):
    task_out_dir = OUTPUT_DIR / task_id
    task_out_dir.mkdir(exist_ok=True)

    await broadcast_ws(task_id, {"status": "processing", "progress": 20})

    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"

    cmd = [
        sys.executable,
        "-m",
        "demucs.separate",
        "-n", "htdemucs",
        "-d", device,
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
