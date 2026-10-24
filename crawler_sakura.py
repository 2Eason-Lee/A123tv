import requests
import json

print("🚀 正在通过增强伪装请求 [樱花影院] 数据...")

API_URL = "https://www.dcjyb.com/api.php/provide/vod/?ac=detail"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Referer': 'https://www.dcjyb.com/',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'X-Requested-With': 'XMLHttpRequest'
}

sakura_vod_list = []

try:
    session = requests.Session()
    # 先访问一次主页获取必要的 Cookies 和维持会话
    session.get("https://www.dcjyb.com/", headers=HEADERS, timeout=10)
    
    for page in range(1, 4):
        target_url = f"{API_URL}&pg={page}"
        res = session.get(target_url, headers=HEADERS, timeout=15)
        
        print(f"📄 第 {page} 页请求状态码: {res.status_code}")
        
        if res.status_code == 200:
            try:
                data = res.json()
                items = data.get("list", [])
                if not items:
                    break
                    
                for item in items:
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
                print(f"✨ 成功解析第 {page} 页，获取大片: {len(items)} 部")
            except json.JSONDecodeError:
                print(f"❌ 错误：服务器未返回 JSON，响应内容前 200 字符为：{res.text[:200]}")
                break
except Exception as e:
    print(f"⚠️ 采集异常: {e}")

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

with open("sakura.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"✅ 樱花影院同步结束，共生成视频数据：{len(sakura_vod_list)} 部，已保存至 sakura.json")
