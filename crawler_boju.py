import requests
import json
import sys

HOST = 'https://www.boju.cc'
# 苹果CMS自带的默认隐藏 API 接口
API_URL = f'{HOST}/api.php/provide/vod/'

vod_list = []
global_id = 30001  # 使用3开头，避免与A123(1开头)冲突

print("🚀 开始通过 API 极速抓取 [播剧网] 数据...")

try:
    # 直接拉取最新更新的前 10 页数据（约 200 部影片）
    for page in range(1, 11):
        # ?ac=detail 参数会直接返回包含影片详情和 m3u8 直链的纯 JSON 数据
        res = requests.get(f"{API_URL}?ac=detail&pg={page}", timeout=10).json()
        
        if "list" in res:
            for item in res["list"]:
                play_url = item.get("vod_play_url", "")
                
                # 如果有多个线路（以$$$分隔），我们只取第一个最快的线路
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
except Exception as e:
    print(f"❌ 抓取失败，网站可能修改了 API: {e}")

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
