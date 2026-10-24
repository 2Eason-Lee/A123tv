import requests
import re
import json
import time

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
seen_ids = set()

for c in classes:
    tid = c["type_id"]
    # 抓取各分类前两页
    for page in range(1, 3):
        url = f"{HOST}/t/{tid}.html" if page == 1 else f"{HOST}/t/{tid}/p{page}.html"
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            # 匹配整个卡片
            items = re.findall(r'<div class="w4-item-wrap">([\s\S]*?)</div>\s*</div>', r.text)
            
            for block in items:
                link = re.search(r'href="/v/([^"]+?)\.html"', block)
                title = re.search(r'title="([^"]+?)"', block)
                img = re.search(r'data-src="([^"]+?)"', block)
                remarks = re.search(r'<span>([^<]+?线路)</span>', block)
                
                if link and title:
                    vid = link.group(1).strip()
                    vname = title.group(1).strip()
                    
                    # 避免重复视频加入
                    if vid in seen_ids:
                        continue
                    seen_ids.add(vid)

                    pic = img.group(1) if img else ''
                    if pic.startswith('//'):
                        pic = 'https:' + pic
                    
                    # 关键修复点：每次循环必须初始化独立的 play_url，防止变量污染
                    current_play_url = ""
                    try:
                        det_url = f"{HOST}/v/{vid}.html"
                        det = requests.get(det_url, headers=HEADERS, timeout=8)
                        
                        # 严格提取该视频专属的 var pp 数据
                        pp = re.search(r'var pp\s*=\s*(\{[\s\S]*?\});</script>', det.text)
                        if pp:
                            lines = json.loads(pp.group(1)).get("la", [])
                            eps = []
                            for idx, line in enumerate(lines):
                                if len(line) > 4 and line[4]:
                                    line_name = line[1] if line[1] else f"线路{idx + 1}"
                                    eps.append(f"{line_name}${line[4]}")
                            current_play_url = "#".join(eps)
                    except Exception as err:
                        print(f"详情页抓取失败: {vid}, 错误: {err}")
                    
                    # 如果成功抓到播放线路才写入列表
                    if current_play_url:
                        vod_list.append({
                            "vod_id": str(vid),
                            "vod_name": vname,
                            "type_id": tid,
                            "type_name": c["type_name"],
                            "vod_pic": pic,
                            "vod_remarks": remarks.group(1) if remarks else '',
                            "vod_play_from": "A123TV聚合",
                            "vod_play_url": current_play_url
                        })
                    
                    # 稍微间隔一下，避免被目标站短时间内高频拦截
                    time.sleep(0.1)
        except Exception as e:
            print(f"列表页抓取失败: {url}, 错误: {e}")

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

print(f"成功更新完成，共收录视频: {len(vod_list)} 部")
