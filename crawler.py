import requests
import re
import json

HOST = 'https://a123tv.com'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Referer': 'https://a123tv.com/'
}

classes = [
    {"type_id": 10, "type_name": "电影"},
    {"type_id": 11, "type_name": "连续剧"},
    {"type_id": 12, "type_name": "综艺"},
    {"type_id": 13, "type_name": "动漫"}
]

vod_list = []

# 爬取各分类前两页影片
for c in classes:
    tid = c["type_id"]
    for page in range(1, 3):
        url = f"{HOST}/t/{tid}.html" if page == 1 else f"{HOST}/t/{tid}/p{page}.html"
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            items = re.findall(r'<div class="w4-item-wrap">([\s\S]*?)</div>\s*</div>', r.text)
            for block in items:
                link = re.search(r'href="/v/([^"]+?)\.html"', block)
                title = re.search(r'title="([^"]+?)"', block)
                img = re.search(r'data-src="([^"]+?)"', block)
                remarks = re.search(r'<span>([^<]+?线路)</span>', block)
                
                if link and title:
                    vid = link.group(1)
                    pic = img.group(1) if img else ''
                    if pic.startswith('//'):
                        pic = 'https:' + pic
                    
                    # 抓取每部影片详情中的真实 m3u8 直链
                    play_url = ""
                    try:
                        det = requests.get(f"{HOST}/v/{vid}.html", headers=HEADERS, timeout=10)
                        pp = re.search(r'var pp\s*=\s*(\{[\s\S]*?\});</script>', det.text)
                        if pp:
                            lines = json.loads(pp.group(1)).get("la", [])
                            eps = [f"{line[1]}${line[4]}" for line in lines if len(line) > 4 and line[4]]
                            play_url = "#".join(eps)
                    except Exception:
                        pass
                    
                    vod_list.append({
                        "vod_id": vid,
                        "vod_name": title.group(1),
                        "type_id": tid,
                        "type_name": c["type_name"],
                        "vod_pic": pic,
                        "vod_remarks": remarks.group(1) if remarks else '',
                        "vod_play_from": "A123TV聚合",
                        "vod_play_url": play_url
                    })
        except Exception:
            continue

result = {
    "code": 1,
    "msg": "数据成功",
    "page": 1,
    "pagecount": 1,
    "limit": len(vod_list),
    "total": len(vod_list),
    "class": classes,
    "list": vod_list
}

with open("vod.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
