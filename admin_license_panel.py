"""
tunemusic Pro • Painel de Gestão e Emissão de Licenças
Permite ao administrador gerar, consultar e enviar chaves criptográficas
vinculadas ao hardware dos clientes pelo WhatsApp ou e-mail.
"""

import os
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Depends, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel

from license_engine import (
    generate_license_key,
    verify_license_key,
    get_system_hwid,
    DATA_DIR
)

router = APIRouter()

ADMIN_SECRET = os.getenv("TUNEMUSIC_ADMIN_SECRET", "tunemusic2026")
LICENCAS_JSON = DATA_DIR / "licencas_emitidas.json"
LICENCAS_TXT = DATA_DIR / "licencas_emitidas.txt"


def format_whatsapp_delivery(client: str, hwid: str, plan: str, email: str, issued: str, expires_display: str, key: str) -> str:
    """Format formatted text ready to copy-paste into WhatsApp."""
    return f"""🎵 *tunemusic Pro • Licença Oficial de Acesso*
━━━━━━━━━━━━━━━━━━━━━━━━━━
Olá *{client}*, sua licença do *tunemusic Pro* foi emitida e liberada com sucesso!

👤 *Cliente:* {client}
🖥️ *ID do Computador:* `{hwid}`
⭐ *Plano:* {plan}
🔒 *Validade:* {expires_display}
📅 *Emissão:* {issued}

━━━━━━━━━━━━━━━━━━━━━━━━━━
🔑 *SUA CHAVE DE ATIVAÇÃO:*
(Copie a linha inteira abaixo)

`{key}`

━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 *PASSO A PASSO PARA ATIVAR:*
1. Abra o aplicativo *tunemusic Pro* no seu computador.
2. Na janela de Ativação, cole a Chave acima no campo indicado.
3. Clique no botão *🚀 Ativar tunemusic Pro*.
4. Pronto! O sistema será desbloqueado na hora com acesso total e a coroa dourada 👑 no topo!

Em caso de dúvidas, estamos à disposição. Bom show! 🎤🎸"""


def load_all_records() -> List[Dict[str, Any]]:
    if not LICENCAS_JSON.exists():
        return []
    try:
        data = json.loads(LICENCAS_JSON.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def save_record(rec: Dict[str, Any]):
    records = load_all_records()
    records.append(rec)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LICENCAS_JSON.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    
    with open(LICENCAS_TXT, "a", encoding="utf-8") as f:
        f.write(f"\n[{rec['issued']}] CLIENTE: {rec['client']} | HWID: {rec['hwid']} | PLANO: {rec['plan']} | EXP: {rec['expires'] or 'Vitalícia'}\n")
        f.write(f"CHAVE: {rec['key']}\n")
        f.write("-" * 80 + "\n")


class GenerateRequest(BaseModel):
    client: str
    hwid: str
    plan_type: str = "vitalicio"  # vitalicio, anual, mensal, demo
    email: Optional[str] = ""
    whatsapp: Optional[str] = ""
    admin_secret: str


class LoginRequest(BaseModel):
    admin_secret: str


@router.post("/api/admin/login")
async def admin_login(data: LoginRequest):
    if data.admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Senha administrativa incorreta.")
    return {"ok": True, "message": "Autenticado com sucesso."}


@router.get("/api/admin/licenses")
async def list_licenses(secret: Optional[str] = None, authorization: Optional[str] = Header(None)):
    token = secret or (authorization.replace("Bearer ", "") if authorization else "")
    if token != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Não autorizado.")
    records = load_all_records()
    return {"ok": True, "licenses": records, "total": len(records)}


@router.post("/api/admin/licenses/create")
async def create_license(data: GenerateRequest):
    if data.admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Não autorizado.")

    client = data.client.strip()
    hwid = data.hwid.strip().upper()

    if not client:
        raise HTTPException(status_code=400, detail="Nome do cliente é obrigatório.")
    if not hwid.startswith("TUNE-") or len(hwid) < 15:
        raise HTTPException(status_code=400, detail="ID da máquina inválido. O ID deve começar com TUNE-XXXX-XXXX...")

    # Calculate expiration
    expires_str = None
    plan_display = "tunemusic Pro Vitalício"
    expires_display = "Vitalícia (Sem expiração)"

    if data.plan_type == "anual":
        exp_date = datetime.now() + timedelta(days=365)
        expires_str = exp_date.strftime("%Y-%m-%d")
        plan_display = "tunemusic Pro Anual (1 Ano)"
        expires_display = f"{expires_str} (365 Dias)"
    elif data.plan_type == "mensal":
        exp_date = datetime.now() + timedelta(days=30)
        expires_str = exp_date.strftime("%Y-%m-%d")
        plan_display = "tunemusic Pro Mensal (30 Dias)"
        expires_display = f"{expires_str} (30 Dias)"
    elif data.plan_type == "demo":
        exp_date = datetime.now() + timedelta(days=7)
        expires_str = exp_date.strftime("%Y-%m-%d")
        plan_display = "tunemusic Pro Demonstração (7 Dias)"
        expires_display = f"{expires_str} (7 Dias)"

    issued_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    key = generate_license_key(
        client_name=client,
        target_hwid=hwid,
        plan_name=plan_display,
        client_email=data.email or "",
        expires_at=expires_str
    )

    whatsapp_msg = format_whatsapp_delivery(
        client=client,
        hwid=hwid,
        plan=plan_display,
        email=data.email or "",
        issued=issued_now,
        expires_display=expires_display,
        key=key
    )

    rec = {
        "client": client,
        "email": data.email or "",
        "whatsapp": data.whatsapp or "",
        "hwid": hwid,
        "plan": plan_display,
        "plan_type": data.plan_type,
        "issued": issued_now,
        "expires": expires_str,
        "expires_display": expires_display,
        "key": key
    }
    save_record(rec)

    return {
        "ok": True,
        "license": rec,
        "whatsapp_message": whatsapp_msg
    }


@router.get("/admin", response_class=HTMLResponse)
@router.get("/admin/licencas", response_class=HTMLResponse)
async def admin_dashboard_page():
    html_content = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>tunemusic Pro • Painel de Gestão de Licenças</title>
  <link rel="icon" type="image/png" href="/LOGO.png">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #07090e;
      --card-bg: #0d121d;
      --card-border: rgba(0, 240, 255, 0.15);
      --card-hover: rgba(0, 240, 255, 0.25);
      --cyan: #00f0ff;
      --cyan-glow: rgba(0, 240, 255, 0.35);
      --gold: #f59e0b;
      --green: #10b981;
      --text: #f1f5f9;
      --muted: #94a3b8;
      --danger: #ef4444;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--bg);
      color: var(--text);
      font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }

    /* HEADER */
    header {
      background: rgba(13, 18, 29, 0.95);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--card-border);
      padding: 16px 28px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      position: sticky;
      top: 0;
      z-index: 50;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .brand img {
      height: 38px;
      width: auto;
      filter: drop-shadow(0 0 10px rgba(0, 240, 255, 0.3));
    }
    .brand-title {
      font-size: 1.25rem;
      font-weight: 800;
      letter-spacing: -0.5px;
      color: #fff;
    }
    .brand-badge {
      font-size: 0.65rem;
      background: rgba(0, 240, 255, 0.12);
      color: var(--cyan);
      border: 1px solid rgba(0, 240, 255, 0.3);
      padding: 3px 8px;
      border-radius: 999px;
      font-weight: 700;
      letter-spacing: 0.5px;
      text-transform: uppercase;
    }

    /* CONTAINER */
    .container {
      max-width: 1200px;
      width: 100%;
      margin: 0 auto;
      padding: 32px 20px;
      flex: 1;
    }

    /* STATS ROW */
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-bottom: 32px;
    }
    .stat-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      padding: 20px;
      display: flex;
      align-items: center;
      gap: 16px;
      transition: all 0.2s ease;
    }
    .stat-card:hover {
      border-color: var(--cyan);
      box-shadow: 0 4px 20px rgba(0, 240, 255, 0.08);
    }
    .stat-icon {
      font-size: 2rem;
      background: rgba(255, 255, 255, 0.04);
      width: 52px;
      height: 52px;
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: 12px;
      border: 1px solid rgba(255, 255, 255, 0.08);
    }
    .stat-val {
      font-size: 1.8rem;
      font-weight: 800;
      color: #fff;
      line-height: 1.1;
    }
    .stat-lbl {
      font-size: 0.8rem;
      color: var(--muted);
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    /* MAIN PANELS */
    .grid-layout {
      display: grid;
      grid-template-columns: 1.1fr 1.3fr;
      gap: 24px;
    }
    @media (max-width: 900px) {
      .grid-layout { grid-template-columns: 1fr; }
    }

    .panel {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 24px;
      box-shadow: 0 8px 30px rgba(0, 0, 0, 0.3);
    }
    .panel-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 20px;
      padding-bottom: 12px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.07);
    }
    .panel-title {
      font-size: 1.1rem;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 10px;
      color: #fff;
    }

    /* FORM ELEMENTS */
    .form-group {
      margin-bottom: 16px;
    }
    .form-label {
      display: block;
      font-size: 0.82rem;
      font-weight: 600;
      color: var(--muted);
      margin-bottom: 6px;
      text-transform: uppercase;
      letter-spacing: 0.3px;
    }
    .form-control {
      width: 100%;
      background: rgba(5, 7, 12, 0.8);
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 10px;
      padding: 12px 14px;
      font-size: 0.95rem;
      color: #fff;
      font-family: inherit;
      outline: none;
      transition: all 0.2s;
    }
    .form-control:focus {
      border-color: var(--cyan);
      box-shadow: 0 0 12px var(--cyan-glow);
    }
    .form-control.mono {
      font-family: 'JetBrains Mono', monospace;
      letter-spacing: 0.5px;
    }

    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      padding: 13px 20px;
      border-radius: 10px;
      font-size: 0.95rem;
      font-weight: 700;
      cursor: pointer;
      transition: all 0.2s ease;
      border: none;
      outline: none;
      text-decoration: none;
    }
    .btn-cyan {
      background: linear-gradient(135deg, #00f0ff, #00a8ff);
      color: #030814;
      box-shadow: 0 4px 18px rgba(0, 240, 255, 0.35);
      width: 100%;
    }
    .btn-cyan:hover {
      box-shadow: 0 6px 24px rgba(0, 240, 255, 0.55);
      transform: translateY(-1px);
    }
    .btn-secondary {
      background: rgba(255, 255, 255, 0.08);
      color: #fff;
      border: 1px solid rgba(255, 255, 255, 0.15);
    }
    .btn-secondary:hover {
      background: rgba(255, 255, 255, 0.15);
    }
    .btn-whatsapp {
      background: #25d366;
      color: #fff;
      font-weight: 700;
    }
    .btn-whatsapp:hover {
      background: #20bd5a;
      box-shadow: 0 4px 15px rgba(37, 211, 102, 0.4);
    }

    /* CARD GERADO */
    .result-box {
      background: rgba(0, 240, 255, 0.04);
      border: 1px solid rgba(0, 240, 255, 0.3);
      border-radius: 12px;
      padding: 18px;
      margin-top: 20px;
      display: none;
    }
    .key-display {
      background: #03060a;
      border: 1px dashed var(--cyan);
      border-radius: 8px;
      padding: 12px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.78rem;
      color: var(--cyan);
      word-break: break-all;
      margin: 12px 0;
      user-select: all;
    }
    .btn-row {
      display: flex;
      gap: 10px;
      margin-top: 10px;
    }
    .btn-row .btn {
      flex: 1;
    }

    /* TABLE */
    .table-container {
      overflow-x: auto;
      max-height: 520px;
      overflow-y: auto;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.85rem;
    }
    th {
      background: rgba(5, 8, 15, 0.9);
      color: var(--muted);
      font-weight: 700;
      text-transform: uppercase;
      font-size: 0.72rem;
      letter-spacing: 0.5px;
      padding: 12px;
      text-align: left;
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
      position: sticky;
      top: 0;
    }
    td {
      padding: 12px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
      color: #e2e8f0;
    }
    tr:hover td {
      background: rgba(255, 255, 255, 0.02);
    }
    .badge-pill {
      font-size: 0.7rem;
      font-weight: 700;
      padding: 2px 7px;
      border-radius: 6px;
      display: inline-block;
    }
    .badge-pro { background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }
    .badge-time { background: rgba(0, 240, 255, 0.15); color: var(--cyan); border: 1px solid rgba(0, 240, 255, 0.3); }

    /* AUTH MODAL */
    #authOverlay {
      position: fixed;
      inset: 0;
      background: rgba(3, 6, 12, 0.95);
      backdrop-filter: blur(16px);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 100;
      padding: 20px;
    }
    .auth-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 32px;
      max-width: 400px;
      width: 100%;
      text-align: center;
      box-shadow: 0 10px 40px rgba(0, 240, 255, 0.15);
    }
    .auth-card img {
      height: 50px;
      margin-bottom: 16px;
      filter: drop-shadow(0 0 15px var(--cyan-glow));
    }
    .auth-title {
      font-size: 1.3rem;
      font-weight: 800;
      margin-bottom: 8px;
    }
    .auth-sub {
      font-size: 0.85rem;
      color: var(--muted);
      margin-bottom: 24px;
    }

    .toast {
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: #10b981;
      color: #fff;
      padding: 12px 20px;
      border-radius: 8px;
      font-weight: 700;
      font-size: 0.9rem;
      box-shadow: 0 6px 20px rgba(0,0,0,0.4);
      display: none;
      z-index: 200;
    }
  </style>
</head>
<body>

  <!-- MODAL DE AUTENTICAÇÃO -->
  <div id="authOverlay">
    <div class="auth-card">
      <img src="/LOGO.png" alt="tunemusic">
      <h2 class="auth-title">Painel Administrativo</h2>
      <p class="auth-sub">Digite sua Chave Mestre de Administrador para gerenciar e emitir licenças.</p>
      <form onsubmit="handleAuthSubmit(event);">
        <div class="form-group">
          <input type="password" id="authSecretInput" class="form-control" placeholder="Chave Mestre..." required autofocus>
        </div>
        <button type="submit" class="btn btn-cyan">Acessar Painel</button>
        <p id="authErrorMsg" style="color:var(--danger);font-size:0.8rem;margin-top:10px;display:none;">Chave incorreta. Tente novamente.</p>
      </form>
    </div>
  </div>

  <!-- HEADER -->
  <header>
    <div class="brand">
      <img src="/LOGO.png" alt="tunemusic Pro">
      <div>
        <span class="brand-title">tunemusic <span style="color:var(--cyan)">Pro</span></span>
        <span class="brand-badge">Admin Licenças</span>
      </div>
    </div>
    <div style="display:flex;align-items:center;gap:12px;">
      <a href="/download/installer" class="btn btn-secondary" style="font-size:0.82rem;padding:8px 14px;" title="Baixar Instalador Windows .exe para enviar aos clientes">
        <span>⬇️</span> <span>Instalador (.exe)</span>
      </a>
      <button class="btn btn-secondary" onclick="logoutAdmin();" style="font-size:0.82rem;padding:8px 14px;">
        Sair
      </button>
    </div>
  </header>

  <div class="container">
    <!-- STATS -->
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-icon">💎</div>
        <div>
          <div class="stat-val" id="statTotal">0</div>
          <div class="stat-lbl">Licenças Emitidas</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon">👑</div>
        <div>
          <div class="stat-val" id="statVitalicias" style="color:var(--gold);">0</div>
          <div class="stat-lbl">Vitalícias Ativas</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon">📅</div>
        <div>
          <div class="stat-val" id="statPeriodicas" style="color:var(--cyan);">0</div>
          <div class="stat-lbl">Assinaturas (Anual/Mensal)</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon">🛡️</div>
        <div>
          <div class="stat-val" style="color:var(--green);font-size:1.3rem;">1 PC Lock</div>
          <div class="stat-lbl">Proteção HMAC Ativa</div>
        </div>
      </div>
    </div>

    <!-- MAIN GRID -->
    <div class="grid-layout">
      
      <!-- FORM DE EMISSÃO -->
      <div class="panel">
        <div class="panel-header">
          <h3 class="panel-title"><span>⚡</span> Emitir Nova Licença</h3>
          <span style="font-size:0.75rem;color:var(--muted);">Hardware-Locked</span>
        </div>

        <form id="licenseForm" onsubmit="handleGenerate(event);">
          <div class="form-group">
            <label class="form-label">Nome do Cliente ou Banda *</label>
            <input type="text" id="inpClient" class="form-control" placeholder="Ex: Banda Som Maior - João" required>
          </div>

          <div class="form-group">
            <label class="form-label">ID do Computador do Cliente (HWID) *</label>
            <input type="text" id="inpHwid" class="form-control mono" placeholder="Ex: TUNE-9400-F282-B955-38FE" required>
            <small style="color:var(--muted);font-size:0.75rem;display:block;margin-top:4px;">
              💡 O cliente copia esse ID diretamente da tela de ativação do tunemusic Pro.
            </small>
          </div>

          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div class="form-group">
              <label class="form-label">WhatsApp (Opcional)</label>
              <input type="text" id="inpWhatsapp" class="form-control" placeholder="Ex: 11999999999">
            </div>
            <div class="form-group">
              <label class="form-label">E-mail (Opcional)</label>
              <input type="email" id="inpEmail" class="form-control" placeholder="cliente@email.com">
            </div>
          </div>

          <div class="form-group">
            <label class="form-label">Plano de Acesso</label>
            <select id="inpPlan" class="form-control">
              <option value="vitalicio">👑 Vitalício (Sem Expiração - R$ Recomendado)</option>
              <option value="anual">📅 Anual (365 Dias de Acesso)</option>
              <option value="mensal">🗓️ Mensal (30 Dias de Acesso)</option>
              <option value="demo">⏳ Degustação / Demonstração (7 Dias)</option>
            </select>
          </div>

          <button type="submit" id="btnSubmit" class="btn btn-cyan">
            <span>🔐</span> <span>Gerar Chave de Ativação</span>
          </button>
        </form>

        <!-- RESULTADO DA GERAÇÃO -->
        <div id="resultBox" class="result-box">
          <div style="display:flex;align-items:center;justify-content:space-between;">
            <span style="font-weight:700;color:var(--green);font-size:0.9rem;">✔️ Chave Gerada com Sucesso!</span>
            <span id="resPlanBadge" class="badge-pill badge-pro">Vitalício</span>
          </div>
          
          <div class="key-display" id="resKeyDisplay">TM-...</div>

          <div class="btn-row">
            <button type="button" class="btn btn-whatsapp" onclick="copyWhatsappMessage();">
              <span>📲</span> <span>Copiar Mensagem WhatsApp</span>
            </button>
            <button type="button" class="btn btn-secondary" onclick="openDirectWhatsapp();" id="btnDirectWa">
              <span>💬</span> <span>Abrir no WhatsApp</span>
            </button>
          </div>
        </div>

      </div>

      <!-- HISTÓRICO DE LICENÇAS -->
      <div class="panel">
        <div class="panel-header">
          <h3 class="panel-title"><span>📋</span> Licenças Emitidas</h3>
          <input type="text" id="tableFilter" oninput="filterLicenses();" class="form-control" style="max-width:200px;padding:6px 10px;font-size:0.8rem;" placeholder="Buscar cliente ou HWID...">
        </div>

        <div class="table-container">
          <table>
            <thead>
              <tr>
                <th>Cliente</th>
                <th>HWID</th>
                <th>Plano</th>
                <th>Emissão</th>
                <th>Ações</th>
              </tr>
            </thead>
            <tbody id="licensesTbody">
              <tr>
                <td colspan="5" style="text-align:center;color:var(--muted);padding:30px;">
                  Carregando registros...
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

    </div>
  </div>

  <div id="toast" class="toast">Mensagem copiada para a Área de Transferência!</div>

  <script>
    let currentAdminSecret = localStorage.getItem('tunemusic_admin_secret') || '';
    let allLicenses = [];
    let lastGeneratedWhatsapp = '';
    let lastPhone = '';

    function showToast(msg) {
      const t = document.getElementById('toast');
      t.textContent = msg;
      t.style.display = 'block';
      setTimeout(() => { t.style.display = 'none'; }, 3000);
    }

    async function checkAuth() {
      if (!currentAdminSecret) {
        document.getElementById('authOverlay').style.display = 'flex';
        return;
      }
      try {
        const res = await fetch('/api/admin/licenses?secret=' + encodeURIComponent(currentAdminSecret));
        if (res.ok) {
          document.getElementById('authOverlay').style.display = 'none';
          const data = await res.json();
          allLicenses = data.licenses || [];
          renderStatsAndTable();
        } else {
          document.getElementById('authOverlay').style.display = 'flex';
        }
      } catch (e) {
        document.getElementById('authOverlay').style.display = 'flex';
      }
    }

    async function handleAuthSubmit(e) {
      e.preventDefault();
      const val = document.getElementById('authSecretInput').value.trim();
      const err = document.getElementById('authErrorMsg');
      err.style.display = 'none';

      try {
        const res = await fetch('/api/admin/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ admin_secret: val })
        });
        if (res.ok) {
          currentAdminSecret = val;
          localStorage.setItem('tunemusic_admin_secret', val);
          document.getElementById('authOverlay').style.display = 'none';
          checkAuth();
        } else {
          err.style.display = 'block';
        }
      } catch (err) {
        err.style.display = 'block';
      }
    }

    function logoutAdmin() {
      localStorage.removeItem('tunemusic_admin_secret');
      currentAdminSecret = '';
      location.reload();
    }

    async function handleGenerate(e) {
      e.preventDefault();
      const btn = document.getElementById('btnSubmit');
      btn.disabled = true;
      btn.innerHTML = '<span>⏳</span> <span>Assinando Criptograficamente...</span>';

      const payload = {
        client: document.getElementById('inpClient').value.trim(),
        hwid: document.getElementById('inpHwid').value.trim(),
        whatsapp: document.getElementById('inpWhatsapp').value.trim(),
        email: document.getElementById('inpEmail').value.trim(),
        plan_type: document.getElementById('inpPlan').value,
        admin_secret: currentAdminSecret
      };

      try {
        const res = await fetch('/api/admin/licenses/create', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (res.ok && data.ok) {
          const rec = data.license;
          lastGeneratedWhatsapp = data.whatsapp_message;
          lastPhone = payload.whatsapp.replace(/\\D/g, '');

          document.getElementById('resKeyDisplay').textContent = rec.key;
          document.getElementById('resPlanBadge').textContent = rec.plan;
          document.getElementById('resultBox').style.display = 'block';

          if (!lastPhone) {
            document.getElementById('btnDirectWa').style.display = 'none';
          } else {
            document.getElementById('btnDirectWa').style.display = 'inline-flex';
          }

          showToast('✔️ Licença criada com sucesso!');
          checkAuth(); // reload table
        } else {
          alert('Erro ao emitir: ' + (data.detail || 'Falha ao processar'));
        }
      } catch (err) {
        alert('Erro de conexão: ' + err.message);
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<span>🔐</span> <span>Gerar Chave de Ativação</span>';
      }
    }

    function copyWhatsappMessage() {
      if (!lastGeneratedWhatsapp) return;
      navigator.clipboard.writeText(lastGeneratedWhatsapp).then(() => {
        showToast('📋 Mensagem completa copiada para o WhatsApp!');
      });
    }

    function openDirectWhatsapp() {
      if (!lastGeneratedWhatsapp) return;
      let clean = lastPhone.replace(/\\D/g, '');
      if (clean.length === 10 || clean.length === 11) {
        clean = '55' + clean;
      }
      const url = 'https://api.whatsapp.com/send?phone=' + clean + '&text=' + encodeURIComponent(lastGeneratedWhatsapp);
      window.open(url, '_blank');
    }

    function renderStatsAndTable() {
      document.getElementById('statTotal').textContent = allLicenses.length;
      const vit = allLicenses.filter(l => l.plan_type === 'vitalicio' || !l.expires).length;
      document.getElementById('statVitalicias').textContent = vit;
      document.getElementById('statPeriodicas').textContent = (allLicenses.length - vit);

      filterLicenses();
    }

    function filterLicenses() {
      const q = (document.getElementById('tableFilter').value || '').toLowerCase().trim();
      const tbody = document.getElementById('licensesTbody');
      
      const filtered = allLicenses.filter(l => {
        return (l.client || '').toLowerCase().includes(q) || (l.hwid || '').toLowerCase().includes(q);
      });

      if (!filtered.length) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:30px;">Nenhuma licença encontrada.</td></tr>';
        return;
      }

      tbody.innerHTML = filtered.slice().reverse().map(l => {
        const isVit = l.plan_type === 'vitalicio' || !l.expires;
        const badge = isVit ? '<span class="badge-pill badge-pro">Vitalício</span>' : '<span class="badge-pill badge-time">' + (l.expires || 'Anual') + '</span>';
        const keyEsc = (l.key || '').replace(/'/g, "\\\\'");
        const clientEsc = (l.client || '').replace(/'/g, "\\\\'");
        return `
          <tr>
            <td>
              <strong style="color:#fff;">${l.client}</strong>
              ${l.whatsapp ? '<br><small style="color:var(--muted);">📱 ' + l.whatsapp + '</small>' : ''}
            </td>
            <td><code style="font-family:'JetBrains Mono';color:var(--cyan);font-size:0.75rem;">${l.hwid}</code></td>
            <td>${badge}</td>
            <td style="font-size:0.75rem;color:var(--muted);">${(l.issued || '').substring(0, 10)}</td>
            <td>
              <button class="btn btn-secondary" style="padding:4px 8px;font-size:0.75rem;" onclick="copySpecificKey('${keyEsc}')" title="Copiar Chave de Licença">
                🔑 Copiar
              </button>
            </td>
          </tr>
        `;
      }).join('');
    }

    function copySpecificKey(k) {
      navigator.clipboard.writeText(k).then(() => {
        showToast('🔑 Chave copiada!');
      });
    }

    // Init
    checkAuth();
  </script>
</body>
</html>
"""
    return HTMLResponse(content=html_content)


@router.get("/download/installer")
async def download_installer():
    """Serves the Windows installer exe for clients."""
    candidates = [
        Path("tunemusic Pro Setup 1.0.0.exe"),
        Path("extracted_stageprompter/dist_app/tunemusic Pro Setup 1.0.0.exe")
    ]
    for p in candidates:
        if p.exists():
            return FileResponse(
                path=str(p),
                filename="tunemusic Pro Setup 1.0.0.exe",
                media_type="application/vnd.microsoft.portable-executable"
            )
    raise HTTPException(status_code=404, detail="Instalador não encontrado no servidor.")
