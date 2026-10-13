self.onmessage = function (e) {
  if (e.data && e.data.command === 'start') {
    try {
      const sampleRate = e.data.sampleRate || 44100;
      const arrayPCM = e.data.arrayPCM;
      const numChannels = arrayPCM.length;
      const numSamples = arrayPCM[0].length;
      const bytesPerSample = 2;
      const blockAlign = numChannels * bytesPerSample;
      const byteRate = sampleRate * blockAlign;
      const dataSize = numSamples * blockAlign;
      const buffer = new ArrayBuffer(44 + dataSize);
      const view = new DataView(buffer);

      function writeString(offset, string) {
        for (let i = 0; i < string.length; i++) {
          view.setUint8(offset + i, string.charCodeAt(i));
        }
      }

      writeString(0, 'RIFF');
      view.setUint32(4, 36 + dataSize, true);
      writeString(8, 'WAVE');
      writeString(12, 'fmt ');
      view.setUint32(16, 16, true);
      view.setUint16(20, 1, true); // PCM
      view.setUint16(22, numChannels, true);
      view.setUint32(24, sampleRate, true);
      view.setUint32(28, byteRate, true);
      view.setUint16(32, blockAlign, true);
      view.setUint16(34, 16, true);
      writeString(36, 'data');
      view.setUint32(40, dataSize, true);

      let offset = 44;
      for (let i = 0; i < numSamples; i++) {
        for (let ch = 0; ch < numChannels; ch++) {
          let s = arrayPCM[ch][i];
          s = s < -1 ? -1 : (s > 1 ? 1 : s);
          view.setInt16(offset, s < 0 ? s * 32768 : s * 32767, true);
          offset += 2;
        }
        if (i % 100000 === 0) {
          self.postMessage({ command: 'progress', value: i / numSamples });
        }
      }

      const blob = new Blob([buffer], { type: 'audio/wav' });
      self.postMessage({ command: 'done', blob: blob });
    } catch (err) {
      console.error('Wav encoder error:', err);
      self.postMessage({ command: 'error', message: err.message });
    }
  }
};
