import requests, re, json, time

HOST = 'https://a123tv.com'
HEADERS = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)', 'Referer': 'https://a123tv.com/'}
classes = [{"type_id": 10, "type_name": "电影"}, {"type_id": 11, "type_name": "连续剧"}, {"type_id": 12, "type_name": "综艺"}, {"type_id": 13, "type_name": "动漫"}]
vod_list = []
seen_slugs = set()
global_id = 10001  # 使用唯一数字ID防冲突

for c in classes:
    tid = c["type_id"]
    for page in range(1, 11):  # 抓取前 10 页
        url = f"{HOST}/t/{tid}.html" if page == 1 else f"{HOST}/t/{tid}/p{page}.html"
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            items = re.findall(r'<div class="w4-item-wrap">([\s\S]*?)</div>\s*</div>', r.text)
            for block in items:
                link, title = re.search(r'href="/v/([^"]+?)\.html"', block), re.search(r'title="([^"]+?)"', block)
                if not (link and title): continue
                slug, vname = link.group(1).strip(), title.group(1).strip()
                if slug in seen_slugs: continue
                seen_slugs.add(slug)
                
                img = re.search(r'data-src="([^"]+?)"', block)
                pic = ('https:' + img.group(1)) if img and img.group(1).startswith('//') else (img.group(1) if img else '')
                
                episodes = []
                try:
                    det = requests.get(f"{HOST}/v/{slug}.html", headers=HEADERS, timeout=8)
                    pp_match = re.search(r'var pp\s*=\s*(\{[\s\S]*?\});', det.text)
                    if pp_match:
                        for idx, line in enumerate(json.loads(pp_match.group(1)).get("la", [])):
                            if len(line) > 4 and line[4] and line[4].startswith("http"):
                                episodes.append(f"{line[1] or f'线路{idx+1}'}${line[4]}".replace(" ", ""))
                except Exception: pass
                
                if episodes:
                    vod_list.append({
                        "vod_id": global_id, "vod_name": vname, "type_id": tid, "type_name": c["type_name"],
                        "vod_pic": pic, "vod_play_from": "A123TV", "vod_play_url": "#".join(episodes)
                    })
                    global_id += 1
                time.sleep(0.05)
        except Exception: continue

with open("vod.json", "w", encoding="utf-8") as f:
    json.dump({"code": 1, "list": vod_list}, f, ensure_ascii=False, indent=2)
print(f"成功抓取 {len(vod_list)} 部")
