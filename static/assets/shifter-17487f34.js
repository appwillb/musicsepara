self.onmessage = function (e) {
  if (e.data && e.data.command === 'start') {
    self.postMessage({
      command: 'done',
      arrayPCM: e.data.arrayPCM
    });
  }
};
