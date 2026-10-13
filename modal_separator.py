import os
import subprocess
import tempfile
import base64
import sys
import types
from pathlib import Path
import modal
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# Shim para garantir que pyworld nunca falhe no import
if "pkg_resources" not in sys.modules:
    dummy_pkg = types.ModuleType("pkg_resources")
    dummy_pkg.get_distribution = lambda n: types.SimpleNamespace(version="0.3.5")
    sys.modules["pkg_resources"] = dummy_pkg

app = modal.App("vocal-remover-ai")

# Imagem com Debian, FFmpeg, PyTorch, Demucs e WORLD Vocoder
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg")
    .pip_install(
        "torch",
        "torchaudio",
        "numpy<2.0",
        "demucs",
        "fastapi[standard]",
        "pyworld",
        "scipy",
        "soundfile",
        "setuptools<70"
    )
)

web_app = FastAPI(title="VocalRemover AI Cloud GPU Engine")
web_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@web_app.post("/separate")
async def separate(request: Request):
    """
    Recebe os bytes do áudio via POST e retorna vocals e no_vocals em base64.
    """
    audio_data = await request.body()
    if not audio_data:
        return JSONResponse({"error": "Nenhum audio enviado"}, status_code=400)

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


@web_app.post("/tune")
async def tune(request: Request):
    """
    Afinador Vocal de Alta Fidelidade (Studio Melodyne Style):
    Recebe bytes do audio no body e parametros na query string.
    """
    try:
        import numpy as np
        import pyworld as pw
        import soundfile as sf
        from scipy.ndimage import uniform_filter1d
        import traceback

        NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        SCALES = {
            "chromatic": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
            "major": [0, 2, 4, 5, 7, 9, 11],
            "minor": [0, 2, 3, 5, 7, 8, 10],
            "pentatonic_major": [0, 2, 4, 7, 9],
            "pentatonic_minor": [0, 3, 5, 7, 10],
        }

        audio_bytes = await request.body()
        if not audio_bytes:
            return JSONResponse({"error": "Nenhum audio enviado"}, status_code=400)

        root = request.query_params.get("root", "C").upper()
        scale = request.query_params.get("scale", "major").lower()
        strength = float(request.query_params.get("strength", "0.85"))
        retune_speed = float(request.query_params.get("retune_speed", "0.5"))
        preserve_vibrato = request.query_params.get("preserve_vibrato", "true").lower() in ("true", "1")

        with tempfile.TemporaryDirectory() as tmpdir:
            in_file = Path(tmpdir) / "vocal_in.wav"
            out_file = Path(tmpdir) / "vocal_tuned.wav"
            in_file.write_bytes(audio_bytes)

            x, fs = sf.read(str(in_file))
            if x.ndim > 1:
                mono_x = np.mean(x, axis=1)
            else:
                mono_x = x

            mono_x = np.ascontiguousarray(mono_x, dtype=np.float64)

            # 1. Análise espectral de alta precisão
            frame_period = 5.0
            _f0, timeaxis = pw.harvest(mono_x, fs, f0_floor=65.0, f0_ceil=700.0, frame_period=frame_period)
            f0 = pw.stonemask(mono_x, _f0, timeaxis, fs)
            sp = pw.cheaptrick(mono_x, f0, timeaxis, fs)
            ap = pw.d4c(mono_x, f0, timeaxis, fs)

            # 2. Escala musical
            root_idx = NOTE_NAMES.index(root) if root in NOTE_NAMES else 0
            intervals = SCALES.get(scale, SCALES["chromatic"])
            allowed_pcs = [(root_idx + iv) % 12 for iv in intervals]

            # 3. Correção de afinação
            voiced_mask = f0 > 0
            if np.any(voiced_mask):
                midi = np.zeros_like(f0)
                midi[voiced_mask] = 69.0 + 12.0 * np.log2(f0[voiced_mask] / 440.0)
                corrected_midi = np.copy(midi)

                voiced_indices = np.where(voiced_mask)[0]
                segments = np.split(voiced_indices, np.where(np.diff(voiced_indices) > 1)[0] + 1)
                window_frames = max(3, int(0.200 / (frame_period / 1000.0)))

                for seg in segments:
                    if len(seg) < 4:
                        continue
                    seg_midi = midi[seg]
                    if preserve_vibrato and len(seg) >= window_frames:
                        trend = uniform_filter1d(seg_midi, size=window_frames, mode='nearest')
                        vibrato = seg_midi - trend
                    else:
                        trend = seg_midi
                        vibrato = np.zeros_like(seg_midi)

                    target_notes = np.zeros_like(trend)
                    for i, val in enumerate(trend):
                        pc = val % 12.0
                        best_diff = 999.0
                        for apc in allowed_pcs:
                            diff = apc - pc
                            if diff > 6: diff -= 12
                            if diff < -6: diff += 12
                            if abs(diff) < abs(best_diff):
                                best_diff = diff
                        target_notes[i] = val + best_diff

                    smooth_window = max(1, int((0.05 + 0.20 * retune_speed) / (frame_period / 1000.0)))
                    smoothed_target = uniform_filter1d(target_notes, size=smooth_window, mode='nearest')
                    tuned_trend = trend + (smoothed_target - trend) * strength

                    corrected_midi[seg] = tuned_trend + vibrato

                corrected_f0 = np.zeros_like(f0)
                corrected_f0[voiced_mask] = 440.0 * (2.0 ** ((corrected_midi[voiced_mask] - 69.0) / 12.0))
            else:
                corrected_f0 = f0

            # 4. Síntese com preservação perfeita de formantes e consoantes
            y = pw.synthesize(corrected_f0, sp, ap, fs, frame_period=frame_period)
            if len(y) > len(mono_x):
                y = y[:len(mono_x)]
            elif len(y) < len(mono_x):
                y = np.pad(y, (0, len(mono_x) - len(y)))

            if x.ndim > 1:
                out_audio = np.stack([y, y], axis=1)
            else:
                out_audio = y

            sf.write(str(out_file), out_audio, fs)
            tuned_b64 = base64.b64encode(out_file.read_bytes()).decode("ascii")

            return JSONResponse({
                "status": "success",
                "tuned_b64": tuned_b64
            })
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        print("Tuner error:\n", err_msg)
        return JSONResponse({"error": str(e), "traceback": err_msg}, status_code=500)


@app.function(
    image=image,
    gpu="T4",
    timeout=300,
    scaledown_window=60
)
@modal.asgi_app()
def api():
    return web_app
