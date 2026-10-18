/**
 * Vocal Remover & Stem Splitter Studio Engine
 * StagePrompter Studio Desktop Workstation Integration
 */
(function() {
  'use strict';

  console.log('[VocalRemover] Initializing Studio Engine...');

  const API_BASE = (window.location.protocol === 'file:') ? 'https://tunemusic.tech' : '';

  // State
  let currentTask = null;
  let pollInterval = null;
  let selectedModel = 1; // 1 = 2 stems (vocals + instrumental), 2 = 4 stems

  // Audio Playback & Synchronization Engine
  let audioCtx = null;
  let audioMusic = null;
  let audioVocal = null;
  let isPlaying = false;
  let isLooping = false;
  let duration = 0;
  let animFrameId = null;

  // Channel States
  let muteMusic = false;
  let soloMusic = false;
  let muteVocal = false;
  let soloVocal = false;
  let volMusic = 1.0;
  let volVocal = 1.0;
  let masterVol = 0.85;

  // Waveform peak data caches
  let peaksMusic = null;
  let peaksVocal = null;

  function initAudioElements() {
    if (!audioMusic) {
      audioMusic = new Audio();
      audioMusic.preload = 'auto';
      audioMusic.crossOrigin = 'anonymous';
    }
    if (!audioVocal) {
      audioVocal = new Audio();
      audioVocal.preload = 'auto';
      audioVocal.crossOrigin = 'anonymous';
    }

    audioMusic.onloadedmetadata = () => {
      if (audioMusic.duration && isFinite(audioMusic.duration)) {
        duration = audioMusic.duration;
        updateTimeDisplays();
      }
    };

    audioMusic.onended = () => {
      if (isLooping) {
        seekTo(0);
        playAudio();
      } else {
        stopAudio();
      }
    };
  }

  function formatTime(seconds) {
    if (!seconds || isNaN(seconds) || !isFinite(seconds)) return '00:00';
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  }

  function updateTimeDisplays() {
    const curTimeEl = document.getElementById('vrCurrentTime');
    const totTimeEl = document.getElementById('vrTotalTime');
    const cur = audioMusic ? audioMusic.currentTime : 0;
    if (curTimeEl) curTimeEl.textContent = formatTime(cur);
    if (totTimeEl) totTimeEl.textContent = formatTime(duration);
    
    const tagDur = document.getElementById('vrTagDuration');
    if (tagDur) tagDur.textContent = `⏱️ ${formatTime(duration)}`;

    updatePlayheads();
  }

  function updatePlayheads() {
    if (!duration || duration <= 0 || !audioMusic) return;
    const progress = Math.min(1, Math.max(0, audioMusic.currentTime / duration));
    const pct = (progress * 100).toFixed(2) + '%';

    const phMusic = document.getElementById('vrPlayheadMusic');
    const phVocal = document.getElementById('vrPlayheadVocal');
    if (phMusic) phMusic.style.left = pct;
    if (phVocal) phVocal.style.left = pct;
  }

  function applyVolumeLevels() {
    if (!audioMusic || !audioVocal) return;

    let effMusic = volMusic * masterVol;
    let effVocal = volVocal * masterVol;

    if (soloMusic) {
      effVocal = 0;
    } else if (soloVocal) {
      effMusic = 0;
    }

    if (muteMusic) effMusic = 0;
    if (muteVocal) effVocal = 0;

    audioMusic.volume = Math.max(0, Math.min(1, effMusic));
    audioVocal.volume = Math.max(0, Math.min(1, effVocal));
  }

  function playAudio() {
    if (!audioMusic || !audioVocal) return;
    initAudioContext();
    
    // Ensure both are aligned
    audioVocal.currentTime = audioMusic.currentTime;

    Promise.all([audioMusic.play(), audioVocal.play()]).then(() => {
      isPlaying = true;
      const playBtn = document.getElementById('vrBtnPlayPause');
      if (playBtn) playBtn.textContent = '⏸';
      startPlaybackTicker();
    }).catch(err => {
      console.warn('Playback error:', err);
    });
  }

  function pauseAudio() {
    if (audioMusic) audioMusic.pause();
    if (audioVocal) audioVocal.pause();
    isPlaying = false;
    const playBtn = document.getElementById('vrBtnPlayPause');
    if (playBtn) playBtn.textContent = '▶';
    stopPlaybackTicker();
  }

  function stopAudio() {
    pauseAudio();
    seekTo(0);
  }

  function seekTo(time) {
    if (!audioMusic || !audioVocal) return;
    const clamped = Math.max(0, Math.min(duration || 0, time));
    audioMusic.currentTime = clamped;
    audioVocal.currentTime = clamped;
    updateTimeDisplays();
  }

  function startPlaybackTicker() {
    stopPlaybackTicker();
    function tick() {
      updateTimeDisplays();
      if (isPlaying) {
        animFrameId = requestAnimationFrame(tick);
      }
    }
    animFrameId = requestAnimationFrame(tick);
  }

  function stopPlaybackTicker() {
    if (animFrameId) {
      cancelAnimationFrame(animFrameId);
      animFrameId = null;
    }
  }

  function initAudioContext() {
    if (!audioCtx) {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (AudioCtx) audioCtx = new AudioCtx();
    }
    if (audioCtx && audioCtx.state === 'suspended') {
      audioCtx.resume();
    }
  }

  // Draw realistic waveform on canvas
  function drawWaveform(canvasId, peaks, colorHex, glowHex) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const width = canvas.offsetWidth || 800;
    const height = canvas.offsetHeight || 90;
    
    canvas.width = width * window.devicePixelRatio || 800;
    canvas.height = height * window.devicePixelRatio || 90;
    ctx.scale(window.devicePixelRatio || 1, window.devicePixelRatio || 1);

    ctx.clearRect(0, 0, width, height);

    // Background grid line
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, height / 2);
    ctx.lineTo(width, height / 2);
    ctx.stroke();

    const barWidth = 3;
    const barGap = 1.5;
    const totalBars = Math.floor(width / (barWidth + barGap));
    const centerY = height / 2;

    ctx.fillStyle = colorHex;
    ctx.shadowColor = glowHex || colorHex;
    ctx.shadowBlur = 6;

    for (let i = 0; i < totalBars; i++) {
      let amp = 0.25;
      if (peaks && peaks.length > 0) {
        const peakIdx = Math.floor((i / totalBars) * peaks.length);
        amp = peaks[peakIdx] || 0.15;
      } else {
        // Fallback natural wave shape
        amp = 0.2 + 0.6 * Math.abs(Math.sin(i * 0.07) * Math.cos(i * 0.03));
      }

      const barHeight = Math.max(4, amp * (height * 0.85));
      const x = i * (barWidth + barGap);
      const y = centerY - barHeight / 2;

      // Rounded rect bar
      ctx.beginPath();
      ctx.roundRect(x, y, barWidth, barHeight, 1.5);
      ctx.fill();
    }
    ctx.shadowBlur = 0;
  }

  // Fetch audio peaks for authentic visual waveform
  async function generateWaveformPeaks(audioUrl) {
    try {
      initAudioContext();
      const response = await fetch(audioUrl);
      const arrayBuffer = await response.arrayBuffer();
      const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
      const rawData = audioBuffer.getChannelData(0);
      const samples = 200;
      const blockSize = Math.floor(rawData.length / samples);
      const peaks = [];

      for (let i = 0; i < samples; i++) {
        let blockStart = blockSize * i;
        let sum = 0;
        for (let j = 0; j < blockSize; j += 10) {
          sum += Math.abs(rawData[blockStart + j] || 0);
        }
        peaks.push(Math.min(1.0, (sum / (blockSize / 10)) * 2.2));
      }
      return peaks;
    } catch (e) {
      console.warn('Could not extract waveform peaks via WebAudio:', e);
      return null;
    }
  }

  // UI Setup & Bindings
  function setupUI() {
    const dropzone = document.getElementById('vrDropzone');
    const fileInput = document.getElementById('vrFileInput');
    const selectBtn = document.getElementById('vrSelectFileBtn');

    if (selectBtn && fileInput) {
      selectBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        fileInput.click();
      });
    }

    if (dropzone && fileInput) {
      dropzone.addEventListener('click', () => fileInput.click());

      dropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropzone.classList.add('dragover');
      });

      ['dragleave', 'dragend'].forEach(ev => {
        dropzone.addEventListener(ev, () => dropzone.classList.remove('dragover'));
      });

      dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]) {
          uploadAndProcess(e.dataTransfer.files[0]);
        }
      });

      fileInput.addEventListener('change', () => {
        if (fileInput.files && fileInput.files[0]) {
          uploadAndProcess(fileInput.files[0]);
        }
      });
    }

    // Model selection buttons (2 vs 4 stems)
    document.querySelectorAll('.vr-model-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.vr-model-btn').forEach(b => {
          b.classList.remove('active');
          const ind = b.querySelector('.vr-btn-indicator');
          if (ind) ind.textContent = '○';
        });
        btn.classList.add('active');
        const ind = btn.querySelector('.vr-btn-indicator');
        if (ind) ind.textContent = '●';
        selectedModel = parseInt(btn.dataset.model || '1', 10);
      });
    });

    // Master transport buttons
    const playBtn = document.getElementById('vrBtnPlayPause');
    if (playBtn) {
      playBtn.addEventListener('click', () => {
        if (isPlaying) pauseAudio();
        else playAudio();
      });
    }

    const stopBtn = document.getElementById('vrBtnStop');
    if (stopBtn) stopBtn.addEventListener('click', stopAudio);

    const rewBtn = document.getElementById('vrBtnRewind');
    if (rewBtn) rewBtn.addEventListener('click', () => seekTo(0));

    const loopBtn = document.getElementById('vrBtnLoop');
    if (loopBtn) {
      loopBtn.addEventListener('click', () => {
        isLooping = !isLooping;
        loopBtn.classList.toggle('active', isLooping);
      });
    }

    // Master volume
    const masterVolSlider = document.getElementById('vrMasterVolume');
    const masterVolVal = document.getElementById('vrMasterVolVal');
    if (masterVolSlider) {
      masterVolSlider.addEventListener('input', () => {
        masterVol = parseInt(masterVolSlider.value, 10) / 100;
        if (masterVolVal) masterVolVal.textContent = `${masterVolSlider.value}%`;
        applyVolumeLevels();
      });
    }

    // Track 1: Music / Playback
    const volMusicSlider = document.getElementById('vrVolMusic');
    const volMusicVal = document.getElementById('vrVolMusicVal');
    if (volMusicSlider) {
      volMusicSlider.addEventListener('input', () => {
        volMusic = parseInt(volMusicSlider.value, 10) / 100;
        if (volMusicVal) volMusicVal.textContent = `${volMusicSlider.value}%`;
        applyVolumeLevels();
      });
    }

    const btnMuteMusic = document.getElementById('vrBtnMuteMusic');
    if (btnMuteMusic) {
      btnMuteMusic.addEventListener('click', () => {
        muteMusic = !muteMusic;
        btnMuteMusic.classList.toggle('active', muteMusic);
        applyVolumeLevels();
      });
    }

    const btnSoloMusic = document.getElementById('vrBtnSoloMusic');
    if (btnSoloMusic) {
      btnSoloMusic.addEventListener('click', () => {
        soloMusic = !soloMusic;
        btnSoloMusic.classList.toggle('active', soloMusic);
        if (soloMusic && soloVocal) {
          soloVocal = false;
          const sv = document.getElementById('vrBtnSoloVocal');
          if (sv) sv.classList.remove('active');
        }
        applyVolumeLevels();
      });
    }

    // Track 2: Vocals
    const volVocalSlider = document.getElementById('vrVolVocal');
    const volVocalVal = document.getElementById('vrVolVocalVal');
    if (volVocalSlider) {
      volVocalSlider.addEventListener('input', () => {
        volVocal = parseInt(volVocalSlider.value, 10) / 100;
        if (volVocalVal) volVocalVal.textContent = `${volVocalSlider.value}%`;
        applyVolumeLevels();
      });
    }

    const btnMuteVocal = document.getElementById('vrBtnMuteVocal');
    if (btnMuteVocal) {
      btnMuteVocal.addEventListener('click', () => {
        muteVocal = !muteVocal;
        btnMuteVocal.classList.toggle('active', muteVocal);
        applyVolumeLevels();
      });
    }

    const btnSoloVocal = document.getElementById('vrBtnSoloVocal');
    if (btnSoloVocal) {
      btnSoloVocal.addEventListener('click', () => {
        soloVocal = !soloVocal;
        btnSoloVocal.classList.toggle('active', soloVocal);
        if (soloVocal && soloMusic) {
          soloMusic = false;
          const sm = document.getElementById('vrBtnSoloMusic');
          if (sm) sm.classList.remove('active');
        }
        applyVolumeLevels();
      });
    }

    // Waveform click seeking
    ['vrCanvasMusic', 'vrCanvasVocal'].forEach(id => {
      const cvs = document.getElementById(id);
      if (cvs) {
        cvs.addEventListener('click', (e) => {
          if (!duration || duration <= 0) return;
          const rect = cvs.getBoundingClientRect();
          const clickX = e.clientX - rect.left;
          const pct = Math.max(0, Math.min(1, clickX / rect.width));
          seekTo(pct * duration);
        });
      }
    });

    // Reset / Process another audio / Cancel
    const newAudioBtn = document.getElementById('vrNewAudioBtn');
    if (newAudioBtn) {
      newAudioBtn.addEventListener('click', resetToUpload);
    }
    const cancelProgressBtn = document.getElementById('vrCancelProgressBtn');
    if (cancelProgressBtn) {
      cancelProgressBtn.addEventListener('click', resetToUpload);
    }

    // STAGEPROMPTER BRIDGE BUTTON
    const bridgeBtn = document.getElementById('vrOpenInStagePrompterBtn');
    if (bridgeBtn) {
      bridgeBtn.addEventListener('click', bridgeToStagePrompter);
    }

    // Spacebar hotkey
    window.addEventListener('keydown', (e) => {
      const vrScreen = document.getElementById('vocalRemoverScreen');
      if (vrScreen && vrScreen.classList.contains('active')) {
        if (e.code === 'Space' && e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') {
          e.preventDefault();
          if (isPlaying) pauseAudio();
          else playAudio();
        }
      }
    });

    // Redraw waveforms on window resize
    window.addEventListener('resize', () => {
      if (currentTask) {
        drawWaveform('vrCanvasMusic', peaksMusic, '#10b981', 'rgba(16, 185, 129, 0.4)');
        drawWaveform('vrCanvasVocal', peaksVocal, '#8b5cf6', 'rgba(139, 92, 246, 0.4)');
      }
    });

    // Load recent tasks on init
    loadRecentTasks();
  }

  // Upload file and start separation
  async function uploadAndProcess(file) {
    if (!file) return;

    // Show Progress Screen
    showVrSection('vrProgressSection');
    const pTitle = document.getElementById('vrProgressTitle');
    const pFile = document.getElementById('vrProgressFilename');
    const pBar = document.getElementById('vrProgressBar');
    const pStat = document.getElementById('vrProgressStatusText');
    const pPct = document.getElementById('vrProgressPercent');

    if (pTitle) pTitle.textContent = 'Enviando áudio para processamento...';
    if (pFile) pFile.textContent = file.name;
    if (pBar) pBar.style.width = '10%';
    if (pStat) pStat.textContent = 'Enviando arquivo para o servidor local...';
    if (pPct) pPct.textContent = '10%';

    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('model', selectedModel);

      const res = await fetch(API_BASE + '/split/tracks', {
        method: 'POST',
        body: formData
      });

      if (!res.ok) throw new Error('Falha no upload do áudio');
      const data = await res.json();
      const taskId = data.id;

      if (pTitle) pTitle.textContent = 'Separando Voz e Playback com IA Demucs...';
      pollTaskStatus(taskId, file.name);

    } catch (err) {
      console.error('Erro na separação:', err);
      alert('Erro ao enviar áudio: ' + err.message);
      resetToUpload();
    }
  }

  // Poll separation task
  function pollTaskStatus(taskId, originalFilename) {
    if (pollInterval) clearInterval(pollInterval);

    const pBar = document.getElementById('vrProgressBar');
    const pStat = document.getElementById('vrProgressStatusText');
    const pPct = document.getElementById('vrProgressPercent');

    let currentPct = 15;

    pollInterval = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/split/status/${taskId}`);
        if (!res.ok) return;
        const task = await res.json();

        if (task.status === 'ready') {
          clearInterval(pollInterval);
          pollInterval = null;
          if (pBar) pBar.style.width = '100%';
          if (pPct) pPct.textContent = '100%';
          if (pStat) pStat.textContent = 'Processamento concluído com sucesso!';

          setTimeout(() => {
            loadTaskIntoMixer({
              id: taskId,
              key: task.key || 'stem',
              filename: originalFilename || task.filename || 'Audio',
              bpm: task.bpm || 120,
              tonality: task.tonality || 'C',
              instrumental_url: `${API_BASE}/split/listen/music/${taskId}/${task.key || 'stem'}`,
              vocal_url: `${API_BASE}/split/listen/vocal/${taskId}/${task.key || 'stem'}`
            });
            loadRecentTasks();
          }, 600);

        } else if (task.status === 'error') {
          clearInterval(pollInterval);
          pollInterval = null;
          alert('Erro no processamento da IA: ' + (task.message || 'Falha ao separar stems'));
          resetToUpload();
        } else {
          // Progress simulation / real progress
          if (task.progress && task.progress > currentPct) {
            currentPct = task.progress;
          } else {
            currentPct = Math.min(92, currentPct + 3);
          }
          if (pBar) pBar.style.width = `${currentPct}%`;
          if (pPct) pPct.textContent = `${currentPct}%`;

          if (currentPct < 30) {
            if (pStat) pStat.textContent = 'Carregando tensores e pesos do Demucs v4...';
          } else if (currentPct < 60) {
            if (pStat) pStat.textContent = 'Isolando frequências vocais e transientes musicais...';
          } else if (currentPct < 85) {
            if (pStat) pStat.textContent = 'Renderizando faixas estéreo de alta fidelidade...';
          } else {
            if (pStat) pStat.textContent = 'Finalizando master e gerando waveforms...';
          }
        }
      } catch (e) {
        console.warn('Polling error:', e);
      }
    }, 1000);
  }

  // Load task into the multi-track studio mixer
  async function loadTaskIntoMixer(task) {
    currentTask = task;
    initAudioElements();
    stopAudio();

    // Set audio sources
    const instUrl = task.instrumental_url;
    const vocUrl = task.vocal_url;

    audioMusic.src = instUrl;
    audioVocal.src = vocUrl;
    audioMusic.load();
    audioVocal.load();

    // Metadata
    const mTitle = document.getElementById('vrMixerTitle');
    const tBpm = document.getElementById('vrTagBpm');
    const tKey = document.getElementById('vrTagKey');
    const tModel = document.getElementById('vrTagModel');

    if (mTitle) mTitle.textContent = cleanTitle(task.filename);
    if (tBpm) tBpm.textContent = `⚡ ${task.bpm || 120} BPM`;
    if (tKey) tKey.textContent = `🎼 Tom: ${task.tonality || 'C'}`;
    if (tModel) tModel.textContent = `🎛️ IA Demucs v4`;

    // Download Links
    const dlMusicMp3 = document.getElementById('vrDlMusicMp3');
    const dlMusicWav = document.getElementById('vrDlMusicWav');
    const dlVocalMp3 = document.getElementById('vrDlVocalMp3');
    const dlVocalWav = document.getElementById('vrDlVocalWav');

    if (dlMusicMp3) dlMusicMp3.href = `${instUrl}?codec=mp3`;
    if (dlMusicWav) dlMusicWav.href = `${instUrl}?download=1`;
    if (dlVocalMp3) dlVocalMp3.href = `${vocUrl}?codec=mp3`;
    if (dlVocalWav) dlVocalWav.href = `${vocUrl}?download=1`;

    applyVolumeLevels();
    showVrSection('vrMixerSection');

    // Draw initial waveforms
    drawWaveform('vrCanvasMusic', null, '#10b981', 'rgba(16, 185, 129, 0.4)');
    drawWaveform('vrCanvasVocal', null, '#8b5cf6', 'rgba(139, 92, 246, 0.4)');

    // Extract genuine peaks in background for studio visual perfection
    generateWaveformPeaks(instUrl).then(p => {
      peaksMusic = p;
      drawWaveform('vrCanvasMusic', peaksMusic, '#10b981', 'rgba(16, 185, 129, 0.4)');
    });
    generateWaveformPeaks(vocUrl).then(p => {
      peaksVocal = p;
      drawWaveform('vrCanvasVocal', peaksVocal, '#8b5cf6', 'rgba(139, 92, 246, 0.4)');
    });
  }

  function cleanTitle(raw) {
    if (!raw) return 'Áudio sem título';
    return raw.replace(/\.[a-zA-Z0-9]+$/, '').replace(/_/g, ' ');
  }

  // BRIDGE TO STAGEPROMPTER
  async function bridgeToStagePrompter() {
    if (!currentTask) return;
    pauseAudio();

    const titleFull = cleanTitle(currentTask.filename);
    let artist = '';
    let track = titleFull;

    // Detect "Artist - Track" or "Track"
    if (titleFull.includes(' - ')) {
      const parts = titleFull.split(' - ');
      artist = parts[0].trim();
      track = parts.slice(1).join(' - ').trim();
    }

    const bridgeBtn = document.getElementById('vrOpenInStagePrompterBtn');
    if (bridgeBtn) {
      bridgeBtn.innerHTML = `<span>⏳ Abrindo no tunemusic...</span>`;
    }

    try {
      // 1. Save or add to Repertoire
      if (window.api && typeof window.api.readRepertorio === 'function') {
        const rep = await window.api.readRepertorio();
        const shows = rep.shows || [];
        let activeShow = shows.find(s => s.id === rep.activeShowId) || shows[0];

        if (!activeShow) {
          activeShow = {
            id: 'show_' + Date.now(),
            nome: 'Show Principal',
            blocos: [{ nome: 'Bloco 1', musicas: [] }]
          };
          shows.push(activeShow);
          rep.activeShowId = activeShow.id;
        }

        if (!activeShow.blocos || activeShow.blocos.length === 0) {
          activeShow.blocos = [{ nome: 'Bloco 1', musicas: [] }];
        }

        const targetBloco = activeShow.blocos[0];
        const newSongItem = {
          track: track,
          artist: artist,
          audioUrl: currentTask.instrumental_url,
          audioPath: currentTask.instrumental_url,
          bpm: currentTask.bpm || 120,
          key: currentTask.tonality || 'C',
          tocada: false
        };

        targetBloco.musicas.push(newSongItem);
        rep.shows = shows;
        await window.api.writeRepertorio(rep);
      }

      // 2. Fetch lyrics and open in StagePrompter
      if (window.api && typeof window.api.searchSongsFallback === 'function') {
        const results = await window.api.searchSongsFallback(`${artist} ${track}`.trim());
        if (results && results.length > 0) {
          const first = results[0];
          // Open search screen or trigger pick
          if (typeof window.showScreen === 'function') {
            window.showScreen('searchScreen');
            const searchInp = document.getElementById('searchInput');
            if (searchInp) {
              searchInp.value = `${artist} ${track}`.trim();
              searchInp.dispatchEvent(new Event('input'));
            }
          }
          return;
        }
      }

      // Fallback: switch directly to Repertoire or Live Show
      if (typeof window.showScreen === 'function') {
        window.showScreen('repertoireScreen');
      }

    } catch (e) {
      console.error('Error bridging to StagePrompter:', e);
      if (typeof window.showScreen === 'function') {
        window.showScreen('repertoireScreen');
      }
    } finally {
      if (bridgeBtn) {
        bridgeBtn.innerHTML = `
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
            <polygon points="6 3 20 12 6 21 6 3"/>
          </svg>
          <span>Abrir este Playback no tunemusic ➔</span>
        `;
      }
    }
  }

  // Load recent tasks from server
  async function loadRecentTasks() {
    const listEl = document.getElementById('vrRecentList');
    const countEl = document.getElementById('vrRecentCount');
    if (!listEl) return;

    try {
      const res = await fetch(`${API_BASE}/api/stageprompter/vocal-tasks`);
      if (!res.ok) throw new Error('API off');
      const tasks = await res.json();

      if (!tasks || tasks.length === 0) {
        listEl.innerHTML = `<div class="vr-recent-empty">Nenhum áudio processado ainda. Arraste uma música acima para começar!</div>`;
        if (countEl) countEl.textContent = '0 faixas';
        return;
      }

      if (countEl) countEl.textContent = `${tasks.length} ${tasks.length === 1 ? 'faixa' : 'faixas'}`;
      listEl.innerHTML = '';

      tasks.forEach(t => {
        const card = document.createElement('div');
        card.className = 'vr-recent-card';
        card.innerHTML = `
          <div class="vr-rc-icon">🎵</div>
          <div class="vr-rc-info">
            <div class="vr-rc-title">${cleanTitle(t.filename)}</div>
            <div class="vr-rc-sub">${t.bpm || 120} BPM • Tom: ${t.tonality || 'C'}</div>
          </div>
          <div class="vr-rc-actions">
            <button type="button" class="vr-rc-btn btn-mix" title="Abrir no Mixer">▶ Carregar no Mixer</button>
            <button type="button" class="vr-rc-btn btn-tp" title="Abrir no tunemusic">📺 Usar no TP</button>
          </div>
        `;

        card.querySelector('.btn-mix').addEventListener('click', () => loadTaskIntoMixer(t));
        card.querySelector('.btn-tp').addEventListener('click', () => {
          loadTaskIntoMixer(t);
          bridgeToStagePrompter();
        });

        listEl.appendChild(card);
      });

    } catch (e) {
      listEl.innerHTML = `<div class="vr-recent-empty">Faixas prontas serão listadas aqui.</div>`;
    }
  }

  function showVrSection(sectionId) {
    ['vrUploadSection', 'vrProgressSection', 'vrMixerSection'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.classList.toggle('hidden', id !== sectionId);
    });
  }

  function resetToUpload() {
    if (pollInterval) {
      clearInterval(pollInterval);
      pollInterval = null;
    }
    stopAudio();
    currentTask = null;
    showVrSection('vrUploadSection');
    const fi = document.getElementById('vrFileInput');
    if (fi) fi.value = '';
    const pBar = document.getElementById('vrProgressBar');
    if (pBar) pBar.style.width = '0%';
    const pPct = document.getElementById('vrProgressPercent');
    if (pPct) pPct.textContent = '0%';
    loadRecentTasks();
  }

  // Global hooks
  window.vocalRemoverStudio = {
    loadTaskIntoMixer,
    resetToUpload,
    loadRecentTasks
  };

  // Run on DOM Ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setupUI);
  } else {
    setupUI();
  }

})();
