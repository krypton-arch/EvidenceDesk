const fs = require('fs');
const path = require('path');

// ─── File paths ────────────────────────────────────────────────────────────────
const allsidesPath   = path.join(__dirname, '..', 'allsides.csv');
const gdeltPath      = path.join(__dirname, '..', 'gdelt_snapshot.csv');
const qbiasPath      = path.join(__dirname, '..', 'qbias_headlines.json');
const pabsPath       = path.join(__dirname, '..', 'pabs_scores.csv');
const outputPath     = path.join(__dirname, 'bias_data.json');

// ─── CSV row parser (handles quoted fields) ────────────────────────────────────
function parseCSVRow(row) {
    let result = [];
    let curVal = '';
    let inQuotes = false;
    for (let i = 0; i < row.length; i++) {
        const char = row[i];
        if (char === '"') {
            if (inQuotes && row[i+1] === '"') {
                curVal += '"';
                i++;
            } else {
                inQuotes = !inQuotes;
            }
        } else if (char === ',' && !inQuotes) {
            result.push(curVal.trim());
            curVal = '';
        } else {
            curVal += char;
        }
    }
    result.push(curVal.trim());
    return result;
}

// ─── Utility: strip TLD from domain to get a key ──────────────────────────────
// "foxnews.com" -> "foxnews", "dailymail.co.uk" -> "dailymail",
// "abcnews.go.com" -> "abcnews"
function domainToKey(domain) {
    // Strip www. prefix
    let d = domain.toLowerCase().replace(/^www\./, '');
    // Remove known multi-part TLDs first
    d = d.replace(/\.(co\.uk|go\.com|com|org|net|io|tv|uk|edu|gov)$/i, '');
    // Remove any remaining dots
    d = d.replace(/\./g, '');
    return d;
}

// ─── Utility: extract root domain from a full hostname ─────────────────────────
// For PABS data which has subdomains: "artsbeat.blogs.nytimes.com" -> "nytimes.com"
function extractRootDomain(fullDomain) {
    const parts = fullDomain.split('.');
    // Handle multi-part TLDs
    const lastTwo = parts.slice(-2).join('.');
    if (['co.uk', 'go.com', 'com.au', 'co.nz', 'co.za'].includes(lastTwo) && parts.length >= 3) {
        return parts.slice(-3).join('.');
    }
    // Default: last 2 parts
    if (parts.length >= 2) {
        return parts.slice(-2).join('.');
    }
    return fullDomain;
}

// ─── Utility: convert source name to name-key (matches AllSides key generation)
function sourceNameToKey(name) {
    return name.split('(')[0].toLowerCase().replace(/[^a-z0-9]/g, '');
}

// ─── AllSides bias label mapping ───────────────────────────────────────────────
const biasMap = {
  'left': -1.0,
  'left-center': -0.5,
  'allsides': 0.0,
  'center': 0.0,
  'right-center': 0.5,
  'right': 1.0
};

// ─── Domain alias -> name-based key mapping ────────────────────────────────────
// The value must match the name-based key generated from the CSV source name.
const DOMAIN_ALIASES = {
  // Major left sources
  'cnn': 'cnn',
  'huffpost': 'huffpost',
  'huffingtonpost': 'huffpost',
  'msnbc': 'msnbc',
  'vox': 'vox',
  'slate': 'slate',
  'salon': 'salon',
  'motherjones': 'motherjones',
  'thedailybeast': 'dailybeast',
  'dailybeast': 'dailybeast',
  'buzzfeednews': 'buzzfeednews',
  'buzzfeed': 'buzzfeednews',
  'alternet': 'alternet',
  'jacobin': 'jacobin',
  'theintercept': 'theintercept',
  'democracynow': 'democracynow',
  'dailykos': 'dailykos',
  'rawstory': 'rawstory',
  'thinkprogress': 'thinkprogress',
  'commondreams': 'commondreams',
  'thenation': 'thenation',
  'newyorker': 'thenewyorker',
  'politicususa': 'politicususa',
  'mediamatters': 'mediamatters',

  // Major center-left sources
  'nytimes': 'newyorktimes',
  'washingtonpost': 'washingtonpost',
  'latimes': 'losangelestimes',
  'politico': 'politico',
  'theatlantic': 'theatlantic',
  'nbcnews': 'nbcnews',
  'abcnews': 'abcnews',
  'cbsnews': 'cbsnews',
  'usatoday': 'usatoday',
  'theguardian': 'theguardian',
  'bloomberg': 'bloomberg',
  'propublica': 'propublica',
  'npr': 'npr',
  'economist': 'theeconomist',
  'bostonglobe': 'thebostonglobe',
  'vanityfair': 'vanityfair',
  'thehill': 'thehill',
  'yahoo': 'yahoonews',
  'news.yahoo': 'yahoonews',
  'axios': 'axios',
  'mediaite': 'mediaite',
  'gizmodo': 'gizmodo',
  'theverge': 'theverge',
  'aljazeera': 'aljazeera',
  'scientificamerican': 'scientificamerican',
  'time': 'timemagazine',
  'usnews': 'usnewsworldreport',
  'espn': 'espncom',
  'teenvogue': 'teenvogue',
  'mashable': 'mashable',

  // Major center sources
  'apnews': 'associatedpress',
  'reuters': 'reuters',
  'bbc': 'bbcnews',
  'bbc.co': 'bbcnews',
  'forbes': 'forbes',
  'wsj': 'wallstreetjournal',
  'cnbc': 'cnbc',
  'cnet': 'cnet',
  'fivethirtyeight': 'fivethirtyeight',
  'realclearpolitics': 'realclearpolitics',
  'newsweek': 'newsweek',
  'chicagotribune': 'chicagotribune',
  'csmonitor': 'christiansciencemonitor',
  'pbs': 'pbsnewshour',
  'cspan': 'cspan',
  'foreignaffairs': 'foreignaffairs',
  'foreignpolicy': 'foreignpolicy',
  'wired': 'wired',
  'techcrunch': 'techcrunch',
  'fortune': 'fortune',
  'rollingstone': 'rollingstonecom',

  // Major right-center sources
  'nypost': 'newyorkpost',
  'washingtonexaminer': 'washingtonexaminer',
  'washingtontimes': 'washingtontimes',
  'reason': 'reason',
  'drudgereport': 'drudgereport',
  'newsmax': 'newsmax',
  'theepochtimes': 'theepochtime',
  'epochtimes': 'theepochtime',
  'quillette': 'quillette',
  'hotair': 'hotair',
  'babylonbee': 'babylonbee',
  'foxbusiness': 'foxbusiness',
  'christianitytoday': 'christianitytoday',
  'zerohedge': 'zerohedge',
  'investors': 'investorsbusinessdaily',
  'thebulwark': 'thebulwark',
  'thedispatch': 'thedispatch',
  'postmillennial': 'thepostmillennial',

  // Major right sources
  'foxnews': 'foxnews',
  'breitbart': 'breitbartnews',
  'dailywire': 'thedailywire',
  'dailycaller': 'thedailycaller',
  'thefederalist': 'thefederalist',
  'nationalreview': 'nationalreview',
  'pjmedia': 'pjmedia',
  'townhall': 'townhall',
  'infowars': 'infowars',
  'theblaze': 'theblazecom',
  'redstate': 'redstate',
  'dailymail': 'dailymail',
  'thegatewaypundit': 'thegatewaypundit',
  'americanthinker': 'americanthinker',
  'westernjournal': 'thewesternjournal',
  'wnd': 'wndcom',
  'oann': 'oneamericanewsnetwork',
  'revolver': 'revolvernews',
  'dailysignal': 'thedailysignal',
  'cnsnews': 'cnsnewscom',
};

// Twitter/X handle -> name-key mapping
// This allows the extension to detect bias from the TWEET AUTHOR, not just external links.
// Prefixed with '@' to avoid collisions with domain keys.
const HANDLE_ALIASES = {
  // Left
  '@abc': 'abcnews',
  '@cnn': 'cnn',
  '@msnbc': 'msnbc',
  '@huffpost': 'huffpost',
  '@vox': 'vox',
  '@slate': 'slate',
  '@salon': 'salon',
  '@motherjones': 'motherjones',
  '@thedailybeast': 'dailybeast',
  '@buzzfeednews': 'buzzfeednews',
  '@alternet': 'alternet',
  '@jacobin': 'jacobin',
  '@theintercept': 'theintercept',
  '@democracynow': 'democracynow',
  '@dailykos': 'dailykos',
  '@rawstory': 'rawstory',
  '@thinkprogress': 'thinkprogress',
  '@commondreams': 'commondreams',
  '@thenation': 'thenation',
  '@newyorker': 'thenewyorker',
  '@mediamatters': 'mediamatters',
  '@esquire': 'esquire',
  '@vice': 'vice',
  '@newrepublic': 'newrepublic',

  // Center-left
  '@nytimes': 'newyorktimes',
  '@washingtonpost': 'washingtonpost',
  '@latimes': 'losangelestimes',
  '@politico': 'politico',
  '@theatlantic': 'theatlantic',
  '@nbcnews': 'nbcnews',
  '@abcnews': 'abcnews',
  '@cbsnews': 'cbsnews',
  '@usatoday': 'usatoday',
  '@guardian': 'theguardian',
  '@bloomberg': 'bloomberg',
  '@propublica': 'propublica',
  '@npr': 'npr',
  '@theeconomist': 'theeconomist',
  '@bostonglobe': 'thebostonglobe',
  '@vanityfair': 'vanityfair',
  '@yahoonews': 'yahoonews',
  '@axios': 'axios',
  '@gizmodo': 'gizmodo',
  '@verge': 'theverge',
  '@ajplus': 'aj',
  '@aljazeera': 'aljazeera',
  '@sciam': 'scientificamerican',
  '@time': 'timemagazine',
  '@usnews': 'usnewsworldreport',
  '@teenvogue': 'teenvogue',
  '@mashable': 'mashable',
  '@mediaite': 'mediaite',
  '@politicususa': 'politicususa',
  '@thetexastribune': 'thetexastribune',
  '@sfchronicle': 'sanfranciscochronicle',

  // Center
  '@ap': 'associatedpress',
  '@apnews': 'associatedpress',
  '@reuters': 'reuters',
  '@bbcworld': 'bbcnews',
  '@bbcnews': 'bbcnews',
  '@bbcbreaking': 'bbcnews',
  '@forbes': 'forbes',
  '@wsj': 'wallstreetjournal',
  '@cnbc': 'cnbc',
  '@cnet': 'cnet',
  '@fivethirtyeight': 'fivethirtyeight',
  '@newsweek': 'newsweek',
  '@chicagotribune': 'chicagotribune',
  '@csmonitor': 'christiansciencemonitor',
  '@pbs': 'pbsnewshour',
  '@cspan': 'cspan',
  '@thehill': 'thehill',
  '@foreignaffairs': 'foreignaffairs',
  '@foreignpolicy': 'foreignpolicy',
  '@wired': 'wired',
  '@techcrunch': 'techcrunch',
  '@fortune': 'fortune',
  '@rollingstone': 'rollingstonecom',
  '@realclearnews': 'realclearpolitics',

  // Right-center
  '@nypost': 'newyorkpost',
  '@dcexaminer': 'washingtonexaminer',
  '@washtimes': 'washingtontimes',
  '@reason': 'reason',
  '@drudge_report': 'drudgereport',
  '@newsmax': 'newsmax',
  '@epochtimes': 'theepochtime',
  '@quillette': 'quillette',
  '@hotair': 'hotair',
  '@thebabylonbee': 'babylonbee',
  '@foxbusiness': 'foxbusiness',
  '@ctmagazine': 'christianitytoday',
  '@zerohedge': 'zerohedge',
  '@ibdinvestors': 'investorsbusinessdaily',
  '@bulwark': 'thebulwark',
  '@thedispatch': 'thedispatch',

  // Right
  '@foxnews': 'foxnews',
  '@breitbartnews': 'breitbartnews',
  '@realdailywire': 'thedailywire',
  '@dailywire': 'thedailywire',
  '@dailycaller': 'thedailycaller',
  '@fdrlst': 'thefederalist',
  '@nationalreview': 'nationalreview',
  '@nrorealclearnews': 'nationalreview',
  '@pjmedia': 'pjmedia',
  '@townhallcom': 'townhall',
  '@infowars': 'infowars',
  '@theblaze': 'theblazecom',
  '@redstate': 'redstate',
  '@dailymail': 'dailymail',
  '@mailonline': 'dailymail',
  '@gatewaypundit': 'thegatewaypundit',
  '@amthinker': 'americanthinker',
  '@westernjournal': 'thewesternjournal',
  '@oaborann': 'oneamericanewsnetwork',
  '@dailysignal': 'thedailysignal',
  '@newsbusters': 'newsbusters',
};

// ─── Default weights for composite scoring ─────────────────────────────────────
const W_AS    = 0.35;  // AllSides
const W_PABS  = 0.30;  // PABS
const W_GDELT = 0.20;  // GDELT
const W_QBIAS = 0.15;  // QBias

// =============================================================================
// STEP 1: Parse AllSides CSV
// =============================================================================
console.log('Parsing AllSides...');
const allsidesContent = fs.readFileSync(allsidesPath, 'utf8');
const allsidesLines = allsidesContent.split('\n').filter(line => line.trim() !== '');

// Map: nameKey -> { score, confidence }
const allsidesData = {};

for (let i = 1; i < allsidesLines.length; i++) {
    const values = parseCSVRow(allsidesLines[i]);
    if (values.length >= 2) {
        const name = values[0];
        const bias = values[1];
        const score = biasMap[bias];
        if (score !== undefined) {
            // Strip parentheticals, lowercase, remove non-alphanumeric
            const cleanName = name.split('(')[0].toLowerCase().replace(/[^a-z0-9]/g, '');

            // Calculate confidence from agree_ratio if available
            let confidence = 0.5; // default
            // Try to find agree_ratio column — look at header
            const header = parseCSVRow(allsidesLines[0]);
            const agreeIdx = header.findIndex(h => h.toLowerCase().replace(/[^a-z_]/g, '') === 'agree_ratio' || h.toLowerCase().replace(/[^a-z_]/g, '') === 'agreeratio');
            if (agreeIdx >= 0 && values[agreeIdx]) {
                const agreeRatio = parseFloat(values[agreeIdx]);
                if (!isNaN(agreeRatio)) {
                    confidence = agreeRatio / (agreeRatio + 1);
                }
            }

            // Prefer first occurrence for duplicate keys
            if (allsidesData[cleanName] === undefined) {
                allsidesData[cleanName] = { score, confidence };
            }
        }
    }
}
console.log(`  AllSides: ${Object.keys(allsidesData).length} entries`);

// =============================================================================
// STEP 2: Parse GDELT snapshot CSV
// =============================================================================
console.log('Parsing GDELT...');
const gdeltContent = fs.readFileSync(gdeltPath, 'utf8');
const gdeltLines = gdeltContent.split('\n').filter(line => line.trim() !== '' && !line.startsWith('#'));

// Map: domainKey -> gdelt bias score (tone / 10)
const gdeltData = {};

const gdeltHeader = parseCSVRow(gdeltLines[0]);
const toneIdx = gdeltHeader.findIndex(h => h.toLowerCase() === 'tone');
const domainIdx = gdeltHeader.findIndex(h => h.toLowerCase() === 'domain');

for (let i = 1; i < gdeltLines.length; i++) {
    const values = parseCSVRow(gdeltLines[i]);
    if (values.length >= gdeltHeader.length) {
        const domain = values[domainIdx];
        const tone = parseFloat(values[toneIdx]);
        if (domain && !isNaN(tone)) {
            const key = domainToKey(domain);
            gdeltData[key] = tone / 10.0; // normalize [-10,10] -> [-1,1]
        }
    }
}
console.log(`  GDELT: ${Object.keys(gdeltData).length} entries`);

// =============================================================================
// STEP 3: Parse QBias headlines JSON
// =============================================================================
console.log('Parsing QBias...');
const qbiasRaw = JSON.parse(fs.readFileSync(qbiasPath, 'utf8'));

// Average spin_bias per source.
// Real Qbias data uses "source" (name like "New York Times (News)") not "domain".
// We convert source names to name-keys the same way AllSides does.
const qbiasAccum = {}; // nameKey -> { sum, count }
for (const record of qbiasRaw) {
    if (record._notice) continue;
    // Support both real format ("source") and legacy synthetic format ("domain")
    const sourceName = record.source || record.domain;
    if (!sourceName) continue;
    let key;
    if (record.source) {
        // Real Qbias: convert source name to AllSides-style name-key
        key = sourceNameToKey(record.source);
    } else {
        // Legacy synthetic: strip TLD from domain
        key = domainToKey(record.domain);
    }
    const spin = parseFloat(record.spin_bias);
    if (!isNaN(spin) && key) {
        if (!qbiasAccum[key]) qbiasAccum[key] = { sum: 0, count: 0 };
        qbiasAccum[key].sum += spin;
        qbiasAccum[key].count++;
    }
}

const qbiasData = {};
for (const [key, { sum, count }] of Object.entries(qbiasAccum)) {
    qbiasData[key] = sum / count;
}
console.log(`  QBias: ${Object.keys(qbiasData).length} entries`);

// =============================================================================
// STEP 4: Parse PABS scores CSV
// =============================================================================
console.log('Parsing PABS...');
const pabsContent = fs.readFileSync(pabsPath, 'utf8');
// Handle \r\n line endings and # comment headers
const pabsLines = pabsContent.split(/\r?\n/).filter(line => line.trim() !== '' && !line.startsWith('#'));

// PABS has subdomains (e.g., artsbeat.blogs.nytimes.com). We extract root
// domains and average all subdomain scores into one per root domain.
const pabsAccum = {}; // rootDomainKey -> { sum, count }
const pabsHeader = parseCSVRow(pabsLines[0]);
const pabsDomainIdx = pabsHeader.findIndex(h => h.toLowerCase().trim() === 'domain');
const pabsScoreIdx = pabsHeader.findIndex(h => h.toLowerCase().trim() === 'pabs_score');

for (let i = 1; i < pabsLines.length; i++) {
    const values = parseCSVRow(pabsLines[i]);
    if (values.length >= 2) {
        const fullDomain = (values[pabsDomainIdx] || '').trim();
        const score = parseFloat((values[pabsScoreIdx] || '').trim());
        if (fullDomain && !isNaN(score)) {
            // Extract root domain, then convert to key
            const rootDomain = extractRootDomain(fullDomain);
            const key = domainToKey(rootDomain);
            if (!pabsAccum[key]) pabsAccum[key] = { sum: 0, count: 0 };
            pabsAccum[key].sum += score;
            pabsAccum[key].count++;
        }
    }
}

const pabsData = {};
for (const [key, { sum, count }] of Object.entries(pabsAccum)) {
    pabsData[key] = sum / count;
}
console.log(`  PABS: ${Object.keys(pabsData).length} entries (from ${pabsLines.length - 1} rows, averaged by root domain)`);

// =============================================================================
// STEP 5: Merge domain-keyed data into name-keys using DOMAIN_ALIASES
// =============================================================================
// GDELT, PABS, and QBias use domain-derived keys (e.g. "nytimes" from nytimes.com)
// AllSides uses name-derived keys (e.g. "newyorktimes" from "New York Times").
// DOMAIN_ALIASES maps domain-keys -> name-keys (e.g. "nytimes" -> "newyorktimes").
// We use this mapping to merge domain-keyed data into the canonical name-key space.

console.log('\nMerging domain-keyed data into name-keys...');

// Build reverse lookup: domainKey -> nameKey (from DOMAIN_ALIASES)
const domainToNameKey = {};
for (const [alias, target] of Object.entries(DOMAIN_ALIASES)) {
    domainToNameKey[alias] = target;
}

// Helper: resolve a domain-derived key to its canonical name-key
function resolveKey(domainKey) {
    return domainToNameKey[domainKey] || domainKey;
}

// Re-key GDELT data to name-keys
const gdeltByNameKey = {};
for (const [dk, val] of Object.entries(gdeltData)) {
    const nk = resolveKey(dk);
    gdeltByNameKey[nk] = val;
}

// Re-key PABS data to name-keys
const pabsByNameKey = {};
for (const [dk, val] of Object.entries(pabsData)) {
    const nk = resolveKey(dk);
    pabsByNameKey[nk] = val;
}

// Re-key QBias data to name-keys
const qbiasByNameKey = {};
for (const [dk, val] of Object.entries(qbiasData)) {
    const nk = resolveKey(dk);
    qbiasByNameKey[nk] = val;
}

// =============================================================================
// STEP 6: Compute composite scores
// =============================================================================
console.log('Computing composite scores...');

// Gather all unique canonical name-keys
const allKeys = new Set();
for (const key of Object.keys(allsidesData)) allKeys.add(key);
for (const key of Object.keys(gdeltByNameKey)) allKeys.add(key);
for (const key of Object.keys(qbiasByNameKey)) allKeys.add(key);
for (const key of Object.keys(pabsByNameKey)) allKeys.add(key);

const compositeData = {}; // nameKey -> { score, confidence, sources }

for (const key of allKeys) {
    const sources = [];
    const weights = [];
    const biases  = [];

    if (allsidesData[key] !== undefined) {
        sources.push('allsides');
        weights.push(W_AS);
        biases.push(allsidesData[key].score);
    }
    if (pabsByNameKey[key] !== undefined) {
        sources.push('pabs');
        weights.push(W_PABS);
        biases.push(pabsByNameKey[key]);
    }
    if (gdeltByNameKey[key] !== undefined) {
        sources.push('gdelt');
        weights.push(W_GDELT);
        biases.push(gdeltByNameKey[key]);
    }
    if (qbiasByNameKey[key] !== undefined) {
        sources.push('qbias');
        weights.push(W_QBIAS);
        biases.push(qbiasByNameKey[key]);
    }

    if (sources.length === 0) continue;

    // Weighted average (redistribute missing weights — normalize to sum to 1)
    const totalWeight = weights.reduce((a, b) => a + b, 0);
    let compositeScore = 0;
    for (let i = 0; i < sources.length; i++) {
        compositeScore += (weights[i] / totalWeight) * biases[i];
    }

    // Confidence: average of AllSides confidence (or 0.5) and count-based confidence
    const asConfidence = allsidesData[key] ? allsidesData[key].confidence : 0.5;
    const countConfidence = sources.length / 4;
    const confidence = (asConfidence + countConfidence) / 2;

    compositeData[key] = {
        score: Math.round(compositeScore * 1000) / 1000,
        confidence: Math.round(confidence * 1000) / 1000,
        sources
    };
}

console.log(`  Composite entries (name-keys): ${Object.keys(compositeData).length}`);

// =============================================================================
// STEP 7: Build final output with aliases
// =============================================================================
const output = {};

// Add all composite name-key entries
for (const [key, entry] of Object.entries(compositeData)) {
    output[key] = entry;
}

// Apply DOMAIN_ALIASES: alias key -> same data as target name-key
for (const [alias, targetNameKey] of Object.entries(DOMAIN_ALIASES)) {
    if (compositeData[targetNameKey] !== undefined) {
        output[alias] = compositeData[targetNameKey];
    }
}

// Apply HANDLE_ALIASES: @handle key -> same data as target name-key
for (const [handle, targetNameKey] of Object.entries(HANDLE_ALIASES)) {
    if (compositeData[targetNameKey] !== undefined) {
        output[handle] = compositeData[targetNameKey];
    }
}

// =============================================================================
// STEP 8: Write output & print summary
// =============================================================================
fs.writeFileSync(outputPath, JSON.stringify(output, null, 2));

const totalEntries = Object.keys(output).length;
console.log(`\n✅ Successfully wrote bias_data.json with ${totalEntries} total entries.`);

// Count how many name-keys have 1/2/3/4 sources
const sourceCounts = { 1: 0, 2: 0, 3: 0, 4: 0 };
for (const entry of Object.values(compositeData)) {
    sourceCounts[entry.sources.length]++;
}
console.log('\nSource coverage (name-keys only):');
console.log(`  1 source:  ${sourceCounts[1]}`);
console.log(`  2 sources: ${sourceCounts[2]}`);
console.log(`  3 sources: ${sourceCounts[3]}`);
console.log(`  4 sources: ${sourceCounts[4]}`);

// Spot check nytimes
const nytKey = 'nytimes';
const nytTarget = DOMAIN_ALIASES[nytKey];
if (output[nytKey]) {
    console.log(`\nSpot check — "${nytKey}" (-> ${nytTarget}):`);
    console.log(`  score:      ${output[nytKey].score}`);
    console.log(`  confidence: ${output[nytKey].confidence}`);
    console.log(`  sources:    ${output[nytKey].sources.join(', ')}`);
} else if (output[nytTarget]) {
    console.log(`\nSpot check — "${nytTarget}":`);
    console.log(`  score:      ${output[nytTarget].score}`);
    console.log(`  confidence: ${output[nytTarget].confidence}`);
    console.log(`  sources:    ${output[nytTarget].sources.join(', ')}`);
}
