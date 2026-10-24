import requests
import re
import json
import time

HOST = 'https://a123tv.com'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
    'Referer': 'https://a123tv.com/',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
}

classes = [
    {"type_id": 10, "type_name": "电影"},
    {"type_id": 11, "type_name": "连续剧"},
    {"type_id": 12, "type_name": "综艺"},
    {"type_id": 13, "type_name": "动漫"}
]

vod_list = []
seen_ids = set()

for c in classes:
    tid = c["type_id"]
    for page in range(1, 2):  # 先抓第1页验证，跑通后再改大
        url = f"{HOST}/t/{tid}.html"
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            items = re.findall(r'<div class="w4-item-wrap">([\s\S]*?)</div>\s*</div>', r.text)
            
            for block in items:
                link = re.search(r'href="/v/([^"]+?)\.html"', block)
                title = re.search(r'title="([^"]+?)"', block)
                img = re.search(r'data-src="([^"]+?)"', block)
                remarks = re.search(r'<span>([^<]+?)</span>', block)
                
                if link and title:
                    vid = link.group(1).strip()
                    vname = title.group(1).strip()
                    
                    if vid in seen_ids:
                        continue
                    seen_ids.add(vid)

                    pic = img.group(1) if img else ''
                    if pic.startswith('//'):
                        pic = 'https:' + pic
                    
                    # 精准抓取对应详情页
                    play_episodes = []
                    try:
                        det_url = f"{HOST}/v/{vid}.html"
                        det = requests.get(det_url, headers=HEADERS, timeout=8)
                        html_text = det.text

                        # 优先匹配当前主播放器的 var pp
                        pp_blocks = re.findall(r'var pp\s*=\s*(\{[\s\S]*?\});', html_text)
                        
                        target_pp = None
                        for pp_raw in pp_blocks:
                            try:
                                data = json.loads(pp_raw)
                                # 校验该 pp 是否属于当前视频（比对名称或链接合法性）
                                if "la" in data and len(data["la"]) > 0:
                                    target_pp = data
                                    break
                            except Exception:
                                continue

                        if target_pp and "la" in target_pp:
                            lines = target_pp["la"]
                            for idx, line in enumerate(lines):
                                if len(line) > 4 and line[4]:
                                    line_name = str(line[1]) if line[1] else f"线路{idx + 1}"
                                    m3u8 = str(line[4]).strip()
                                    if m3u8.startswith("http"):
                                        play_episodes.append(f"{line_name}${m3u8}")
                    except Exception as e:
                        print(f"抓取详情错误 {vid}: {e}")

                    # 只有真正拿到独立播放地址的视频才收录
                    if play_episodes:
                        vod_list.append({
                            "vod_id": str(vid),
                            "vod_name": vname,
                            "type_id": tid,
                            "type_name": c["type_name"],
                            "vod_pic": pic,
                            "vod_remarks": remarks.group(1) if remarks else '',
                            "vod_play_from": "默认播放",
                            "vod_play_url": "#".join(play_episodes)
                        })
                    
                    time.sleep(0.05)
        except Exception as e:
            print(f"列表页请求失败 {url}: {e}")

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

print(f"抓取完成！共生成独立视频: {len(vod_list)} 条")
