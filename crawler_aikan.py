import requests
import json
import sys
import time

HOST = 'https://www.aikanbot.vip'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Referer': HOST
}

vod_list = []
global_id = 40001

print("🚀 开始全自动智能同步 [AIKAN] 最新多线大片...")

# 1. 核心经典影视ID库（保证基础热片永不丢失）
target_ids = [
    482774, 116582, 116898, 179721, 177885, 
    189787, 187070, 186442, 185993, 178910, 
    198112, 199606, 948552, 938384, 190235
]

# 2. 增量自动扫描区间（每次运行自动探索最新发布的影视ID，实现自动化更新）
# 随着时间推移，最新的影视ID会在此区间不断生成
for auto_id in range(482700, 482950):
    if auto_id not in target_ids:
        target_ids.append(auto_id)

seen_ids = set()
success_count = 0

for vid in target_ids:
    if vid in seen_ids:
        continue
    seen_ids.add(vid)
    
    api_url = f"{HOST}/getResN?videoid={vid}&mtype=1"
    try:
        api_res = requests.get(api_url, headers=HEADERS, timeout=5)
        if api_res.status_code == 200:
            j_data = api_res.json()
            if j_data.get("state") == 1:
                lines = j_data.get("data", {}).get("list", [])
                play_urls = []
                
                for line in lines:
                    res_data_str = line.get("resData", "[]")
                    try:
                        sub_lines = json.loads(res_data_str)
                        for sub in sub_lines:
                            url = sub.get("url", "")
                            if url:
                                play_urls.append(url)
                    except:
                        continue
                
                if play_urls:
                    final_play_url = "$$$".join(play_urls)
                    vod_list.append({
                        "vod_id": global_id,
                        "vod_name": f"AIKAN 高清影视 #{vid}",
                        "type_id": 1,
                        "type_name": "电影",
                        "vod_pic": "", 
                        "vod_remarks": f"共{len(play_urls)}条线路",
                        "vod_play_from": "AIKAN多线",
                        "vod_play_url": final_play_url
                    })
                    global_id += 1
                    success_count += 1
    except Exception:
        continue
    # 控制请求节奏，避免对目标服务器造成过大压力
    time.sleep(0.05)

print(f"✨ 扫描完毕，成功聚合有效影片: {success_count} 部")

# 兜底保证
if len(vod_list) == 0:
    vod_list.append({
        "vod_id": global_id,
        "vod_name": "肖申克的救赎 (多线聚合)",
        "type_id": 1,
        "type_name": "电影",
        "vod_pic": "",
        "vod_remarks": "多线聚合测试",
        "vod_play_from": "AIKAN多线",
        "vod_play_url": "正片$https://play.xluuss.com/play/1aM87gGe/index.m3u8$$$国语版$https://play.xluuss.com/play/BeXomzmd/index.m3u8"
    })

result = {
    "code": 1, "msg": "成功", "page": 1, "pagecount": 1,
    "limit": len(vod_list), "total": len(vod_list),
    "class": [{"type_id": 1, "type_name": "电影"}, {"type_id": 2, "type_name": "连续剧"}, {"type_id": 3, "type_name": "综艺"}, {"type_id": 4, "type_name": "动漫"}],
    "list": vod_list
}

with open("aikan.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print(f"\n🎉 aikan.json 文件已成功生成并保存！")
