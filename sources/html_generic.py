# -*- coding: utf-8 -*-
"""
纯 HTML 源模板（给 www.kpkuang.fun 这类站用）

这类站没有可用 JSON 接口，只能抓列表页 + 详情页。
模板采用「扫链接 + 就近取字段」的策略，不依赖某个具体 class 名，
大部分苹果CMS 模板站不用改代码就能跑；跑不出来再按 --probe 的结果微调。

用法：复制本文件 → 改名 → 改 host / 路径模板 / 正则 → 在 __init__.py 注册
"""

import re

from .base import HttpClient, make_item, extract_play, abs_url


class HtmlGenericSource:
    key = 'html_template'
    name = '纯HTML模板源'
    enabled = False                 # 改完记得打开

    host = 'https://example.com'
    id_base = 3_000_000

    classes = [
        {'type_id': 1, 'type_name': '电影'},
        {'type_id': 2, 'type_name': '连续剧'},
        {'type_id': 3, 'type_name': '综艺'},
        {'type_id': 4, 'type_name': '动漫'},
    ]

    # ---- 需要按站点修改的三处 ----
    # 1. 列表页地址模板（{page} 从 1 开始）
    LIST_URL = '{host}/vodshow/{tid}--------{page}---.html'
    # 2. 列表页里「详情链接」的正则，group(1) 是 href
    DETAIL_LINK_RE = r'href="(/(?:voddetail|detail|vod)/[^"]+?\.html)"'
    # 3. 详情页地址模板（{id} 是上面正则里抠出来的路径片段）
    DETAIL_URL = '{host}{id}'

    def __init__(self):
        self.http = HttpClient(referer=self.host)

    # ---------------- 列表 ----------------
    def _parse_list(self, html):
        """
        扫出所有详情链接，并在链接附近（±500 字符）找标题、封面、备注。
        返回 [{id, name, pic, remarks}, ...]
        """
        out = []
        seen = set()
        for m in re.finditer(self.DETAIL_LINK_RE, html):
            href = m.group(1)
            if href in seen:
                continue
            seen.add(href)

            window = html[max(0, m.start() - 500): m.end() + 500]

            # 标题：优先 title 属性，其次 a 标签内文字
            tm = re.search(r'title="([^"]{1,80})"', window)
            if not tm:
                tm = re.search(r'>([^<>]{2,80})</a>', html[m.start(): m.end() + 200])
            name = tm.group(1).strip() if tm else ''
            if not name:
                continue

            # 封面：就近的 jpg/webp/png
            pm = re.search(r'(?:data-src|data-original|src)="([^"]+?\.(?:jpg|jpeg|png|webp)[^"]*)"', window)
            pic = abs_url(self.host, pm.group(1)) if pm else ''

            # 备注：就近的短 span（更新至xx集 / HD 之类）
            rm = re.findall(r'<span[^>]*>([^<>]{1,20})</span>', window)
            remarks = rm[-1].strip() if rm else ''

            out.append({'id': href, 'name': name, 'pic': pic, 'remarks': remarks})
        return out

    # ---------------- 详情 ----------------
    def _fetch_detail(self, path):
        url = self.DETAIL_URL.format(host=self.host, id=path)
        try:
            html = self.http.get(url)
        except Exception as e:
            print(f'  [{self.key}] 详情失败 {url}: {e}')
            return ''
        return html

    # ---------------- 主流程 ----------------
    def crawl(self, pages=2, max_details=60, skip=None):
        items = []
        seq = 0
        detail_count = 0

        for c in self.classes:
            tid = c['type_id']
            for page in range(1, pages + 1):
                url = self.LIST_URL.format(host=self.host, tid=tid, page=page)
                try:
                    html = self.http.get(url)
                except Exception as e:
                    print(f'  [{self.key}] 列表失败 {url}: {e}')
                    break

                rows = self._parse_list(html)
                if not rows:
                    print(f'  [{self.key}] 列表没匹配到条目，检查 DETAIL_LINK_RE: {url}')
                    break
                print(f'  [{self.key}] tid={tid} p{page} 列表 {len(rows)} 条')

                for r in rows:
                    if max_details and detail_count >= max_details:
                        return items
                    if skip and skip(r['name'], r['remarks']):
                        continue
                    detail_count += 1

                    detail = self._fetch_detail(r['id'])
                    if not detail:
                        continue

                    groups = extract_play(detail)
                    if not groups:
                        print(f'  [{self.key}] 没解析到播放地址: {r["name"]}')
                        continue

                    item = make_item(
                        vod_id=self.id_base + seq,
                        name=r['name'],
                        type_id=tid,
                        type_name=c['type_name'],
                        pic=r['pic'],
                        remarks=r['remarks'],
                        groups=groups,
                        source=self.key,
                    )
                    if item:
                        items.append(item)
                        seq += 1

        return items

    # ---------------- 调试 ----------------
    def probe(self, tid=1, page=1):
        """打印列表页解析结果，用来确认正则对不对。"""
        url = self.LIST_URL.format(host=self.host, tid=tid, page=page)
        print(f'列表页: {url}')
        html = self.http.get(url)
        print(f'HTML 长度: {len(html)}')
        rows = self._parse_list(html)
        print(f'解析到 {len(rows)} 条:')
        for r in rows[:5]:
            print('  ', r)
        if rows:
            detail = self._fetch_detail(rows[0]['id'])
            print(f'详情页长度: {len(detail)}')
            print(f'播放组: {extract_play(detail)}')
