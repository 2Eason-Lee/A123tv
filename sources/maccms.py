# -*- coding: utf-8 -*-
"""
通用苹果CMS V10 源。

这是最省事的一类源：站方自己开了接口，列表和播放地址都是 JSON，
不需要解析 HTML，加一个新站只要改 API 一行。

判断标准（浏览器或 curl 试一下）：
    https://站点/api.php/provide/vod/?ac=list
返回 {"code":1,"class":[...],"list":[...]} 就能直接用本文件。
返回 "closed" 说明接口被关，得用 html_generic.py 那套。
"""

from .base import HttpClient, make_item, clean_episodes, abs_url


class MacCMSSource:
    key = 'maccms'
    name = '通用苹果CMS'
    enabled = False          # 默认关闭，确认接口可用再打开

    host = ''                # 例如 https://www.example.com
    api = ''                 # 例如 https://www.example.com/api.php/provide/vod/
    id_base = 9_000_000      # vod_id 分段，避免和别的源撞号

    classes = [
        {'type_id': 10, 'type_name': '电影'},
        {'type_id': 11, 'type_name': '连续剧'},
        {'type_id': 12, 'type_name': '综艺'},
        {'type_id': 13, 'type_name': '动漫'},
    ]

    def __init__(self):
        self.http = HttpClient(referer=self.host)

    # ---------- 列表 ----------
    def _list_page(self, tid, page):
        url = f'{self.api}?ac=list&pg={page}&t={tid}'
        data = self.http.get_json(url)
        if str(data.get('code')) != '1':
            raise RuntimeError(f'接口返回异常: {str(data)[:120]}')
        return data

    # ---------- 详情（拿播放地址）----------
    def _detail(self, ids):
        """一次批量查，减少请求数。返回 {vod_id: (from, url)}"""
        url = f'{self.api}?ac=detail&ids={",".join(str(i) for i in ids)}'
        data = self.http.get_json(url)
        out = {}
        for v in data.get('list', []):
            out[str(v.get('vod_id'))] = (v.get('vod_play_from', ''), v.get('vod_play_url', ''))
        return out

    # ---------- 主流程 ----------
    def crawl(self, pages=2, page_size_hint=20, skip=None):
        items = []
        seq = 0
        for c in self.classes:
            tid = c['type_id']
            for page in range(1, pages + 1):
                try:
                    data = self._list_page(tid, page)
                except Exception as e:
                    print(f'  [{self.key}] 列表失败 tid={tid} p{page}: {e}')
                    break

                rows = data.get('list', [])
                if not rows:
                    break

                # 批量查详情
                id_map = {}
                try:
                    id_map = self._detail([r['vod_id'] for r in rows])
                except Exception as e:
                    print(f'  [{self.key}] 详情失败 tid={tid} p{page}: {e}')

                for r in rows:
                    vid = str(r.get('vod_id'))
                    if skip and skip(r.get('vod_name', ''), r.get('vod_remarks', '')):
                        continue
                    play_from, play_url = id_map.get(vid, ('', ''))
                    if not play_url:
                        continue

                    # 苹果CMS 的 vod_play_url 本身已是标准格式，这里只做去重
                    groups = []
                    from_list = play_from.split('$$$')
                    url_list = play_url.split('$$$')
                    for i, group in enumerate(url_list):
                        pairs = []
                        for ep in group.split('#'):
                            if '$' not in ep:
                                continue
                            ep_name, ep_url = ep.split('$', 1)
                            pairs.append((ep_name, ep_url))
                        cleaned = clean_episodes(pairs)
                        if cleaned:
                            groups.append((from_list[i] if i < len(from_list) else f'线路{i + 1}',
                                           cleaned))

                    item = make_item(
                        vod_id=self.id_base + seq,
                        name=r.get('vod_name', ''),
                        type_id=tid,
                        type_name=c['type_name'],
                        pic=abs_url(self.host, r.get('vod_pic', '')),
                        remarks=r.get('vod_remarks', ''),
                        groups=groups,
                        source=self.key,
                    )
                    if item:
                        items.append(item)
                        seq += 1
        return items
