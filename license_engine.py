"""
tunemusic • Cryptographic Hardware-Locked License Engine
Protects software against unauthorized sharing, piracy, and reverse engineering.
Binds each activation strictly to the target PC's physical hardware.
"""

import os
import sys
import json
import base64
import hmac
import hashlib

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
try:
    import winreg
except ImportError:
    winreg = None
import platform
import subprocess
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from datetime import datetime

# Master HMAC Secret Key (Cryptographic Signature Seed for tunemusic Pro)
# Keep this secure. This key signs and validates licenses.
MASTER_SIGNING_SECRET = b"tunemusic-live-teleprompter-secure-master-key-2026-obsidian-cipher"

# License file location
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LICENSE_FILE = DATA_DIR / "license.lic"


def get_machine_guid() -> str:
    """Retrieves Windows Cryptography Machine GUID from Registry."""
    if not winreg:
        return ""
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography")
        guid, _ = winreg.QueryValueEx(key, "MachineGuid")
        winreg.CloseKey(key)
        return str(guid).strip()
    except Exception:
        return ""


def get_powershell_hw_metric(cmd: str) -> str:
    """Executes a fast PowerShell CimInstance command to retrieve physical hardware ID on Windows."""
    if sys.platform != "win32":
        return ""
    try:
        res = subprocess.check_output(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3
        )
        return res.strip()
    except Exception:
        return ""


def get_linux_hardware_id() -> str:
    """Retrieves hardware identifiers on Linux / Coolify / Docker containers."""
    parts = []
    
    # 1. /etc/machine-id or /var/lib/dbus/machine-id
    for mid_path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            p = Path(mid_path)
            if p.exists():
                parts.append(p.read_text().strip())
                break
        except Exception:
            pass

    # 2. DMI Product UUID
    try:
        uuid_path = Path("/sys/class/dmi/id/product_uuid")
        if uuid_path.exists():
            parts.append(uuid_path.read_text().strip())
    except Exception:
        pass

    # 3. CPU Info model or serial
    try:
        cpu_path = Path("/proc/cpuinfo")
        if cpu_path.exists():
            cpu_content = cpu_path.read_text()
            for line in cpu_content.splitlines():
                if "model name" in line or "Serial" in line:
                    parts.append(line.split(":", 1)[1].strip())
                    break
    except Exception:
        pass

    return "::".join(parts)


def get_system_hwid() -> str:
    """
    Computes a permanent, non-spoofable Hardware Fingerprint (HWID)
    combining Motherboard UUID, Primary Disk Serial, CPU ID, and OS Machine GUID.
    Works seamlessly on Windows, Linux (Coolify/Docker), and macOS.
    """
    if sys.platform == "win32":
        # Windows: Motherboard UUID + Disk Serial + CPU ID + Machine GUID
        mb_uuid = get_powershell_hw_metric("(Get-CimInstance Win32_ComputerSystemProduct).UUID") or "MB-DEFAULT"
        disk_serial = get_powershell_hw_metric("(Get-CimInstance Win32_DiskDrive | Select-Object -First 1).SerialNumber") or "DISK-DEFAULT"
        cpu_id = get_powershell_hw_metric("(Get-CimInstance Win32_Processor | Select-Object -First 1).ProcessorId") or "CPU-DEFAULT"
        machine_guid = get_machine_guid() or "WIN-GUID-DEFAULT"
        raw_fingerprint = f"{mb_uuid}::{disk_serial}::{cpu_id}::{machine_guid}"
    else:
        # Linux / Docker / Coolify / macOS
        linux_hw = get_linux_hardware_id()
        mac_node = hex(uuid.getnode())
        raw_fingerprint = f"{linux_hw}::{platform.node()}::{mac_node}"

    # Fallback if empty
    if not raw_fingerprint or len(raw_fingerprint.replace(":", "")) < 6:
        raw_fingerprint = f"SYS::{platform.node()}::{hex(uuid.getnode())}"

    # SHA-256 Digest
    digest = hashlib.sha256(raw_fingerprint.encode("utf-8")).hexdigest().upper()
    
    # Format as friendly user code: TUNE-XXXX-XXXX-XXXX-XXXX (16 chars)
    formatted = f"TUNE-{digest[0:4]}-{digest[4:8]}-{digest[8:12]}-{digest[12:16]}"
    return formatted


def generate_license_key(
    client_name: str,
    target_hwid: str,
    plan_name: str = "Pro Vitalício",
    client_email: str = "",
    expires_at: Optional[str] = None
) -> str:
    """
    Generates a cryptographically signed license key bound to a specific PC HWID.
    Format: TM-<B64_PAYLOAD>.<HEX_SIGNATURE>
    """
    clean_hwid = target_hwid.strip().upper()
    payload = {
        "client": client_name.strip(),
        "email": client_email.strip(),
        "hwid": clean_hwid,
        "plan": plan_name.strip(),
        "issued": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "expires": expires_at  # None or YYYY-MM-DD
    }
    
    payload_json = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("utf-8").rstrip("=")
    
    # Cryptographic HMAC-SHA256 signature
    signature = hmac.new(MASTER_SIGNING_SECRET, payload_json.encode("utf-8"), hashlib.sha256).hexdigest().upper()
    
    # Key Format
    full_key = f"TM-{payload_b64}.{signature}"
    return full_key


def verify_license_key(key_str: str, current_hwid: Optional[str] = None) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Verifies the cryptographic integrity of a license key and ensures
    it matches the current machine's physical hardware.
    
    Returns (is_valid, message, payload_dict)
    """
    if not key_str or not isinstance(key_str, str):
        return False, "Chave de licença vazia ou inválida.", None
    
    clean_key = key_str.strip()
    if not clean_key.startswith("TM-") or "." not in clean_key:
        return False, "Formato de chave inválido. A chave deve começar com TM-.", None
    
    try:
        body = clean_key[3:]
        payload_b64, signature = body.split(".", 1)
        
        # Pad Base64 if needed
        padding = (4 - len(payload_b64) % 4) % 4
        padded_b64 = payload_b64 + ("=" * padding)
        
        payload_json = base64.urlsafe_b64decode(padded_b64.encode("utf-8")).decode("utf-8")
        payload = json.loads(payload_json)
        
        # 1. Verify cryptographic HMAC signature
        expected_sig = hmac.new(MASTER_SIGNING_SECRET, payload_json.encode("utf-8"), hashlib.sha256).hexdigest().upper()
        if not hmac.compare_digest(signature.upper(), expected_sig):
            return False, "Assinatura digital inválida! Chave corrompida ou falsificada.", None
        
        # 2. Verify Hardware ID (HWID Lock)
        target_hwid = payload.get("hwid", "").strip().upper()
        if current_hwid is None:
            current_hwid = get_system_hwid()
        
        if target_hwid not in ("ALL", "GLOBAL", "UNIVERSAL") and target_hwid != current_hwid.strip().upper():
            return (
                False,
                f"Esta licença foi gerada para outro computador (ID: {target_hwid}). O ID deste PC é {current_hwid}.",
                payload
            )
        
        # 3. Verify Expiration if applicable
        exp_date_str = payload.get("expires")
        if exp_date_str:
            try:
                exp_date = datetime.strptime(exp_date_str, "%Y-%m-%d")
                if datetime.now() > exp_date:
                    return False, f"Esta licença expirou em {exp_date_str}.", payload
            except Exception:
                pass
        
        return True, "Licença autêntica e válida para este computador!", payload

    except Exception as e:
        return False, f"Erro ao decodificar a chave: {str(e)}", None


def load_installed_license() -> Tuple[bool, Dict[str, Any]]:
    """
    Reads the stored license file from data/license.lic and validates it.
    """
    current_hwid = get_system_hwid()
    
    if not LICENSE_FILE.exists():
        return False, {
            "licensed": False,
            "hwid": current_hwid,
            "message": "Nenhuma licença instalada. Ative seu tunemusic Pro para liberar o sistema."
        }
    
    try:
        content = LICENSE_FILE.read_text(encoding="utf-8").strip()
        data = json.loads(content)
        key = data.get("key", "")
        
        is_valid, msg, payload = verify_license_key(key, current_hwid)
        if is_valid and payload:
            return True, {
                "licensed": True,
                "hwid": current_hwid,
                "client": payload.get("client", "Músico Pro"),
                "email": payload.get("email", ""),
                "plan": payload.get("plan", "tunemusic Pro"),
                "issued": payload.get("issued", ""),
                "expires": payload.get("expires") or "Vitalícia",
                "message": "Licença ativa e autenticada neste computador."
            }
        else:
            return False, {
                "licensed": False,
                "hwid": current_hwid,
                "message": msg or "Licença inválida para este computador."
            }
    except Exception as e:
        return False, {
            "licensed": False,
            "hwid": current_hwid,
            "message": f"Erro ao ler arquivo de licença: {str(e)}"
        }


def save_license(key_str: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Validates and permanently installs a license key on this machine.
    """
    current_hwid = get_system_hwid()
    is_valid, msg, payload = verify_license_key(key_str, current_hwid)
    
    if not is_valid or not payload:
        return False, msg, None
    
    record = {
        "key": key_str.strip(),
        "hwid": current_hwid,
        "activated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "payload": payload
    }
    
    try:
        LICENSE_FILE.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        return True, "Licença ativada com sucesso! Bem-vindo ao tunemusic Pro.", payload
    except Exception as e:
        return False, f"Falha ao salvar licença no disco: {str(e)}", None


def remove_license() -> bool:
    """Removes the license file (for testing / reset purposes)."""
    try:
        if LICENSE_FILE.exists():
            LICENSE_FILE.unlink()
        return True
    except Exception:
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("  tunemusic • Teste do Motor de Licença por Hardware")
    print("=" * 60)
    hwid = get_system_hwid()
    print("HWID deste Computador:", hwid)
    
    # Generate test license for this machine
    test_key = generate_license_key("Produtor Musical", hwid, "Pro Vitalício", "produtor@tunemusic.app")
    print("\nChave Gerada para este PC:")
    print(test_key)
    
    # Verify test key
    valid, msg, payload = verify_license_key(test_key, hwid)
    print("\nValidação no mesmo PC:", valid, f"({msg})")
    
    # Verify test key on different HWID
    fake_hwid = "TUNE-0000-1111-2222-3333"
    valid_fake, msg_fake, _ = verify_license_key(test_key, fake_hwid)
    print("Validação em outro PC:", valid_fake, f"({msg_fake})")
