#!/usr/bin/env python3
"""
===============================================================================
  tunemusic Pro • Gerador de Licenças Administrativo
  Software Licenser & Anti-Piracy Tool
===============================================================================
Use este script exclusivo da administração para emitir chaves de ativação
criptográficas vinculadas ao hardware de cada cliente (1 PC).

Exemplos de uso:
  python gerar_licenca.py
  python gerar_licenca.py --client "João Silva" --hwid "TUNE-XXXX-XXXX-XXXX-XXXX"
  python gerar_licenca.py --verify "TM-..."
  python gerar_licenca.py --list
"""

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure parent directory is on sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from license_engine import (
    generate_license_key,
    verify_license_key,
    get_system_hwid,
    DATA_DIR
)

LICENCAS_JSON = DATA_DIR / "licencas_emitidas.json"
LICENCAS_TXT = DATA_DIR / "licencas_emitidas.txt"


def format_delivery_card(client: str, hwid: str, plan: str, email: str, issued: str, expires_display: str, key: str) -> str:
    card = f"""
===============================================================================
  🎵 tunemusic Pro • DADOS DE ATIVAÇÃO DA LICENÇA
===============================================================================
👤 Cliente:          {client}
📧 Email:            {email or 'Não informado'}
🖥️ ID do Computador: {hwid}
⭐ Plano:            {plan}
📅 Data de Emissão:  {issued}
🔒 Validade:         {expires_display}

🔑 CHAVE DE ATIVAÇÃO (Copie a linha inteira):
{key}

📋 INSTRUÇÕES PARA O CLIENTE:
1. Abra o tunemusic Pro no computador onde o aplicativo foi instalado.
2. Na janela de Ativação, cole a Chave de Ativação acima no campo indicado.
3. Clique no botão "Ativar tunemusic Pro".
4. O sistema será liberado imediatamente com acesso total e vitalício!
===============================================================================
"""
    return card.strip()


def save_issued_license(record: dict):
    """Saves issued license to JSON database and plain text log."""
    # 1. JSON
    records = []
    if LICENCAS_JSON.exists():
        try:
            records = json.loads(LICENCAS_JSON.read_text(encoding="utf-8"))
        except Exception:
            records = []
    records.append(record)
    LICENCAS_JSON.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")

    # 2. Text Log
    with open(LICENCAS_TXT, "a", encoding="utf-8") as f:
        f.write(f"\n[{record['issued']}] CLIENTE: {record['client']} | HWID: {record['hwid']} | PLANO: {record['plan']} | EXP: {record['expires'] or 'Vitalícia'}\n")
        f.write(f"CHAVE: {record['key']}\n")
        f.write("-" * 80 + "\n")


def cmd_list():
    """Lists all generated licenses."""
    print("\n" + "=" * 70)
    print("  📋 tunemusic Pro • HISTÓRICO DE LICENÇAS EMITIDAS")
    print("=" * 70)
    if not LICENCAS_JSON.exists():
        print("Nenhuma licença emitida até o momento.")
        return

    try:
        records = json.loads(LICENCAS_JSON.read_text(encoding="utf-8"))
        if not records:
            print("Nenhuma licença encontrada.")
            return

        for idx, r in enumerate(records, 1):
            exp = r.get("expires") or "Vitalícia"
            print(f"#{idx} | {r.get('client')} ({r.get('email', '')})")
            print(f"    HWID:    {r.get('hwid')}")
            print(f"    Plano:   {r.get('plan')} | Validade: {exp}")
            print(f"    Emissão: {r.get('issued')}")
            print(f"    Chave:   {r.get('key')[:40]}...")
            print("-" * 70)
        print(f"Total: {len(records)} licença(s) registrada(s).\n")
    except Exception as e:
        print(f"Erro ao ler histórico: {e}")


def cmd_verify(key_str: str):
    """Verifies and inspects a license key."""
    print("\n" + "=" * 70)
    print("  🔍 tunemusic Pro • AUDITORIA DE CHAVE DE LICENÇA")
    print("=" * 70)
    current_hwid = get_system_hwid()
    valid, msg, payload = verify_license_key(key_str, current_hwid)
    
    if payload:
        print("STATUS DA ASSINATURA:  [OK] Criptografia Válida e Autêntica")
        print(f"Cliente:               {payload.get('client')}")
        print(f"Email:                 {payload.get('email')}")
        print(f"HWID Vinculado:        {payload.get('hwid')}")
        print(f"Plano:                 {payload.get('plan')}")
        print(f"Data de Emissão:       {payload.get('issued')}")
        print(f"Expiração:             {payload.get('expires') or 'Vitalícia'}")
        print("-" * 70)
        print(f"HWID Deste Computador: {current_hwid}")
        if valid:
            print("VINCULAÇÃO:            [OK] Compatível com esta máquina atual!")
        else:
            print(f"VINCULAÇÃO:            [BLOQUEADO] {msg}")
    else:
        print(f"[ERRO] Chave inválida ou corrompida: {msg}")
    print("=" * 70 + "\n")


def cmd_generate(client: str, hwid: str, plan: str, email: str = "", days: int = 0):
    issued_dt = datetime.now()
    issued_str = issued_dt.strftime("%Y-%m-%d %H:%M:%S")
    expires_str = None
    expires_display = "Vitalícia (Sem expiração)"

    if days > 0:
        exp_dt = issued_dt + timedelta(days=days)
        expires_str = exp_dt.strftime("%Y-%m-%d")
        expires_display = f"{days} dias (Até {expires_str})"

    key = generate_license_key(
        client_name=client,
        target_hwid=hwid,
        plan_name=plan,
        client_email=email,
        expires_at=expires_str
    )

    card = format_delivery_card(
        client=client,
        hwid=hwid,
        plan=plan,
        email=email,
        issued=issued_str,
        expires_display=expires_display,
        key=key
    )

    record = {
        "client": client,
        "email": email,
        "hwid": hwid.strip().upper(),
        "plan": plan,
        "issued": issued_str,
        "expires": expires_str,
        "key": key
    }
    save_issued_license(record)

    print("\n" + card + "\n")
    print(f"✔️ Licença gravada em: {LICENCAS_JSON}")
    print(f"✔️ Registro de auditoria em: {LICENCAS_TXT}\n")


def interactive_mode():
    print("""
╔══════════════════════════════════════════════════════════════════════════╗
║               🎵 tunemusic Pro • GERADOR DE LICENÇAS                    ║
║         Sistema Criptográfico com Bloqueio de Hardware (1 PC)            ║
╚══════════════════════════════════════════════════════════════════════════╝
""")
    this_hwid = get_system_hwid()
    print(f"ℹ️  [Dica] O HWID deste computador atual é: {this_hwid}\n")

    client = input("1. Nome do Cliente ou Banda: ").strip()
    while not client:
        client = input("   [!] Por favor, digite o nome do cliente: ").strip()

    email = input("2. Email do Cliente (opcional): ").strip()

    hwid = input(f"3. ID do Computador (HWID informado pelo cliente) [Enter para usar deste PC]: ").strip()
    if not hwid:
        hwid = this_hwid

    print("\n4. Selecione o Plano:")
    print("   [1] tunemusic Pro Vitalício (Recomendado)")
    print("   [2] Licença Anual (365 dias)")
    print("   [3] Licença Mensal (30 dias)")
    print("   [4] Personalizado")
    plan_choice = input("   Opção (padrão 1): ").strip() or "1"

    plan = "tunemusic Pro Vitalício"
    days = 0
    if plan_choice == "2":
        plan = "tunemusic Pro Anual"
        days = 365
    elif plan_choice == "3":
        plan = "tunemusic Pro Mensal"
        days = 30
    elif plan_choice == "4":
        plan = input("   Nome do Plano Personalizado: ").strip() or "tunemusic Pro Especial"
        try:
            days = int(input("   Dias de validade (0 para vitalício): ").strip() or "0")
        except ValueError:
            days = 0

    cmd_generate(client=client, hwid=hwid, plan=plan, email=email, days=days)


def main():
    parser = argparse.ArgumentParser(description="tunemusic Pro • Gerador de Licenças Administrativo")
    parser.add_argument("--client", "-c", help="Nome do cliente ou banda")
    parser.add_argument("--hwid", "-w", help="ID do computador do cliente (TUNE-XXXX-XXXX-XXXX-XXXX)")
    parser.add_argument("--plan", "-p", default="tunemusic Pro Vitalício", help="Nome do plano")
    parser.add_argument("--email", "-e", default="", help="Email do cliente")
    parser.add_argument("--days", "-d", type=int, default=0, help="Validade em dias (0 para vitalícia)")
    parser.add_argument("--verify", "-v", help="Auditar e verificar chave de licença existente")
    parser.add_argument("--list", "-l", action="store_true", help="Listar todas as licenças emitidas")

    args = parser.parse_args()

    if args.list:
        cmd_list()
    elif args.verify:
        cmd_verify(args.verify)
    elif args.client and args.hwid:
        cmd_generate(client=args.client, hwid=args.hwid, plan=args.plan, email=args.email, days=args.days)
    else:
        interactive_mode()


if __name__ == "__main__":
    main()
