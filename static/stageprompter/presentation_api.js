// StagePrompter Presentation Screen Web Bridge
(function() {
  'use strict';

  console.log('[StagePrompter] Presentation Screen Bridge initialized.');

  const syncChannel = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('stageprompter_sync') : null;
  let updateCallback = null;

  window.api = {
    onPresentationUpdate: (callback) => {
      updateCallback = callback;

      // 1. Listen on BroadcastChannel
      if (syncChannel) {
        syncChannel.addEventListener('message', (event) => {
          if (event.data && event.data.type === 'update' && event.data.state) {
            callback(event.data.state);
          }
        });
      }

      // 2. Listen on window message (iframe preview or direct window.postMessage)
      window.addEventListener('message', (event) => {
        if (event.data && event.data.__spPreviewState) {
          callback(event.data.__spPreviewState);
        }
      });

      // 3. Listen on localStorage change (cross-tab fallback)
      window.addEventListener('storage', (event) => {
        if (event.key === '__sp_presentation_state' && event.newValue) {
          try {
            callback(JSON.parse(event.newValue));
          } catch (e) {}
        }
      });

      // 4. Initial state load if available
      try {
        const stored = localStorage.getItem('__sp_presentation_state');
        if (stored) {
          const parsed = JSON.parse(stored);
          setTimeout(() => callback(parsed), 50);
        }
      } catch (e) {}
    },

    sendPresentationKey: (key) => {
      if (syncChannel) {
        syncChannel.postMessage({ type: 'key', key: key });
      }
      if (window.opener && !window.opener.closed) {
        window.opener.postMessage({ __spPresentationKey: key }, '*');
      }
    },

    sendStopwatchBox: (box) => {
      if (syncChannel) {
        syncChannel.postMessage({ type: 'stopwatchBox', box: box });
      }
    }
  };

  // Forward keyboard events (foot pedals, space, arrows) back to operator console
  window.addEventListener('keydown', (e) => {
    const validKeys = [' ', 'Space', 'ArrowRight', 'ArrowLeft', 'ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'p', 'P', 'r', 'R'];
    if (validKeys.includes(e.key) || validKeys.includes(e.code)) {
      window.api.sendPresentationKey(e.key);
    }
    if (e.key === 'F11') {
      e.preventDefault();
      if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen().catch(() => {});
      } else {
        document.exitFullscreen().catch(() => {});
      }
    }
  });

  // Double click toggles fullscreen
  window.addEventListener('dblclick', () => {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(() => {});
    } else {
      document.exitFullscreen().catch(() => {});
    }
  });
})();
