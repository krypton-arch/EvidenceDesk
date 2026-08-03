importScripts('config.js');
let companionCapturesThisSession = 0;
let companionLastEventAt = null;

async function getCompanionStatus() {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 2500);
    const response = await fetch(CONFIG.API_BASE_URL + '/api/feed', { signal: controller.signal });
    clearTimeout(timeout);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return {
      connected: true,
      capturesThisSession: companionCapturesThisSession,
      lastEventAt: companionLastEventAt,
    };
  } catch (error) {
    return { connected: false, capturesThisSession: companionCapturesThisSession, lastEventAt: companionLastEventAt };
  }
}

function deliverCapture(payload) {
  fetch(CONFIG.API_BASE_URL + '/api/capture', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    companionCapturesThisSession++;
    companionLastEventAt = Date.now();
  }).catch((error) => {
    console.warn('[Bias Auditor BG] Capture delivery failed:', error);
  });
}

chrome.runtime.onInstalled.addListener((details) => {
  console.log('[Bias Auditor BG] Extension installed/updated:', details.reason);
});

// Deliberately fire-and-forget: content scripts do not wait for Google News
// enrichment, so no runtime response channel can be left open on navigation.
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'capture' && message.payload) deliverCapture(message.payload);
  if (message.type === 'companion-status') {
    getCompanionStatus().then(sendResponse);
    return true;
  }
});
