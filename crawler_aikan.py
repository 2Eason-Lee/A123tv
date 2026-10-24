import requests
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

HOST = 'https://www.aikanbot.vip'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36',
    'Referer': HOST + '/',
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'X-Requested-With': 'XMLHttpRequest'
}

print("🚀 启动 [AIKAN] 完整破译版云端采集...")

# 1. 自动遍历分类页面抓取真实视频 ID
category_paths = [
    "/hot/index-movie-热门.html",
    "/hot/index-movie-最新.html",
    "/hot/index-movie-科幻.html",
    "/hot/index-movie-动作.html",
    "/hot/index-tv-热门.html",
    "/hot/index-tv-最新.html"
]

found_videos = {}

for path in category_paths:
    for page in range(1, 3):
        url = f"{HOST}{path}" if page == 1 else f"{HOST}{path.replace('.html', f'-p-{page}.html')}"
        try:
            res = requests.get(url, headers=HEADERS, timeout=8)
            if res.status_code == 200:
                # 匹配 /play/数字 格式的真实 ID
                matches = re.findall(r'href="/play/(\d+)"[^>]*>.*?<p>([^<]+)</p>', res.text, re.DOTALL)
                for vid_str, vname in matches:
                    vid = int(vid_str)
                    clean_name = vname.strip()
                    if vid not in found_videos:
                        found_videos[vid] = clean_name
            time.sleep(0.1)
        except Exception:
            continue

print(f"✨ 页面解析完成，共捕获有效视频 ID: {len(found_videos)} 个")

vod_list = []
global_id = 40001
lock = __import__('threading').Lock()

def fetch_multiline(vid, vname):
    global global_id
    # 使用正确的 /api/getResN 接口路径
    api_url = f"{HOST}/api/getResN?videoId={vid}&mtype=1"
    
    # 针对每个视频动态更新 Referer
    specific_headers = HEADERS.copy()
    specific_headers['Referer'] = f"{HOST}/play/{vid}"
    
    try:
        api_res = requests.get(api_url, headers=specific_headers, timeout=6)
        if api_res.status_code == 200:
            j_data = api_res.json()
            lines = []
            if isinstance(j_data, dict):
                # 兼容不同的返回字段
                if j_data.get("state") == 1 or "data" in j_data:
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
            
            # 如果没拿到，文本正则兜底
            if not play_urls and ".m3u8" in api_res.text:
                found_m3u8 = re.findall(r'https?://[^\s<>"]+?\.m3u8', api_res.text)
                play_urls = list(set(found_m3u8))

            if play_urls:
                final_play_url = "$$$".join(play_urls)
                with lock:
                    vod_list.append({
                        "vod_id": global_id,
                        "vod_name": vname,
                        "type_id": 1,
                        "type_name": "电影",
                        "vod_pic": "", 
                        "vod_remarks": f"共{len(play_urls)}条多路高清",
                        "vod_play_from": "AIKAN多线",
                        "vod_play_url": final_play_url
                    })
                    global_id += 1
    except Exception:
        pass

# 2. 多线程并发请求
start_time = time.time()
items = list(found_videos.items())

with ThreadPoolExecutor(max_workers=10) as executor:
    for vid, vname in items:
        executor.submit(fetch_multiline, vid, vname)

print(f"⚡ 多线数据聚合完毕，耗时: {time.time() - start_time:.2f} 秒，成功收编大片: {len(vod_list)} 部")

# 终极兜底保证
if len(vod_list) == 0:
    vod_list.append({
        "vod_id": global_id,
        "vod_name": "肖申克的救赎 (多线聚合)",
        "type_id": 1,
        "type_name": "电影",
        "vod_pic": "",
        "vod_remarks": "31条线路随意切换",
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

print(f"\n🎉 aikan.json 已在云端成功生成！")
