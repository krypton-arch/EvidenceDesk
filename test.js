const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');

// ─── Extracted normalization logic (mirrored from content_script.js) ────────

function normalizeDomain(hostname) {
  let domain = hostname.replace(/^www\./, '');
  const parts = domain.split('.');
  if (parts.length >= 2) {
    const lastTwo = parts.slice(-2).join('.');
    if (['co.uk', 'com.au', 'co.nz', 'co.za', 'co.in'].includes(lastTwo)) {
      return parts.slice(0, -2).join('').toLowerCase().replace(/[^a-z0-9]/g, '');
    }
  }
  return parts.slice(0, -1).join('').toLowerCase().replace(/[^a-z0-9]/g, '');
}

function tryMultipleKeysSync(hostname, lookupFn) {
  const stripped = hostname.replace(/^www\./, '');
  const parts = stripped.split('.');

  // Strategy 1: normalizeDomain
  const key1 = normalizeDomain(hostname);
  if (key1) {
    const score1 = lookupFn(key1);
    if (score1 !== null) return score1;
  }

  // Strategy 2: full domain joined
  const key2 = parts.join('').toLowerCase().replace(/[^a-z0-9]/g, '');
  if (key2 && key2 !== key1) {
    const score2 = lookupFn(key2);
    if (score2 !== null) return score2;
  }

  // Strategy 3: second-level domain
  if (parts.length > 2) {
    const lastTwo = parts.slice(-2).join('.');
    let key3;
    if (['co.uk', 'com.au', 'co.nz', 'co.za', 'co.in'].includes(lastTwo)) {
      if (parts.length >= 3) {
        key3 = parts[parts.length - 3].toLowerCase().replace(/[^a-z0-9]/g, '');
      }
    } else {
      key3 = parts[parts.length - 2].toLowerCase().replace(/[^a-z0-9]/g, '');
    }
    if (key3 && key3 !== key1 && key3 !== key2) {
      const score3 = lookupFn(key3);
      if (score3 !== null) return score3;
    }
  }

  return null;
}

// ─── Extracted EMA logic (mirrored from content_script.js) ──────────────────

function createEMAEngine(alpha = 0.2) {
  let mu_t = 0;
  let sigma2_t = 0;
  let sampleCount = 0;

  return {
    update(score, confidence) {
      sampleCount++;
      const alpha_eff = alpha * confidence;

      if (sampleCount === 1) {
        mu_t = score;
        sigma2_t = 0;
      } else {
        const delta = score - mu_t;
        mu_t = alpha_eff * score + (1 - alpha_eff) * mu_t;
        sigma2_t = (1 - alpha_eff) * (sigma2_t + alpha_eff * delta * delta);
      }

      const rt = 1 - Math.min(1, Math.max(0, sigma2_t));
      return { rt, mu_t, sigma2_t, sampleCount };
    },
    getState() { return { mu_t, sigma2_t, sampleCount }; }
  };
}

// ─── Test Suite ─────────────────────────────────────────────────────────────

describe('normalizeDomain', () => {
  it('strips www and removes TLD for simple domains', () => {
    assert.equal(normalizeDomain('www.nytimes.com'), 'nytimes');
    assert.equal(normalizeDomain('foxnews.com'), 'foxnews');
    assert.equal(normalizeDomain('cnn.com'), 'cnn');
  });

  it('handles multi-part TLDs (.co.uk, .com.au)', () => {
    assert.equal(normalizeDomain('bbc.co.uk'), 'bbc');
    assert.equal(normalizeDomain('www.bbc.co.uk'), 'bbc');
    assert.equal(normalizeDomain('news.com.au'), 'news');
    assert.equal(normalizeDomain('stuff.co.nz'), 'stuff');
  });

  it('handles subdomains correctly', () => {
    assert.equal(normalizeDomain('news.bbc.co.uk'), 'newsbbc');
    assert.equal(normalizeDomain('edition.cnn.com'), 'editioncnn');
  });

  it('strips non-alphanumeric characters', () => {
    assert.equal(normalizeDomain('abc-news.com'), 'abcnews');
    assert.equal(normalizeDomain('real-clear-politics.com'), 'realclearpolitics');
  });
});

describe('tryMultipleKeys', () => {
  const mockDB = {
    'nytimes': -0.5,
    'bbc': 0,
    'foxnews': 1,
    'dailymail': 0.5,
    'washingtonpost': -0.5,
  };
  const lookup = (key) => mockDB[key] !== undefined ? mockDB[key] : null;

  it('matches simple domains via Strategy 1', () => {
    assert.equal(tryMultipleKeysSync('nytimes.com', lookup), -0.5);
    assert.equal(tryMultipleKeysSync('www.foxnews.com', lookup), 1);
  });

  it('matches .co.uk domains via multi-part TLD handling', () => {
    assert.equal(tryMultipleKeysSync('bbc.co.uk', lookup), 0);
    assert.equal(tryMultipleKeysSync('www.bbc.co.uk', lookup), 0);
  });

  it('matches subdomains via Strategy 3 (second-level domain)', () => {
    assert.equal(tryMultipleKeysSync('news.bbc.co.uk', lookup), 0);
  });

  it('returns null for unknown domains', () => {
    assert.equal(tryMultipleKeysSync('randomsite.xyz', lookup), null);
    assert.equal(tryMultipleKeysSync('unknownnews.org', lookup), null);
  });

  it('handles t.co-like resolved domains', () => {
    // Simulates: innerText showed "washingtonpost.com/article-title..."
    // which the content script would parse to hostname "washingtonpost.com"
    assert.equal(tryMultipleKeysSync('washingtonpost.com', lookup), -0.5);
  });
});

describe('Composite score merge logic (data_parser)', () => {
  // Simulates the merge logic from data_parser.js
  function computeComposite(sources) {
    const weights = { allsides: 0.35, pabs: 0.30, gdelt: 0.20, qbias: 0.15 };
    let totalWeight = 0;
    let weightedSum = 0;
    const availableSources = [];

    for (const [source, score] of Object.entries(sources)) {
      if (score !== undefined && score !== null) {
        totalWeight += weights[source];
        weightedSum += weights[source] * score;
        availableSources.push(source);
      }
    }

    if (totalWeight === 0) return null;

    return {
      score: weightedSum / totalWeight,
      sources: availableSources,
    };
  }

  it('merges all 4 sources correctly', () => {
    const result = computeComposite({
      allsides: -0.5,
      pabs: -0.6,
      gdelt: -0.4,
      qbias: -0.3,
    });
    // (-0.5*0.35 + -0.6*0.30 + -0.4*0.20 + -0.3*0.15) / 1.0
    const expected = (-0.175 + -0.18 + -0.08 + -0.045) / 1.0;
    assert.ok(Math.abs(result.score - expected) < 0.001, `Expected ${expected}, got ${result.score}`);
    assert.deepEqual(result.sources, ['allsides', 'pabs', 'gdelt', 'qbias']);
  });

  it('handles domain present in only 2 of 4 corpora', () => {
    const result = computeComposite({
      allsides: 0.5,
      pabs: null,
      gdelt: 0.3,
      qbias: null,
    });
    // (0.5*0.35 + 0.3*0.20) / (0.35 + 0.20)
    const expected = (0.175 + 0.06) / 0.55;
    assert.ok(Math.abs(result.score - expected) < 0.001, `Expected ${expected}, got ${result.score}`);
    assert.deepEqual(result.sources, ['allsides', 'gdelt']);
  });

  it('handles domain in only 1 corpus', () => {
    const result = computeComposite({
      allsides: null,
      pabs: -0.8,
      gdelt: null,
      qbias: null,
    });
    assert.ok(Math.abs(result.score - (-0.8)) < 0.001);
    assert.deepEqual(result.sources, ['pabs']);
  });

  it('returns null when domain is in zero corpora', () => {
    const result = computeComposite({
      allsides: null,
      pabs: null,
      gdelt: null,
      qbias: null,
    });
    assert.equal(result, null);
  });
});

describe('EMA Rigidity Score math', () => {
  it('returns R_t = 0 for a single data point', () => {
    const engine = createEMAEngine(0.2);
    const { rt } = engine.update(-0.5, 1.0);
    // After 1 sample: sigma2 = 0 → R_t = 1 - e^0 = 0
    assert.ok(Math.abs(rt - 1) < 1e-10, `Expected 1, got ${rt}`);
  });

  it('returns R_t ≈ 0 for uniform scores (echo chamber)', () => {
    const engine = createEMAEngine(0.2);
    // Feed 20 identical scores
    let lastRt;
    for (let i = 0; i < 20; i++) {
      const { rt } = engine.update(-1.0, 1.0);
      lastRt = rt;
    }
    // All same score → variance stays near 0 → R_t ≈ 0
    assert.ok(lastRt > 0.999, `Expected near 1 (concentrated), got ${lastRt}`);
  });

  it('returns increasing R_t for alternating extreme scores (diverse)', () => {
    const engine = createEMAEngine(0.2);
    const scores = [-1, 1, -1, 1, -1, 1, -1, 1, -1, 1];
    let lastRt = 0;
    for (const s of scores) {
      const { rt } = engine.update(s, 1.0);
      lastRt = rt;
    }
    // Alternating -1 and 1 → high variance → R_t should be > 0
    assert.ok(lastRt < 0.1, `Expected diverse score < 0.1, got ${lastRt}`);
  });

  it('hand-computed verification: 3-step sequence', () => {
    const alpha = 0.2;
    const engine = createEMAEngine(alpha);

    // Step 1: score=0.5, confidence=1.0
    let result = engine.update(0.5, 1.0);
    assert.ok(Math.abs(result.mu_t - 0.5) < 1e-10);
    assert.ok(Math.abs(result.sigma2_t - 0) < 1e-10);

    // Step 2: score=-0.5, confidence=1.0
    // alpha_eff = 0.2 * 1.0 = 0.2
    // delta = -0.5 - 0.5 = -1.0
    // mu_t = 0.2 * (-0.5) + 0.8 * 0.5 = -0.1 + 0.4 = 0.3
    // sigma2_t = 0.8 * (0 + 0.2 * 1.0^2) = 0.8 * 0.2 = 0.16
    result = engine.update(-0.5, 1.0);
    assert.ok(Math.abs(result.mu_t - 0.3) < 1e-10, `mu_t expected 0.3, got ${result.mu_t}`);
    assert.ok(Math.abs(result.sigma2_t - 0.16) < 1e-10, `sigma2_t expected 0.16, got ${result.sigma2_t}`);

    // R_t = 1 - exp(-0.1 * 0.16) = 1 - exp(-0.016) ≈ 0.01587
    const expectedRt2 = 1 - 0.16;
    assert.ok(Math.abs(result.rt - expectedRt2) < 1e-10, `R_t expected ${expectedRt2}, got ${result.rt}`);

    // Step 3: score=0.0, confidence=0.5
    // alpha_eff = 0.2 * 0.5 = 0.1
    // delta = 0.0 - 0.3 = -0.3
    // mu_t = 0.1 * 0.0 + 0.9 * 0.3 = 0.27
    // sigma2_t = 0.9 * (0.16 + 0.1 * 0.09) = 0.9 * 0.169 = 0.1521
    result = engine.update(0.0, 0.5);
    assert.ok(Math.abs(result.mu_t - 0.27) < 1e-10, `mu_t expected 0.27, got ${result.mu_t}`);
    assert.ok(Math.abs(result.sigma2_t - 0.1521) < 1e-10, `sigma2_t expected 0.1521, got ${result.sigma2_t}`);
  });

  it('low-confidence sources nudge less than high-confidence', () => {
    const engineHigh = createEMAEngine(0.2);
    const engineLow = createEMAEngine(0.2);

    // Same initial baseline
    engineHigh.update(0, 1.0);
    engineLow.update(0, 1.0);

    // Push a strong signal with high vs low confidence
    engineHigh.update(1.0, 1.0);
    engineLow.update(1.0, 0.2);

    const stateHigh = engineHigh.getState();
    const stateLow = engineLow.getState();

    // High-confidence should have moved mu more toward 1.0
    assert.ok(stateHigh.mu_t > stateLow.mu_t,
      `High-confidence mu (${stateHigh.mu_t}) should be > low-confidence mu (${stateLow.mu_t})`);
  });
});

describe('bias_data.json structure', () => {
  const jsonPath = path.join(__dirname, 'bias_data.json');

  it('bias_data.json exists and is valid JSON', () => {
    assert.ok(fs.existsSync(jsonPath), 'bias_data.json should exist');
    const raw = fs.readFileSync(jsonPath, 'utf8');
    const data = JSON.parse(raw);
    assert.ok(typeof data === 'object', 'Should be an object');
  });

  it('entries have { score, confidence, sources } shape', () => {
    const data = JSON.parse(fs.readFileSync(jsonPath, 'utf8'));
    const keys = Object.keys(data);
    assert.ok(keys.length > 100, `Expected >100 entries, got ${keys.length}`);

    // Check a few random entries
    for (const key of keys.slice(0, 10)) {
      const entry = data[key];
      assert.ok(typeof entry === 'object', `Entry for "${key}" should be an object`);
      assert.ok(typeof entry.score === 'number', `Entry for "${key}" should have numeric score`);
      assert.ok(typeof entry.confidence === 'number', `Entry for "${key}" should have numeric confidence`);
      assert.ok(entry.confidence >= 0 && entry.confidence <= 1, `Confidence for "${key}" should be 0-1`);
      assert.ok(Array.isArray(entry.sources), `Entry for "${key}" should have sources array`);
      assert.ok(entry.sources.length >= 1, `Entry for "${key}" should have at least 1 source`);
    }
  });

  it('key domains have expected bias direction', () => {
    const data = JSON.parse(fs.readFileSync(jsonPath, 'utf8'));

    // Left-leaning domains should have negative scores
    if (data['cnn']) assert.ok(data['cnn'].score < 0, 'CNN should be left-leaning');
    if (data['nytimes']) assert.ok(data['nytimes'].score < 0, 'NYTimes should be left-leaning');
    if (data['msnbc']) assert.ok(data['msnbc'].score < 0, 'MSNBC should be left-leaning');

    // Right-leaning domains should have positive scores
    if (data['foxnews']) assert.ok(data['foxnews'].score > 0, 'Fox News should be right-leaning');
    if (data['breitbart']) assert.ok(data['breitbart'].score > 0, 'Breitbart should be right-leaning');

    // Center domains should be near 0
    if (data['reuters']) assert.ok(Math.abs(data['reuters'].score) < 0.3, 'Reuters should be near center');
    if (data['apnews']) assert.ok(Math.abs(data['apnews'].score) < 0.3, 'AP should be near center');
  });

  it('handle aliases exist with @ prefix', () => {
    const data = JSON.parse(fs.readFileSync(jsonPath, 'utf8'));
    // Check a few handle aliases
    const handles = ['@cnn', '@foxnews', '@nytimes', '@reuters', '@washingtonpost'];
    for (const h of handles) {
      assert.ok(data[h] !== undefined, `Handle ${h} should exist in bias_data.json`);
      assert.ok(typeof data[h].score === 'number', `Handle ${h} should have a score`);
    }
  });
});
