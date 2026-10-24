import requests
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

HOST = 'https://www.aikanbot.vip'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'X-Requested-With': 'XMLHttpRequest'
}

print("🚀 启动 [AIKAN] 诊断日志采集模式...")

category_paths = [
    "/hot/index-movie-热门.html",
    "/hot/index-movie-科幻.html"
]

found_videos = {}

for path in category_paths:
    url = f"{HOST}{path}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=8)
        if res.status_code == 200:
            matches = re.findall(r'href="/play/(\d+)"[^>]*>.*?<p>([^<]+)</p>', res.text, re.DOTALL)
            for vid_str, vname in matches:
                vid = int(vid_str)
                clean_name = vname.strip().encode('utf-8', 'ignore').decode('utf-8')
                if vid not in found_videos:
                    found_videos[vid] = clean_name
    except Exception as e:
        print(f"❌ 页面解析异常: {e}")

print(f"✨ 成功捕获有效视频 ID 总数: {len(found_videos)} 个")

vod_list = []
global_id = 40001
lock = __import__('threading').Lock()

def fetch_multiline(vid, vname):
    global global_id
    session = requests.Session()
    session.headers.update(HEADERS)
    
    play_page_url = f"{HOST}/play/{vid}"
    specific_headers = HEADERS.copy()
    specific_headers['Referer'] = play_page_url
    
    try:
        # 第一步：访问播放页提取动态 token
        page_res = session.get(play_page_url, headers=specific_headers, timeout=8)
        
        token = ""
        if page_res.status_code == 200:
            token_match = re.search(r'token\s*[:=]\s*[\'"]([a-fA-F0-9]{32})[\'"]', page_res.text)
            if not token_match:
                token_match = re.search(r'token=([a-fA-F0-9]{32})', page_res.text)
            if token_match:
                token = token_match.group(1)
        
        # 备用静态 token 兜底（如果动态没抓到）
        if not token:
            token = "8a8b8581b7b50d7d34a59becb5740889"

        # 第二步：使用标准 params 传入参数
        api_url = f"{HOST}/api/getResN"
        params = {
            "videoId": vid,
            "mtype": 1,
            "token": token
        }
        
        api_res = session.get(
            api_url,
            params=params,
            headers=specific_headers,
            timeout=15,
        )

        # 【核心第一步诊断日志】
        try:
            j_data = api_res.json()
            print(
                f"[DEBUG] ID={vid}, "
                f"HTTP={api_res.status_code}, "
                f"state={j_data.get('state')}, "
                f"message={j_data.get('message')}, "
                f"keys={list(j_data.keys())}, "
                f"token_len={len(token)}"
            )
            if j_data.get("state") != 1:
                print(f"[FAIL] ID={vid}: {j_data}")
                return
        except (ValueError, AttributeError, TypeError) as exc:
            print(f"响应解析失败 [ID={vid}]: {repr(exc)}")
            print(api_res.text[:300])
            return

        # 第三步：解析标准的列表数据
        sources = j_data.get("data", {}).get("list", [])
        if not sources:
            print(f"[WARN] ID={vid}: state=1 但 list 为空")
            return

        play_from_list = []
        play_url_list = []

        for source in sources:
            site_id = source.get("siteId", 0)
            source_name = f"AIKAN线路{site_id}"
            
            res_data = source.get("resData", "[]")
            if isinstance(res_data, str):
                try:
                    sub_lines = json.loads(res_data)
                except:
                    sub_lines = []
            elif isinstance(res_data, list):
                sub_lines = res_data
            else:
                sub_lines = []

            source_episodes = []
            for sub in sub_lines:
                if isinstance(sub, dict):
                    raw_url = sub.get("url", "")
                    new_name = sub.get("newName", "")
                    if raw_url:
                        # 兼容处理带名称或无名称的 url
                        if "$" not in raw_url and new_name:
                            final_ep_str = f"{new_name}${raw_url}"
                        else:
                            final_ep_str = raw_url
                        source_episodes.append(final_ep_str)
            
            if source_episodes:
                play_from_list.append(source_name)
                play_url_list.append("#".join(source_episodes))

        if play_from_list and play_url_list:
            final_play_from = "$$$".join(play_from_list)
            final_play_url = "$$$".join(play_url_list)

            with lock:
                vod_list.append({
                    "vod_id": global_id,
                    "vod_name": vname,
                    "type_id": 1,
                    "type_name": "电影",
                    "vod_pic": "", 
                    "vod_remarks": f"已聚合{len(play_from_list)}个源",
                    "vod_play_from": final_play_from,
                    "vod_play_url": final_play_url
                })
                global_id += 1
    except Exception as e:
        print(f"⚠️ 请求异常 [ID={vid}]: {e}")

# 限制并发先跑少量以便观察详细诊断输出
start_time = time.time()
items = list(found_videos.items())[:15]

with ThreadPoolExecutor(max_workers=3) as executor:
    for vid, vname in items:
        executor.submit(fetch_multiline, vid, vname)

print(f"\n⚡ 调试聚合完毕，成功收编大片: {len(vod_list)} 部")

if len(vod_list) == 0:
    vod_list.append({
        "vod_id": global_id,
        "vod_name": "星际穿越 (诊断测试)",
        "type_id": 1,
        "type_name": "电影",
        "vod_pic": "",
        "vod_remarks": "测试线路",
        "vod_play_from": "AIKAN多线",
        "vod_play_url": "正片$https://play.xluuss.com/play/1aM51maW/index.m3u8"
    })

result = {
    "code": 1, "msg": "成功", "page": 1, "pagecount": 1,
    "limit": len(vod_list), "total": len(vod_list),
    "class": [{"type_id": 1, "type_name": "电影"}, {"type_id": 2, "type_name": "连续剧"}, {"type_id": 3, "type_name": "综艺"}, {"type_id": 4, "type_name": "动漫"}],
    "list": vod_list
}

with open("aikan.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"🎉 诊断版 aikan.json 已生成！")
