import httpx, json, time

captures = [
    {"type":"domain","value":"cnn.com","score":-0.42,"confidence":0.78,"sources":["allsides","pabs","gdelt"],"tweet_text":"Biden administration announces new tariffs on Chinese goods in latest trade move","tweet_id":"456","timestamp":time.time()*1000},
    {"type":"handle","value":"nytimes","score":-0.465,"confidence":0.71,"sources":["allsides","pabs","gdelt","qbias"],"tweet_text":"Federal Reserve signals potential rate cut amid cooling inflation data","tweet_id":"789","timestamp":time.time()*1000},
    {"type":"domain","value":"breitbart.com","score":0.82,"confidence":0.75,"sources":["allsides","pabs"],"tweet_text":"Elon Musk announces major changes to Twitter content moderation policies","tweet_id":"101","timestamp":time.time()*1000},
    {"type":"domain","value":"apnews.com","score":-0.05,"confidence":0.85,"sources":["allsides","gdelt","pabs","qbias"],"tweet_text":"Hurricane season 2024 forecast predicts above average activity in Atlantic","tweet_id":"102","timestamp":time.time()*1000},
    {"type":"handle","value":"reuters","score":0.02,"confidence":0.82,"sources":["allsides","gdelt","pabs"],"tweet_text":"Tech stocks rally as AI spending surges among major companies","tweet_id":"103","timestamp":time.time()*1000},
]

for c in captures:
    r = httpx.post('http://localhost:8000/api/capture', json=c)
    d = r.json()
    print(f"{c['value']:20s} -> {d['alternatives_found']} alternates found")
    time.sleep(0.5)

# Summary
r = httpx.get('http://localhost:8000/api/feed')
d = r.json()
print(f"\nTotal: {d['stats']['total']} | With alts: {d['stats']['items_with_alts']} | Total alts: {d['stats']['total_alts_found']}")
