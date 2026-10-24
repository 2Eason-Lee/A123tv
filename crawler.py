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
seen_slugs = set()
global_id = 10001  # 使用标准唯一数字自增 ID，避免数据库缓存冲突

for c in classes:
    tid = c["type_id"]
    for page in range(1, 11):
        url = f"{HOST}/t/{tid}.html" if page == 1 else f"{HOST}/t/{tid}/p{page}.html"
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            items = re.findall(r'<div class="w4-item-wrap">([\s\S]*?)</div>\s*</div>', r.text)
            
            for block in items:
                link = re.search(r'href="/v/([^"]+?)\.html"', block)
                title = re.search(r'title="([^"]+?)"', block)
                img = re.search(r'data-src="([^"]+?)"', block)
                remarks = re.search(r'<span>([^<]+?)</span>', block)
                
                if link and title:
                    slug = link.group(1).strip()
                    vname = title.group(1).strip()
                    
                    if slug in seen_slugs:
                        continue
                    seen_slugs.add(slug)

                    pic = img.group(1) if img else ''
                    if pic.startswith('//'):
                        pic = 'https:' + pic
                    
                    # 抓取真实详情页
                    play_sources = []
                    play_urls = []
                    
                    try:
                        det_url = f"{HOST}/v/{slug}.html"
                        det = requests.get(det_url, headers=HEADERS, timeout=8)
                        
                        # 抓取 var pp 播放列表
                        pp_match = re.search(r'var pp\s*=\s*(\{[\s\S]*?\});', det.text)
                        if pp_match:
                            data = json.loads(pp_match.group(1))
                            lines = data.get("la", [])
                            
                            # 提取每个可用的 m3u8
                            episodes = []
                            for idx, line in enumerate(lines):
                                if len(line) > 4 and line[4] and line[4].startswith("http"):
                                    line_name = line[1] if line[1] else f"线路{idx + 1}"
                                    # 将每一个有效播放地址都作为正片/独立分集
                                    episodes.append(f"{line_name}$ {line[4]}".replace(" ", ""))
                            
                            if episodes:
                                # 标准规范：单一播放组多线路切换
                                play_sources.append("A123TV聚合")
                                play_urls.append("#".join(episodes))
                    except Exception as e:
                        print(f"解析详情失败 {slug}: {e}")

                    # 只有真正拿到独立播放地址的视频才写入
                    if play_urls:
                        vod_list.append({
                            "vod_id": global_id,  # 纯数字唯一主键
                            "vod_name": vname,
                            "type_id": tid,
                            "type_name": c["type_name"],
                            "vod_pic": pic,
                            "vod_remarks": remarks.group(1) if remarks else '',
                            "vod_play_from": "$$$".join(play_sources),
                            "vod_play_url": "$$$".join(play_urls)
                        })
                        global_id += 1
                    
                    time.sleep(0.05)
        except Exception as e:
            print(f"列表页抓取失败: {e}")

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

print(f"更新完成！共生成合法视频数据: {len(vod_list)} 部")
