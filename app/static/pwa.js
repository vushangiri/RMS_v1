'use strict';

let rmsInstallPrompt = null;

function syncInstallButton() {
  const installed = window.matchMedia('(display-mode: standalone)').matches;
  for (const button of document.querySelectorAll('[data-install-rms]')) {
    button.hidden = !rmsInstallPrompt || installed;
  }
}

window.addEventListener('beforeinstallprompt', event => {
  event.preventDefault();
  rmsInstallPrompt = event;
  syncInstallButton();
});

document.addEventListener('DOMContentLoaded', syncInstallButton);
document.addEventListener('htmx:afterSwap', syncInstallButton);
window.addEventListener('appinstalled', () => {
  rmsInstallPrompt = null;
  syncInstallButton();
});

document.addEventListener('click', async event => {
  if (!rmsInstallPrompt || !event.target.closest('[data-install-rms]')) return;
  const prompt = rmsInstallPrompt;
  rmsInstallPrompt = null;
  syncInstallButton();
  try {
    await prompt.prompt();
  } catch {
    // The browser menu remains available if the native prompt cannot open.
  }
});

if (window.isSecureContext && 'serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}
