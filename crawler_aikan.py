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

print("🚀 启动 [AIKAN] 深度调试与透传采集...")

category_paths = [
    "/hot/index-movie-科幻.html"
]

found_videos = {}

for path in category_paths:
    url = f"{HOST}{path}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=8)
        print(f"📄 分页请求状态码: {res.status_code}, 目标: {url}")
        if res.status_code == 200:
            matches = re.findall(r'href="/play/(\d+)"[^>]*>.*?<p>([^<]+)</p>', res.text, re.DOTALL)
            print(f"🔍 正则成功匹配到原始条目数: {len(matches)}")
            for vid_str, vname in matches[:5]:
                print(f"   -> 捕获ID: {vid_str}, 片名: {vname.strip()}")
            
            for vid_str, vname in matches:
                vid = int(vid_str)
                clean_name = vname.strip()
                if vid not in found_videos:
                    found_videos[vid] = clean_name
    except Exception as e:
        print(f"❌ 页面解析异常: {e}")

print(f"✨ 有效视频 ID 去重后总数: {len(found_videos)} 个")

vod_list = []
global_id = 40001
lock = __import__('threading').Lock()

def fetch_multiline(vid, vname):
    global global_id
    api_url = f"{HOST}/api/getResN?videoId={vid}&mtype=1"
    specific_headers = HEADERS.copy()
    specific_headers['Referer'] = f"{HOST}/play/{vid}"
    
    try:
        api_res = requests.get(api_url, headers=specific_headers, timeout=6)
        
        # 打印前两个视频的真实响应情况（已加上引号修复）
        first_two_keys = list(found_videos.keys())[:2]
        if vid in first_two_keys:
            print(f"\n--- 调试视频 ID: {vid} ({vname}) ---")
            print(f"HTTP 状态码: {api_res.status_code}")
            print(f"响应头 Content-Type: {api_res.headers.get('Content-Type')}")
            print(f"响应正文前 300 字符: {api_res.text[:300]}")
            print("-" * 40)

        if api_res.status_code == 200:
            try:
                j_data = api_res.json()
            except json.JSONDecodeError:
                return

            lines = []
            data_field = j_data.get("data")
            if isinstance(data_field, list):
                lines = data_field
            elif isinstance(data_field, dict):
                lines = data_field.get("list", [])

            play_urls = []
            for line in lines:
                res_data_str = line.get("resData", "[]")
                if isinstance(res_data_str, list):
                    sub_lines = res_data_str
                else:
                    try:
                        sub_lines = json.loads(res_data_str)
                    except:
                        sub_lines = []
                
                for sub in sub_lines:
                    if isinstance(sub, dict):
                        url = sub.get("url", "")
                        name = sub.get("name", "正片")
                        if url:
                            play_urls.append(f"{name}${url}")

            if play_urls:
                final_play_url = "#".join(play_urls)
                with lock:
                    vod_list.append({
                        "vod_id": global_id,
                        "vod_name": vname,
                        "type_id": 1,
                        "type_name": "电影",
                        "vod_pic": "", 
                        "vod_remarks": f"共{len(play_urls)}条高清线路",
                        "vod_play_from": "AIKAN多线",
                        "vod_play_url": final_play_url
                    })
                    global_id += 1
    except Exception as e:
        print(f"⚠️ 请求接口异常 [ID: {vid}]: {e}")

start_time = time.time()
items = list(found_videos.items())[:10]

with ThreadPoolExecutor(max_workers=3) as executor:
    for vid, vname in items:
        executor.submit(fetch_multiline, vid, vname)

print(f"\n⚡ 调试聚合完毕，耗时: {time.time() - start_time:.2f} 秒，成功收编大片: {len(vod_list)} 部")

if len(vod_list) == 0:
    vod_list.append({
        "vod_id": global_id,
        "vod_name": "肖申克的救赎 (调试兜底)",
        "type_id": 1,
        "type_name": "电影",
        "vod_pic": "",
        "vod_remarks": "多线聚合测试",
        "vod_play_from": "AIKAN多线",
        "vod_play_url": "正片$https://play.xluuss.com/play/1aM87gGe/index.m3u8"
    })

result = {
    "code": 1, "msg": "成功", "page": 1, "pagecount": 1,
    "limit": len(vod_list), "total": len(vod_list),
    "class": [{"type_id": 1, "type_name": "电影"}, {"type_id": 2, "type_name": "连续剧"}, {"type_id": 3, "type_name": "综艺"}, {"type_id": 4, "type_name": "动漫"}],
    "list": vod_list
}

with open("aikan.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"🎉 调试版 aikan.json 已生成！")
