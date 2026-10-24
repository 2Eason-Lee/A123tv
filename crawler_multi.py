import requests
import json
import sys
import time

# 请将此处替换为你抓包时看到的该多线路网站的主域名
HOST = 'https://你的目标网站域名.com' 

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Referer': HOST
}

vod_list = []
global_id = 40001 # 使用4开头，与A123(1开头)区分开

print("🚀 开始抓取多线路聚合站数据...")

try:
    # 模拟获取首页或列表的影片ID（这里以遍历常见ID或通过API获取为例）
    # 假设我们通过接口获取最新列表，此处编写你的列表获取逻辑
    # 为了演示稳定，我们以核心接口请求为例：
    
    # 示例：假设我们获取到了一批影片ID列表（你可以根据实际抓包的列表接口调整）
    # 这里我们采用安全稳健的方式，生成标准的多线路结构
    
    # 实际生产中，你可以请求其列表API，这里为你写好了解析多线路的核心逻辑：
    sample_video_ids = [482774] # 可以扩展为从列表页动态抓取的一批ID
    
    for vid in sample_video_ids:
        api_url = f"{HOST}/getResN?videoid={vid}&mtype=1"
        res = requests.get(api_url, headers=HEADERS, timeout=10)
        
        if res.status_code == 200:
            result_json = res.json()
            if result_json.get("state") == 1:
                data_list = result_json.get("data", {}).get("list", [])
                
                play_urls = []
                for line in data_list:
                    res_data_str = line.get("resData", "[]")
                    try:
                        # 解析嵌套的 JSON 字符串
                        sub_lines = json.loads(res_data_str)
                        for sub in sub_lines:
                            url = sub.get("url", "")
                            if url:
                                play_urls.append(url)
                    except:
                        continue
                
                if play_urls:
                    # 将多条线路用 $$$ 拼接起来，苹果CMS和播放器完美支持多线路切换
                    final_play_url = "$$$".join(play_urls)
                    
                    vod_list.append({
                        "vod_id": global_id,
                        "vod_name": f"多线路测试影片_{vid}",
                        "type_id": 1,
                        "type_name": "电影",
                        "vod_pic": "", # 可从详情页补充
                        "vod_remarks": f"共{len(play_urls)}条线路",
                        "vod_play_from": "流霞多线",
                        "vod_play_url": final_play_url
                    })
                    global_id += 1

except Exception as e:
    print(f"❌ 抓取报错: {e}")

if len(vod_list) == 0:
    print("\n⚠️ 提示：请将脚本中的 HOST 替换为实际抓包的网站主域名。")

result = {
    "code": 1, "msg": "成功", "page": 1, "pagecount": 1,
    "limit": len(vod_list), "total": len(vod_list),
    "class": [{"type_id": 1, "type_name": "电影"}, {"type_id": 2, "type_name": "连续剧"}, {"type_id": 3, "type_name": "综艺"}, {"type_id": 4, "type_name": "动漫"}],
    "list": vod_list
}

with open("multi.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print(f"\n🎉 多线路数据生成完毕！共处理 {len(vod_list)} 部影片")
