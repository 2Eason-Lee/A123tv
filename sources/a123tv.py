# -*- coding: utf-8 -*-
"""
A123TV 源（你原来 crawler.py 的移植版）

原逻辑保留，只是套进 v2 的 Source 基类：
  - 列表 /t/{tid}.html、/t/{tid}/p{page}.html，一页 36 条
  - 详情页里有 var pp = {"la": [...]}，extract_play() 已经能解
  - 同一 slug 只保留一次

这样 v2 = a123tv + jsard，正式跑不会把你原来 720 条的数据弄丢。
"""

import re

from .base import Source, extract_play, abs_url


class A123TVSource(Source):
    key = 'a123tv'
    name = 'A123TV（自研核心）'
    enabled = True

    domain = 'https://a123tv.com'
    offset = 1_000_000

    categories = [
        {'type_id': 10, 'type_name': '电影'},
        {'type_id': 11, 'type_name': '连续剧'},
        {'type_id': 12, 'type_name': '综艺'},
        {'type_id': 13, 'type_name': '动漫'},
    ]

    def __init__(self):
        super().__init__()
        self._seen = set()          # 跨页去重，和原 crawler.py 一致

    def list_page(self, category, page):
        tid = category['type_id']
        if page == 1:
            url = f'{self.domain}/t/{tid}.html'
        else:
            url = f'{self.domain}/t/{tid}/p{page}.html'

        html = self.http.get(url)
        rows = []
        for block in re.findall(r'<div class="w4-item-wrap">([\s\S]*?)</div>\s*</div>', html):
            link = re.search(r'href="/v/([^"]+?)\.html"', block)
            title = re.search(r'title="([^"]+?)"', block)
            if not link or not title:
                continue

            slug = link.group(1).strip()
            if slug in self._seen:
                continue
            self._seen.add(slug)

            img = re.search(r'data-src="([^"]+?)"', block)
            remarks = re.search(r'<span>([^<]+?)</span>', block)

            rows.append({
                'vod_name': title.group(1).strip(),
                'vod_pic': abs_url(self.domain, img.group(1) if img else ''),
                'vod_remarks': remarks.group(1).strip() if remarks else '',
                'detail_link': f'/v/{slug}.html',
            })
        return rows

    def play(self, item):
        html = self.http.get(self.domain + item['detail_link'])
        return extract_play(html)
