import asyncio
import time
from server import query_gdelt, try_multiple_keys
from urllib.parse import urlparse

headlines = [
    "Supreme Court strikes down Chevron, curtailing power of federal agencies",
    "Fed keeps rates steady, signals only one cut this year",
    "Nvidia briefly becomes world's most valuable company",
    "Tesla shareholders approve Elon Musk's $56 billion pay package",
    "EU tariffs on Chinese EVs to hit 38% in trade war escalation",
    "Boeing CEO Dave Calhoun faces grueling Senate hearing over safety",
    "McDonald's ends AI drive-thru test with IBM",
    "Apple announces Apple Intelligence, its deeply integrated AI system",
    "Surgeon General calls for warning labels on social media platforms",
    "S&P 500 hits record high as tech rally continues"
]

async def test_all():
    total_latency_full = 0
    total_latency_kw = 0
    full_hits = 0
    kw_hits = 0

    print("Testing GDELT Coverage Strategies...")
    for h in headlines:
        # Full headline
        start = time.time()
        res_full = await query_gdelt(h, use_keywords=False)
        total_latency_full += (time.time() - start)
        if len(res_full) > 0:
            full_hits += 1

        # Keyword
        start = time.time()
        res_kw = await query_gdelt(h, use_keywords=True)
        total_latency_kw += (time.time() - start)
        if len(res_kw) > 0:
            kw_hits += 1
            
        print(f"'{h[:40]}...' -> Full: {len(res_full)}, KW: {len(res_kw)}")
        
    print(f"\nResults over {len(headlines)} headlines:")
    print(f"Full Headline Hit Rate: {full_hits}/{len(headlines)}")
    print(f"Full Headline Avg Latency: {(total_latency_full/len(headlines))*1000:.1f}ms")
    print(f"Keyword Hit Rate: {kw_hits}/{len(headlines)}")
    print(f"Keyword Avg Latency: {(total_latency_kw/len(headlines))*1000:.1f}ms")

if __name__ == "__main__":
    asyncio.run(test_all())
