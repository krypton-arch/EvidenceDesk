"""Verify the enhanced alternate-coverage card fields."""
import httpx, json, time

# Wait for test_evidence_desk to populate
time.sleep(15)

r = httpx.get('http://localhost:8000/api/feed')
d = r.json()

print("=== Alternate Coverage Card Verification ===\n")
found_any = False
for item in d['items']:
    alts = item.get('alternatives', [])
    if not alts:
        continue
    found_any = True
    print(f"Original: {item['value']} (score={item['score']:.2f}, {item['bias_label']})")
    print(f"  Tweet: {item.get('tweet_text','')[:60]}...")
    for a in alts:
        print(f"  ├─ {a['source_name'] or a['domain']}")
        print(f"  │  Position: {a['bias_label']} ({a['bias_score']:.2f})")
        print(f"  │  Relevance: {a.get('relevance_label','?')} ({a.get('relevance_pct',0)}%)")
        print(f"  │  Perspective: {a.get('perspective_diff','?')}")
        print(f"  │  Confidence: {(a['confidence']*100):.0f}% ({a.get('confidence_qualifier','?')})")
        print(f"  │  Published: {a.get('published','?')}")
        print(f"  │  URL: {a['url'][:60]}...")
    print()

if not found_any:
    print("No alternates found yet — data may still be populating.")
