import requests
import re
import json
import sys
import time

HOST = 'https://www.boju.cc'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Referer': HOST
}

vod_list = []
global_id = 30001

print("🚀 开始深度网页抓取 [播剧网] 数据...")

try:
    # 抓取电影分类的前 3 页网页列表
    for page in range(1, 4):
        url = f"{HOST}/vodshow/1-----------{page}.html" if page > 1 else f"{HOST}/vodshow/1-----------.html"
        res = requests.get(url, headers=HEADERS, timeout=15)
        
        if res.status_code != 200:
            print(f"❌ 列表页请求失败: {res.status_code}")
            continue
            
        # 匹配网页中的影片卡片
        # 根据播剧网结构提取详情页链接与标题
        items = re.findall(r'<a[^>]+href="(/voddetail/\d+\.html)"[^>]*title="([^"]+)"', res.text)
        
        for detail_url, vname in items:
            try:
                det_res = requests.get(HOST + detail_url, headers=HEADERS, timeout=10)
                
                # 尝试从详情页的 mac_player_info 中提取 m3u8 直链
                player_match = re.search(r'var\s+mac_player_info\s*=\s*(\{.+?\});', det_res.text)
                if player_match:
                    player_data = json.loads(player_match.group(1))
                    m3u8_url = player_data.get("url", "")
                    
                    if m3u8_url and "m3u8" in m3u8_url:
                        # 提取封面图片
                        pic_match = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', det_res.text)
                        pic = pic_match.group(1) if pic_match else ""
                        
                        vod_list.append({
                            "vod_id": global_id,
                            "vod_name": vname.strip(),
                            "type_id": 1,
                            "type_name": "电影",
                            "vod_pic": pic,
                            "vod_remarks": "HD",
                            "vod_play_from": "播剧直连",
                            "vod_play_url": f"正片${m3u8_url}"
                        })
                        global_id += 1
                        print(f"✅ 成功捕获: {vname}")
            except Exception as e:
                pass
                
            time.sleep(0.3) # 减慢速度防止被防爬虫拦截
        print(f"✅ 列表页 {page} 扫描完成")

except Exception as e:
    print(f"❌ 运行报错: {e}")

if len(vod_list) == 0:
    print("\n🚨 网页抓取失败！该网站防火墙过于严格，无法提取网页直链。")
    sys.exit(1)

result = {
    "code": 1, "msg": "成功", "page": 1, "pagecount": 1,
    "limit": len(vod_list), "total": len(vod_list),
    "class": [{"type_id": 1, "type_name": "电影"}, {"type_id": 2, "type_name": "连续剧"}, {"type_id": 3, "type_name": "综艺"}, {"type_id": 4, "type_name": "动漫"}],
    "list": vod_list
}

with open("boju.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print(f"\n🎉 播剧网网页直连抓取完成！共生成 {len(vod_list)} 部影片")
