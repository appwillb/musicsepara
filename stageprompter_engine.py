import asyncio
import json
import os
import re
import shutil
import subprocess
import time
import uuid
import unicodedata
import urllib.parse
from pathlib import Path
from typing import Dict, Any, List, Optional

import httpx
from bs4 import BeautifulSoup
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "stageprompter"
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR = BASE_DIR / "outputs"
VIDEO_OUT_DIR = BASE_DIR / "outputs" / "videos"
VIDEO_OUT_DIR.mkdir(parents=True, exist_ok=True)

REPERTORIO_FILE = DATA_DIR / "repertorio.json"
CREDITOS_FILE = DATA_DIR / "creditos.json"
LYRICS_CACHE_FILE = DATA_DIR / "lyrics_cache.json"

# Detect bundled ffmpeg
FFMPEG_BIN = str(BASE_DIR / "bin" / "ffmpeg.exe")
if not os.path.exists(FFMPEG_BIN):
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        FFMPEG_BIN = system_ffmpeg
    else:
        sp_ffmpeg = Path("C:/Users/mauri/AppData/Local/Programs/StagePrompter lite/resources/app.asar.unpacked/node_modules/ffmpeg-static/ffmpeg.exe")
        if sp_ffmpeg.exists():
            FFMPEG_BIN = str(sp_ffmpeg)

# Fonts detection
FONT_PATH = "C:/Windows/Fonts/segoeuib.ttf"
if not os.path.exists(FONT_PATH):
    FONT_PATH = "C:/Windows/Fonts/arialbd.ttf"
if not os.path.exists(FONT_PATH):
    FONT_PATH = "C:/Windows/Fonts/arial.ttf"

router = APIRouter(prefix="/api/stageprompter", tags=["StagePrompter"])

# Initial default data setup
def get_default_repertorio() -> dict:
    return {
        "shows": [
            {
                "id": "show-demo-1",
                "titulo": "Show Principal",
                "blocos": [
                    {
                        "id": "bloco-1",
                        "nome": "Bloco 1 - Abertura",
                        "musicas": [
                            {
                                "id": "mus-1",
                                "track": "Evidências",
                                "artist": "Chitãozinho & Xororó",
                                "semLetra": False
                            },
                            {
                                "id": "mus-2",
                                "track": "Cheia de Manias",
                                "artist": "Raça Negra",
                                "semLetra": False
                            }
                        ]
                    },
                    {
                        "id": "bloco-2",
                        "nome": "Bloco 2 - Animação",
                        "musicas": [
                            {
                                "id": "mus-3",
                                "track": "Ai Se Eu Te Pego",
                                "artist": "Michel Teló",
                                "semLetra": False
                            }
                        ]
                    }
                ]
            }
        ],
        "activeShowId": "show-demo-1"
    }

def get_default_creditos() -> dict:
    return {
        "agradecimentos": [
            [
                {"t": "PATROCINADORES", "cor": "#FFD400"},
                {"t": "Cervejaria Premium"},
                {"t": "Hotel & Eventos Plaza"}
            ],
            [
                {"t": "EQUIPE TÉCNICA", "cor": "#00E5FF"},
                {"t": "Iluminação: Marcos Som"},
                {"t": "Técnico de PA: Rodrigo"}
            ]
        ],
        "participacoes": [
            [
                {"t": "PARTICIPAÇÕES ESPECIAIS", "cor": "#FF8A3D"},
                {"t": "DJ Alok - Set Especial"},
                {"t": "Banda Convidada"}
            ]
        ],
        "avisos": [
            [
                {"t": "AVISOS DA PRODUÇÃO", "cor": "#1DB954"},
                {"t": "Proibido garrafas de vidro"},
                {"t": "Estacionamento liberado até 04h"}
            ]
        ],
        "tituloAvisos": "Avisos"
    }

def fix_mojibake(s: str) -> str:
    """Repairs UTF-8 strings accidentally decoded as Windows-1252 or Latin-1."""
    if not s or not isinstance(s, str):
        return s or ""
    try:
        if any(m in s for m in ["Ã", "Â", "â", "ã", "ç", "©"]):
            cand = s.encode('latin1').decode('utf-8')
            return cand
    except Exception:
        pass
    return s

def clean_repertoire_mojibake(data: Any) -> Any:
    """Recursively cleans mojibake in repertoire objects."""
    if isinstance(data, dict):
        return {k: clean_repertoire_mojibake(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [clean_repertoire_mojibake(item) for item in data]
    elif isinstance(data, str):
        return fix_mojibake(data)
    return data

def read_json_file(file_path: Path, default_factory) -> dict:
    if not file_path.exists():
        data = default_factory()
        write_json_file(file_path, data)
        return data
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return clean_repertoire_mojibake(data)
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return default_factory()

def write_json_file(file_path: Path, data: dict):
    tmp_path = file_path.with_suffix(".tmp")
    data_cleaned = clean_repertoire_mojibake(data)
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data_cleaned, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, file_path)

def normalize_text(s: str) -> str:
    if not s:
        return ""
    fixed = fix_mojibake(s)
    nfkd = unicodedata.normalize('NFKD', fixed)
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    return no_accents.lower().strip()

def clean_song_query(text: str) -> str:
    """Cleans track/artist names by stripping noisy prefixes, feat tags, and live annotations."""
    if not text:
        return ""
    t = fix_mojibake(text)
    # Remove all parentheticals like (Ao Vivo), (feat. ...), (part. ...), (Live), (Acústico)
    t = re.sub(r'\s*\([^)]*\)\s*', ' ', t)
    # Remove brackets
    t = re.sub(r'\s*\[[^\]]*\]\s*', ' ', t)
    # Remove standalone feat/ft/part suffixes
    t = re.sub(r'\s*(feat\.|ft\.|part\.).*$', '', t, flags=re.IGNORECASE)
    # Remove trailing - Ao Vivo, - Versão, etc.
    t = re.sub(r'\s*-\s*(ao vivo|remaster|versão|acústico).*$', '', t, flags=re.IGNORECASE)
    # Normalize multiple whitespace
    t = re.sub(r'\s+', ' ', t)
    return t.strip()

def text_to_blocks(raw_text: str) -> List[str]:
    """
    CRITICAL: StagePrompter expects blocks to be an array of strings:
    [ "Verse 1 line 1\\nVerse 1 line 2", "Chorus line 1\\nChorus line 2", ... ]
    renderer.js iterates with: blocks.forEach(block => block.split('\\n'))
    Returning anything other than List[str] causes TypeError: block.split is not a function!
    """
    if not raw_text:
        return []
    
    # Split paragraphs by double newlines or blank lines
    raw_text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = re.split(r'\n\s*\n+', raw_text.strip())
    blocks = []
    
    for p in paragraphs:
        lines = [line.strip() for line in p.splitlines() if line.strip()]
        if lines:
            blocks.append("\n".join(lines))
            
    return blocks

# ----------------- REPERTOIRE ENDPOINTS ----------------- #
@router.get("/repertoire")
async def get_repertoire():
    return read_json_file(REPERTORIO_FILE, get_default_repertorio)

@router.post("/repertoire")
async def save_repertoire(data: dict):
    write_json_file(REPERTORIO_FILE, data)
    return {"ok": True}

# ----------------- CREDITS ENDPOINTS ----------------- #
@router.get("/credits")
async def get_credits():
    return read_json_file(CREDITOS_FILE, get_default_creditos)

@router.post("/credits")
async def save_credits(data: dict):
    write_json_file(CREDITOS_FILE, data)
    return {"ok": True}

# ----------------- SONGS / LYRICS CACHE ENDPOINTS ----------------- #
@router.get("/songs")
async def get_saved_songs():
    cache = read_json_file(LYRICS_CACHE_FILE, dict)
    songs = []
    for key, item in cache.items():
        if isinstance(item, dict):
            # Normalize blocks to List[str]
            b_list = item.get("blocks", [])
            if isinstance(b_list, list):
                item["blocks"] = ["\n".join(b) if isinstance(b, list) else str(b) for b in b_list]
            elif isinstance(b_list, str):
                item["blocks"] = text_to_blocks(b_list)
            songs.append(item)
    return songs

@router.get("/songs/keys")
async def get_song_keys():
    cache = read_json_file(LYRICS_CACHE_FILE, dict)
    return list(cache.keys())

def save_to_lyrics_cache(cache: dict, artist: str, track: str, blocks: List[str], source: str, synced_lyrics: Optional[str] = None):
    entry = {
        "artist": artist,
        "track": track,
        "blocks": blocks,
        "source": source,
        "syncedLyrics": synced_lyrics,
        "updatedAt": int(time.time() * 1000)
    }
    k1 = f"{artist.lower().strip()}|{track.lower().strip()}"
    k2 = f"{normalize_text(artist)}|{normalize_text(track)}"
    cache[k1] = entry
    cache[k2] = entry
    write_json_file(LYRICS_CACHE_FILE, cache)

@router.post("/songs")
async def save_song(payload: dict):
    artist = payload.get("artist", "").strip()
    track = payload.get("track", "").strip()
    raw_blocks = payload.get("blocks", [])
    if not artist or not track:
        raise HTTPException(status_code=400, detail="Artista e música são obrigatórios")
    
    # Normalize blocks
    if isinstance(raw_blocks, str):
        blocks = text_to_blocks(raw_blocks)
    elif isinstance(raw_blocks, list):
        blocks = ["\n".join(b) if isinstance(b, list) else str(b) for b in raw_blocks]
    else:
        blocks = []

    key = f"{artist.lower()}|{track.lower()}"
    cache = read_json_file(LYRICS_CACHE_FILE, dict)
    save_to_lyrics_cache(cache, artist, track, blocks, payload.get("source", "manual"))
    return {"ok": True, "key": key, "blocks": blocks}

@router.delete("/songs")
async def delete_song(payload: dict):
    artist = payload.get("artist", "").strip()
    track = payload.get("track", "").strip()
    key = f"{artist.lower()}|{track.lower()}"
    cache = read_json_file(LYRICS_CACHE_FILE, dict)
    if key in cache:
        del cache[key]
        write_json_file(LYRICS_CACHE_FILE, cache)
        return {"ok": True}
    return {"ok": False, "detail": "Música não encontrada"}

# ----------------- BACKUP EXPORT / IMPORT ----------------- #
@router.get("/backup")
async def export_backup():
    rep = read_json_file(REPERTORIO_FILE, get_default_repertorio)
    cred = read_json_file(CREDITOS_FILE, get_default_creditos)
    lyrics = read_json_file(LYRICS_CACHE_FILE, dict)
    backup_data = {
        "version": "2.6.3",
        "exportedAt": int(time.time() * 1000),
        "repertoire": rep,
        "credits": cred,
        "lyricsCache": lyrics
    }
    return JSONResponse(
        content=backup_data,
        headers={"Content-Disposition": f"attachment; filename=stageprompter-backup-{int(time.time())}.json"}
    )

@router.post("/backup")
async def import_backup(file: UploadFile = File(...)):
    try:
        content = await file.read()
        data = json.loads(content.decode("utf-8"))
        if "repertoire" in data:
            write_json_file(REPERTORIO_FILE, data["repertoire"])
        if "credits" in data:
            write_json_file(CREDITOS_FILE, data["credits"])
        if "lyricsCache" in data:
            write_json_file(LYRICS_CACHE_FILE, data["lyricsCache"])
        return {"ok": True, "message": "Backup importado com sucesso!"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao importar backup: {str(e)}")

# ----------------- SEARCH & LYRICS SCRAPING ----------------- #
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7"
}

@router.get("/search")
async def search_suggestions(q: str = Query(..., min_length=1), pref: str = "nacional"):
    """
    Search suggestions combining:
    1. Local saved repertoire / cache songs
    2. Letras Solr auto-suggest (Studio Sol)
    3. iTunes Search API (BR / US)
    4. LrcLib search API
    """
    results = []
    seen = set()

    # 1. Local saved songs
    cache = read_json_file(LYRICS_CACHE_FILE, dict)
    norm_q = normalize_text(q)
    for key, song in cache.items():
        if isinstance(song, dict):
            comb = normalize_text(f"{song.get('artist', '')} {song.get('track', '')}")
            if norm_q in comb:
                s_key = f"{normalize_text(song.get('track', ''))}|{normalize_text(song.get('artist', ''))}"
                if s_key not in seen:
                    seen.add(s_key)
                    results.append({
                        "track": song.get("track"),
                        "artist": song.get("artist"),
                        "saved": True
                    })

    # 2. Letras Solr CDN
    try:
        solr_url = f"https://solr.sscdn.co/letras/m1/?q={httpx.URL('', params={'q': q}).query.decode('utf-8')[2:]}"
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(solr_url, headers=HEADERS)
            if resp.status_code == 200:
                text = resp.text.strip()
                if text.startswith("LetrasSug(") and text.endswith(")"):
                    raw_json = text[10:-1]
                    solr_data = json.loads(raw_json)
                    docs = solr_data.get("response", {}).get("docs", [])
                    for d in docs:
                        if d.get("id", "").startswith("mus"):
                            track_name = d.get("txt")
                            artist_name = d.get("art")
                            if track_name and artist_name:
                                s_key = f"{normalize_text(track_name)}|{normalize_text(artist_name)}"
                                if s_key not in seen:
                                    seen.add(s_key)
                                    results.append({
                                        "track": track_name,
                                        "artist": artist_name,
                                        "url": f"https://www.letras.mus.br/{d.get('dns', '')}/{d.get('url', '')}/" if d.get('dns') and d.get('url') else None,
                                        "saved": False
                                    })
    except Exception:
        pass

    # 3. iTunes Search API
    try:
        country = "br" if pref != "internacional" else "us"
        itunes_url = f"https://itunes.apple.com/search?term={httpx.URL('', params={'q': q}).query.decode('utf-8')[2:]}&entity=song&limit=12&country={country}"
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(itunes_url, headers=HEADERS)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("results", []):
                    track_name = item.get("trackName")
                    artist_name = item.get("artistName")
                    if track_name and artist_name:
                        s_key = f"{normalize_text(track_name)}|{normalize_text(artist_name)}"
                        if s_key not in seen:
                            seen.add(s_key)
                            results.append({
                                "track": track_name,
                                "artist": artist_name,
                                "saved": False
                            })
    except Exception:
        pass

    # 4. LrcLib Search API
    try:
        lrclib_url = f"https://lrclib.net/api/search?q={httpx.URL('', params={'q': q}).query.decode('utf-8')[2:]}"
        async with httpx.AsyncClient(timeout=3.5) as client:
            resp = await client.get(lrclib_url, headers=HEADERS)
            if resp.status_code == 200:
                for item in resp.json()[:8]:
                    track_name = item.get("trackName")
                    artist_name = item.get("artistName")
                    if track_name and artist_name:
                        s_key = f"{normalize_text(track_name)}|{normalize_text(artist_name)}"
                        if s_key not in seen:
                            seen.add(s_key)
                            results.append({
                                "track": track_name,
                                "artist": artist_name,
                                "saved": False
                            })
    except Exception:
        pass

    return {"ok": True, "results": results[:20]}

def unquote_ddg(url: str) -> str:
    m = re.search(r'[?&]uddg=([^&]+)', url)
    if m:
        return urllib.parse.unquote(m.group(1))
    return url

def extract_featured_artist(text: str) -> Optional[str]:
    """Extracts featured artist if present (e.g. feat. Zé Neto e Cristiano)."""
    m = re.search(r'\((?:feat\.|ft\.|part\.)\s*([^)]+)\)', text, re.IGNORECASE)
    if m:
        return clean_song_query(m.group(1))
    m2 = re.search(r'(?:feat\.|ft\.|part\.)\s*(.+)$', text, re.IGNORECASE)
    if m2:
        return clean_song_query(m2.group(1))
    return None

def slugify(text: str) -> str:
    """Produces clean URL slug matching Letras.com.br / Letras.mus.br URL patterns."""
    if not text:
        return ""
    t = fix_mojibake(text)
    t = unicodedata.normalize('NFKD', t).encode('ascii', 'ignore').decode('utf-8')
    t = t.replace('&', ' e ').replace('+', ' e ')
    t = re.sub(r'[^a-zA-Z0-9]+', '-', t.lower()).strip('-')
    return t

def is_valid_lyrics(blocks: List[str]) -> bool:
    """Strictly validates that blocks represent actual song lyrics, NOT artist bios or descriptions."""
    if not blocks:
        return False
    full_text = "\n".join(blocks).strip()
    total_lines = len(full_text.splitlines())
    
    junk_patterns = [
        r'ouça músicas de',
        r'ouca musicas de',
        r'veja as letras de',
        r'biografia de',
        r'discografia de',
        r'confira a biografia',
        r'esta canção aparece em',
        r'pedimos desculpas, mas infelizmente',
        r'todos os direitos reservados',
        r'ouça no spotify'
    ]
    for jp in junk_patterns:
        if re.search(jp, full_text, re.IGNORECASE):
            return False
            
    if total_lines < 4:
        return False
        
    return True

def is_valid_lyrics_url(url: str) -> bool:
    """Checks if the URL is a genuine song URL and NOT an artist profile, album list, or biography."""
    try:
        parsed = urllib.parse.urlparse(url)
        path = parsed.path.strip('/')
        segments = [s for s in path.split('/') if s]
        
        # letras.com.br / letras.mus.br:
        # Artist page: /mauricio-e-eduardo (1 segment) -> REJECT
        # Bio: /mauricio-e-eduardo/biografia -> REJECT
        # Song page: /mauricio-e-eduardo/gaiola (2 segments) -> ACCEPT
        if any(dom in parsed.netloc for dom in ['letras.com.br', 'letras.mus.br', 'letras.com']):
            if len(segments) < 2:
                return False
            if segments[1] in ['biografia', 'discografia', 'curiosidades', 'fotos', 'albuns', 'videos']:
                return False
            return True
            
        if 'cifraclub.com.br' in parsed.netloc:
            if len(segments) < 2:
                return False
            return True
            
        if 'genius.com' in parsed.netloc:
            if segments and (segments[0] == 'artists' or segments[0] == 'albums'):
                return False
            return True
            
        if 'vagalume.com.br' in parsed.netloc:
            if len(segments) < 2:
                return False
            return True
    except Exception:
        pass
    return True

def clean_verse_lines(raw_text: str) -> List[str]:
    """Cleans Genius, CifraClub, and site artifacts into verse blocks."""
    if not raw_text:
        return []
    lines = []
    for line in raw_text.splitlines():
        l = line.strip()
        if not l:
            lines.append("")
            continue
        # Strip Genius metadata & contributor prefixes
        if re.search(r'^\d+\s*Contributors', l, re.IGNORECASE):
            continue
        if re.search(r'Lyrics\s*$', l, re.IGNORECASE) and len(l) < 80 and not any(c in l for c in [",", "."]):
            continue
        if re.search(r'^\d*\s*Embed$', l, re.IGNORECASE):
            continue
        if re.search(r'^\[.*?\]$', l):
            continue
        lines.append(l)
    return text_to_blocks("\n".join(lines))

async def scrape_lyrics_url(url: str, client: Optional[httpx.AsyncClient] = None) -> List[str]:
    """Scrapes lyrics from a supported URL, rejecting artist bios and invalid pages."""
    if not is_valid_lyrics_url(url):
        return []
    close_client = False
    if client is None:
        client = httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=8.0)
        close_client = True

    try:
        resp = await client.get(url, timeout=7.0)
        if resp.status_code != 200:
            return []

        # 1. letras.com.br / letras.mus.br Vue prop
        if "letras.com.br" in url or "letras.mus.br" in url:
            m = re.search(r':lyrics="`([^`]+)`"', resp.text)
            if m:
                b = clean_verse_lines(m.group(1))
                if is_valid_lyrics(b):
                    return b

        soup = BeautifulSoup(resp.text, "html.parser")
        
        # 2. letras.com.br / letras.mus.br HTML containers
        div = soup.find("div", class_="lyric-original") or soup.find("div", class_="lyric") or soup.find("div", class_="cnt-letra")
        if div:
            paragraphs = []
            for p in div.find_all("p"):
                lines = [line.strip() for line in p.stripped_strings]
                if lines:
                    paragraphs.append("\n".join(lines))
            if paragraphs:
                b = clean_verse_lines("\n\n".join(paragraphs))
                if is_valid_lyrics(b):
                    return b

        # 3. Vagalume
        if "vagalume.com.br" in url:
            lyrics_el = soup.find(id="lyrics")
            if lyrics_el:
                for br in lyrics_el.find_all("br"):
                    br.replace_with("\n")
                b = clean_verse_lines(lyrics_el.get_text())
                if is_valid_lyrics(b):
                    return b

        # 4. Genius
        if "genius.com" in url:
            containers = soup.find_all(attrs={"data-lyrics-container": "true"})
            if containers:
                text_parts = []
                for c in containers:
                    for br in c.find_all("br"):
                        br.replace_with("\n")
                    text_parts.append(c.get_text())
                combined = "\n\n".join(text_parts)
                b = clean_verse_lines(combined)
                if is_valid_lyrics(b):
                    return b
                    
    except Exception as e:
        pass
    finally:
        if close_client:
            await client.aclose()
    return []

@router.post("/fetch-lyrics")
async def fetch_lyrics_endpoint(payload: dict):
    """
    Fetches song lyrics by track and artist, or directly from a URL.
    Multi-stage strategy:
    1. Direct URL if provided
    2. Local verified cache check (invalidates any stored bios)
    3. Direct Letras slug matching (primary artist & featured artist)
    4. Letras artist catalog scan
    5. DuckDuckGo / web search fallback (validating song URLs and contents)
    6. Vagalume & LrcLib fallback
    """
    track = payload.get("track", "").strip()
    artist = payload.get("artist", "").strip()
    url = payload.get("url", "").strip()

    # 1. Direct URL fetch
    if url:
        blocks = await scrape_lyrics_url(url)
        if blocks and is_valid_lyrics(blocks):
            return {
                "ok": True,
                "track": track or "Música",
                "artist": artist or "Artista",
                "blocks": blocks,
                "source": url
            }
        return {
            "ok": False,
            "error": "Não foi possível extrair a letra do link informado."
        }

    # Clean artist & track names with mojibake repair
    track = fix_mojibake(track)
    artist = fix_mojibake(artist)
    c_track = clean_song_query(track)
    c_artist = clean_song_query(artist)
    feat_artist = extract_featured_artist(track)
    
    key_exact = f"{artist.lower().strip()}|{track.lower().strip()}"
    key_norm = f"{normalize_text(artist)}|{normalize_text(track)}"
    cache = read_json_file(LYRICS_CACHE_FILE, dict)

    # 2. Check local cache first, purifying any corrupted bio entries
    found_key = key_exact if key_exact in cache else (key_norm if key_norm in cache else None)
    if found_key and not payload.get("force"):
        saved = cache[found_key]
        raw_b = saved.get("blocks", [])
        if isinstance(raw_b, list):
            blocks = ["\n".join(b) if isinstance(b, list) else str(b) for b in raw_b]
        elif isinstance(raw_b, str):
            blocks = text_to_blocks(raw_b)
        else:
            blocks = []
            
        if is_valid_lyrics(blocks):
            return {
                "ok": True,
                "track": saved.get("track", track),
                "artist": saved.get("artist", artist),
                "blocks": blocks,
                "source": saved.get("source", "cache")
            }
        else:
            # Purge bad cached entry
            if found_key in cache:
                del cache[found_key]
                write_json_file(LYRICS_CACHE_FILE, cache)

    artists_to_try = [c_artist] if c_artist else []
    if feat_artist and feat_artist not in artists_to_try:
        artists_to_try.append(feat_artist)
    track_slug = slugify(c_track)

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=7.0) as client:
        # 3. Strategy A: Direct Letras slugs
        if track_slug:
            for art in artists_to_try:
                art_slug = slugify(art)
                candidates = [
                    f"https://www.letras.com.br/{art_slug}/{track_slug}",
                    f"https://www.letras.com.br/{art_slug.replace('-e-', '-')}/{track_slug}",
                    f"https://www.letras.mus.br/{art_slug}/{track_slug}/",
                    f"https://www.letras.mus.br/{art_slug.replace('-e-', '-')}/{track_slug}/",
                ]
                for c_url in candidates:
                    blocks = await scrape_lyrics_url(c_url, client)
                    if blocks and is_valid_lyrics(blocks):
                        save_to_lyrics_cache(cache, artist, track, blocks, c_url)
                        return {
                            "ok": True,
                            "track": track,
                            "artist": artist,
                            "blocks": blocks,
                            "source": c_url
                        }

        # 4. Strategy B: Artist catalog page on Letras.com.br
        if track_slug:
            for art in artists_to_try:
                art_slug = slugify(art)
                for aslug in [art_slug, art_slug.replace('-e-', '-')]:
                    artist_url = f"https://www.letras.com.br/{aslug}"
                    try:
                        r_art = await client.get(artist_url, timeout=6.0)
                        if r_art.status_code == 200:
                            soup = BeautifulSoup(r_art.text, "html.parser")
                            for a in soup.find_all("a", href=True):
                                href = a["href"]
                                title = a.get_text().strip()
                                clean_href = href.split("#")[0].strip("/")
                                if clean_href.startswith(aslug + "/") and len(clean_href.split("/")) == 2:
                                    song_part = clean_href.split("/")[1]
                                    if song_part == track_slug or slugify(title) == track_slug or track_slug in song_part:
                                        target_song_url = f"https://www.letras.com.br/{clean_href}"
                                        blocks = await scrape_lyrics_url(target_song_url, client)
                                        if blocks and is_valid_lyrics(blocks):
                                            save_to_lyrics_cache(cache, artist, track, blocks, target_song_url)
                                            return {
                                                "ok": True,
                                                "track": track,
                                                "artist": artist,
                                                "blocks": blocks,
                                                "source": target_song_url
                                            }
                    except Exception:
                        pass

        # 5. Strategy C: Web search fallback (DuckDuckGo Lite)
        queries = [
            f"site:letras.com.br {c_track} {c_artist}".strip(),
            f"letra {c_track} {c_artist}".strip()
        ]
        if feat_artist:
            queries.insert(1, f"site:letras.com.br {c_track} {feat_artist}".strip())

        seen_urls = set()
        for q in queries:
            try:
                r_ddg = await client.post("https://lite.duckduckgo.com/lite/", data={"q": q}, timeout=6.0)
                if r_ddg.status_code == 200:
                    soup = BeautifulSoup(r_ddg.text, "html.parser")
                    for a in soup.find_all("a", href=True):
                        raw_href = a["href"]
                        m = re.search(r'[?&]uddg=([^&]+)', raw_href)
                        clean_url = urllib.parse.unquote(m.group(1)) if m else raw_href
                        if clean_url in seen_urls:
                            continue
                        seen_urls.add(clean_url)
                        if is_valid_lyrics_url(clean_url):
                            blocks = await scrape_lyrics_url(clean_url, client)
                            if blocks and is_valid_lyrics(blocks):
                                save_to_lyrics_cache(cache, artist, track, blocks, clean_url)
                                return {
                                    "ok": True,
                                    "track": track,
                                    "artist": artist,
                                    "blocks": blocks,
                                    "source": clean_url
                                }
            except Exception:
                pass

        # 6. Strategy D: Vagalume API
        if c_artist and c_track:
            try:
                vaga_url = "https://api.vagalume.com.br/search.php"
                vaga_resp = await client.get(vaga_url, params={"art": c_artist, "mus": c_track}, timeout=5.0)
                if vaga_resp.status_code == 200:
                    data = vaga_resp.json()
                    if data.get("type") in ["exact", "aprox"] and data.get("mus"):
                        lyric_text = data["mus"][0].get("text")
                        if lyric_text:
                            blocks = clean_verse_lines(lyric_text)
                            if blocks and is_valid_lyrics(blocks):
                                save_to_lyrics_cache(cache, artist, track, blocks, "vagalume-api")
                                return {
                                    "ok": True,
                                    "track": track,
                                    "artist": artist,
                                    "blocks": blocks,
                                    "source": "vagalume"
                                }
            except Exception:
                pass

        # 7. Strategy E: LrcLib.net (Exact Get & Search)
        if c_artist and c_track:
            try:
                resp = await client.get(
                    "https://lrclib.net/api/get",
                    params={"artist_name": c_artist, "track_name": c_track},
                    headers={"User-Agent": "StagePrompter/2.6.3 (https://stageprompter.com.br)"},
                    timeout=5.0
                )
                if resp.status_code == 200:
                    data = resp.json()
                    plain = data.get("plainLyrics")
                    if plain:
                        blocks = clean_verse_lines(plain)
                        if blocks and is_valid_lyrics(blocks):
                            save_to_lyrics_cache(cache, artist, track, blocks, "lrclib", data.get("syncedLyrics"))
                            return {
                                "ok": True,
                                "track": track,
                                "artist": artist,
                                "blocks": blocks,
                                "syncedLyrics": data.get("syncedLyrics"),
                                "source": "lrclib"
                            }
            except Exception:
                pass

    return {
        "ok": False,
        "track": track,
        "artist": artist,
        "blocks": [],
        "error": "Letra não encontrada automaticamente. Você pode digitar ou colar a letra manualmente."
    }

# ----------------- AUDIO PEAKS ENDPOINT ----------------- #
@router.post("/audio-peaks")
async def calculate_audio_peaks(file: UploadFile = File(...)):
    """Computes downsampled normalized audio peaks for the rhythm waveform marker."""
    temp_id = str(uuid.uuid4())
    temp_wav = UPLOAD_DIR / f"{temp_id}.wav"
    try:
        content = await file.read()
        with open(temp_wav, "wb") as f:
            f.write(content)

        import soundfile as sf
        import numpy as np

        data, sr = sf.read(str(temp_wav), dtype="float32")
        if data.ndim > 1:
            data = np.mean(data, axis=1)

        total_samples = len(data)
        num_peaks = 1500
        step = max(1, total_samples // num_peaks)
        peaks = []

        for i in range(0, total_samples, step):
            chunk = data[i:i + step]
            if len(chunk) > 0:
                peaks.append(float(np.max(np.abs(chunk))))

        max_val = max(peaks) if peaks else 1.0
        if max_val > 0:
            peaks = [round(p / max_val, 4) for p in peaks]

        duration = total_samples / sr
        return {
            "ok": True,
            "duration": round(duration, 2),
            "peaks": peaks
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        if temp_wav.exists():
            try:
                os.remove(temp_wav)
            except Exception:
                pass

# ----------------- VIDEO EXPORT ENDPOINT ----------------- #
video_export_tasks: Dict[str, Dict[str, Any]] = {}

@router.post("/export-video")
async def export_video_endpoint(
    audio: Optional[UploadFile] = File(None),
    audio_path: Optional[str] = Form(None),
    markers: str = Form(...),
    fps: int = Form(30)
):
    """
    Renders synchronized MP4 video (1080p) from audio + rhythm markers using bundled FFmpeg.
    Supports either direct file upload or path on disk.
    """
    job_id = str(uuid.uuid4())
    markers_data = json.loads(markers)

    target_audio_file = None
    if audio is not None:
        ext = Path(audio.filename).suffix or ".wav"
        target_audio_file = UPLOAD_DIR / f"vs_{job_id}{ext}"
        audio_bytes = await audio.read()
        with open(target_audio_file, "wb") as f:
            f.write(audio_bytes)
    elif audio_path:
        # Check if local path exists
        candidate = Path(audio_path)
        if candidate.exists():
            target_audio_file = candidate
        elif (UPLOAD_DIR / audio_path).exists():
            target_audio_file = UPLOAD_DIR / audio_path
        elif (BASE_DIR / audio_path).exists():
            target_audio_file = BASE_DIR / audio_path

    output_mp4 = VIDEO_OUT_DIR / f"show_video_{job_id}.mp4"

    video_export_tasks[job_id] = {
        "status": "processing",
        "progress": 5,
        "label": "Iniciando renderização de vídeo...",
        "output_path": str(output_mp4),
        "job_id": job_id
    }

    # Launch background render
    asyncio.create_task(run_video_render_task(job_id, target_audio_file, output_mp4, markers_data, fps))

    return {"ok": True, "job_id": job_id}

@router.get("/export-video-status/{job_id}")
async def get_video_status(job_id: str):
    if job_id in video_export_tasks:
        return video_export_tasks[job_id]
    raise HTTPException(status_code=404, detail="Tarefa de vídeo não encontrada")

@router.get("/download-video/{job_id}")
async def download_video(job_id: str):
    if job_id not in video_export_tasks:
        raise HTTPException(status_code=404, detail="Vídeo não encontrado")
    info = video_export_tasks[job_id]
    out_path = Path(info["output_path"])
    if not out_path.exists():
        raise HTTPException(status_code=404, detail="Arquivo de vídeo ainda não gerado")
    return FileResponse(
        out_path,
        media_type="video/mp4",
        filename="tunemusic_Show_Sincronizado.mp4",
        headers={"Content-Disposition": 'attachment; filename="tunemusic_Show_Sincronizado.mp4"'}
    )

async def run_video_render_task(
    job_id: str,
    audio_path: Optional[Path],
    output_mp4: Path,
    markers_data: dict,
    fps: int
):
    """
    Renders pixel-perfect 1080p MP4 teleprompter video matching StagePrompter's live layout.
    """
    temp_dir = DATA_DIR / f"tmp_render_{job_id}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        video_export_tasks[job_id]["progress"] = 15
        video_export_tasks[job_id]["label"] = "Processando áudio e marcadores..."

        # 1. Determine duration
        total_duration = float(markers_data.get("duration", 0) or 0)
        
        # Ensure we have audio
        actual_audio_path = audio_path
        if not actual_audio_path or not actual_audio_path.exists():
            # Generate silent audio with ffmpeg if no audio was supplied
            if total_duration <= 0:
                total_duration = 60.0
            actual_audio_path = temp_dir / "silent_audio.wav"
            subprocess.run([
                FFMPEG_BIN, "-y",
                "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={total_duration:.2f}",
                "-c:a", "pcm_s16le", str(actual_audio_path)
            ], check=True, capture_output=True)
        else:
            if total_duration <= 0:
                try:
                    import soundfile as sf
                    info = sf.info(str(actual_audio_path))
                    total_duration = info.duration
                except Exception:
                    total_duration = 180.0

        video_export_tasks[job_id]["progress"] = 30
        video_export_tasks[job_id]["label"] = "Gerando telas do teleprompter em 1080p..."

        # 2. Setup typography and colors
        font_title = ImageFont.truetype(FONT_PATH, 38)
        font_artist = ImageFont.truetype(FONT_PATH, 24)
        font_badge = ImageFont.truetype(FONT_PATH, 20)
        font_active = ImageFont.truetype(FONT_PATH, 50)
        font_dimmed = ImageFont.truetype(FONT_PATH, 36)
        font_footer = ImageFont.truetype(FONT_PATH, 22)
        font_welcome_title = ImageFont.truetype(FONT_PATH, 68)
        font_welcome_sub = ImageFont.truetype(FONT_PATH, 28)

        raw_markers = markers_data.get("markers", [])
        songs = markers_data.get("songs", [])
        show_name = markers_data.get("showName") or "tunemusic"

        # Load brand logo for welcome slide if available
        logo_path = BASE_DIR / "static" / "stageprompter" / "LOGO.png"
        brand_logo = None
        if logo_path.exists():
            try:
                raw_logo = Image.open(logo_path).convert("RGBA")
                target_w = 460
                target_h = int(raw_logo.height * (target_w / raw_logo.width))
                brand_logo = raw_logo.resize((target_w, target_h), Image.Resampling.LANCZOS)
            except Exception as e:
                logger.warning(f"Failed to load brand logo: {e}")

        # Build clean marker sequence
        sorted_markers = sorted(raw_markers, key=lambda m: m.get("time", 0.0))
        if not sorted_markers or sorted_markers[0].get("time", 0.0) > 0.05:
            sorted_markers.insert(0, {"time": 0.0, "type": "welcome"})

        # If markers has only welcome and we have songs, generate markers for each verse
        if len(sorted_markers) == 1 and songs:
            total_verses = sum(len(s.get("blocks", [])) for s in songs)
            if total_verses > 0:
                step = total_duration / (total_verses + 1)
                curr_t = step
                for s_i, s_data in enumerate(songs):
                    for v_i in range(len(s_data.get("blocks", []))):
                        sorted_markers.append({
                            "time": curr_t,
                            "type": "lyrics",
                            "song": s_i,
                            "index": v_i
                        })
                        curr_t += step

        concat_entries = []
        total_markers = len(sorted_markers)

        for idx, m in enumerate(sorted_markers):
            t_start = max(0.0, float(m.get("time", 0.0)))
            if idx + 1 < total_markers:
                t_end = float(sorted_markers[idx + 1].get("time", t_start + 5.0))
                dur = max(0.15, t_end - t_start)
            else:
                dur = max(1.0, total_duration - t_start)

            # Create 1920x1080 slide
            img = Image.new("RGB", (1920, 1080), color=(10, 10, 10))
            draw = ImageDraw.Draw(img)

            # Outer Stage Safe Area border (Signature Emerald Green)
            draw.rounded_rectangle([(40, 40), (1880, 1040)], radius=24, outline=(29, 185, 84), width=4)

            m_type = m.get("type", "welcome")

            if m_type == "welcome":
                # Welcome / Show Title screen with tunemusic official logo
                if brand_logo:
                    lx = (1920 - brand_logo.width) // 2
                    ly = 240
                    img.paste(brand_logo, (lx, ly), brand_logo)
                    draw.text((960, ly + brand_logo.height + 40), "TELEPROMPTER DE SHOW", font=font_badge, fill=(0, 240, 255), anchor="mm")
                    draw.text((960, ly + brand_logo.height + 105), show_name.upper(), font=font_welcome_title, fill=(255, 255, 255), anchor="mm")
                    draw.text((960, ly + brand_logo.height + 165), "SHOW SINCRONIZADO AO VIVO", font=font_welcome_sub, fill=(180, 180, 180), anchor="mm")
                else:
                    draw.text((960, 420), "tunemusic", font=font_welcome_title, fill=(0, 240, 255), anchor="mm")
                    draw.text((960, 480), "TELEPROMPTER DE SHOW", font=font_badge, fill=(255, 255, 255), anchor="mm")
                    draw.text((960, 560), show_name.upper(), font=font_welcome_title, fill=(255, 255, 255), anchor="mm")
                    draw.text((960, 630), "SHOW SINCRONIZADO AO VIVO", font=font_welcome_sub, fill=(180, 180, 180), anchor="mm")

                if songs:
                    first_song = songs[0]
                    draw.text((960, 920), f"A seguir: {first_song.get('track', '')} - {first_song.get('artist', '')}", font=font_footer, fill=(0, 240, 255), anchor="mm")

            else:
                # Teleprompter Lyrics Screen
                s_idx = int(m.get("song", 0))
                v_idx = int(m.get("index", 0))
                
                curr_song = songs[s_idx] if s_idx < len(songs) else {}
                track_title = curr_song.get("track", "")
                artist_name = curr_song.get("artist", "")
                lines = curr_song.get("blocks", [])

                # Header Top Left
                if track_title:
                    draw.text((80, 70), f"▶ {track_title.upper()}", font=font_title, fill=(255, 255, 255))
                if artist_name:
                    draw.text((80, 120), artist_name, font=font_artist, fill=(29, 185, 84))

                # Header Top Right: Live badge
                draw.rounded_rectangle([(1720, 70), (1840, 110)], radius=8, fill=(29, 185, 84))
                draw.text((1780, 90), "AO VIVO", font=font_badge, fill=(0, 0, 0), anchor="mm")

                # Center Teleprompter Verses
                settings = markers_data.get("settings", {}) or {}
                raw_vh = settings.get("versesHighlight", 2)
                try:
                    num_active = int(raw_vh)
                except Exception:
                    num_active = 2

                if num_active <= 1:
                    # Single Verse Mode
                    if v_idx > 0 and v_idx - 1 < len(lines):
                        draw.text((960, 430), lines[v_idx - 1], font=font_dimmed, fill=(80, 80, 80), anchor="mm")

                    if v_idx < len(lines):
                        active_text = lines[v_idx]
                        draw.rounded_rectangle([(220, 500), (1700, 580)], radius=16, fill=(18, 18, 18), outline=(29, 185, 84), width=2)
                        draw.text((960, 540), f"▶  {active_text}", font=font_active, fill=(255, 255, 255), anchor="mm")

                    if v_idx + 1 < len(lines):
                        draw.text((960, 650), lines[v_idx + 1], font=font_dimmed, fill=(110, 110, 110), anchor="mm")
                    if v_idx + 2 < len(lines):
                        draw.text((960, 730), lines[v_idx + 2], font=font_dimmed, fill=(65, 65, 65), anchor="mm")
                else:
                    # 2 or More Verses Mode
                    if v_idx > 0 and v_idx - 1 < len(lines):
                        draw.text((960, 390), lines[v_idx - 1], font=font_dimmed, fill=(80, 80, 80), anchor="mm")

                    has_v1 = v_idx < len(lines)
                    has_v2 = (v_idx + 1) < len(lines)

                    if has_v1 and has_v2:
                        draw.rounded_rectangle([(220, 460), (1700, 630)], radius=16, fill=(18, 18, 18), outline=(29, 185, 84), width=2)
                        draw.text((960, 505), f"▶  {lines[v_idx]}", font=font_active, fill=(255, 255, 255), anchor="mm")
                        draw.text((960, 575), f"    {lines[v_idx + 1]}", font=font_active, fill=(255, 255, 255), anchor="mm")
                    elif has_v1:
                        draw.rounded_rectangle([(220, 490), (1700, 590)], radius=16, fill=(18, 18, 18), outline=(29, 185, 84), width=2)
                        draw.text((960, 540), f"▶  {lines[v_idx]}", font=font_active, fill=(255, 255, 255), anchor="mm")

                    if v_idx + 2 < len(lines):
                        draw.text((960, 700), lines[v_idx + 2], font=font_dimmed, fill=(110, 110, 110), anchor="mm")
                    if v_idx + 3 < len(lines):
                        draw.text((960, 780), lines[v_idx + 3], font=font_dimmed, fill=(65, 65, 65), anchor="mm")

                # Footer Bottom
                next_song_text = ""
                if s_idx + 1 < len(songs):
                    ns = songs[s_idx + 1]
                    next_song_text = f"Próxima: {ns.get('track', '')} - {ns.get('artist', '')}"
                
                if next_song_text:
                    draw.text((80, 990), next_song_text, font=font_footer, fill=(160, 160, 160))
                else:
                    draw.text((80, 990), "tunemusic • Teleprompter de Show", font=font_footer, fill=(100, 100, 100))

                draw.text((1840, 990), f"Música {s_idx + 1} de {len(songs)}", font=font_footer, fill=(140, 140, 140), anchor="ra")

            slide_file = temp_dir / f"slide_{idx:04d}.png"
            img.save(slide_file, "PNG")
            concat_entries.append((slide_file, dur))

        # 3. Write concat list.txt
        list_file = temp_dir / "list.txt"
        with open(list_file, "w", encoding="utf-8") as f:
            for sf, d in concat_entries:
                p_str = str(sf).replace("\\", "/")
                f.write(f"file '{p_str}'\nduration {d:.3f}\n")
            if concat_entries:
                last_p = str(concat_entries[-1][0]).replace("\\", "/")
                f.write(f"file '{last_p}'\n")

        video_export_tasks[job_id]["progress"] = 65
        video_export_tasks[job_id]["label"] = "Codificando vídeo MP4 1080p com FFmpeg..."

        # 4. Run FFmpeg command
        cmd = [
            FFMPEG_BIN, "-y",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-i", str(actual_audio_path),
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
            "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(fps),
            "-c:a", "aac", "-b:a", "192k",
            "-t", f"{total_duration:.2f}",
            "-movflags", "+faststart",
            str(output_mp4)
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            err_msg = stderr.decode(errors="ignore")
            print("FFmpeg error:", err_msg)
            video_export_tasks[job_id]["status"] = "error"
            video_export_tasks[job_id]["error"] = f"Erro FFmpeg: {err_msg[:200]}"
            return

        video_export_tasks[job_id]["status"] = "completed"
        video_export_tasks[job_id]["progress"] = 100
        video_export_tasks[job_id]["label"] = "Vídeo MP4 gerado com sucesso!"

    except Exception as e:
        print("Video render exception:", e)
        video_export_tasks[job_id]["status"] = "error"
        video_export_tasks[job_id]["error"] = str(e)
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)

# ----------------- AI AUDIO TRANSCRIPTION ENDPOINT ----------------- #
@router.post("/transcribe")
async def transcribe_audio_endpoint(file: UploadFile = File(...)):
    """
    Transcribes audio into lyrics using authentic AI transcription (Gemini multimodal audio & Whisper fallback).
    """
    import base64
    temp_id = str(uuid.uuid4())
    audio_path = UPLOAD_DIR / f"tr_{temp_id}_{file.filename}"
    compressed_mp3 = UPLOAD_DIR / f"tr_comp_{temp_id}.mp3"
    
    try:
        content = await file.read()
        with open(audio_path, "wb") as f:
            f.write(content)

        # 1. Compress audio to 16kHz mono 48kbps MP3 with ffmpeg (matches original StagePrompter pipeline)
        cmd = [
            FFMPEG_BIN, "-y", "-i", str(audio_path),
            "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k",
            str(compressed_mp3)
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        target_audio = compressed_mp3 if compressed_mp3.exists() and compressed_mp3.stat().st_size > 0 else audio_path

        # 2. Primary Provider: Gemini Multimodal Audio (Env Key or Local Server Configuration)
        GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
        prompt = (
            "Transcreva a letra desta música em português brasileiro, do começo ao fim do áudio. "
            "Escreva um verso por linha e separe as estrofes com uma linha em branco. "
            "Transcreva também falas e vinhetas que existirem na gravação. "
            "Seja fiel ao que se ouve: não invente palavras, não resuma e não pule trechos. "
            "Responda apenas com a letra, sem título, sem comentários e sem marcações como [refrão]."
        )

        with open(target_audio, "rb") as f_aud:
            b64_audio = base64.b64encode(f_aud.read()).decode("utf-8")

        models_to_try = ["gemini-flash-latest", "gemini-flash-lite-latest"]
        async with httpx.AsyncClient(timeout=90.0) as client:
            for mod in models_to_try:
                for attempt in range(3):
                    try:
                        url = f"https://generativelanguage.googleapis.com/v1beta/models/{mod}:generateContent?key={GEMINI_KEY}"
                        body = {
                            "contents": [
                                {
                                    "parts": [
                                        {
                                            "inline_data": {
                                                "mime_type": "audio/mp3",
                                                "data": b64_audio
                                            }
                                        },
                                        {
                                            "text": prompt
                                        }
                                    ]
                                }
                            ],
                            "generationConfig": {
                                "temperature": 0.2
                            }
                        }
                        resp = await client.post(url, json=body)
                        if resp.status_code == 200:
                            res_data = resp.json()
                            candidates = res_data.get("candidates", [])
                            if candidates:
                                parts = candidates[0].get("content", {}).get("parts", [])
                                text = "".join(p.get("text", "") for p in parts)
                                # Clean text artifacts
                                text = re.sub(r'[♪♫*`]', '', text).strip()
                                lines = [
                                    l.strip() for l in text.splitlines()
                                    if l.strip() and not l.strip().lower().startswith('[música')
                                    and not l.strip().lower().startswith('[musica')
                                    and not l.strip().lower().startswith('(música')
                                    and not l.strip().lower().startswith('(musica')
                                ]
                                if len(lines) >= 2:
                                    return {"ok": True, "rawText": text, "model": mod}
                                else:
                                    print(f"Gemini {mod} output had no valid vocal lyrics lines: {text[:100]}")
                        elif resp.status_code in (429, 503):
                            print(f"Gemini {mod} rate limit / busy ({resp.status_code}), attempt {attempt+1}/3. Waiting...")
                            await asyncio.sleep(3.5 * (attempt + 1))
                            continue
                        else:
                            print(f"Gemini {mod} returned status {resp.status_code}: {resp.text[:200]}")
                            break
                    except Exception as e_gemini:
                        print(f"Gemini {mod} transcription error: {e_gemini}")
                        break

        # 3. Secondary Fallback: Groq Whisper API (if configured)
        GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
        if GROQ_API_KEY:
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    with open(target_audio, "rb") as f_audio:
                        resp = await client.post(
                            "https://api.groq.com/openai/v1/audio/transcriptions",
                            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                            files={"file": ("audio.mp3", f_audio, "audio/mp3")},
                            data={
                                "model": "whisper-large-v3",
                                "language": "pt",
                                "response_format": "verbose_json",
                                "prompt": "Letra de música em português do Brasil com estrofes e versos bem divididos."
                            }
                        )
                    if resp.status_code == 200:
                        data = resp.json()
                        segments = data.get("segments", [])
                        lines = []
                        last_end = None
                        for seg in segments:
                            txt = seg.get("text", "").strip()
                            if not txt:
                                continue
                            start = seg.get("start", 0)
                            if last_end is not None and (start - last_end) > 0.6:
                                lines.append("")
                            lines.append(txt)
                            last_end = seg.get("end", start)
                        formatted = "\n".join(lines).strip()
                        if formatted:
                            return {"ok": True, "rawText": formatted}
            except Exception as e_groq:
                print("Groq transcription error:", e_groq)

        return {
            "ok": False,
            "error": "Não foi possível transcrever o áudio automaticamente. Verifique se o vocal está nítido."
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        for p in [audio_path, compressed_mp3]:
            if p.exists():
                try:
                    os.remove(p)
                except Exception:
                    pass
