import re
import json
import os
import time
import httpx
import xml.etree.ElementTree as ET
from html import unescape
from datetime import datetime
from urllib.parse import urlparse, quote_plus
from collections import Counter
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List

# ── Data Loading ─────────────────────────────────────────────────────────────

bias_data = {}
bias_path = os.path.join(os.path.dirname(__file__), '..', 'bias_data.json')
if os.path.exists(bias_path):
    with open(bias_path, 'r', encoding='utf-8') as f:
        bias_data = json.load(f)

corpus_stats = {
    'total_entries': len(bias_data),
    'handle_entries': len([k for k in bias_data if k.startswith('@')]),
    'domain_entries': len([k for k in bias_data if not k.startswith('@')]),
    'sources': list(set(s for v in bias_data.values() for s in v.get('sources', []))),
    'multi_source_count': len([k for k, v in bias_data.items() if len(v.get('sources', [])) >= 2]),
    'high_confidence_count': len([k for k, v in bias_data.items() if v.get('confidence', 0) >= 0.7]),
}

# ── Domain Resolution (mirrored from content_script.js) ─────────────────────

def normalize_domain(hostname: str) -> str:
    domain = re.sub(r'^www\.', '', hostname)
    parts = domain.split('.')
    if len(parts) >= 2:
        last_two = ".".join(parts[-2:])
        if last_two in ['co.uk', 'com.au', 'co.nz', 'co.za', 'co.in']:
            core = "".join(parts[:-2]).lower()
            return re.sub(r'[^a-z0-9]', '', core)
    core = "".join(parts[:-1]).lower()
    return re.sub(r'[^a-z0-9]', '', core)

def try_multiple_keys(hostname: str):
    stripped = re.sub(r'^www\.', '', hostname)
    parts = stripped.split('.')
    key1 = normalize_domain(hostname)
    if key1 and key1 in bias_data:
        return {**bias_data[key1], 'matched_key': key1}
    key2 = re.sub(r'[^a-z0-9]', '', "".join(parts).lower())
    if key2 and key2 != key1 and key2 in bias_data:
        return {**bias_data[key2], 'matched_key': key2}
    if len(parts) > 2:
        last_two = ".".join(parts[-2:])
        key3 = None
        if last_two in ['co.uk', 'com.au', 'co.nz', 'co.za', 'co.in']:
            if len(parts) >= 3:
                key3 = re.sub(r'[^a-z0-9]', '', parts[-3].lower())
        else:
            key3 = re.sub(r'[^a-z0-9]', '', parts[-2].lower())
        if key3 and key3 != key1 and key3 != key2 and key3 in bias_data:
            return {**bias_data[key3], 'matched_key': key3}
    return None

def get_bias_label(score):
    if score < -0.6: return 'Far Left'
    if score < -0.3: return 'Left'
    if score < -0.1: return 'Lean Left'
    if score <= 0.1: return 'Center'
    if score <= 0.3: return 'Lean Right'
    if score <= 0.6: return 'Right'
    return 'Far Right'

def get_bias_color(score):
    if score < -0.3: return '#4a6fa5'   # muted slate-blue
    if score <= 0.3: return '#7a7a7a'   # neutral gray
    return '#a54a4a'                     # muted brick-red

# ── Google News RSS ──────────────────────────────────────────────────────────

STOPWORDS = {"a","an","and","are","as","at","be","but","by","for","from","has",
             "have","he","her","his","how","i","if","in","into","is","it","its",
             "me","my","no","not","of","on","or","our","s","she","so","such",
             "t","than","that","the","their","them","then","there","these","they",
             "this","to","too","us","very","was","we","were","what","when","where",
             "which","while","who","whom","will","with","would","you","your",
             "http","https","co","pic","twitter","com","rt","amp","via"}

news_cache = {}
NEWS_CACHE_TTL = 900  # 15 minutes

def extract_keywords(text: str, max_words: int = 6) -> str:
    """Extract top content words from tweet text for news search."""
    words = re.findall(r'[a-zA-Z]{3,}', text)
    filtered = [w for w in words if w.lower() not in STOPWORDS]
    return " ".join(filtered[:max_words])

async def query_google_news(keywords: str) -> list:
    """Query Google News RSS and return parsed articles."""
    if not keywords or len(keywords.strip()) < 4:
        return []
    cache_key = keywords.lower().strip()
    if cache_key in news_cache:
        cached, ts = news_cache[cache_key]
        if time.time() - ts < NEWS_CACHE_TTL:
            return cached
    url = f"https://news.google.com/rss/search?q={quote_plus(keywords)}&hl=en&gl=US&ceid=US:en"
    articles = []
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=8, follow_redirects=True)
            if resp.status_code == 200:
                root = ET.fromstring(resp.text)
                for item in root.findall('.//item'):
                    title_el = item.find('title')
                    link_el = item.find('link')
                    pub_el = item.find('pubDate')
                    source_el = item.find('source')
                    if title_el is not None and link_el is not None:
                        title = unescape(title_el.text or '')
                        link = link_el.text or ''
                        source_name = source_el.text if source_el is not None else ''
                        source_url = source_el.get('url', '') if source_el is not None else ''
                        domain = ''
                        try:
                            if source_url:
                                domain = urlparse(source_url).hostname or ''
                            if not domain:
                                domain = urlparse(link).hostname or ''
                            domain = domain.lower()
                        except:
                            pass
                        articles.append({
                            'title': title, 'url': link, 'domain': domain,
                            'source_name': source_name,
                            'published': pub_el.text if pub_el is not None else '',
                        })
    except Exception as e:
        print(f"[GoogleNews] Error: {e}")
    news_cache[cache_key] = (articles, time.time())
    return articles

def find_alternate_coverage(articles: list, original_domain: str, original_text: str = '', original_score: float = 0) -> list:
    """From a list of news articles, find bias-diverse alternatives with relevance and perspective analysis."""
    left_match = None
    center_match = None
    right_match = None

    # Extract keywords from original for relevance scoring
    orig_words = set(w.lower() for w in re.findall(r'[a-zA-Z]{3,}', original_text) if w.lower() not in STOPWORDS) if original_text else set()

    for article in articles:
        domain = article.get('domain', '')
        if not domain:
            continue
        norm_orig = normalize_domain(original_domain) if original_domain else ''
        norm_art = normalize_domain(domain)
        if norm_art == norm_orig:
            continue
        bias_info = try_multiple_keys(domain)
        if not bias_info:
            continue
        score = bias_info.get('score', 0)
        conf = bias_info.get('confidence', 0)

        # Relevance: keyword overlap between original text and alternate headline
        alt_words = set(w.lower() for w in re.findall(r'[a-zA-Z]{3,}', article['title']) if w.lower() not in STOPWORDS)
        if orig_words and alt_words:
            overlap = len(orig_words & alt_words)
            union = len(orig_words | alt_words)
            relevance = round(overlap / union * 100) if union else 0
        else:
            relevance = 0  # can't assess

        if relevance >= 40:
            rel_label = 'high'
        elif relevance >= 20:
            rel_label = 'moderate'
        elif relevance > 0:
            rel_label = 'low'
        else:
            rel_label = 'unknown'

        # Perspective difference summary
        score_diff = score - original_score
        if abs(score_diff) < 0.15:
            persp_diff = "Similar editorial positioning"
        elif score_diff > 0.5:
            persp_diff = f"Substantially more right-leaning (+{score_diff:.1f})"
        elif score_diff > 0.2:
            persp_diff = f"More right-leaning (+{score_diff:.1f})"
        elif score_diff < -0.5:
            persp_diff = f"Substantially more left-leaning ({score_diff:.1f})"
        elif score_diff < -0.2:
            persp_diff = f"More left-leaning ({score_diff:.1f})"
        else:
            persp_diff = f"Slightly different positioning ({score_diff:+.1f})"

        # Confidence qualifier
        n_sources = len(bias_info.get('sources', []))
        if n_sources >= 3:
            conf_qual = 'well-corroborated'
        elif n_sources == 2:
            conf_qual = 'corroborated'
        else:
            conf_qual = 'single-dataset'

        item = {
            'url': article['url'], 'title': article['title'],
            'domain': domain, 'source_name': article.get('source_name', ''),
            'bias_score': score, 'confidence': conf,
            'bias_label': get_bias_label(score), 'color': get_bias_color(score),
            'sources': bias_info.get('sources', []),
            'published': article.get('published', ''),
            'relevance_pct': relevance,
            'relevance_label': rel_label,
            'perspective_diff': persp_diff,
            'confidence_qualifier': conf_qual,
        }
        # Skip very-low-relevance matches — they are likely false positives
        if relevance < 10:
            continue
        if score < -0.3:
            if not left_match or (relevance > left_match.get('relevance_pct', 0)) or (relevance == left_match.get('relevance_pct', 0) and conf > left_match['confidence']):
                left_match = item
        elif score > 0.3:
            if not right_match or (relevance > right_match.get('relevance_pct', 0)) or (relevance == right_match.get('relevance_pct', 0) and conf > right_match['confidence']):
                right_match = item
        else:
            if not center_match or (relevance > center_match.get('relevance_pct', 0)) or (relevance == center_match.get('relevance_pct', 0) and conf > center_match['confidence']):
                center_match = item
    alts = []
    if left_match: alts.append(left_match)
    if center_match: alts.append(center_match)
    if right_match: alts.append(right_match)
    return alts

# ── Story Clustering ─────────────────────────────────────────────────────────

def cluster_stories(items: list) -> list:
    """Group captured items into story clusters based on keyword overlap."""
    clusters = []  # Each: { 'label': str, 'keywords': set, 'items': [] }
    for item in items:
        kw_str = item.get('query_keywords', '')
        if not kw_str:
            kw_str = extract_keywords(item.get('tweet_text', ''))
        words = set(w.lower() for w in kw_str.split() if len(w) >= 3)
        if not words:
            continue
        # Try to merge into an existing cluster
        best_cluster = None
        best_overlap = 0
        for c in clusters:
            overlap = len(words & c['keywords'])
            # Require at least 2 shared keywords or >40% Jaccard
            union = len(words | c['keywords'])
            jaccard = overlap / union if union else 0
            if overlap >= 2 or jaccard > 0.4:
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_cluster = c
        if best_cluster:
            best_cluster['items'].append(item)
            best_cluster['keywords'] |= words
        else:
            clusters.append({'keywords': words, 'items': [item]})

    # Generate labels and stats for each cluster
    result = []
    for c in clusters:
        items_in = c['items']
        scores = [i['score'] for i in items_in]
        avg = sum(scores) / len(scores) if scores else 0
        left_n = len([s for s in scores if s < -0.3])
        right_n = len([s for s in scores if s > 0.3])
        center_n = len(scores) - left_n - right_n
        # Label from most common keywords
        all_words = []
        for it in items_in:
            kw = it.get('query_keywords', '') or extract_keywords(it.get('tweet_text', ''))
            all_words.extend(w.lower() for w in kw.split() if len(w) >= 3)
        word_counts = Counter(all_words)
        label_words = [w for w, _ in word_counts.most_common(3)]
        label = " ".join(w.capitalize() for w in label_words) if label_words else "Uncategorized"
        keywords = [w for w, _ in word_counts.most_common(8)]
        # Determine lean
        if left_n > right_n and left_n > center_n:
            lean = "mostly Left"
        elif right_n > left_n and right_n > center_n:
            lean = "mostly Right"
        elif center_n >= left_n and center_n >= right_n:
            lean = "Center-leaning"
        else:
            lean = "mixed"
        # Collect all alternates
        all_alts = []
        for it in items_in:
            all_alts.extend(it.get('alternatives', []))
            
        # Try to use the best alternate coverage headline as the story title
        best_label = label
        if all_alts:
            best_alt = max(all_alts, key=lambda a: a.get('relevance_pct', 0))
            if best_alt.get('relevance_pct', 0) > 10:
                best_label = best_alt['title']
                
        # Description from first non-empty tweet
        desc = ""
        for it in items_in:
            if it.get('tweet_text'):
                desc = it['tweet_text']
                if len(desc) > 150:
                    desc = desc[:147] + "..."
                break

        # Determine Verification Status based on Corroboration Spectrum
        valid_alts = [a for a in all_alts if a.get('relevance_pct', 0) >= 20]
        alt_l = len([a for a in valid_alts if a.get('bias_score', 0) < -0.3])
        alt_r = len([a for a in valid_alts if a.get('bias_score', 0) > 0.3])
        alt_c = len([a for a in valid_alts if -0.3 <= a.get('bias_score', 0) <= 0.3])

        if len(valid_alts) == 0:
            v_status = "Unverified"
            v_reason = "No high-relevance alternate coverage found."
        elif alt_c > 0 and (alt_l > 0 or alt_r > 0):
            v_status = "Highly Verified"
            v_reason = "Corroborated by centrist and partisan sources."
        elif alt_l > 0 and alt_r > 0 and alt_c == 0:
            v_status = "Highly Verified"
            v_reason = "Corroborated by opposing partisan sources."
        elif alt_c > 0 and alt_l == 0 and alt_r == 0:
            v_status = "Establishment Verified"
            v_reason = "Corroborated exclusively by centrist sources."
        else:
            v_status = "Contested (Echo Chamber)"
            v_reason = "Corroborated exclusively by one-sided partisan sources."

        result.append({
            'label': best_label,
            'description': desc,
            'count': len(items_in),
            'lean': lean,
            'avg_score': round(avg, 3),
            'left': left_n, 'center': center_n, 'right': right_n,
            'keywords': keywords,
            'verification_status': v_status,
            'verification_reason': v_reason,
            'items': items_in,
            'alternatives': all_alts,
        })
    result.sort(key=lambda x: x['count'], reverse=True)
    return result

# ── Rigidity Explanation ─────────────────────────────────────────────────────

def compute_rigidity_panel(items: list, window: int = 25) -> dict:
    """Compute an interpretable rigidity/concentration panel."""
    total_scanned = len(items)
    recent = items[-window:] if len(items) >= window else items
    n = len(recent)
    if n == 0:
        return {
            'state': 'waiting',
            'message': 'Collecting evidence…',
            'concentration_pct': 0,
            'confidence_qualifier': 'no evidence',
            'matched': 0, 'scanned': 0,
            'window': window,
            'left': 0, 'center': 0, 'right': 0,
            'why_changed': '',
            'drift': [],
        }
    scores = [i['score'] for i in recent]
    avg = sum(scores) / n
    # Concentration = how clustered the scores are (inverse of diversity)
    # Use standard deviation: low SD = high concentration
    variance = sum((s - avg) ** 2 for s in scores) / n
    sd = variance ** 0.5
    # Max possible SD is ~1.0 (scores range -1 to 1), so normalize
    # concentration = 1 - normalized_sd (capped)
    concentration = max(0, min(100, int((1 - min(sd, 1.0)) * 100)))

    left_n = len([s for s in scores if s < -0.3])
    center_n = len([s for s in scores if -0.3 <= s <= 0.3])
    right_n = len([s for s in scores if s > 0.3])

    # Confidence qualifier
    if n < 5:
        state = 'collecting'
        qualifier = 'very limited evidence'
    elif n < 15:
        state = 'preliminary'
        qualifier = 'limited evidence'
    elif n < 25:
        state = 'developing'
        qualifier = 'moderate evidence'
    else:
        state = 'established'
        qualifier = 'substantial evidence'

    # "Why this changed" — look at last 5
    last5 = items[-5:] if len(items) >= 5 else items
    last5_left = len([i for i in last5 if i['score'] < -0.3])
    last5_right = len([i for i in last5 if i['score'] > 0.3])
    last5_center = len(last5) - last5_left - last5_right
    why_parts = []
    if last5_right > 0:
        why_parts.append(f"{last5_right} right-leaning source{'s' if last5_right > 1 else ''}")
    if last5_left > 0:
        why_parts.append(f"{last5_left} left-leaning source{'s' if last5_left > 1 else ''}")
    if last5_center > 0:
        why_parts.append(f"{last5_center} center source{'s' if last5_center > 1 else ''}")
    why_changed = f"{', '.join(why_parts)} in the last {len(last5)} matched posts." if why_parts else ""

    # Drift points for sparkline
    drift = []
    running = 0
    for idx, item in enumerate(recent):
        running = (running * idx + item['score']) / (idx + 1)
        drift.append(round(running, 4))

    return {
        'state': state,
        'message': f"Exposure concentration over the last {n} matched posts.",
        'concentration_pct': concentration,
        'confidence_qualifier': qualifier,
        'matched': n,
        'scanned': total_scanned,
        'window': window,
        'left': left_n, 'center': center_n, 'right': right_n,
        'avg_score': round(avg, 4),
        'why_changed': why_changed,
        'drift': drift,
    }

# ── In-Memory Session Store ─────────────────────────────────────────────────

captured_items = []
session_start = time.time()
posts_scanned = 0  # incremented by capture endpoint

# ── Models ───────────────────────────────────────────────────────────────────

class CaptureSignal(BaseModel):
    type: str
    value: str
    score: float
    confidence: float
    sources: List[str]
    tweet_text: Optional[str] = ''
    tweet_id: Optional[str] = ''
    timestamp: float

# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API Endpoints ────────────────────────────────────────────────────────────

@app.post("/api/reset")
async def reset_session():
    """Clear all session state for reproducible test runs."""
    global captured_items, posts_scanned, session_start
    captured_items = []
    posts_scanned = 0
    session_start = time.time()
    return {"status": "reset", "message": "Session cleared."}

@app.post("/api/capture")
async def capture_item(signal: CaptureSignal):
    """Receives each scored handle/domain from the extension, queries Google News for alternates."""
    global posts_scanned
    posts_scanned += 1
    item = signal.dict()
    item['bias_label'] = get_bias_label(signal.score)
    item['color'] = get_bias_color(signal.score)
    item['alternatives'] = []

    if signal.type == 'handle':
        key = '@' + signal.value
        if key in bias_data:
            item['corpus_data'] = bias_data[key]
    else:
        info = try_multiple_keys(signal.value)
        if info:
            item['corpus_data'] = {k: v for k, v in info.items() if k != 'matched_key'}
            item['matched_key'] = info.get('matched_key', '')

    if signal.tweet_text and len(signal.tweet_text.strip()) > 10:
        keywords = extract_keywords(signal.tweet_text)
        if keywords:
            articles = await query_google_news(keywords)
            alts = find_alternate_coverage(articles, signal.value, signal.tweet_text, signal.score)
            item['alternatives'] = alts
            item['query_keywords'] = keywords
            item['query_results_total'] = len(articles)
            item['query_matched_corpus'] = len([a for a in articles if try_multiple_keys(a.get('domain',''))])

    captured_items.append(item)
    return {"status": "ok", "total_captured": len(captured_items), "alternatives_found": len(item['alternatives'])}

@app.get("/api/feed")
async def get_feed():
    """Returns all captured items with stats, clusters, and rigidity panel."""
    scores = [i['score'] for i in captured_items]
    left = [i for i in captured_items if i['score'] < -0.3]
    center = [i for i in captured_items if -0.3 <= i['score'] <= 0.3]
    right = [i for i in captured_items if i['score'] > 0.3]

    source_counts = {}
    for item in captured_items:
        for s in item.get('sources', []):
            source_counts[s] = source_counts.get(s, 0) + 1

    items_with_alts = [i for i in captured_items if i.get('alternatives')]
    total_alts = sum(len(i.get('alternatives', [])) for i in captured_items)
    avg_confidence = sum(i.get('confidence', 0) for i in captured_items) / len(captured_items) if captured_items else 0

    # Rigidity panel
    rigidity = compute_rigidity_panel(captured_items)

    # Story clusters
    clusters = cluster_stories(captured_items)

    # Perspective map dots
    perspective_dots = []
    source_seen = {}
    for item in captured_items:
        key = item['value']
        if key not in source_seen:
            source_seen[key] = {'score': item['score'], 'confidence': item['confidence'], 'count': 0, 'value': key, 'label': item['bias_label']}
        source_seen[key]['count'] += 1
    perspective_dots = list(source_seen.values())

    # Information Nutrition Label logic
    nutrition = {"establishment": 0, "commentary": 0, "niche": 0}
    for item in captured_items:
        conf = item.get('confidence', 0)
        score = item.get('score', 0)
        if conf >= 0.75:
            nutrition["establishment"] += 1
        elif conf < 0.75 and abs(score) > 0.3:
            nutrition["commentary"] += 1
        else:
            nutrition["niche"] += 1

    return {
        "items": captured_items[-100:],
        "stats": {
            "total": len(captured_items),
            "posts_scanned": posts_scanned,
            "unique_sources": len(source_seen),
            "left": len(left), "center": len(center), "right": len(right),
            "avg_score": sum(scores) / len(scores) if scores else 0,
            "source_counts": source_counts,
            "items_with_alts": len(items_with_alts),
            "total_alts_found": total_alts,
            "avg_confidence": round(avg_confidence, 3),
            "session_start": session_start,
            "nutrition": nutrition,
        },
        "rigidity": rigidity,
        "clusters": clusters,
        "perspective_dots": perspective_dots,
        "corpus_stats": corpus_stats,
    }

@app.get("/api/lookup/{key}")
async def lookup_key(key: str):
    if key in bias_data:
        return {"key": key, "found": True, "data": bias_data[key], "label": get_bias_label(bias_data[key]['score'])}
    handle_key = '@' + key
    if handle_key in bias_data:
        return {"key": handle_key, "found": True, "data": bias_data[handle_key], "label": get_bias_label(bias_data[handle_key]['score'])}
    info = try_multiple_keys(key)
    if info:
        return {"key": info.get('matched_key', key), "found": True, "data": {k: v for k, v in info.items() if k != 'matched_key'}, "label": get_bias_label(info['score'])}
    return {"key": key, "found": False}

@app.get("/api/corpus/browse")
async def browse_corpus(offset: int = 0, limit: int = 50, filter: str = '', sort: str = 'score'):
    entries = []
    for key, val in bias_data.items():
        if filter:
            if filter == 'handles' and not key.startswith('@'): continue
            if filter == 'domains' and key.startswith('@'): continue
            if filter == 'left' and val['score'] >= -0.3: continue
            if filter == 'right' and val['score'] <= 0.3: continue
            if filter == 'center' and (val['score'] < -0.3 or val['score'] > 0.3): continue
            if filter == 'high_conf' and val.get('confidence', 0) < 0.7: continue
            if filter == 'multi_source' and len(val.get('sources', [])) < 2: continue
        entries.append({
            'key': key, 'score': val['score'], 'confidence': val.get('confidence', 0),
            'sources': val.get('sources', []), 'label': get_bias_label(val['score']), 'color': get_bias_color(val['score']),
        })
    if sort == 'score': entries.sort(key=lambda x: x['score'])
    elif sort == 'confidence': entries.sort(key=lambda x: x['confidence'], reverse=True)
    elif sort == 'sources': entries.sort(key=lambda x: len(x['sources']), reverse=True)
    elif sort == 'alpha': entries.sort(key=lambda x: x['key'])
    total = len(entries)
    return {"total": total, "offset": offset, "limit": limit, "entries": entries[offset:offset + limit]}

@app.get("/api/corpus/distribution")
async def corpus_distribution():
    buckets = {}
    for val in bias_data.values():
        bucket = round(val['score'], 1)
        buckets[bucket] = buckets.get(bucket, 0) + 1
    return {"distribution": [{"score": k, "count": v} for k, v in sorted(buckets.items())], "total": len(bias_data)}

# ── Dashboard HTML ───────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return DASHBOARD_HTML

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Evidence Desk — Social Bias Auditor</title>
<link href="https://fonts.googleapis.com/css2?family=Source+Serif+4:wght@400;600;700&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #111113; --bg-surface: #1a1a1e; --bg-card: rgba(255,255,255,0.03);
  --border: rgba(255,255,255,0.08); --border-active: rgba(255,255,255,0.16);
  --ink: #e8e6e1; --ink2: rgba(232,230,225,0.7); --muted: rgba(232,230,225,0.4);
  --left: #4a6fa5; --center: #8a8a7a; --right: #a54a4a;
  --green: #5a9a6a; --orange: #c9873a; --accent: #b8a070;
}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--ink);min-height:100vh;font-size:14px;line-height:1.6}
h1,h2,h3,.serif{font-family:'Source Serif 4','Georgia',serif}
.app{max-width:1200px;margin:0 auto;padding:0 32px;padding-bottom:100px}

/* ── Status Strip ── */
.status-strip{padding:10px 0;border-bottom:1px solid var(--border);font-size:11px;color:var(--muted);display:flex;align-items:center;gap:8px;letter-spacing:0.4px;text-transform:uppercase}
.status-dot{width:6px;height:6px;border-radius:50%;flex-shrink:0}
.status-dot.connected{background:var(--green);box-shadow:0 0 6px var(--green)}
.status-dot.disconnected{background:var(--right);box-shadow:0 0 6px var(--right)}

/* ── Header ── */
.header{padding:40px 0 32px;border-bottom:1px solid var(--border)}
.header h1{font-size:28px;font-weight:700;color:var(--ink);letter-spacing:-0.5px}
.header-sub{font-size:13px;color:var(--muted);margin-top:6px}

/* ── Tabs ── */
.tabs{display:flex;gap:24px;border-bottom:1px solid var(--border);margin-top:0}
.tab{padding:16px 0;font-size:13px;font-weight:500;color:var(--muted);cursor:pointer;border-bottom:2px solid transparent;transition:.2s;letter-spacing:0.2px}
.tab:hover{color:var(--ink2)}
.tab.active{color:var(--ink);border-bottom-color:var(--accent)}

/* ── Bento Grid (Analytics) ── */
.bento-grid{display:grid;grid-template-columns:repeat(12, 1fr);gap:20px;padding:32px 0;border-bottom:1px solid var(--border)}
.bento-card{background:var(--bg-card);border:1px solid var(--border);border-radius:12px;padding:24px;display:flex;flex-direction:column}
.bento-title{font-family:'Source Serif 4',serif;font-size:16px;font-weight:600;margin-bottom:8px;color:var(--ink)}
.bento-sub{font-size:12px;color:var(--muted);margin-bottom:16px}

/* ── 2D Media Matrix ── */
.map-container{position:relative;height:240px;background:rgba(255,255,255,0.02);border-radius:8px;margin-top:12px;border:1px solid rgba(255,255,255,0.05);overflow:hidden;cursor:crosshair}
.map-axis-x{position:absolute;top:50%;left:0;right:0;height:1px;background:rgba(255,255,255,0.1);z-index:1}
.map-axis-y{position:absolute;top:0;bottom:0;left:50%;width:1px;background:rgba(255,255,255,0.1);z-index:1}
.quad-label{position:absolute;font-size:10px;color:rgba(255,255,255,0.2);text-transform:uppercase;letter-spacing:1px;z-index:1;font-weight:700}
.quad-tl{top:12px;left:12px} .quad-tr{top:12px;right:12px}
.quad-bl{bottom:12px;left:12px} .quad-br{bottom:12px;right:12px}
.map-dot{position:absolute;width:12px;height:12px;border-radius:50%;transform:translate(-50%,-50%);z-index:2;box-shadow:0 0 10px rgba(0,0,0,0.5);border:2px solid rgba(255,255,255,0.8);transition:transform 0.2s}
.map-dot:hover{transform:translate(-50%,-50%) scale(1.5);z-index:10}
.map-tooltip{position:absolute;bottom:100%;left:50%;transform:translateX(-50%);background:var(--bg-card);color:var(--ink);padding:6px 10px;border-radius:6px;font-size:11px;white-space:nowrap;opacity:0;pointer-events:none;transition:opacity 0.2s, bottom 0.2s;border:1px solid var(--border);margin-bottom:8px;box-shadow:0 4px 12px rgba(0,0,0,0.3);z-index:20}
.map-dot:hover .map-tooltip{opacity:1;bottom:calc(100% + 4px)}
.map-legend{display:flex;justify-content:space-between;font-size:11px;color:var(--muted);margin-top:12px;padding:0 4px}
.map-legend-y{position:absolute;top:0;bottom:0;left:-20px;font-size:10px;color:var(--muted);writing-mode:vertical-rl;transform:rotate(180deg);display:flex;justify-content:space-between;padding:12px 0}

/* ── Information Nutrition ── */
.nutrition-content{display:flex;flex-direction:column;gap:12px;height:100%;justify-content:center}
.nutri-row{display:flex;justify-content:space-between;align-items:center;font-family:'Source Serif 4',serif;font-size:15px;border-bottom:1px solid rgba(255,255,255,0.05);padding-bottom:8px}
.nutri-row:last-child{border-bottom:none}
.nutri-val{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;font-weight:700;font-size:16px}
.nutri-bar{height:4px;background:rgba(255,255,255,0.05);border-radius:2px;margin-top:4px;overflow:hidden}
.nutri-fill{height:100%;background:var(--ink2);border-radius:2px}

/* ── Stories Data-Dense Layout ── */
.tab-content{display:none;padding:32px 0}.tab-content.active{display:block}
.cluster{background:var(--bg-card);border:1px solid var(--border);border-radius:12px;margin-bottom:24px;overflow:hidden;transition:border-color 0.2s}
.cluster:hover{border-color:var(--border-active)}
.cluster-header{padding:20px 24px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;background:rgba(255,255,255,0.01);cursor:pointer;transition:background 0.2s}
.cluster-header:hover{background:rgba(255,255,255,0.03)}
.cluster-header-left{display:flex;flex-direction:column;gap:6px}
.cluster-label{font-family:'Source Serif 4',serif;font-size:18px;font-weight:600;display:flex;align-items:flex-start;gap:10px;line-height:1.2}
.cluster-desc{font-size:12px;color:var(--ink2);margin-left:26px;font-style:italic;line-height:1.4}
.cluster-keywords{font-size:11px;color:var(--muted);display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-left:26px}
.cluster-kw{background:rgba(255,255,255,0.04);padding:2px 6px;border-radius:4px;letter-spacing:0.3px}
.cluster-meta{display:flex;align-items:center;gap:16px;font-size:12px;color:var(--muted)}
.cluster-lean{font-size:10px;font-weight:700;padding:3px 8px;border-radius:4px;text-transform:uppercase;letter-spacing:0.5px}
.verif-badge{font-size:10px;font-weight:700;padding:3px 8px;border-radius:4px;display:inline-flex;align-items:center;gap:4px;letter-spacing:0.3px}
.verif-highly{background:rgba(90,154,106,0.15);color:var(--green);border:1px solid rgba(90,154,106,0.3)}
.verif-est{background:rgba(74,111,165,0.15);color:#7ca8e6;border:1px solid rgba(74,111,165,0.3)}
.verif-contested{background:rgba(201,135,58,0.15);color:var(--orange);border:1px solid rgba(201,135,58,0.3)}
.verif-unverified{background:rgba(255,255,255,0.05);color:var(--muted);border:1px solid var(--border)}
.cluster-mini-bar{display:flex;width:60px;height:4px;border-radius:2px;overflow:hidden;background:rgba(255,255,255,0.04)}
.chevron{width:16px;height:16px;stroke:currentColor;stroke-width:2;fill:none;transition:transform 0.3s}
.cluster-body{max-height:0;overflow:hidden;transition:max-height 0.4s cubic-bezier(0,1,0,1)}
.cluster-body.open{max-height:5000px;transition:max-height 0.8s ease-in-out}

.cluster-grid{display:grid;grid-template-columns:1fr 1fr;gap:0}
.cluster-col{padding:20px 24px}
.cap-col{border-right:1px solid var(--border)}
.col-header{font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:0.8px;margin-bottom:16px}

/* Capture Item */
.cap-item{padding:12px 0;border-bottom:1px solid rgba(255,255,255,0.04);display:flex;gap:12px}
.cap-item:last-child{border-bottom:none}
.cap-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0;margin-top:6px}
.cap-body{flex:1;min-width:0}
.cap-source{font-size:14px;font-weight:600;display:flex;align-items:center;gap:8px;margin-bottom:4px}
.cap-text{font-size:13px;color:var(--ink2);line-height:1.6}
.cap-meta{font-size:11px;color:var(--muted);margin-top:6px;display:flex;gap:8px;align-items:center}
.cap-score{font-size:13px;font-weight:700;font-variant-numeric:tabular-nums;flex-shrink:0}

/* Source Tags */
.src-tag{font-size:9px;font-weight:700;padding:2px 6px;border-radius:4px;text-transform:uppercase;letter-spacing:0.4px}
.src-allsides{background:rgba(90,154,106,0.15);color:var(--green)}
.src-gdelt{background:rgba(74,111,165,0.15);color:var(--left)}
.src-pabs{background:rgba(201,135,58,0.15);color:var(--orange)}
.src-qbias{background:rgba(138,138,122,0.15);color:var(--center)}

/* Alternate Card */
.alt-card{padding:12px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);border-radius:8px;margin-bottom:12px;display:flex;gap:12px;transition:.2s}
.alt-card:hover{background:rgba(255,255,255,0.04);border-color:var(--border-active)}
.alt-bar{width:4px;border-radius:2px;align-self:stretch;flex-shrink:0}
.alt-info{flex:1;min-width:0}
.alt-title{font-size:14px;font-weight:500;margin-bottom:6px;line-height:1.4}
.alt-title a{color:var(--ink);text-decoration:none}
.alt-title a:hover{text-decoration:underline}
.alt-meta{font-size:11px;color:var(--muted);display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:6px}
.alt-conf{display:flex;align-items:center;gap:4px}
.alt-conf-bar{width:30px;height:4px;background:rgba(255,255,255,0.08);border-radius:2px;overflow:hidden}
.alt-conf-fill{height:100%;border-radius:2px;background:var(--green)}
.no-alts{font-size:13px;color:var(--muted);font-style:italic;padding:12px;background:rgba(255,255,255,0.02);border-radius:8px}

.rel-badge{font-size:10px;font-weight:700;padding:2px 6px;border-radius:4px;text-transform:uppercase;letter-spacing:0.4px}
.rel-high{background:rgba(90,154,106,0.2);color:var(--green)}
.rel-moderate{background:rgba(201,135,58,0.2);color:var(--orange)}
.rel-low{background:rgba(165,74,74,0.15);color:var(--right)}
.rel-unknown{background:rgba(138,138,122,0.15);color:var(--center)}
.persp-diff{font-size:12px;color:var(--ink2);padding-top:6px;border-top:1px dashed rgba(255,255,255,0.08)}
.conf-qual{font-size:10px;color:var(--muted);padding:1px 6px;border:1px solid var(--border);border-radius:4px}

.bias-badge{font-size:10px;font-weight:700;padding:2px 6px;border-radius:4px;letter-spacing:0.3px}
.bias-left{background:rgba(74,111,165,0.2);color:var(--left)}
.bias-center{background:rgba(138,138,122,0.2);color:var(--center)}
.bias-right{background:rgba(165,74,74,0.2);color:var(--right)}

/* ── Methodology ── */
.methodology{margin-top:32px;padding:24px;border:1px solid var(--border);border-radius:12px;background:rgba(255,255,255,0.01)}
.meth-title{font-family:'Source Serif 4',serif;font-size:16px;font-weight:600;margin-bottom:12px}
.meth-inner{font-size:12px;color:var(--ink2);line-height:1.7;column-count:2;column-gap:32px}

/* ── Corpus Browser ── */
.browser-filters{display:flex;gap:6px;margin-bottom:20px;flex-wrap:wrap}
.bfilt{font-size:12px;font-weight:500;padding:6px 14px;border-radius:6px;border:1px solid var(--border);background:var(--bg-card);color:var(--muted);cursor:pointer;transition:.2s}
.bfilt:hover{border-color:var(--border-active);color:var(--ink2)}
.bfilt.active{background:rgba(184,160,112,0.15);border-color:var(--accent);color:var(--accent)}
.bento-wide{grid-column:1 / -1}
.bento-nutrition{grid-column:1 / -1}
@media(min-width:900px){
  .bento-nutrition{grid-column:span 4}
  .bento-card:nth-child(1){grid-column:span 4}
  .bento-card:nth-child(2){grid-column:span 4}
}
.bento-title{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:var(--muted);margin-bottom:16px}
.ctable{width:100%;border-collapse:collapse;background:var(--bg-card);border-radius:12px;overflow:hidden;border:1px solid var(--border)}
.ctable th{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.6px;color:var(--muted);text-align:left;padding:12px 16px;border-bottom:1px solid var(--border);cursor:pointer;background:rgba(255,255,255,0.02)}
.ctable td{padding:12px 16px;font-size:13px;border-bottom:1px solid rgba(255,255,255,0.03)}
.ctable tr:last-child td{border-bottom:none}
.ctable tr:hover td{background:rgba(255,255,255,0.03)}
.page-nav{display:flex;justify-content:center;gap:12px;margin-top:20px}

::-webkit-scrollbar{width:6px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.1);border-radius:3px}
@media(max-width:900px){
  .bento-card{grid-column:span 12 !important}
  .cluster-grid{grid-template-columns:1fr}
  .cap-col{border-right:none;border-bottom:1px solid var(--border)}
  .meth-inner{column-count:1}
}
</style>
</head>
<body>
<div class="app">

  <div class="status-strip" id="statusStrip">
    <div class="status-dot disconnected" id="statusDot"></div>
    <span id="statusText">Connecting to companion service…</span>
  </div>

  <div class="header">
    <h1>Evidence Desk</h1>
    <div class="header-sub">Bias exposure analysis · Fused corpus of 20,336 sources (AllSides + GDELT + Qbias + PABS)</div>
  </div>

  <div class="tabs">
    <div class="tab active" data-tab="analytics">Analytics</div>
    <div class="tab" data-tab="stories">Stories</div>
    <div class="tab" data-tab="corpus">Corpus</div>
  </div>

  <!-- Analytics Bento Grid -->
  <div class="tab-content active" id="tab-analytics">
    <div class="bento-grid">
      <div class="bento-card bento-hero">
        <div class="bento-title">Echo Chamber Concentration</div>
        <div id="panelConcentration" class="hero-value">--</div>
        <div id="panelQualifier" class="bento-subtitle" style="margin-bottom:12px">--</div>
        <div id="panelMessage" class="bento-desc"></div>
      </div>
      <div class="bento-card">
        <div class="bento-title">Exposure Distribution</div>
        <div id="panelLCR" class="hero-value" style="font-size:28px">--</div>
        <div class="dist-bar"><div id="distLeft"></div><div id="distCenter"></div><div id="distRight"></div></div>
        <div class="dist-labels"><span>Left</span><span>Center</span><span>Right</span></div>
        <div id="panelWhy" class="bento-desc" style="margin-top:16px"></div>
      </div>
      <div class="bento-card bento-nutrition">
        <div class="bento-title">Information Nutrition</div>
        <div id="nutritionLabel" class="nutrition-content"></div>
      </div>
      <div class="bento-card bento-wide">
        <div class="bento-title">2D Media Matrix (Quality vs Bias)</div>
        <div class="map-container" id="perspectiveMap">
          <!-- Matrix Quadrant Labels -->
          <div class="quad-label quad-tl">Left-Leaning Fact</div>
          <div class="quad-label quad-tr">Right-Leaning Fact</div>
          <div class="quad-label quad-bl">Left-Leaning Opinion</div>
          <div class="quad-label quad-br">Right-Leaning Opinion</div>
          <div class="map-axis-x"></div><div class="map-axis-y"></div>
          <div id="mapDots"></div>
        </div>
        <div class="map-legend">
          <span>&larr; Left Bias</span>
          <span>Center</span>
          <span>Right Bias &rarr;</span>
        </div>
        <div class="map-legend-y">
          <span style="position:absolute;top:-10px;left:0">High Confidence (Fact) &uarr;</span>
          <span style="position:absolute;bottom:-10px;left:0">Low Confidence (Opinion) &darr;</span>
        </div>
      </div>
    </div>
  </div>

  <!-- Stories Tab -->
  <div class="tab-content" id="tab-stories">
    <div style="font-size:13px;color:var(--muted);margin-bottom:24px" id="clusterSummary">Captures will be grouped by topic as they arrive.</div>
    <div id="clusterList"></div>
  </div>

  <!-- Corpus Tab -->
  <div class="tab-content" id="tab-corpus">
    <div class="bento-title" style="margin-bottom:8px">Fused Source Corpus</div>
    <div class="bento-sub" style="margin-bottom:24px">Browse all 20,336 scored domains and handles across four datasets.</div>
    <div class="browser-filters" id="browserFilters">
      <button class="bfilt active" data-filter="">All</button>
      <button class="bfilt" data-filter="handles">Handles</button>
      <button class="bfilt" data-filter="domains">Domains</button>
      <button class="bfilt" data-filter="left">Left</button>
      <button class="bfilt" data-filter="center">Center</button>
      <button class="bfilt" data-filter="right">Right</button>
      <button class="bfilt" data-filter="high_conf">High Conf.</button>
      <button class="bfilt" data-filter="multi_source">Multi-Source</button>
    </div>
    <table class="ctable"><thead><tr>
      <th data-sort="alpha">Source</th><th data-sort="score">Score</th>
      <th data-sort="confidence">Confidence</th><th>Position</th><th data-sort="sources">Datasets</th>
    </tr></thead><tbody id="corpusBody"></tbody></table>
    <div class="page-nav" id="pageNav"></div>
  </div>

  <!-- Methodology -->
  <div class="methodology">
    <div class="meth-title">Methodology & Limitations</div>
    <div class="meth-inner">
      <strong>What scores represent:</strong> Source-position scores reflect the historical/structural ideological positioning of linked sources and accounts as measured across four independent datasets. They do <em>not</em> measure the truthfulness, quality, or political intent of any individual post.<br><br>
      <strong>Concentration metric:</strong> Exposure concentration is computed as the inverse of score variance across a rolling window. High concentration means the feed clusters around a narrow band of the ideological spectrum. The metric intentionally avoids causal claims about behavior.<br><br>
      <strong>Alternate coverage:</strong> Alternate articles are retrieved via Google News RSS and cross-referenced against the fused corpus for bias labeling. Relevance depends on keyword extraction quality; not all matches describe the same event.<br><br>
      <strong>Confidence:</strong> Multi-dataset corroboration increases confidence. Scores from a single dataset are labeled "single-dataset".<br><br>
      <strong>Privacy:</strong> The core rigidity score runs entirely in-browser with zero telemetry. This companion dashboard receives captured domains/handles and tweet text to provide alternate coverage — a deliberate architectural trade-off documented in the dual-trust model.
    </div>
  </div>

</div>

<script>
let cFilter='',cSort='score',cOffset=0;const PS=50;
let lastEventTime=0,connectionOk=false;

document.querySelectorAll('.tab').forEach(t=>{t.addEventListener('click',()=>{
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(x=>x.classList.remove('active'));
  t.classList.add('active');document.getElementById('tab-'+t.dataset.tab).classList.add('active');
  if(t.dataset.tab==='corpus')loadCorpus();
})});

async function refresh(){
  try{
    const r=await fetch('/api/feed');const d=await r.json();
    connectionOk=true;lastEventTime=Date.now();
    renderStatus(d);renderDashboard(d);
  }catch(e){connectionOk=false;renderStatusDisconnected();console.error(e)}
}

function renderStatus(d){
  const s=d.stats;
  const dot=document.getElementById('statusDot');
  dot.className='status-dot connected';
  const ago=s.total>0?Math.round((Date.now()-lastEventTime)/1000):0;
  document.getElementById('statusText').textContent=
    `Companion connected · ${s.total} captures · ${s.unique_sources} unique sources${ago>0?' · Last event '+ago+'s ago':''}`;
}

function renderDashboard(data){
  const r = data.rigidity;
  const stats = data.stats;
  
  // Concentration/Rigidity
  document.getElementById('panelConcentration').textContent = r.state === 'waiting' ? '--' : r.concentration_pct + '%';
  document.getElementById('panelQualifier').textContent = r.confidence_qualifier || '--';
  document.getElementById('panelMessage').textContent = r.why_changed || 'Waiting for activity...';

  // LCR Distribution
  document.getElementById('panelLCR').textContent = `${r.left}/${r.center}/${r.right}`;
  const tot = r.left + r.center + r.right || 1;
  document.getElementById('distLeft').style.width = (r.left/tot*100) + '%';
  document.getElementById('distCenter').style.width = (r.center/tot*100) + '%';
  document.getElementById('distRight').style.width = (r.right/tot*100) + '%';

  // Nutrition Label
  const nut = stats.nutrition || {establishment:0, commentary:0, niche:0};
  const totNut = stats.total || 1;
  document.getElementById('nutritionLabel').innerHTML = `
    <div class="nutri-row">
      <div>Establishment News<div class="nutri-bar"><div class="nutri-fill" style="width:${(nut.establishment/totNut)*100}%"></div></div></div>
      <div class="nutri-val">${Math.round((nut.establishment/totNut)*100)}%</div>
    </div>
    <div class="nutri-row">
      <div>Commentary / Opinion<div class="nutri-bar"><div class="nutri-fill" style="width:${(nut.commentary/totNut)*100}%"></div></div></div>
      <div class="nutri-val">${Math.round((nut.commentary/totNut)*100)}%</div>
    </div>
    <div class="nutri-row">
      <div>Niche / Independent<div class="nutri-bar"><div class="nutri-fill" style="width:${(nut.niche/totNut)*100}%"></div></div></div>
      <div class="nutri-val">${Math.round((nut.niche/totNut)*100)}%</div>
    </div>
  `;

  // 2D Media Matrix
  const dotsHtml = data.perspective_dots.map(d=>{
    const xPct = ((d.score + 1) / 2) * 100;
    const yPct = (1 - Math.max(0, Math.min(1, d.confidence))) * 100;
    
    let color = 'var(--center)';
    if(d.score<-0.3) color='var(--left)';
    if(d.score>0.3) color='var(--right)';
    
    return `<div class="map-dot" style="left:${xPct}%;top:${yPct}%;background:${color}">
      <div class="map-tooltip">
        <strong>${esc(d.value)}</strong><br>
        Bias: ${d.score>0?'+':''}${d.score.toFixed(2)} | Conf: ${d.confidence.toFixed(2)}<br>
        <span style="color:var(--muted)">${d.count} exposure${d.count>1?'s':''}</span>
      </div>
    </div>`;
  }).join('');
  document.getElementById('mapDots').innerHTML = dotsHtml;
  
  renderClusters(data.clusters);
}

function renderStatusDisconnected(){
  document.getElementById('statusDot').className='status-dot disconnected';
  document.getElementById('statusText').innerHTML='Backend unavailable — <a href="javascript:void(0)" onclick="refresh()" style="color:var(--orange);text-decoration:underline">retry</a> or start companion service';
}

function renderClusters(clusters){
  if(!clusters||!clusters.length){
    document.getElementById('clusterList').innerHTML='<div style="color:var(--muted);font-style:italic">No stories captured yet. Browse X/Twitter with the extension active.</div>';
    document.getElementById('clusterSummary').textContent='Captures will be grouped by topic as they arrive.';
    return;
  }
  document.getElementById('clusterSummary').textContent=clusters.length+' story cluster'+(clusters.length>1?'s':'')+' identified from captured posts.';
  document.getElementById('clusterList').innerHTML=clusters.map((cl,ci)=>{
    const leanClass=cl.lean.includes('Left')?'bias-left':cl.lean.includes('Right')?'bias-right':'bias-center';
    
    // Captures
    const itemsHtml=cl.items.map(it=>{
      const icon=it.type==='handle'?'@':'';
      const bc=it.score<-0.3?'bias-left':it.score>0.3?'bias-right':'bias-center';
      const srcs=(it.sources||[]).map(s=>'<span class="src-tag src-'+s+'">'+s+'</span>').join(' ');
      return '<div class="cap-item">'+
        '<div class="cap-dot" style="background:'+it.color+'"></div>'+
        '<div class="cap-body">'+
          '<div class="cap-source">'+icon+esc(it.value)+' <span class="bias-badge '+bc+'">'+it.bias_label+'</span></div>'+
          (it.tweet_text?'<div class="cap-text">'+esc(it.tweet_text)+'</div>':'')+
          '<div class="cap-meta">'+srcs+' <span>'+(it.confidence*100).toFixed(0)+'% conf</span></div>'+
        '</div>'+
        '<div class="cap-score" style="color:'+it.color+'">'+it.score.toFixed(2)+'</div>'+
      '</div>';
    }).join('');

    // Alternates
    let altsHtml='';
    if(cl.alternatives&&cl.alternatives.length){
      const seen=new Set();
      cl.alternatives.forEach(a=>{
        if(seen.has(a.domain))return;seen.add(a.domain);
        const abc=a.bias_score<-0.3?'bias-left':a.bias_score>0.3?'bias-right':'bias-center';
        const relClass='rel-'+(a.relevance_label||'unknown');
        const relText=a.relevance_label==='high'?'High relevance':a.relevance_label==='moderate'?'Moderate relevance':a.relevance_label==='low'?'Low relevance':'Relevance unknown';
        altsHtml+='<div class="alt-card">'+
          '<div class="alt-bar" style="background:'+a.color+'"></div>'+
          '<div class="alt-info">'+
            '<div class="alt-title"><a href="'+esc(a.url)+'" target="_blank">'+esc(a.title)+'</a></div>'+
            '<div class="alt-meta">'+
              '<span>'+esc(a.source_name||a.domain)+'</span> '+
              '<span class="bias-badge '+abc+'">'+a.bias_label+'</span> '+
              '<span class="rel-badge '+relClass+'">'+relText+'</span> '+
              '<span class="alt-conf"><span class="alt-conf-bar"><span class="alt-conf-fill" style="width:'+(a.confidence*100)+'%"></span></span>'+(a.confidence*100).toFixed(0)+'%</span> '+
              '<span class="conf-qual">'+(a.confidence_qualifier||'')+'</span>'+
              (a.published?' <span>'+formatDate(a.published)+'</span>':'')+
            '</div>'+
            (a.perspective_diff?'<div class="persp-diff">'+esc(a.perspective_diff)+'</div>':'')+
          '</div>'+
        '</div>';
      });
    } else {
      altsHtml='<div class="no-alts">No corpus-verified alternate coverage available. This may reflect limited keyword overlap with current news, not an absence of other perspectives.</div>';
    }

    const tot = cl.left + cl.center + cl.right || 1;
    const lPct = (cl.left/tot)*100, cPct = (cl.center/tot)*100, rPct = (cl.right/tot)*100;
    const kwHtml = cl.keywords ? cl.keywords.map(k=>`<span class="cluster-kw">${esc(k)}</span>`).join('') : '';

    const descHtml = cl.description ? '<div class="cluster-desc">"'+esc(cl.description)+'"</div>' : '';

    let vClass = 'verif-unverified';
    let vIcon = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>';
    if(cl.verification_status==='Highly Verified'){ vClass='verif-highly'; vIcon='<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>'; }
    else if(cl.verification_status==='Establishment Verified'){ vClass='verif-est'; vIcon='<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>'; }
    else if(cl.verification_status==='Contested (Echo Chamber)'){ vClass='verif-contested'; vIcon='<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'; }

    return '<div class="cluster">'+
      '<div class="cluster-header" onclick="toggleCluster(\'cl-'+ci+'\', this)">'+
        '<div class="cluster-header-left">'+
          '<div class="cluster-label">'+
            '<svg class="chevron" viewBox="0 0 24 24" style="transform:rotate(90deg);margin-top:2px;flex-shrink:0"><path d="M9 18l6-6-6-6"/></svg>'+
            '<span>'+esc(cl.label)+'</span>'+
          '</div>'+
          descHtml+
          '<div class="cluster-keywords">'+kwHtml+'</div>'+
        '</div>'+
        '<div class="cluster-meta">'+
          '<div class="verif-badge '+vClass+'" title="'+esc(cl.verification_reason)+'">'+vIcon+' '+cl.verification_status+'</div>'+
          '<div class="cluster-mini-bar">'+
            '<div style="width:'+lPct+'%;background:var(--left)"></div>'+
            '<div style="width:'+cPct+'%;background:var(--center)"></div>'+
            '<div style="width:'+rPct+'%;background:var(--right)"></div>'+
          '</div>'+
          '<span>'+cl.count+' exposure'+(cl.count>1?'s':'')+'</span>'+
          '<span class="cluster-lean '+leanClass+'">'+cl.lean+'</span>'+
        '</div>'+
      '</div>'+
      '<div class="cluster-body open" id="cl-'+ci+'">'+
        '<div class="cluster-grid">'+
          '<div class="cluster-col cap-col">'+
            '<div class="col-header">Your Exposure</div>'+
            itemsHtml+
          '</div>'+
          '<div class="cluster-col alt-col">'+
            '<div class="col-header">Alternate Coverage</div>'+
            altsHtml+
          '</div>'+
        '</div>'+
      '</div>'+
    '</div>';
  }).join('');
}
function toggleCluster(id, headerEl){
  const body = document.getElementById(id);
  const chevron = headerEl.querySelector('.chevron');
  body.classList.toggle('open');
  if(body.classList.contains('open')){
    chevron.style.transform='rotate(90deg)';
  } else {
    chevron.style.transform='rotate(0deg)';
  }
}

function loadCorpus(){
  fetch('/api/corpus/browse?offset='+cOffset+'&limit='+PS+'&filter='+cFilter+'&sort='+cSort)
    .then(r=>r.json()).then(renderCorpus).catch(console.error);
}
function renderCorpus(d){
  document.getElementById('corpusBody').innerHTML=d.entries.map(e=>{
    const bc=e.score<-0.3?'bias-left':e.score>0.3?'bias-right':'bias-center';
    const srcs=e.sources.map(s=>'<span class="src-tag src-'+s+'">'+s+'</span>').join(' ');
    return '<tr><td style="font-weight:600">'+esc(e.key)+'</td>'+
    '<td><span style="color:'+e.color+';font-weight:700">'+e.score.toFixed(3)+'</span></td>'+
    '<td><span class="alt-conf"><span class="alt-conf-bar"><span class="alt-conf-fill" style="width:'+(e.confidence*100)+'%"></span></span>'+(e.confidence*100).toFixed(0)+'%</span></td>'+
    '<td><span class="bias-badge '+bc+'">'+e.label+'</span></td>'+
    '<td>'+srcs+'</td></tr>';
  }).join('');
  const tp=Math.ceil(d.total/PS),cp=Math.floor(cOffset/PS)+1;
  document.getElementById('pageNav').innerHTML=
    '<button class="bfilt" '+(cOffset<=0?'disabled':'')+' onclick="cOffset-='+PS+';loadCorpus()">← Prev</button>'+
    '<span style="font-size:12px;color:var(--muted);padding:6px 12px">Page '+cp+' of '+tp+' ('+d.total.toLocaleString()+' entries)</span>'+
    '<button class="bfilt" '+(cOffset+PS>=d.total?'disabled':'')+' onclick="cOffset+='+PS+';loadCorpus()">Next →</button>';
}
document.getElementById('browserFilters').addEventListener('click',e=>{if(e.target.classList.contains('bfilt')){
  document.querySelectorAll('#browserFilters .bfilt').forEach(b=>b.classList.remove('active'));
  e.target.classList.add('active');cFilter=e.target.dataset.filter;cOffset=0;loadCorpus();
}});
document.querySelectorAll('.ctable th[data-sort]').forEach(th=>{th.addEventListener('click',()=>{cSort=th.dataset.sort;cOffset=0;loadCorpus()})});

function esc(s){if(!s)return'';const d=document.createElement('div');d.textContent=s;return d.innerHTML}
function formatDate(s){try{const d=new Date(s);return d.toLocaleDateString('en-US',{month:'short',day:'numeric'})}catch(e){return''}}

refresh();setInterval(refresh,4000);
</script>
</body>
</html>"""