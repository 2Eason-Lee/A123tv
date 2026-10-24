import requests
import json
import sys
import time
import re

# AIKAN 网站真实域名
HOST = 'https://www.aikanbot.vip'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Referer': HOST
}

vod_list = []
global_id = 40001

print("🚀 开始自动抓取 [AIKAN] 多线路聚合数据...")

try:
    # 访问 AIKAN 首页获取推荐/热门电影的 videoid 和标题
    list_url = f"{HOST}/"
    res = requests.get(list_url, headers=HEADERS, timeout=15)
    
    if res.status_code == 200:
        # 从页面中匹配出视频的 videoid 和名称
        video_matches = re.findall(r'href="[^"]*videoid=(\d+)[^"]*"[^>]*>([^<]+)</a>', res.text)
        
        # 如果首页正则没匹配到足够数量，兜底加入我们刚才抓包确认过的经典ID（如肖申克的救赎 482774）
        if not video_matches:
            video_matches = [("482774", "肖申克的救赎")]
            
        seen_ids = set()
        for vid_str, vname in video_matches:
            vid = int(vid_str)
            if vid in seen_ids:
                continue
            seen_ids.add(vid)
            
            # 针对每个视频ID，请求多线路聚合接口 `getResN`
            api_url = f"{HOST}/getResN?videoid={vid}&mtype=1"
            try:
                api_res = requests.get(api_url, headers=HEADERS, timeout=8)
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
                            # 将几十条线路用 $$$ 完美拼接，供播放器多线切换
                            final_play_url = "$$$".join(play_urls)
                            vod_list.append({
                                "vod_id": global_id,
                                "vod_name": vname.strip(),
                                "type_id": 1,
                                "type_name": "电影",
                                "vod_pic": "", 
                                "vod_remarks": f"共{len(play_urls)}条线路",
                                "vod_play_from": "AIKAN多线",
                                "vod_play_url": final_play_url
                            })
                            global_id += 1
            except Exception as e:
                continue
            time.sleep(0.2)
            
except Exception as e:
    print(f"❌ 运行报错: {e}")

if len(vod_list) == 0:
    print("\n🚨 提示：未采集到有效数据，将使用默认测试数据保证文件不为空。")
    # 兜底测试数据
    vod_list.append({
        "vod_id": global_id,
        "vod_name": "肖申克的救赎 (多线测试)",
        "type_id": 1,
        "type_name": "电影",
        "vod_pic": "",
        "vod_remarks": "多线聚合",
        "vod_play_from": "AIKAN多线",
        "vod_play_url": "正片$https://play.xluuss.com/play/1aM87gGe/index.m3u8$$$正片$https://v.gsuus.com/play/wdL9ADre/index.m3u8"
    })

result = {
    "code": 1, "msg": "成功", "page": 1, "pagecount": 1,
    "limit": len(vod_list), "total": len(vod_list),
    "class": [{"type_id": 1, "type_name": "电影"}, {"type_id": 2, "type_name": "连续剧"}, {"type_id": 3, "type_name": "综艺"}, {"type_id": 4, "type_name": "动漫"}],
    "list": vod_list
}

with open("aikan.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print(f"\n🎉 AIKAN 多线路数据生成完毕！共收编 {len(vod_list)} 部影片")
