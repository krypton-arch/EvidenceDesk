import httpx, json
r = httpx.get('http://localhost:8000/api/feed')
d = r.json()
items = d['items']
print('Total:', d['stats']['total'])
print('With alts:', d['stats']['items_with_alts'])
print('Total alts:', d['stats']['total_alts_found'])
item = items[0]
print('\nOriginal:', item['value'], '| Score:', item['score'], '| Label:', item['bias_label'])
print('Tweet:', item['tweet_text'])
print('Keywords:', item.get('query_keywords', ''))
print('GNEWS results:', item.get('query_results_total', 0))
print('Corpus matches:', item.get('query_matched_corpus', 0))
print('\nAlternatives:')
for a in item.get('alternatives', []):
    print(f"  {a['bias_label']:12s} | {a['domain']:30s} | {a['bias_score']:.2f} | {a['title'][:70]}")
