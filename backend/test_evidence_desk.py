"""Populate the Evidence Desk with realistic test data to verify all features."""
import httpx, json, time

# Reset session state for reproducible runs
print("Resetting session state...")
httpx.post('http://localhost:8000/api/reset')

captures = [
    # Immigration story cluster
    {"type":"domain","value":"foxnews.com","score":0.65,"confidence":0.8,"sources":["allsides","pabs"],
     "tweet_text":"Supreme Court rules on major immigration case affecting border policy deportation","tweet_id":"1","timestamp":time.time()*1000},
    {"type":"domain","value":"cnn.com","score":-0.42,"confidence":0.78,"sources":["allsides","pabs","gdelt"],
     "tweet_text":"Supreme Court immigration ruling border policy impact on asylum seekers","tweet_id":"2","timestamp":time.time()*1000},
    {"type":"handle","value":"nytimes","score":-0.465,"confidence":0.71,"sources":["allsides","pabs","gdelt","qbias"],
     "tweet_text":"Analysis: Supreme Court border ruling shifts immigration enforcement powers","tweet_id":"3","timestamp":time.time()*1000},
    {"type":"domain","value":"breitbart.com","score":0.82,"confidence":0.75,"sources":["allsides","pabs"],
     "tweet_text":"Supreme Court delivers major win on border security immigration enforcement","tweet_id":"4","timestamp":time.time()*1000},

    # Federal Reserve story cluster
    {"type":"domain","value":"apnews.com","score":-0.05,"confidence":0.85,"sources":["allsides","gdelt","pabs","qbias"],
     "tweet_text":"Federal Reserve signals potential rate cut amid cooling inflation data","tweet_id":"5","timestamp":time.time()*1000},
    {"type":"handle","value":"reuters","score":0.02,"confidence":0.82,"sources":["allsides","gdelt","pabs"],
     "tweet_text":"Federal Reserve rate decision inflation expectations economic outlook","tweet_id":"6","timestamp":time.time()*1000},
    {"type":"handle","value":"WSJ","score":0.28,"confidence":0.76,"sources":["allsides","pabs","qbias"],
     "tweet_text":"Fed rate cut expectations rise after inflation report economic data","tweet_id":"7","timestamp":time.time()*1000},

    # Tech/AI story cluster
    {"type":"domain","value":"theverge.com","score":-0.18,"confidence":0.62,"sources":["allsides","gdelt"],
     "tweet_text":"Elon Musk announces major changes to Twitter content moderation AI","tweet_id":"8","timestamp":time.time()*1000},
    {"type":"domain","value":"nypost.com","score":0.55,"confidence":0.73,"sources":["allsides","pabs"],
     "tweet_text":"Musk Twitter content policy changes free speech AI moderation","tweet_id":"9","timestamp":time.time()*1000},

    # Climate/environment
    {"type":"domain","value":"theguardian.com","score":-0.58,"confidence":0.69,"sources":["allsides","pabs","gdelt"],
     "tweet_text":"Hurricane season forecast predicts above average Atlantic storm activity climate","tweet_id":"10","timestamp":time.time()*1000},
    {"type":"domain","value":"dailywire.com","score":0.73,"confidence":0.68,"sources":["allsides","pabs"],
     "tweet_text":"Climate predictions Atlantic hurricane season weather forecasting accuracy","tweet_id":"11","timestamp":time.time()*1000},

    # Extra right-leaning to create concentration
    {"type":"handle","value":"FoxNews","score":0.60,"confidence":0.79,"sources":["allsides","pabs","gdelt"],
     "tweet_text":"Biden administration policy failures economic impact border crisis","tweet_id":"12","timestamp":time.time()*1000},
]

print(f"Sending {len(captures)} captures...")
total_latency = 0
for i, c in enumerate(captures):
    t0 = time.time()
    r = httpx.post('http://localhost:8000/api/capture', json=c)
    latency_ms = (time.time() - t0) * 1000
    total_latency += latency_ms
    d = r.json()
    print(f"  [{i+1:2d}] {c['value']:20s} -> {d['alternatives_found']} alternates  ({latency_ms:.0f}ms)")
    time.sleep(0.3)

avg_latency = total_latency / len(captures)
print(f"\n--- Latency ---")
print(f"Total: {total_latency:.0f}ms  |  Avg per capture: {avg_latency:.0f}ms (includes Google News RSS)")

# Check final state
r = httpx.get('http://localhost:8000/api/feed')
d = r.json()
print(f"\n{'='*60}")
print(f"Total captured: {d['stats']['total']}")
print(f"Unique sources: {d['stats']['unique_sources']}")
print(f"With alternates: {d['stats']['items_with_alts']}")
print(f"\n--- Rigidity Panel ---")
rig = d['rigidity']
print(f"State: {rig['state']}")
print(f"Concentration: {rig['concentration_pct']}% ({rig['confidence_qualifier']})")
print(f"Message: {rig['message']}")
print(f"Coverage: {rig['matched']} matched / {rig['scanned']} scanned")
print(f"L/C/R: {rig['left']}/{rig['center']}/{rig['right']}")
print(f"Why changed: {rig['why_changed']}")
print(f"\n--- Story Clusters ---")
for cl in d['clusters']:
    v = cl.get('verification_status', '?')
    print(f"  [{v}] '{cl['label']}' - {cl['count']} exposures - {cl['lean']} - {len(cl['alternatives'])} alternates")
print(f"\n--- Perspective Dots ---")
for dot in d['perspective_dots']:
    print(f"  {dot['value']:20s}  score={dot['score']:+.2f}  conf={dot['confidence']:.2f}  x{dot['count']}")
