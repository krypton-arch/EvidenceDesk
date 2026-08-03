const DB_NAME = 'SocialBiasDB';
const DB_VERSION = 1;
const STORE_NAME = 'biasScores';
const DEBUG = true; // Set to true for now so we can verify in console
const EXTENSION_BUILD = '1.3.0';

if (DEBUG) console.info(`[BiasAuditor] Content script loaded (v${EXTENSION_BUILD})`);

// EMA parameters
// alpha: Smoothing factor (0-1). Higher = more weight on recent items.
//   Raising alpha makes the score react faster to new data but more volatile.
//   Lowering alpha makes it smoother but slower to respond.
const ALPHA = 0.2;
// A score is calculated once per matched tweet. Multiple links and the author
// are evidence about that one exposure, not independent feed items.
const MIN_SAMPLES_FOR_LABEL = 5;
const RIGIDITY_STATE_KEY = 'rigidityStateV2';
const RECENT_OBSERVATIONS_LIMIT = 25;
const COMPANION_STATUS_INTERVAL_MS = 10000;

// Handle weight factor: author handle scores count at this fraction
// of a direct link score. This prevents double-counting when a tweet
// is both from a partisan account AND links to a partisan domain.
const HANDLE_WEIGHT = 0.5;

// Known URL shortener domains that should be skipped during bias resolution.
// t.co is handled separately above (innerText parsing), but these others
// cannot be resolved from a content script due to CORS restrictions.
const KNOWN_SHORTENERS = new Set([
  'bit.ly', 'tinyurl.com', 'ow.ly', 'goo.gl', 'buff.ly',
  'is.gd', 'v.gd', 'shorturl.at', 'rb.gy', 'cutt.ly',
  'lnkd.in', 'amzn.to', 'youtu.be',
]);

// ── Data Loading ────────────────────────────────────────────────────────────

let fullBiasData = null;
let dataLoadPromise = null;

function hasExtensionContext() {
  try {
    return typeof chrome !== 'undefined' && Boolean(chrome.runtime && chrome.runtime.id);
  } catch (error) {
    return false;
  }
}

function getBiasScore(domain) {
  return new Promise((resolve) => {
    if (fullBiasData) {
      resolve(fullBiasData[domain] || null);
      return;
    }

    if (!dataLoadPromise) {
      if (!hasExtensionContext()) {
        resolve(null);
        return;
      }
      let dataUrl;
      try {
        dataUrl = chrome.runtime.getURL('bias_data.json');
      } catch (error) {
        resolve(null);
        return;
      }
      dataLoadPromise = fetch(dataUrl)
        .then(res => res.json())
        .then(data => {
          fullBiasData = data;
          if (DEBUG) console.log('[BiasAuditor] Loaded bias data into memory, entries:', Object.keys(data).length);
        })
        .catch(e => {
          if (DEBUG) console.error('[BiasAuditor] Failed to load bias data:', e);
        });
    }

    dataLoadPromise.then(() => {
      resolve(fullBiasData ? (fullBiasData[domain] || null) : null);
    });
  });
}

// ── Domain Normalization ────────────────────────────────────────────────────

function normalizeDomain(hostname) {
  // Strip www. prefix
  let domain = hostname.replace(/^www\./, '');
  // Try full domain without TLD: e.g. "nytimes.com" -> "nytimes"
  // Handle multi-part TLDs: "bbc.co.uk" -> "bbc"
  const parts = domain.split('.');
  if (parts.length >= 2) {
    // Check common multi-part TLDs
    const lastTwo = parts.slice(-2).join('.');
    if (['co.uk', 'com.au', 'co.nz', 'co.za', 'co.in'].includes(lastTwo)) {
      return parts.slice(0, -2).join('').toLowerCase().replace(/[^a-z0-9]/g, '');
    }
  }
  // Default: take everything before the last dot
  return parts.slice(0, -1).join('').toLowerCase().replace(/[^a-z0-9]/g, '');
}

async function tryMultipleKeys(hostname) {
  const stripped = hostname.replace(/^www\./, '');
  const parts = stripped.split('.');

  // Strategy 1: Full domain without TLD via normalizeDomain
  const key1 = normalizeDomain(hostname);
  if (key1) {
    const result1 = await getBiasScore(key1);
    if (result1 !== null) return result1;
  }

  // Strategy 2: Full domain joined (e.g. "nytimescom")
  const key2 = parts.join('').toLowerCase().replace(/[^a-z0-9]/g, '');
  if (key2 && key2 !== key1) {
    const result2 = await getBiasScore(key2);
    if (result2 !== null) return result2;
  }

  // Strategy 3: Just the second-level domain (e.g. for "news.bbc.co.uk" -> "bbc")
  if (parts.length > 2) {
    const lastTwo = parts.slice(-2).join('.');
    let key3;
    if (['co.uk', 'com.au', 'co.nz', 'co.za', 'co.in'].includes(lastTwo)) {
      // e.g. news.bbc.co.uk -> parts[-3] = "bbc"
      if (parts.length >= 3) {
        key3 = parts[parts.length - 3].toLowerCase().replace(/[^a-z0-9]/g, '');
      }
    } else {
      // e.g. news.nytimes.com -> parts[-2] = "nytimes"
      key3 = parts[parts.length - 2].toLowerCase().replace(/[^a-z0-9]/g, '');
    }
    if (key3 && key3 !== key1 && key3 !== key2) {
      const result3 = await getBiasScore(key3);
      if (result3 !== null) return result3;
    }
  }

  return null;
}

// ── EMA-based Rigidity Score ────────────────────────────────────────────────

let mu_t = 0;      // EMA of bias scores
let sigma2_t = 0;   // EMA of variance
let sampleCount = 0;
let stateSaveTimer = null;
let recentObservations = [];
let companionStatusTimer = null;

function observationBucket(score) {
  if (score < -0.3) return 'left';
  if (score > 0.3) return 'right';
  return 'center';
}

function recordObservation(score) {
  recentObservations.push({ score, at: Date.now() });
  if (recentObservations.length > RECENT_OBSERVATIONS_LIMIT) {
    recentObservations = recentObservations.slice(-RECENT_OBSERVATIONS_LIMIT);
  }
}

function updateRigidityScore(score, confidence) {
  sampleCount++;
  // Confidence-weighted alpha: low-confidence sources nudge less
  const alpha_eff = ALPHA * confidence;

  if (sampleCount === 1) {
    mu_t = score;
    sigma2_t = 0;
  } else {
    const delta = score - mu_t;
    mu_t = alpha_eff * score + (1 - alpha_eff) * mu_t;
    sigma2_t = (1 - alpha_eff) * (sigma2_t + alpha_eff * delta * delta);
  }

  // Diversity = min(1, sigma2_t), clamped to [0, 1].
  // When variance is ~0 (echo chamber): returns 0 → "Echo Chamber"
  // When variance is high (diverse feed): returns 1 → "Diverse"
  // This is a linear mapping of score variance. The original exponential
  // form R_t = 1 - exp(-λσ²) was considered but the linear version provides
  // adequate separation for typical social-media exposure distributions.
  return 1 - Math.min(1, Math.max(0, sigma2_t));
}

function saveRigidityState() {
  clearTimeout(stateSaveTimer);
  stateSaveTimer = setTimeout(() => {
    if (!hasExtensionContext()) return;
    try {
      const save = chrome.storage.local.set({
        [RIGIDITY_STATE_KEY]: {
          mu_t, sigma2_t, sampleCount,
          totalLinksMatched, totalHandlesMatched, totalTweetsScanned,
          leftCount, centerCount, rightCount,
          recentObservations,
        }
      });
      if (save && typeof save.catch === 'function') save.catch(() => {});
    } catch (error) { /* Extension was reloaded while this page was open. */ }
  }, 500);
}

async function restoreRigidityState() {
  if (!hasExtensionContext()) return;
  let stored;
  try {
    stored = await chrome.storage.local.get(RIGIDITY_STATE_KEY);
  } catch (error) {
    return;
  }
  const state = stored[RIGIDITY_STATE_KEY];
  if (!state || !Number.isFinite(state.mu_t) || !Number.isFinite(state.sigma2_t)) return;

  mu_t = state.mu_t;
  sigma2_t = Math.min(1, Math.max(0, state.sigma2_t));
  sampleCount = Number.isSafeInteger(state.sampleCount) ? state.sampleCount : 0;
  totalLinksMatched = Number.isSafeInteger(state.totalLinksMatched) ? state.totalLinksMatched : 0;
  totalHandlesMatched = Number.isSafeInteger(state.totalHandlesMatched) ? state.totalHandlesMatched : 0;
  totalTweetsScanned = Number.isSafeInteger(state.totalTweetsScanned) ? state.totalTweetsScanned : 0;
  leftCount = Number.isSafeInteger(state.leftCount) ? state.leftCount : 0;
  centerCount = Number.isSafeInteger(state.centerCount) ? state.centerCount : 0;
  rightCount = Number.isSafeInteger(state.rightCount) ? state.rightCount : 0;
  recentObservations = Array.isArray(state.recentObservations)
    ? state.recentObservations
      .filter(item => item && Number.isFinite(item.score) && Number.isFinite(item.at))
      .slice(-RECENT_OBSERVATIONS_LIMIT)
    : [];
}

function reportCapture(type, value, score, confidence, sources, tweetText, tweetId) {
  // The page runs on HTTPS, while the local companion uses HTTP. Send via the
  // extension service worker (which has localhost host permission) to avoid
  // page-context mixed-content/private-network restrictions.
  if (!hasExtensionContext()) return;
  try {
    const sent = chrome.runtime.sendMessage({
      type: 'capture',
      payload: {
        type: type,
        value: value,
        score: score,
        confidence: confidence,
        sources: sources || [],
        tweet_text: tweetText || '',
        tweet_id: tweetId || '',
        timestamp: Date.now()
      }
    });
    if (sent && typeof sent.catch === 'function') sent.catch(() => {});
  } catch (error) { /* Extension was reloaded while this page was open. */ }
}

// ── UI Injection (Shadow DOM) ───────────────────────────────────────────────

let dashboardElements = null;

function createDashboard() {
  const host = document.createElement('div');
  host.id = 'social-bias-auditor-host';
  host.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:999999;';

  const shadow = host.attachShadow({ mode: 'closed' });

  const style = document.createElement('style');
  style.textContent = `
    * {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }

    :host {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }

    .dashboard {
      width: 292px;
      background: rgba(18, 18, 24, 0.82);
      backdrop-filter: blur(18px);
      -webkit-backdrop-filter: blur(18px);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 14px;
      overflow: hidden;
      color: #e0e0e0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.45);
      transition: box-shadow 0.3s ease;
    }

    .dashboard:hover {
      box-shadow: 0 10px 40px rgba(0, 0, 0, 0.55);
    }

    .header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 10px 14px;
      cursor: grab;
      user-select: none;
      background: rgba(255, 255, 255, 0.04);
      border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    }

    .header:active {
      cursor: grabbing;
    }

    .header-title {
      font-size: 12px;
      font-weight: 600;
      letter-spacing: 0.5px;
      text-transform: uppercase;
      color: rgba(255, 255, 255, 0.7);
    }

    .toggle-btn {
      background: none;
      border: none;
      color: rgba(255, 255, 255, 0.5);
      cursor: pointer;
      font-size: 12px;
      padding: 2px 6px;
      border-radius: 4px;
      transition: background 0.2s, color 0.2s;
    }

    .toggle-btn:hover {
      background: rgba(255, 255, 255, 0.1);
      color: rgba(255, 255, 255, 0.9);
    }

    .body {
      padding: 16px 14px;
      transition: max-height 0.3s ease, opacity 0.2s ease, padding 0.3s ease;
      max-height: 560px;
      opacity: 1;
      overflow: hidden;
    }

    .body.collapsed {
      max-height: 0;
      opacity: 0;
      padding: 0 14px;
    }

    .score-display {
      margin-bottom: 12px;
    }

    .measurement-kicker {
      color: rgba(255, 255, 255, 0.46);
      font-size: 9px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .score-value {
      font-size: 29px;
      font-weight: 700;
      letter-spacing: -1px;
      transition: color 0.5s ease;
      color: #ef4444;
    }

    .score-label {
      font-size: 12px;
      font-weight: 500;
      margin-top: 2px;
      transition: color 0.5s ease;
      color: #ef4444;
    }

    .evidence-window {
      color: rgba(255, 255, 255, 0.58);
      font-size: 10px;
      line-height: 1.4;
      margin-top: 4px;
    }

    .companion-status {
      align-items: center;
      background: rgba(255, 255, 255, 0.045);
      border-bottom: 1px solid rgba(255, 255, 255, 0.07);
      color: rgba(255, 255, 255, 0.64);
      display: flex;
      font-size: 10px;
      gap: 7px;
      line-height: 1.35;
      padding: 8px 14px;
    }

    .companion-status.is-disconnected { color: #fbbf24; }
    .status-dot { color: #64748b; font-size: 11px; line-height: 1; }
    .companion-status.is-connected .status-dot { color: #34d399; }
    .companion-status.is-disconnected .status-dot { color: #f59e0b; }

    .timeline {
      align-items: end;
      display: flex;
      gap: 3px;
      height: 24px;
      margin: 5px 0 3px;
    }

    .timeline-step {
      background: rgba(148, 163, 184, 0.35);
      border-radius: 2px 2px 0 0;
      flex: 1;
      min-width: 2px;
      transition: height 0.3s ease;
    }

    .timeline-step.left { background: #60a5fa; }
    .timeline-step.center { background: #c084fc; }
    .timeline-step.right { background: #fb7185; }

    .timeline-label {
      color: rgba(255, 255, 255, 0.38);
      display: flex;
      font-size: 9px;
      justify-content: space-between;
    }

    .why-changed {
      border-left: 2px solid rgba(251, 191, 36, 0.72);
      color: rgba(255, 255, 255, 0.66);
      font-size: 10px;
      line-height: 1.4;
      margin: 11px 0 12px;
      padding-left: 8px;
    }

    .stats-row {
      display: flex;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 4px 8px;
      font-size: 11px;
      color: rgba(255, 255, 255, 0.4);
      margin-bottom: 12px;
      padding: 0 2px;
    }

    .breakdown-container {
      margin-top: 4px;
    }

    .breakdown-labels {
      display: flex;
      justify-content: space-between;
      font-size: 10px;
      margin-bottom: 4px;
      color: rgba(255, 255, 255, 0.5);
    }

    .breakdown-bar {
      display: flex;
      height: 6px;
      border-radius: 3px;
      overflow: hidden;
      background: rgba(255, 255, 255, 0.06);
    }

    .bar-left {
      background: #3b82f6;
      transition: width 0.4s ease;
    }

    .bar-center {
      background: #a855f7;
      transition: width 0.4s ease;
    }

    .bar-right {
      background: #ef4444;
      transition: width 0.4s ease;
    }
  `;

  const dashboard = document.createElement('div');
  dashboard.className = 'dashboard';

  const header = document.createElement('div');
  header.className = 'header';

  const headerTitle = document.createElement('span');
  headerTitle.className = 'header-title';
  headerTitle.textContent = 'Feed Rigidity';

  const toggleBtn = document.createElement('button');
  toggleBtn.className = 'toggle-btn';
  toggleBtn.textContent = '▼';

  header.appendChild(headerTitle);
  header.appendChild(toggleBtn);

  const body = document.createElement('div');
  body.className = 'body';

  const companionStatus = document.createElement('div');
  companionStatus.className = 'companion-status';
  const statusDot = document.createElement('span');
  statusDot.className = 'status-dot';
  statusDot.textContent = '●';
  const companionStatusText = document.createElement('span');
  companionStatusText.textContent = 'Checking companion service…';
  companionStatus.appendChild(statusDot);
  companionStatus.appendChild(companionStatusText);

  const scoreDisplay = document.createElement('div');
  scoreDisplay.className = 'score-display';

  const measurementKicker = document.createElement('div');
  measurementKicker.className = 'measurement-kicker';
  measurementKicker.textContent = 'Exposure concentration';

  const scoreValue = document.createElement('div');
  scoreValue.className = 'score-value';
  scoreValue.textContent = '—';

  const scoreLabel = document.createElement('div');
  scoreLabel.className = 'score-label';
  scoreLabel.textContent = 'Collecting evidence';

  const evidenceWindow = document.createElement('div');
  evidenceWindow.className = 'evidence-window';
  evidenceWindow.textContent = 'Over the last 25 matched posts';

  scoreDisplay.appendChild(measurementKicker);
  scoreDisplay.appendChild(scoreValue);
  scoreDisplay.appendChild(scoreLabel);
  scoreDisplay.appendChild(evidenceWindow);

  const statsRow = document.createElement('div');
  statsRow.className = 'stats-row';

  const linksSpan = document.createElement('span');
  linksSpan.textContent = 'Links: 0';

  const handlesSpan = document.createElement('span');
  handlesSpan.textContent = 'Handles: 0';

  const samplesSpan = document.createElement('span');
  samplesSpan.textContent = 'Samples: 0';

  const coverageSpan = document.createElement('span');
  coverageSpan.textContent = 'Coverage: 0/0';

  statsRow.appendChild(linksSpan);
  statsRow.appendChild(handlesSpan);
  statsRow.appendChild(samplesSpan);
  statsRow.appendChild(coverageSpan);

  const breakdownContainer = document.createElement('div');
  breakdownContainer.className = 'breakdown-container';

  const breakdownLabels = document.createElement('div');
  breakdownLabels.className = 'breakdown-labels';

  const leftLabel = document.createElement('span');
  leftLabel.textContent = 'Left';
  const centerLabel = document.createElement('span');
  centerLabel.textContent = 'Center';
  const rightLabel = document.createElement('span');
  rightLabel.textContent = 'Right';

  breakdownLabels.appendChild(leftLabel);
  breakdownLabels.appendChild(centerLabel);
  breakdownLabels.appendChild(rightLabel);

  const breakdownBar = document.createElement('div');
  breakdownBar.className = 'breakdown-bar';

  const barLeft = document.createElement('div');
  barLeft.className = 'bar-left';
  barLeft.style.width = '0%';

  const barCenter = document.createElement('div');
  barCenter.className = 'bar-center';
  barCenter.style.width = '0%';

  const barRight = document.createElement('div');
  barRight.className = 'bar-right';
  barRight.style.width = '0%';

  breakdownBar.appendChild(barLeft);
  breakdownBar.appendChild(barCenter);
  breakdownBar.appendChild(barRight);

  breakdownContainer.appendChild(breakdownLabels);
  breakdownContainer.appendChild(breakdownBar);

  const timeline = document.createElement('div');
  timeline.className = 'timeline';
  timeline.setAttribute('aria-label', 'Rolling matched-post timeline');
  const timelineLabel = document.createElement('div');
  timelineLabel.className = 'timeline-label';
  timelineLabel.innerHTML = '<span>Earlier</span><span>Recent</span>';

  const whyChanged = document.createElement('div');
  whyChanged.className = 'why-changed';
  whyChanged.textContent = 'Collecting enough matched posts to explain changes.';

  body.appendChild(scoreDisplay);
  body.appendChild(statsRow);
  body.appendChild(breakdownContainer);
  body.appendChild(timeline);
  body.appendChild(timelineLabel);
  body.appendChild(whyChanged);

  const dashboardLink = document.createElement('a');
  dashboardLink.href = CONFIG.API_BASE_URL;
  dashboardLink.target = '_blank';
  dashboardLink.textContent = '📊 Open Dashboard';
  dashboardLink.style.cssText = 'display: block; text-align: center; margin-top: 12px; padding: 8px; background: rgba(168, 85, 247, 0.15); border: 1px solid rgba(168, 85, 247, 0.25); border-radius: 8px; color: #a855f7; text-decoration: none; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; transition: background 0.2s;';
  dashboardLink.addEventListener('mouseover', () => dashboardLink.style.background = 'rgba(168, 85, 247, 0.25)');
  dashboardLink.addEventListener('mouseout', () => dashboardLink.style.background = 'rgba(168, 85, 247, 0.15)');
  body.appendChild(dashboardLink);

  dashboard.appendChild(header);
  dashboard.appendChild(companionStatus);
  dashboard.appendChild(body);

  shadow.appendChild(style);
  shadow.appendChild(dashboard);

  document.body.appendChild(host);

  // Cache all element references
  dashboardElements = {
    host,
    shadow,
    dashboard,
    header,
    toggleBtn,
    body,
    scoreValue,
    scoreLabel,
    companionStatus,
    companionStatusText,
    linksSpan,
    handlesSpan,
    samplesSpan,
    coverageSpan,
    leftLabel,
    centerLabel,
    rightLabel,
    barLeft,
    barCenter,
    barRight,
    timeline,
    whyChanged
  };

  // ── Collapse / Expand ───────────────────────────────────────────────────
  let collapsed = false;
  toggleBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    collapsed = !collapsed;
    if (collapsed) {
      body.classList.add('collapsed');
      toggleBtn.textContent = '▲';
    } else {
      body.classList.remove('collapsed');
      toggleBtn.textContent = '▼';
    }
  });

  // ── Dragging ────────────────────────────────────────────────────────────
  let isDragging = false;
  let dragOffsetX = 0;
  let dragOffsetY = 0;

  header.addEventListener('mousedown', (e) => {
    if (e.target === toggleBtn) return;
    isDragging = true;
    const rect = host.getBoundingClientRect();
    dragOffsetX = e.clientX - rect.left;
    dragOffsetY = e.clientY - rect.top;
    e.preventDefault();
  });

  document.addEventListener('mousemove', (e) => {
    if (!isDragging) return;
    host.style.left = (e.clientX - dragOffsetX) + 'px';
    host.style.top = (e.clientY - dragOffsetY) + 'px';
    host.style.right = 'auto';
    host.style.bottom = 'auto';
  });

  document.addEventListener('mouseup', () => {
    isDragging = false;
  });
}

function getRecentEvidence() {
  const observations = recentObservations.slice(-RECENT_OBSERVATIONS_LIMIT);
  const counts = { left: 0, center: 0, right: 0 };
  let mean = 0;
  for (const observation of observations) {
    mean += observation.score;
    counts[observationBucket(observation.score)]++;
  }
  mean /= observations.length || 1;
  const variance = observations.reduce((sum, observation) => sum + Math.pow(observation.score - mean, 2), 0) / (observations.length || 1);
  return { observations, counts, concentration: 1 - Math.min(1, Math.max(0, variance)) };
}

function describeRecentChange(observations) {
  const recent = observations.slice(-5);
  if (!recent.length) return 'Collecting enough matched posts to explain changes.';
  const counts = { left: 0, center: 0, right: 0 };
  recent.forEach(observation => counts[observationBucket(observation.score)]++);
  const [bucket, count] = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
  if (count < 2) return `The last ${recent.length} matched posts were mixed across perspectives.`;
  const wording = bucket === 'center' ? 'center sources' : `${bucket}-leaning sources`;
  return `${count} ${wording} in the last ${recent.length} matched posts.`;
}

function updateDashboardUI() {
  if (!dashboardElements) return;

  const {
    scoreValue, scoreLabel, linksSpan, handlesSpan, samplesSpan, coverageSpan,
    leftLabel, centerLabel, rightLabel, barLeft, barCenter, barRight, timeline, whyChanged
  } = dashboardElements;
  const evidence = getRecentEvidence();
  const concentration = evidence.concentration;
  let label, color;
  if (evidence.observations.length < MIN_SAMPLES_FOR_LABEL) {
    scoreValue.textContent = '—';
    label = `Collecting evidence (${evidence.observations.length}/${MIN_SAMPLES_FOR_LABEL})`;
    color = '#94a3b8';
  } else {
    scoreValue.textContent = `${Math.round(concentration * 100)}% concentration`;
    label = evidence.observations.length >= 15 ? 'strong evidence' : 'moderate evidence';
    color = concentration >= 0.85 ? '#ef4444' : concentration >= 0.65 ? '#f97316' : concentration >= 0.35 ? '#eab308' : '#22c55e';
  }

  scoreValue.style.color = color;
  scoreLabel.style.color = color;
  scoreLabel.textContent = label;
  linksSpan.textContent = `Links: ${totalLinksMatched}`;
  handlesSpan.textContent = `Handles: ${totalHandlesMatched}`;
  samplesSpan.textContent = `Matched: ${sampleCount}`;
  coverageSpan.textContent = `Coverage: ${sampleCount} matched / ${totalTweetsScanned} posts scanned`;

  const total = evidence.observations.length;
  leftLabel.textContent = `Left ${evidence.counts.left}`;
  centerLabel.textContent = `Center ${evidence.counts.center}`;
  rightLabel.textContent = `Right ${evidence.counts.right}`;
  if (total > 0) {
    barLeft.style.width = ((evidence.counts.left / total) * 100).toFixed(1) + '%';
    barCenter.style.width = ((evidence.counts.center / total) * 100).toFixed(1) + '%';
    barRight.style.width = ((evidence.counts.right / total) * 100).toFixed(1) + '%';
  }

  timeline.replaceChildren();
  evidence.observations.forEach(observation => {
    const step = document.createElement('span');
    const bucket = observationBucket(observation.score);
    step.className = `timeline-step ${bucket}`;
    step.style.height = `${Math.max(22, 35 + Math.abs(observation.score) * 65)}%`;
    step.title = `${bucket[0].toUpperCase() + bucket.slice(1)} exposure`;
    timeline.appendChild(step);
  });
  whyChanged.textContent = describeRecentChange(evidence.observations);
}

function formatElapsedTime(timestamp) {
  if (!timestamp) return 'no events yet';
  const seconds = Math.max(0, Math.round((Date.now() - timestamp) / 1000));
  return seconds < 60 ? `${seconds}s ago` : `${Math.floor(seconds / 60)}m ago`;
}

function updateCompanionStatus(status) {
  if (!dashboardElements) return;
  const { companionStatus, companionStatusText } = dashboardElements;
  companionStatus.classList.toggle('is-connected', Boolean(status && status.connected));
  companionStatus.classList.toggle('is-disconnected', !status || !status.connected);
  companionStatusText.textContent = status && status.connected
    ? `Companion connected · ${status.capturesThisSession || 0} captures this session · Last event ${formatElapsedTime(status.lastEventAt)}`
    : 'Backend unavailable — start companion service';
}

function refreshCompanionStatus() {
  if (!hasExtensionContext()) return;
  try {
    chrome.runtime.sendMessage({ type: 'companion-status' }, status => {
      if (!hasExtensionContext() || chrome.runtime.lastError) return updateCompanionStatus(null);
      updateCompanionStatus(status);
    });
  } catch (error) {
    updateCompanionStatus(null);
  }
}

// ── DOM Scraping with Debounced MutationObserver ────────────────────────────

const processedTweets = new WeakSet();
const processedTweetIds = new Set();
const TWEET_SELECTOR = '[data-testid="tweet"]';
let pendingNodes = [];
let processingScheduled = false;
let totalLinksMatched = 0;
let totalHandlesMatched = 0;
let totalTweetsScanned = 0;
let leftCount = 0, centerCount = 0, rightCount = 0;

function categorizeScore(score) {
  if (score < -0.3) {
    leftCount++;
  } else if (score > 0.3) {
    rightCount++;
  } else {
    centerCount++;
  }
}

async function processTweet(tweetElement) {
  if (processedTweets.has(tweetElement)) return;
  processedTweets.add(tweetElement);

  // Strategy 1: Find a link whose href matches a bare profile URL or contains a tweet ID
  const allLinks = tweetElement.querySelectorAll('a[href]');
  
  let headline = '';
  const textEl = tweetElement.querySelector('[data-testid="tweetText"]');
  if (textEl) {
    headline = textEl.innerText.trim();
  }

  // Extract Tweet ID to prevent double-counting across DOM virtualization
  let tweetId = null;
  for (const link of allLinks) {
    const idMatch = link.href.match(/\/status\/(\d+)/);
    if (idMatch) {
      tweetId = idMatch[1];
      break;
    }
  }

  if (tweetId) {
    if (processedTweetIds.has(tweetId)) return;
    processedTweetIds.add(tweetId);
  }

  totalTweetsScanned++;
  saveRigidityState();

  const signals = [];

  // ── Author handle extraction ──────────────────────────────────────────
  const profilePattern = /^https?:\/\/(twitter\.com|x\.com)\/[a-zA-Z0-9_]+$/;
  let handle = null;

  for (const link of allLinks) {
    if (profilePattern.test(link.href)) {
      try {
        const url = new URL(link.href);
        const pathHandle = url.pathname.replace('/', '').toLowerCase();
        if (pathHandle && pathHandle.length > 0) {
          handle = pathHandle;
          break;
        }
      } catch (e) { /* ignore */ }
    }
  }

  // Strategy 2: Look for @username in User-Name testid area
  if (!handle) {
    const userNameEl = tweetElement.querySelector('[data-testid="User-Name"]');
    if (userNameEl) {
      const textContent = userNameEl.textContent;
      const atMatch = textContent.match(/@([a-zA-Z0-9_]+)/);
      if (atMatch) {
        handle = atMatch[1].toLowerCase();
      }
    }
  }

  // Look up handle in the bias database
  if (handle) {
    const handleKey = '@' + handle;
    const handleResult = await getBiasScore(handleKey);

    if (handleResult !== null) {
      totalHandlesMatched++;
      signals.push({ score: handleResult.score, confidence: handleResult.confidence, weight: HANDLE_WEIGHT });

      if (DEBUG) console.log(`[BiasAuditor] Handle @${handle} => score: ${handleResult.score}, confidence: ${handleResult.confidence}`);
      
      reportCapture('handle', handle, handleResult.score, handleResult.confidence, handleResult.sources, headline, tweetId);
    }
  }

  // ── Link extraction ───────────────────────────────────────────────────
  const links = tweetElement.querySelectorAll('a[href^="http"]');

  for (const link of links) {
    let hostname = null;

    try {
      const url = new URL(link.href);
      hostname = url.hostname.toLowerCase();
    } catch (e) {
      continue;
    }

    // Skip twitter/x links
    if (hostname === 'twitter.com' || hostname === 'x.com' ||
        hostname.endsWith('.twitter.com') || hostname.endsWith('.x.com')) {
      continue;
    }

    // Handle t.co links: extract domain from link's innerText
    if (hostname === 't.co') {
      const text = link.innerText.trim();
      if (text && text.includes('.')) {
        try {
          // innerText may show something like "nytimes.com/article..." or "https://nytimes.com/..."
          let parseable = text;
          if (!parseable.startsWith('http')) {
            parseable = 'https://' + parseable;
          }
          const parsed = new URL(parseable);
          hostname = parsed.hostname.toLowerCase();

          // Skip if resolved domain is still twitter/x
          if (hostname === 'twitter.com' || hostname === 'x.com' ||
              hostname.endsWith('.twitter.com') || hostname.endsWith('.x.com')) {
            continue;
          }
        } catch (e) {
          continue;
        }
      } else {
        continue;
      }
    }

    // Skip known URL shorteners — can't resolve the real destination from a content script
    if (KNOWN_SHORTENERS.has(hostname)) {
      if (DEBUG) console.log('[BiasAuditor] Skipping shortener:', hostname);
      continue;
    }

    if (DEBUG) console.log('[BiasAuditor] Processing link:', hostname);

    const result = await tryMultipleKeys(hostname);

    if (result !== null) {
      totalLinksMatched++;
      signals.push({ score: result.score, confidence: result.confidence, weight: 1 });

      if (DEBUG) console.log(`[BiasAuditor] ${hostname} => score: ${result.score}, confidence: ${result.confidence}`);
      
      reportCapture('domain', hostname, result.score, result.confidence, result.sources, headline, tweetId);
    }
  }

  // Merge all evidence about a tweet into one exposure observation.
  if (signals.length > 0) {
    const totalWeight = signals.reduce((sum, signal) => sum + signal.weight * signal.confidence, 0);
    if (totalWeight <= 0) return;
    const compositeScore = signals.reduce(
      (sum, signal) => sum + signal.score * signal.weight * signal.confidence, 0
    ) / totalWeight;
    const compositeConfidence = totalWeight / signals.reduce((sum, signal) => sum + signal.weight, 0);
    categorizeScore(compositeScore);
    const currentRigidityScore = updateRigidityScore(compositeScore, compositeConfidence);
    recordObservation(compositeScore);
    saveRigidityState();
    if (DEBUG) console.log(`[BiasAuditor] Tweet ${tweetId || '(no id)'} => score: ${compositeScore.toFixed(4)}, rigidity: ${currentRigidityScore.toFixed(4)}`);
    updateDashboardUI(currentRigidityScore);
  }
}

function processQueue() {
  processingScheduled = false;

  if (pendingNodes.length === 0) return;

  const scheduleCallback = typeof requestIdleCallback === 'function'
    ? requestIdleCallback
    : (fn) => setTimeout(fn, 16);

  scheduleCallback(async () => {
    const batch = pendingNodes.splice(0, 5);

    for (const node of batch) {
      await processTweet(node);
    }

    if (pendingNodes.length > 0) {
      processingScheduled = true;
      processQueue();
    }
  });
}

function startObserver() {
  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      if (mutation.type !== 'childList') continue;

      for (const added of mutation.addedNodes) {
        if (added.nodeType !== Node.ELEMENT_NODE) continue;

        // Check if the added node itself is a tweet
        if (added.matches && added.matches(TWEET_SELECTOR)) {
          pendingNodes.push(added);
        }

        // Check descendants
        if (added.querySelectorAll) {
          const tweets = added.querySelectorAll(TWEET_SELECTOR);
          for (const tweet of tweets) {
            pendingNodes.push(tweet);
          }
        }
      }
    }

    if (pendingNodes.length > 0 && !processingScheduled) {
      processingScheduled = true;
      processQueue();
    }
  });

  observer.observe(document.body, { childList: true, subtree: true });

  // Also process any tweets already on the page
  const existing = document.querySelectorAll(TWEET_SELECTOR);
  for (const tweet of existing) {
    pendingNodes.push(tweet);
  }
  if (pendingNodes.length > 0 && !processingScheduled) {
    processingScheduled = true;
    processQueue();
  }
}

// ── Initialization ──────────────────────────────────────────────────────────

(async function init() {
  // Pre-load data
  getBiasScore('preload');

  createDashboard();
  await restoreRigidityState();
  updateDashboardUI();
  refreshCompanionStatus();
  companionStatusTimer = setInterval(refreshCompanionStatus, COMPANION_STATUS_INTERVAL_MS);
  startObserver();
})();
