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

print("🚀 开始批量采集 [AIKAN] 多线路聚合大片...")

# 预设一批高质量、热门影视的 ID 范围（你可以随时在后面追加更多 ID）
# 覆盖经典电影、热播剧等
base_video_ids = [
    482774, 482775, 482776, 482777, 482778, 
    116582, 116583, 116584, 116585, 116586,
    179721, 177885, 189787, 187070, 186442,
    185993, 178910, 198112, 199606, 948552,
    938384, 190235, 210040, 186019, 132042
]

# 也可以动态扩展一段 ID 范围进行自动扫描
for i in range(482700, 482800):
    if i not in base_video_ids:
        base_video_ids.append(i)

seen_ids = set()
for vid in base_video_ids:
    if vid in seen_ids:
        continue
    seen_ids.add(vid)
    
    api_url = f"{HOST}/getResN?videoid={vid}&mtype=1"
    try:
        api_res = requests.get(api_url, headers=HEADERS, timeout=6)
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
                        "vod_remarks": f"共{len(play_urls)}条多线",
                        "vod_play_from": "AIKAN多线",
                        "vod_play_url": final_play_url
                    })
                    global_id += 1
    except Exception:
        continue
    time.sleep(0.1) # 控制请求频率

# 如果依然为空，加一条兜底
if len(vod_list) == 0:
    vod_list.append({
        "vod_id": global_id,
        "vod_name": "肖申克的救赎 (多线聚合测试)",
        "type_id": 1,
        "type_name": "电影",
        "vod_pic": "",
        "vod_remarks": "多线聚合",
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
print(f"\n🎉 AIKAN 多线路数据生成完毕！成功收编 {len(vod_list)} 部影片")
