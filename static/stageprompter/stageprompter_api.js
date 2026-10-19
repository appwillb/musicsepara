// StagePrompter Web Bridge API (Reconstruction of Electron Preload)
(function() {
  'use strict';

  console.log('[StagePrompter] Initializing Web Bridge API...');

  const syncChannel = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('stageprompter_sync') : null;
  let presentationWindow = null;
  let activeAudioFile = null;
  let activeAudioUrl = null;
  let activeAudioDuration = 0;
  let exportProgressCallback = null;
  let transcribeProgressCallback = null;
  let presentationUpdateCallback = null;
  let presentationClosedCallback = null;
  let presentationKeyCallback = null;
  let stopwatchBoxCallback = null;
  const entitlementsCallbacks = [];

  async function notifyEntitlements(forcedEnt) {
    try {
      const ent = forcedEnt || (window.api && typeof window.api.getEntitlements === 'function' ? await window.api.getEntitlements() : null);
      if (ent) {
        for (const cb of entitlementsCallbacks) {
          try { cb(ent); } catch (e) {}
        }
      }
    } catch(e) {}
  }

  // Listen to cross-window sync messages
  if (syncChannel) {
    syncChannel.onmessage = (event) => {
      const data = event.data;
      if (!data) return;
      if (data.type === 'key' && presentationKeyCallback) {
        presentationKeyCallback(data.key);
      } else if (data.type === 'update' && presentationUpdateCallback) {
        presentationUpdateCallback(data.state);
      } else if (data.type === 'stopwatchBox' && stopwatchBoxCallback) {
        stopwatchBoxCallback(data.box);
      }
    };
  }

  // File picker helper
  function pickFile(accept) {
    return new Promise((resolve) => {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = accept || '*/*';
      input.style.display = 'none';
      document.body.appendChild(input);
      input.onchange = (e) => {
        const file = e.target.files && e.target.files[0];
        document.body.removeChild(input);
        resolve(file || null);
      };
      input.click();
    });
  }

  // Trigger JSON download
  function downloadJson(filename, data) {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // Web Device Fingerprint / Persistent Web HWID (per browser)
  function getOrCreateWebHwid() {
    let hwid = localStorage.getItem('tunemusic_web_hwid');
    if (!hwid) {
      let part = '';
      try {
        const arr = new Uint8Array(8);
        (window.crypto || window.msCrypto).getRandomValues(arr);
        part = Array.from(arr).map(b => b.toString(16).padStart(2, '0')).join('').toUpperCase();
      } catch(e) {
        part = Math.random().toString(36).substring(2, 10).toUpperCase() + Math.random().toString(36).substring(2, 10).toUpperCase();
      }
      hwid = 'TUNE-WEB-' + part.slice(0, 4) + '-' + part.slice(4, 8) + '-' + part.slice(8, 12);
      localStorage.setItem('tunemusic_web_hwid', hwid);
    }
    return hwid;
  }

  window.api = {
    // 1. REPERTOIRE
    readRepertorio: async () => {
      try {
        const res = await fetch('/api/stageprompter/repertoire');
        return await res.json();
      } catch (err) {
        console.error('Erro ao ler repertório:', err);
        return { shows: [], activeShowId: null };
      }
    },

    writeRepertorio: async (data) => {
      try {
        const res = await fetch('/api/stageprompter/repertoire', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });
        return await res.json();
      } catch (err) {
        console.error('Erro ao gravar repertório:', err);
        return { ok: false };
      }
    },

    // 2. CREDITS / MESSAGES
    readCredits: async () => {
      try {
        const res = await fetch('/api/stageprompter/credits');
        return await res.json();
      } catch (err) {
        console.error('Erro ao ler créditos:', err);
        return { agradecimentos: [], participacoes: [], avisos: [], tituloAvisos: 'Avisos' };
      }
    },

    writeCredits: async (data) => {
      try {
        const res = await fetch('/api/stageprompter/credits', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });
        return await res.json();
      } catch (err) {
        console.error('Erro ao gravar créditos:', err);
        return { ok: false };
      }
    },

    // 3. SAVED SONGS
    getSavedSongs: async () => {
      try {
        const res = await fetch('/api/stageprompter/songs');
        return await res.json();
      } catch (err) {
        return [];
      }
    },

    getLyricsCacheKeys: async () => {
      try {
        const res = await fetch('/api/stageprompter/songs/keys');
        return await res.json();
      } catch (err) {
        return [];
      }
    },

    saveLyricsManual: async (track, artist, blocks) => {
      try {
        const res = await fetch('/api/stageprompter/songs', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ track, artist, blocks, source: 'manual' })
        });
        return await res.json();
      } catch (err) {
        return { ok: false, error: err.message };
      }
    },

    deleteSavedSong: async (track, artist) => {
      try {
        const res = await fetch('/api/stageprompter/songs', {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ track, artist })
        });
        return await res.json();
      } catch (err) {
        return { ok: false, error: err.message };
      }
    },

    // 4. SEARCH & LYRICS
    searchSongsFallback: async (term) => {
      try {
        const res = await fetch(`/api/stageprompter/search?q=${encodeURIComponent(term)}`);
        return await res.json();
      } catch (err) {
        return { ok: false, results: [] };
      }
    },

    searchLyricsOptions: async (track, artist) => {
      try {
        const res = await fetch(`/api/stageprompter/search?q=${encodeURIComponent(track + ' ' + (artist || ''))}`);
        return await res.json();
      } catch (err) {
        return { ok: false, results: [] };
      }
    },

    fetchLyrics: async (track, artist, source) => {
      try {
        const res = await fetch('/api/stageprompter/fetch-lyrics', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ track, artist, source })
        });
        const data = await res.json();
        if (data && data.blocks && Array.isArray(data.blocks)) {
          data.blocks = data.blocks.map(b => Array.isArray(b) ? b.join('\n') : String(b));
        }
        return data;
      } catch (err) {
        return { ok: false, error: err.message };
      }
    },

    fetchLyricsUrl: async (url) => {
      try {
        const res = await fetch('/api/stageprompter/fetch-lyrics', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url })
        });
        const data = await res.json();
        if (data && data.blocks && Array.isArray(data.blocks)) {
          data.blocks = data.blocks.map(b => Array.isArray(b) ? b.join('\n') : String(b));
        }
        return data;
      } catch (err) {
        return { ok: false, error: err.message };
      }
    },

    // 5. BACKUP
    exportBackup: async (data) => {
      try {
        if (!data) {
          const res = await fetch('/api/stageprompter/backup');
          data = await res.json();
        }
        downloadJson(`tunemusic-backup-${new Date().toISOString().slice(0, 10)}.json`, data);
        return { ok: true };
      } catch (err) {
        return { ok: false, error: err.message };
      }
    },

    importBackup: async () => {
      const file = await pickFile('.json');
      if (!file) return { ok: false };
      try {
        const formData = new FormData();
        formData.append('file', file);
        const res = await fetch('/api/stageprompter/backup', {
          method: 'POST',
          body: formData
        });
        return await res.json();
      } catch (err) {
        return { ok: false, error: err.message };
      }
    },

    // 6. SEARCH PREFERENCES
    getBuscaPreferencia: async () => {
      return localStorage.getItem('busca_preferencia') || 'nacional';
    },

    setBuscaPreferencia: async (pref) => {
      localStorage.setItem('busca_preferencia', pref);
      return { ok: true, preferencia: pref };
    },

    getVagalumeKey: async () => {
      return localStorage.getItem('vagalume_key') || '';
    },

    setVagalumeKey: async (key) => {
      localStorage.setItem('vagalume_key', key);
      return { ok: true };
    },

    // 7. PRESENTATION (SEGUNDA TELA / TELÃO)
    startPresentation: async () => {
      try {
        if (presentationWindow && !presentationWindow.closed) {
          presentationWindow.focus();
          return { ok: true };
        }
        const width = 1280;
        const height = 720;
        const left = (screen.width - width) / 2;
        const top = (screen.height - height) / 2;
        presentationWindow = window.open(
          '/stageprompter/presentation',
          'StagePrompterPresentationWindow',
          `width=${width},height=${height},left=${left},top=${top},menubar=no,toolbar=no,location=no,status=no`
        );
        if (presentationWindow) {
          presentationWindow.focus();
          const checkClosed = setInterval(() => {
            if (presentationWindow.closed) {
              clearInterval(checkClosed);
              presentationWindow = null;
              if (presentationClosedCallback) presentationClosedCallback();
            }
          }, 1000);
          return { ok: true };
        }
        return { ok: false, error: 'Popup bloqueado pelo navegador. Permita popups para abrir a segunda tela.' };
      } catch (err) {
        return { ok: false, error: err.message };
      }
    },

    updatePresentation: (state) => {
      // 1. Update Preview iframe if present
      const previewFrame = document.getElementById('telaoPreviewFrame');
      if (previewFrame && previewFrame.contentWindow) {
        try {
          previewFrame.contentWindow.postMessage({ __spPreviewState: state }, '*');
        } catch (e) {}
      }
      const opFrame = document.getElementById('msgOperatorFrame');
      if (opFrame && opFrame.contentWindow) {
        try {
          opFrame.contentWindow.postMessage({ __spPreviewState: state }, '*');
        } catch (e) {}
      }

      // 2. Update external presentation window if open
      if (presentationWindow && !presentationWindow.closed) {
        try {
          presentationWindow.postMessage({ __spPreviewState: state }, '*');
        } catch (e) {}
      }

      // 3. BroadcastChannel cross-tab
      if (syncChannel) {
        try {
          syncChannel.postMessage({ type: 'update', state: state });
        } catch (e) {}
      }

      // 4. LocalStorage fallback
      try {
        localStorage.setItem('__sp_presentation_state', JSON.stringify(state));
      } catch (e) {}
    },

    onPresentationUpdate: (callback) => {
      presentationUpdateCallback = callback;
    },

    onPresentationClosed: (callback) => {
      presentationClosedCallback = callback;
    },

    sendPresentationKey: (key) => {
      if (syncChannel) {
        syncChannel.postMessage({ type: 'key', key: key });
      }
    },

    onPresentationKey: (callback) => {
      presentationKeyCallback = callback;
    },

    sendStopwatchBox: (box) => {
      if (syncChannel) {
        syncChannel.postMessage({ type: 'stopwatchBox', box: box });
      }
    },

    onStopwatchBox: (callback) => {
      stopwatchBoxCallback = callback;
    },

    toggleFullscreen: () => {
      if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen().catch(() => {});
      } else {
        document.exitFullscreen().catch(() => {});
      }
    },

    // 8. AUDIO & RHYTHM MARKER
    chooseAudioFile: async () => {
      const file = await pickFile('.mp3,.wav,.m4a,.flac,.ogg,.aac,.webm');
      if (!file) return null;
      activeAudioFile = file;
      activeAudioUrl = URL.createObjectURL(file);
      return { path: activeAudioUrl, name: file.name, size: file.size };
    },

    useAudioFile: async (filePath) => {
      if (activeAudioFile) {
        return { name: activeAudioFile.name, size: activeAudioFile.size, path: activeAudioUrl };
      }
      return { name: filePath, size: 0, path: filePath };
    },

    prepareAudioProxy: async () => {
      if (activeAudioUrl) {
        return { ok: true, path: activeAudioUrl, url: activeAudioUrl };
      }
      return { ok: false, error: 'Nenhum áudio selecionado' };
    },

    getAudioPeaks: async () => {
      if (!activeAudioFile) {
        return { ok: false, error: 'Nenhum áudio carregado' };
      }
      try {
        // Fast in-browser decoding via Web Audio API
        const arrayBuffer = await activeAudioFile.arrayBuffer();
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
        activeAudioDuration = audioBuffer.duration;

        const channelData = audioBuffer.getChannelData(0);
        const totalSamples = channelData.length;
        const numPeaks = 1200;
        const step = Math.max(1, Math.floor(totalSamples / numPeaks));
        const peaks = [];

        for (let i = 0; i < totalSamples; i += step) {
          let max = 0;
          const end = Math.min(i + step, totalSamples);
          for (let j = i; j < end; j++) {
            const val = Math.abs(channelData[j]);
            if (val > max) max = val;
          }
          peaks.push(max);
        }

        const maxPeak = Math.max(...peaks, 1.0);
        const normalized = peaks.map(p => Number((p / maxPeak).toFixed(4)));

        return {
          ok: true,
          duration: activeAudioDuration,
          peaks: normalized
        };
      } catch (err) {
        console.error('Audio peaks error:', err);
        return { ok: false, error: err.message };
      }
    },

    vsSaveMarksFile: async (marks) => {
      downloadJson('marcacoes-show.json', marks);
      return { ok: true };
    },

    vsLoadMarksFile: async () => {
      const file = await pickFile('.json');
      if (!file) return { ok: false };
      try {
        const text = await file.text();
        const data = JSON.parse(text);
        return { ok: true, data: data };
      } catch (err) {
        return { ok: false, error: err.message };
      }
    },

    onAudioProxyProgress: (callback) => {
      // Browser Web Audio decodes directly
    },

    onUpdateReady: (callback) => {
      // Pro version is always up to date
    },

    // Integration Bridge with Vocal Remover
    loadAudioFromUrl: async (url, filename) => {
      try {
        console.log('[StagePrompter] Carregando áudio do Vocal Remover:', url);
        const res = await fetch(url);
        const blob = await res.blob();
        const file = new File([blob], filename || 'playback_vocal_remover.wav', { type: blob.type || 'audio/wav' });
        activeAudioFile = file;
        activeAudioUrl = URL.createObjectURL(file);
        return { ok: true, name: file.name, size: file.size, path: activeAudioUrl };
      } catch (err) {
        console.error('Erro ao carregar áudio do Vocal Remover:', err);
        return { ok: false, error: err.message };
      }
    },

    listVocalTasks: async () => {
      try {
        const res = await fetch('/api/stageprompter/vocal-tasks');
        return await res.json();
      } catch (err) {
        return [];
      }
    },

    // 9. VIDEO EXPORT
    exportVideo: async (options) => {
      try {
        // 1. Resolve audio file if not already set
        if (!activeAudioFile) {
          if (activeAudioUrl) {
            try {
              const bRes = await fetch(activeAudioUrl);
              const blob = await bRes.blob();
              activeAudioFile = new File([blob], 'audio_track.wav', { type: blob.type || 'audio/wav' });
            } catch (e) {}
          }
          if (!activeAudioFile) {
            const vsAudioEl = document.getElementById('vsAudio');
            if (vsAudioEl && vsAudioEl.src) {
              try {
                const bRes = await fetch(vsAudioEl.src);
                const blob = await bRes.blob();
                activeAudioFile = new File([blob], 'audio_track.wav', { type: blob.type || 'audio/wav' });
              } catch (e) {}
            }
          }
        }

        const formData = new FormData();
        if (activeAudioFile) {
          formData.append('audio', activeAudioFile);
        }
        if (options && options.audioPath) {
          formData.append('audio_path', options.audioPath);
        }
        formData.append('markers', JSON.stringify(options || {}));
        formData.append('fps', options && options.fps ? String(options.fps) : '30');

        if (exportProgressCallback) {
          exportProgressCallback({ stage: 'Iniciando preparação de vídeo...', percent: 10 });
        }

        const res = await fetch('/api/stageprompter/export-video', {
          method: 'POST',
          body: formData
        });
        const result = await res.json();
        if (!result.ok) {
          return result;
        }

        const jobId = result.job_id;
        // Poll status until ready
        return new Promise((resolve) => {
          const interval = setInterval(async () => {
            try {
              const statusRes = await fetch(`/api/stageprompter/export-video-status/${jobId}`);
              const status = await statusRes.json();
              if (exportProgressCallback) {
                exportProgressCallback({
                  stage: status.label || 'Processando...',
                  percent: status.progress || 50
                });
              }
              if (status.status === 'completed') {
                clearInterval(interval);
                // Trigger download via anchor
                const dlLink = document.createElement('a');
                dlLink.href = `/api/stageprompter/download-video/${jobId}`;
                dlLink.download = 'tunemusic_Show_Sincronizado.mp4';
                document.body.appendChild(dlLink);
                dlLink.click();
                document.body.removeChild(dlLink);
                resolve({ ok: true, filePath: 'tunemusic_Show_Sincronizado.mp4' });
              } else if (status.status === 'error') {
                clearInterval(interval);
                resolve({ ok: false, error: status.error || 'Falha ao renderizar vídeo' });
              }
            } catch (pollErr) {
              clearInterval(interval);
              resolve({ ok: false, error: pollErr.message });
            }
          }, 1200);
        });
      } catch (err) {
        return { ok: false, error: err.message };
      }
    },

    onExportProgress: (callback) => {
      exportProgressCallback = callback;
    },

    // 10. AI AUDIO TRANSCRIPTION
    chooseTranscribeAudio: async () => {
      const file = await pickFile('.mp3,.wav,.m4a,.flac,.ogg,.aac');
      if (!file) return null;
      activeAudioFile = file;
      activeAudioUrl = URL.createObjectURL(file);
      return { path: activeAudioUrl, name: file.name };
    },

    transcribeAudio: async (payload) => {
      let fileToSend = activeAudioFile;
      if (!fileToSend && payload) {
        if (typeof payload === 'object' && (payload instanceof File || payload instanceof Blob)) {
          fileToSend = payload;
        } else if (typeof payload === 'string') {
          try {
            const resp = await fetch(payload);
            const blob = await resp.blob();
            fileToSend = new File([blob], "audio.mp3", { type: blob.type || "audio/mpeg" });
          } catch(e) {}
        }
      }
      if (!fileToSend) {
        return { ok: false, error: 'Selecione um arquivo de áudio para transcrever' };
      }
      try {
        if (transcribeProgressCallback) {
          transcribeProgressCallback({ stage: 'Enviando áudio...', percent: 20 });
        }

        const formData = new FormData();
        formData.append('file', fileToSend);

        const res = await fetch('/api/stageprompter/transcribe', {
          method: 'POST',
          body: formData
        });

        if (transcribeProgressCallback) {
          transcribeProgressCallback({ stage: 'Processando com Inteligência Artificial...', percent: 75 });
        }

        const data = await res.json();

        if (transcribeProgressCallback) {
          transcribeProgressCallback({ stage: 'Concluído!', percent: 100 });
        }

        return data;
      } catch (err) {
        return { ok: false, error: err.message };
      }
    },

    onTranscribeProgress: (callback) => {
      transcribeProgressCallback = callback;
    },

    // 11. CRYPTOGRAPHIC HARDWARE LICENSING (BROWSER & WEB LOCK)
    getHwid: async () => {
      return getOrCreateWebHwid();
    },

    getEntitlements: async () => {
      const hwid = getOrCreateWebHwid();
      const stored = localStorage.getItem('tunemusic_web_license');
      if (!stored) {
        return {
          licensed: false,
          pro: false,
          active: false,
          nome: 'Não Ativado',
          client: 'Não Ativado',
          plan: 'Sem Licença',
          expires: null,
          exp: null,
          expiracao: 'Bloqueado',
          expiresDisplay: 'Não Ativado',
          isLifetime: false,
          hwid: hwid,
          key: null
        };
      }
      try {
        const licObj = JSON.parse(stored);
        if (!licObj || !licObj.key) throw new Error('Dados corrompidos');
        
        // Quick verify with server
        const res = await fetch('/api/license/verify', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ key: licObj.key, hwid: hwid })
        });
        const data = await res.json();
        if (res.ok && data.ok) {
          const payload = data.payload || {};
          const expDate = payload.expires || null;
          return {
            licensed: true,
            pro: true,
            active: true,
            nome: payload.client || 'tunemusic Pro',
            client: payload.client || 'tunemusic Pro',
            plan: payload.plan || 'tunemusic Pro',
            email: payload.email || '',
            expires: expDate,
            exp: expDate,
            expiracao: expDate ? `Válido até ${expDate}` : 'Vitalícia',
            expiresDisplay: expDate ? `Válido até ${expDate}` : 'Vitalícia (Sem expiração)',
            isLifetime: !expDate,
            transcricoesTotal: 9999,
            transcricoesUsadas: 0,
            hwid: hwid,
            key: licObj.key
          };
        } else {
          // Key invalidated or expired
          localStorage.removeItem('tunemusic_web_license');
          return {
            licensed: false,
            pro: false,
            active: false,
            nome: 'Não Ativado',
            client: 'Não Ativado',
            plan: 'Sem Licença',
            expires: null,
            exp: null,
            expiracao: 'Bloqueado',
            expiresDisplay: 'Não Ativado',
            isLifetime: false,
            hwid: hwid,
            key: null
          };
        }
      } catch (e) {
        // Fallback for offline cached verification
        try {
          const licObj = JSON.parse(stored);
          if (licObj && (licObj.payload || licObj.key)) {
            const payload = licObj.payload || {};
            const expDate = payload.expires || null;
            return {
              licensed: true,
              pro: true,
              active: true,
              nome: payload.client || 'tunemusic Pro',
              client: payload.client || 'tunemusic Pro',
              plan: payload.plan || 'tunemusic Pro',
              email: payload.email || '',
              expires: expDate,
              exp: expDate,
              expiracao: expDate ? `Válido até ${expDate}` : 'Vitalícia',
              expiresDisplay: expDate ? `Válido até ${expDate}` : 'Vitalícia (Sem expiração)',
              isLifetime: !expDate,
              hwid: hwid,
              key: licObj.key
            };
          }
        } catch(err) {}
        return {
          licensed: false,
          pro: false,
          active: false,
          nome: 'Não Ativado',
          client: 'Não Ativado',
          plan: 'Sem Licença',
          expires: null,
          exp: null,
          expiracao: 'Bloqueado',
          expiresDisplay: 'Não Ativado',
          isLifetime: false,
          hwid: hwid,
          key: null
        };
      }
    },

    getLicenseStatus: async () => {
      return await window.api.getEntitlements();
    },

    activateLicense: async (key) => {
      const hwid = getOrCreateWebHwid();
      try {
        const res = await fetch('/api/license/verify', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ key: key.trim(), hwid: hwid })
        });
        const data = await res.json();
        if (res.ok && data.ok) {
          localStorage.setItem('tunemusic_web_license', JSON.stringify({
            key: key.trim(),
            payload: data.payload,
            activated_at: new Date().toISOString()
          }));
          const newEnt = await window.api.getEntitlements();
          notifyEntitlements(newEnt);
          return {
            ok: true,
            valid: true,
            pro: true,
            plan: data.payload.plan,
            client: data.payload.client,
            nome: data.payload.client,
            expires: data.payload.expires,
            exp: data.payload.expires,
            message: data.message || 'Licença autenticada com sucesso! Bem-vindo ao tunemusic Pro.'
          };
        }
        return {
          ok: false,
          valid: false,
          detail: data.detail || data.message || 'Chave de licença inválida para este navegador.'
        };
      } catch (e) {
        return { ok: false, valid: false, detail: 'Erro de conexão ao validar licença: ' + e.message };
      }
    },

    deactivateLicense: async () => {
      localStorage.removeItem('tunemusic_web_license');
      const lockedEnt = await window.api.getEntitlements();
      notifyEntitlements(lockedEnt);
      return { ok: true, message: 'Licença desativada deste navegador com sucesso.' };
    },

    resetLicense: async () => {
      return await window.api.deactivateLicense();
    },

    hasLead: async () => {
      const stored = localStorage.getItem('tunemusic_web_license');
      return !!stored;
    },

    getLeadInfo: async () => {
      const stored = localStorage.getItem('tunemusic_web_license');
      if (stored) {
        try {
          const lic = JSON.parse(stored);
          const client = (lic && lic.payload && lic.payload.client) || 'tunemusic Pro';
          return { nome: client, plano: 'Pro' };
        } catch(e) {}
      }
      return { nome: '', plano: 'free' };
    },

    registerLead: async (info) => ({ ok: true }),

    onEntitlementsChanged: (callback) => {
      if (typeof callback === 'function') {
        entitlementsCallbacks.push(callback);
        setTimeout(async () => {
          try {
            const st = await window.api.getEntitlements();
            callback(st);
          } catch(e) {}
        }, 50);
      }
    },

    openExternalLink: (url) => {
      window.open(url, '_blank');
    },

    reportProblem: () => ({ ok: true }),

    installUpdateNow: async () => ({ ok: true })
  };

  // Automatic integration detection when opening via URL with ?task_id=... or ?audio_url=...
  window.addEventListener('DOMContentLoaded', async () => {
    try {
      const params = new URLSearchParams(window.location.search);
      const taskId = params.get('task_id');
      const audioUrl = params.get('audio_url') || (taskId ? `/split/listen/music/${taskId}/local` : null);
      const songName = params.get('name') || params.get('track');
      if (audioUrl) {
        console.log('[StagePrompter Integration] Detectada faixa do Vocal Remover:', audioUrl);
        await window.api.loadAudioFromUrl(audioUrl, songName ? `${songName}.wav` : 'playback.wav');
        if (songName) {
          const searchInput = document.querySelector('.search-input') || document.querySelector('input[type="text"]');
          if (searchInput) searchInput.value = songName;
        }
      }
    } catch (e) {
      console.warn('[StagePrompter Integration] URL param handling:', e);
    }
  });

  console.log('[StagePrompter] Web Bridge API initialized successfully!');
})();
