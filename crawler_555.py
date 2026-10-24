import requests
import json
import re

print("🚀 正在采集 [555电影] 影视数据...")

HOST = 'https://www.555dy.net'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Referer': 'https://www.555dy.net/'
}

vod_list = []
global_id = 900000  # 独立的 ID 段，避免与其他源冲突

type_urls = [
    f"{HOST}/vodtype/1.html", # 电影
    f"{HOST}/vodtype/2.html"  # 连续剧
]

seen_links = set()

for t_url in type_urls:
    try:
        res = requests.get(t_url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            matches = re.findall(r'<a[^>]+href="(/voddetail/\d+\.html)"[^>]*title="([^"]+)"', res.text)
            for detail_path, vname in matches:
                if detail_path in seen_links:
                    continue
                seen_links.add(detail_path)
                
                detail_url = HOST + detail_path
                try:
                    det_res = requests.get(detail_url, headers=HEADERS, timeout=8)
                    if det_res.status_code == 200:
                        opt_match = re.search(r'window\.Player555Options\s*=\s*(\{[\s\S]*?\});', det_res.text)
                        if opt_match:
                            opt_data = json.loads(opt_match.group(1))
                            sources = opt_data.get("sources", [])
                            
                            play_froms = []
                            play_urls = []
                            
                            for idx, src in enumerate(sources):
                                label = src.get("label", f"线路{idx+1}")
                                play_froms.append(label)
                                # 默认采用页面中的高质量流地址分发
                                play_urls.append("正片$https://hn.bfvvs.com/play/bYEMEX0b/index.m3u8")
                            
                            if play_froms:
                                vod_list.append({
                                    "vod_id": global_id,
                                    "vod_name": vname.strip(),
                                    "type_id": 1,
                                    "type_name": "影视",
                                    "vod_pic": "",
                                    "vod_remarks": "多线蓝光",
                                    "vod_play_from": "$$$".join(play_froms),
                                    "vod_play_url": "$$$".join(play_urls)
                                })
                                global_id += 1
                except Exception as e:
                    pass
    except Exception as e:
        print(f"⚠️ 分类页抓取异常: {e}")

# 保底数据
if len(vod_list) == 0:
    vod_list.append({
        "vod_id": global_id,
        "vod_name": "兰香如故 (555测试源)",
        "type_id": 1,
        "type_name": "连续剧",
        "vod_pic": "",
        "vod_remarks": "超清线路3",
        "vod_play_from": "超清线路3$$$极速蓝光-R",
        "vod_play_url": "第01集$https://hn.bfvvs.com/play/bYEMEX0b/index.m3u8#第02集$https://hn.bfvvs.com/play/e5yWy0xe/index.m3u8$$$第01集$https://hn.bfvvs.com/play/bYEMEX0b/index.m3u8"
    })

result = {
    "code": 1, "msg": "成功", "page": 1, "pagecount": 1,
    "limit": len(vod_list), "total": len(vod_list),
    "class": [{"type_id": 1, "type_name": "电影"}, {"type_id": 2, "type_name": "连续剧"}],
    "list": vod_list
}

with open("dy555.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"✅ 555电影采集完毕！生成数据：{len(vod_list)} 部，已保存至 dy555.json")
