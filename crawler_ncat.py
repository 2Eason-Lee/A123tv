import requests
import re
import json
import time

HOST = 'https://www.ncat21.com'
# 增强浏览器伪装
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Referer': HOST,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9'
}

classes = [
    {"type_id": 1, "type_name": "电影"},
    {"type_id": 2, "type_name": "连续剧"},
    {"type_id": 3, "type_name": "动漫"},
    {"type_id": 4, "type_name": "综艺纪录"}
]

vod_list = []
global_id = 20001

print("开始抓取网飞猫数据...")
for c in classes:
    tid = c["type_id"]
    url = f"{HOST}/channel/{tid}.html"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        print(f"请求分类 {c['type_name']} 状态码: {r.status_code}")
        
        # 放宽正则，兼容各种空格和换行
        items = re.findall(r'href="(/detail/[^"]+\.html)"[^>]*class="v-item"[^>]*>([\s\S]*?)</a>', r.text)
        print(f"在 {c['type_name']} 找到 {len(items)} 个影视块")
        
        for detail_url, block in items:
            img_matches = re.findall(r'data-original="([^"]+)"', block)
            pic = img_matches[-1] if img_matches else ""
            if pic.startswith('/'):
                pic = HOST + pic
                
            # 精确匹配真实标题，避开隐藏的 SEO 标签
            title_match = re.search(r'<div class="v-item-title">([^<]+)</div>', block)
            remarks_match = re.search(r'v-item-bottom[^>]*>[\s\S]*?<span>\s*([^<]+?)\s*</span>', block)
            
            if not title_match: 
                continue
            vname = title_match.group(1).strip()
            remarks = remarks_match.group(1).strip() if remarks_match else ""
            
            try:
                det = requests.get(HOST + detail_url, headers=HEADERS, timeout=10)
                episodes = re.findall(r'href="(/play/[^"]+)"[^>]*>\s*<span>([^<]+)</span>', det.text)
                
                play_urls = []
                for play_link, ep_name in episodes[:10]:
                    try:
                        play_page = requests.get(HOST + play_link, headers=HEADERS, timeout=8)
                        m3u8_match = re.search(r'src:\s*["\']([^"\']+\.m3u8)["\']', play_page.text)
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
                    print(f"  -> 成功解析: {vname}")
            except Exception as e:
                print(f"  -> 详情页失败 {vname}: {e}")
            
            time.sleep(0.5)  # 增加停顿，防止触发反爬
    except Exception as e:
        print(f"列表页抓取报错: {e}")

result = {
    "code": 1, "msg": "成功", "page": 1, "pagecount": 1,
    "limit": len(vod_list), "total": len(vod_list),
    "class": classes, "list": vod_list
}

with open("ncat.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print(f"网飞猫抓取完成！共生成 {len(vod_list)} 部数据")
