import requests
import json
import sys
import time

HOST = 'https://www.boju.cc'
API_URL = f'{HOST}/api.php/provide/vod/'

# 增加浏览器伪装，防止被服务器秒踢
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/javascript, */*; q=0.01'
}

vod_list = []
global_id = 30001

print("🚀 开始通过 API 极速抓取 [播剧网] 数据...")

try:
    for page in range(1, 11):
        url = f"{API_URL}?ac=detail&pg={page}"
        # 加入 headers 伪装
        res = requests.get(url, headers=HEADERS, timeout=15)
        
        if res.status_code != 200:
            print(f"❌ 第 {page} 页请求失败，状态码: {res.status_code}")
            continue
            
        try:
            data = res.json()
        except json.decoder.JSONDecodeError:
            print(f"❌ 返回的不是 JSON，已被防火墙拦截！")
            print(f"拦截页面内容前100字符: {res.text[:100]}")
            break # 已经被拦截，跳出循环

        if "list" in data:
            for item in data["list"]:
                play_url = item.get("vod_play_url", "")
                if "$$$" in play_url:
                    play_url = play_url.split("$$$")[0]
                if not play_url:
                    continue
                
                vod_list.append({
                    "vod_id": global_id,
                    "vod_name": item.get("vod_name", ""),
                    "type_id": item.get("type_id", 1),
                    "type_name": item.get("type_name", "电影"),
                    "vod_pic": item.get("vod_pic", ""),
                    "vod_remarks": item.get("vod_remarks", ""),
                    "vod_play_from": "流霞极速",
                    "vod_play_url": play_url
                })
                global_id += 1
        print(f"✅ 成功获取第 {page} 页")
        time.sleep(1)  # 稍微停顿，避免请求过猛被封 IP

except Exception as e:
    print(f"❌ 运行报错: {e}")

if len(vod_list) == 0:
    print("\n🚨 抓取失败！未拿到任何数据，放弃覆盖。")
    sys.exit(1)

result = {
    "code": 1, "msg": "成功", "page": 1, "pagecount": 1,
    "limit": len(vod_list), "total": len(vod_list),
    "class": [{"type_id": 1, "type_name": "电影"}, {"type_id": 2, "type_name": "连续剧"}, {"type_id": 3, "type_name": "综艺"}, {"type_id": 4, "type_name": "动漫"}],
    "list": vod_list
}

with open("boju.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print(f"\n🎉 播剧网抓取完成！共秒抓 {len(vod_list)} 部影片")
