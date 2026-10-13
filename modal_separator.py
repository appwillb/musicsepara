import os
import subprocess
import tempfile
import base64
from pathlib import Path
import modal
from fastapi import Request
from fastapi.responses import JSONResponse

app = modal.App("vocal-remover-ai")

# Imagem com Debian, FFmpeg, PyTorch e Demucs
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg")
    .pip_install("torch", "torchaudio", "numpy<2.0", "demucs", "fastapi[standard]")
)

@app.function(
    image=image,
    gpu="T4",
    timeout=300,
    scaledown_window=60
)
@modal.fastapi_endpoint(method="POST")
async def separate(request: Request):
    """
    Recebe os bytes do áudio via POST e retorna vocals e no_vocals em base64.
    """
    audio_data = await request.body()
    if not audio_data:
        return JSONResponse({"error": "Nenhum audio enviado"}, status_code=400)

    # Identifica formato pelos primeiros bytes
    ext = ".wav" if audio_data.startswith(b"RIFF") else ".mp3"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        input_file = tmp_path / f"input{ext}"
        input_file.write_bytes(audio_data)

        out_dir = tmp_path / "out"
        out_dir.mkdir(exist_ok=True)

        cmd = [
            "demucs",
            "-n", "htdemucs",
            "-d", "cuda",
            "--two-stems", "vocals",
            "--clip-mode", "clamp",
            "-o", str(out_dir),
            str(input_file)
        ]

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print("Demucs error:", res.stderr)
            return JSONResponse({"error": res.stderr}, status_code=500)

        track_stem = "input"
        vocals_path = out_dir / "htdemucs" / track_stem / "vocals.wav"
        no_vocals_path = out_dir / "htdemucs" / track_stem / "no_vocals.wav"

        if not vocals_path.exists() or not no_vocals_path.exists():
            return JSONResponse({"error": "Arquivos de saida nao encontrados"}, status_code=500)

        vocals_b64 = base64.b64encode(vocals_path.read_bytes()).decode("ascii")
        no_vocals_b64 = base64.b64encode(no_vocals_path.read_bytes()).decode("ascii")

        return JSONResponse({
            "status": "success",
            "vocals_b64": vocals_b64,
            "no_vocals_b64": no_vocals_b64
        })
