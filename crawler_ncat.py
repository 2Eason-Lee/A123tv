import requests
import re
import json
import time

HOST = 'https://www.ncat21.com'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    'Referer': HOST
}

classes = [
    {"type_id": 1, "type_name": "电影"},
    {"type_id": 2, "type_name": "连续剧"},
    {"type_id": 3, "type_name": "动漫"},
    {"type_id": 4, "type_name": "综艺纪录"}
]

vod_list = []
global_id = 20001  # 使用2开头的ID，避免与A123的1开头ID冲突

print("开始抓取网飞猫数据...")
for c in classes:
    tid = c["type_id"]
    # 为保证速度且不被封IP，网飞猫暂抓取第1页最热门数据
    url = f"{HOST}/channel/{tid}.html"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        items = re.findall(r'<a href="(/detail/\d+\.html)" class="v-item">([\s\S]*?)</a>', r.text)
        
        for detail_url, block in items:
            # 提取真实海报（避开占位图）和标题
            img_matches = re.findall(r'data-original="([^"]+)"', block)
            pic = img_matches[-1] if img_matches else ""
            if pic.startswith('/'):
                pic = HOST + pic
                
            title_match = re.search(r'<div class="v-item-title">([^<]+)</div>', block)
            remarks_match = re.search(r'<div class="v-item-bottom">\s*<span>\s*([^<]+?)\s*</span>', block)
            
            if not title_match: continue
            vname = title_match.group(1).strip()
            remarks = remarks_match.group(1).strip() if remarks_match else ""
            
            # 进入详情页获取各集播放链接
            try:
                det = requests.get(HOST + detail_url, headers=HEADERS, timeout=8).text
                episodes = re.findall(r'<a href="(/play/[^"]+)"[^>]*>\s*<span>([^<]+)</span>', det)
                
                play_urls = []
                # 限制最多抓取前10集直链，防止云端运行超时
                for play_link, ep_name in episodes[:10]:
                    try:
                        play_page = requests.get(HOST + play_link, headers=HEADERS, timeout=5).text
                        m3u8_match = re.search(r'src:\s*"([^"]+\.m3u8)"', play_page)
                        if m3u8_match:
                            play_urls.append(f"{ep_name.strip()}${m3u8_match.group(1)}")
                    except:
                        pass
                        
                if play_urls:
                    vod_list.append({
                        "vod_id": global_id,
                        "vod_name": vname,
                        "type_id": tid,
                        "type_name": c["type_name"],
                        "vod_pic": pic,
                        "vod_remarks": remarks,
                        "vod_play_from": "网飞猫",
                        "vod_play_url": "#".join(play_urls)
                    })
                    global_id += 1
                    print(f"成功获取: {vname}")
            except Exception as e:
                print(f"解析失败: {vname}")
            
            time.sleep(0.2)  # 防封停顿
    except Exception as e:
        print(f"列表页抓取失败: {e}")

result = {
    "code": 1, "msg": "成功", "page": 1, "pagecount": 1,
    "limit": len(vod_list), "total": len(vod_list),
    "class": classes, "list": vod_list
}

# 独立保存为 ncat.json
with open("ncat.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print(f"网飞猫抓取完成！共 {len(vod_list)} 部")
