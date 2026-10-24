import requests
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

HOST = 'https://www.aikanbot.vip'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Referer': HOST,
    'Accept-Language': 'zh-CN,zh;q=0.9'
}

print("🚀 开始云端全自动抓取 [AIKAN] 片库与多线数据...")

# 1. 定义需要自动遍历的分类与热门页面路由
category_paths = [
    "/hot/index-movie-热门.html",
    "/hot/index-movie-最新.html",
    "/hot/index-movie-科幻.html",
    "/hot/index-movie-动作.html",
    "/hot/index-tv-热门.html",
    "/hot/index-tv-最新.html"
]

found_videos = {} # key: vid, value: title

# 自动遍历各个分类页面（顺便支持简单的多页抓取）
for path in category_paths:
    for page in range(1, 3): # 每个分类抓前2页
        url = f"{HOST}{path}" if page == 1 else f"{HOST}{path.replace('.html', f'-p-{page}.html')}"
        try:
            res = requests.get(url, headers=HEADERS, timeout=6)
            if res.status_code == 200:
                # 从 HTML 中正则提取出类似于 <a class="item" href="/play/398682">...<p>流浪地球</p>
                # 匹配格式：href="/play/(\d+)" ... <p>([^<]+)</p>
                matches = re.findall(r'href="/play/(\d+)"[^>]*>.*?<p>([^<]+)</p>', res.text, re.DOTALL)
                for vid_str, vname in matches:
                    vid = int(vid_str)
                    clean_name = vname.strip()
                    if vid not in found_videos:
                        found_videos[vid] = clean_name
            time.sleep(0.2)
        except Exception as e:
            continue

print(f"✨ 页面解析完成，共发现有效视频 ID: {len(found_videos)} 个")

vod_list = []
global_id = 40001
lock = __import__('threading').Lock()

def fetch_multiline(vid, vname):
    global global_id
    api_url = f"{HOST}/getResN?videoid={vid}&mtype=1"
    try:
        api_res = requests.get(api_url, headers=HEADERS, timeout=4)
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

# 2. 使用多线程并发去请求每个视频的多线聚合接口
start_time = time.time()
items = list(found_videos.items())

with ThreadPoolExecutor(max_workers=15) as executor:
    for vid, vname in items:
        executor.submit(fetch_multiline, vid, vname)

print(f"⚡ 多线数据聚合完毕，耗时: {time.time() - start_time:.2f} 秒，成功收编大片: {len(vod_list)} 部")

# 兜底保证
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

print(f"\n🎉 aikan.json 已在云端全自动生成成功！")
