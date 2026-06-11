"""Diagnose timezone and market matching"""
import requests, json, time, math

now = int(time.time())
print(f"Server UTC: {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(now))}")

# EDT offset
et_now = now - 4 * 3600
et_window = math.floor(et_now / 300) * 300
print(f"ET time:    {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(et_now))}")
print(f"ET window:  {et_window}")
print()

# Search using ET-based window
print("=== ET-based slug search ===")
for offset in range(-3, 4):
    ts = et_window + offset * 300
    slug = f"btc-updown-5m-{ts}"
    try:
        r = requests.get('https://gamma-api.polymarket.com/events', params={'slug': slug}, timeout=8)
        if r.ok and r.json():
            ev = r.json()[0]
            title = ev.get('title','')
            if 'bitcoin' in title.lower():
                closed = ev.get('closed')
                mkts = ev.get('markets', [])
                if mkts:
                    cids = json.loads(mkts[0].get('clobTokenIds','[]')) if isinstance(mkts[0].get('clobTokenIds'), str) else mkts[0].get('clobTokenIds',[])
                    if cids:
                        br = requests.get('https://clob.polymarket.com/book', params={'token_id': cids[0]}, timeout=5)
                        if br.ok:
                            bk = br.json()
                            b = float(bk['bids'][0]['price']) if bk.get('bids') else None
                            a = float(bk['asks'][0]['price']) if bk.get('asks') else None
                            m = (b+a)/2 if b and a else None
                            print(f"  [{offset:+d}] {title} closed={closed} bid={b} ask={a} mid={m}")
                        else:
                            print(f"  [{offset:+d}] {title} closed={closed} OB_ERR={br.status_code}")
    except Exception as e:
        pass

# Also try UTC-based
print()
print("=== UTC-based slug search ===")
utc_window = math.floor(now / 300) * 300
for offset in range(-3, 4):
    ts = utc_window + offset * 300
    slug = f"btc-updown-5m-{ts}"
    try:
        r = requests.get('https://gamma-api.polymarket.com/events', params={'slug': slug}, timeout=8)
        if r.ok and r.json():
            ev = r.json()[0]
            title = ev.get('title','')
            if 'bitcoin' in title.lower():
                print(f"  [{offset:+d}] slug_ts={ts} -> {title} closed={ev.get('closed')}")
    except:
        pass
