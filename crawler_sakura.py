import requests
import json

print("🚀 正在通过苹果CMS标准接口采集 [樱花影院] 数据...")

# 樱花影院的苹果CMS标准采集接口
API_URL = "https://www.dcjyb.com/api.php/provide/vod/?ac=detail"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Referer': 'https://www.dcjyb.com/'
}

sakura_vod_list = []

try:
    # 采集前 3 页（可以根据需要调整页数范围）
    for page in range(1, 4):
        res = requests.get(f"{API_URL}&pg={page}", headers=HEADERS, timeout=15)
        if res.status_code == 200:
            data = res.json()
            items = data.get("list", [])
            if not items:
                break
                
            for item in items:
                # 给 ID 加上一个专属前缀或偏移量，防止和 A123TV 的 ID 冲突
                orig_id = item.get("vod_id", 0)
                sakura_vod_list.append({
                    "vod_id": 800000 + int(orig_id) if str(orig_id).isdigit() else orig_id,
                    "vod_name": item.get("vod_name"),
                    "type_id": item.get("type_id", 20),
                    "type_name": item.get("type_name", "电影"),
                    "vod_pic": item.get("vod_pic", ""),
                    "vod_remarks": item.get("vod_remarks", "高清"),
                    "vod_play_from": item.get("vod_play_from", "樱花多线"),
                    "vod_play_url": item.get("vod_play_url", "")
                })
        print(f"📄 樱花影院已完成第 {page} 页采集...")
except Exception as e:
    print(f"⚠️ 樱花影院采集异常: {e}")

result = {
    "code": 1,
    "msg": "数据成功",
    "page": 1,
    "pagecount": 1,
    "limit": len(sakura_vod_list),
    "total": len(sakura_vod_list),
    "class": [
        {"type_id": 20, "type_name": "电影"},
        {"type_id": 35, "type_name": "连续剧"},
        {"type_id": 43, "type_name": "综艺节目"},
        {"type_id": 55, "type_name": "短剧"},
        {"type_id": 48, "type_name": "动漫"},
        {"type_id": 54, "type_name": "影视解说"}
    ],
    "list": sakura_vod_list
}

# 独立生成一个 sakura.json 文件
with open("sakura.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"✅ 樱花影院采集完毕！共生成视频数据：{len(sakura_vod_list)} 部，已保存至 sakura.json")
