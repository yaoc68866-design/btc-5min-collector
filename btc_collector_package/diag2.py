"""Check current active market order books"""
import requests, json, time, math

now = int(time.time())
window = math.floor(now / 300) * 300
print(f"UTC: {time.strftime('%H:%M:%S', time.gmtime(now))}")
print(f"ET:  {time.strftime('%H:%M:%S', time.gmtime(now - 4*3600))}")
print()

# Check current window and neighbors with full order book
for offset in [-1, 0, 1, 2]:
    ts = window + offset * 300
    slug = f"btc-updown-5m-{ts}"
    try:
        r = requests.get('https://gamma-api.polymarket.com/events', params={'slug': slug}, timeout=8)
        if r.ok and r.json():
            ev = r.json()[0]
            title = ev.get('title','')
            if 'bitcoin' not in title.lower():
                continue
            closed = ev.get('closed')
            vol = ev.get('volume', 0)
            mkts = ev.get('markets', [])
            if not mkts:
                continue
            m = mkts[0]
            outcomes = json.loads(m['outcomes']) if isinstance(m.get('outcomes'), str) else m.get('outcomes',[])
            cids = json.loads(m['clobTokenIds']) if isinstance(m.get('clobTokenIds'), str) else m.get('clobTokenIds',[])

            print(f"[offset={offset:+d}] {title} closed={closed} vol=${vol}")

            for label, tid in zip(outcomes, cids):
                try:
                    br = requests.get('https://clob.polymarket.com/book', params={'token_id': tid}, timeout=5)
                    if br.ok:
                        bk = br.json()
                        bids = [(float(b['price']), float(b['size'])) for b in bk.get('bids',[])[:5]]
                        asks = [(float(a['price']), float(a['size'])) for a in bk.get('asks',[])[:5]]
                        bb = bids[0][0] if bids else None
                        ba = asks[0][0] if asks else None
                        mid = (bb+ba)/2 if bb and ba else None
                        print(f"  {label}: bid={bb} ask={ba} mid={mid}")
                        print(f"    bids: {bids}")
                        print(f"    asks: {asks}")
                except Exception as e:
                    print(f"  {label}: ERROR {e}")
            print()
    except Exception as e:
        pass
