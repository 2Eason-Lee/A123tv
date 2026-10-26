# -*- coding: utf-8 -*-
"""
tv.tzqjdy.com / 飘零影院

取数链路（2026-10 实测）：
  1. 列表页 HTML：/m/{tid}.shtml（第1页） /m/{tid}/p{N}.shtml（后续页）
     每一项里有详情链接 /q/{id}.shtml、片名、封面、备注
  2. 详情页 HTML：/q/{id}.shtml
     页面下方 id="detail" 区域里列出所有线路 × 所有集的播放页链接：
       /09/{id}-{source}m3u8-{nid}.shtml
  3. 播放页 HTML：/{num}/{id}-{source}m3u8-{nid}.shtml
     内联脚本里 var dp = new DPlayer({ video: { url: 'xxx.m3u8' } })
     直接用正则抠 m3u8 地址，无需解码
"""

import re
import html as _html
from .base import HttpClient, make_item, clean_episodes, abs_url


class TzqjdySource:
    key = 'tzqjdy'
    name = '飘零影院'
    enabled = True

    host = 'https://tv.tzqjdy.com'
    id_base = 30_000_000
    delay = 0.2

    max_lines = 2
    max_eps = 30

    classes = [
        {'type_id': 19553, 'type_name': '电影'},
        {'type_id': 19568, 'type_name': '连续剧'},
        {'type_id': 19585, 'type_name': '动漫'},
        {'type_id': 19591, 'type_name': '综艺'},
    ]

    def __init__(self):
        self.http = HttpClient(referer=self.host, delay=self.delay)

    def _list_page(self, tid, page):
        if page == 1:
            url = f'{self.host}/m/{tid}.shtml'
        else:
            url = f'{self.host}/m/{tid}/p{page}.shtml'
        html = self.http.get(url)

        rows = []
        seen = set()

        item_re = re.compile(
            r'<div class="pic"><a[^>]*href="(https://tv\.tzqjdy\.com/(?:q|m)/[^"]+?\.shtml)"[^>]*>([\s\S]*?)</a>'
            r'[\s\S]*?'
            r'(?:<span[^>]*>([^<]*)</span>)?'
            r'[\s\S]*?'
            r'</div>'
            r'[\s\S]*?'
            r'<div class="biaoti"><a[^>]*href="\1"[^>]*>([\s\S]*?)</a></div>'
        )
        for m in item_re.finditer(html):
            href = m.group(1)
            if href in seen:
                continue
            seen.add(href)

            inner_pic = m.group(2)
            remarks = _html.unescape((m.group(3) or '').strip())
            title_tag = m.group(4)
            name = re.sub(r'<[^>]+>', '', title_tag).strip()
            name = _html.unescape(name)
            if not name or len(name) < 2:
                continue

            pm = re.search(
                r'(?:data-original|data-src|src)="([^"]+?\.(?:jpg|jpeg|png|webp)[^"]*)"',
                inner_pic,
            )
            pic = abs_url(self.host, pm.group(1)) if pm else ''

            rows.append({'detail_link': href, 'vod_name': name,
                         'vod_pic': pic, 'vod_remarks': remarks})

        return rows

    def _lines_and_episodes(self, detail_url):
        html = self.http.get(detail_url)

        detail_m = re.search(r'id="detail"[\s\S]*', html)
        if detail_m:
            dhtml = html[detail_m.start():]
        else:
            dhtml = html

        play_link_re = re.compile(
            r'<a[^>]*title="([^"]*)"[^>]*href="(https://tv\.tzqjdy\.com/\d+/[^"]+?\.shtml)"[^>]*>'
        )

        groups = {}
        for pm in play_link_re.finditer(dhtml):
            ep_title = pm.group(1).strip()
            href = pm.group(2)
            m_source = re.search(r'-([a-z]+m3u8)-\d+\.shtml$', href)
            source = m_source.group(1) if m_source else 'unknown'
            line_map = {
                'gsm3u8': '光速',
                'hhm3u8': '哈哈',
                'jym3u8': '鲸鱼',
                'dbm3u8': '豆瓣',
                'ykm3u8': '优酷',
                'txm3u8': '腾讯',
                'dlm3u8': '哆啦',
            }
            line_name = line_map.get(source, source)

            if line_name not in groups:
                groups[line_name] = []
            groups[line_name].append((ep_title, href))

        return [(n, eps) for n, eps in groups.items()]

    def _extract_m3u8(self, play_url):
        html = self.http.get(play_url)
        m = re.search(
            r"video\s*:\s*\{[^}]*url\s*:\s*['\"]([^'\"]+\.m3u8[^'\"]*)['\"]",
            html,
        )
        if m:
            return m.group(1)
        m = re.search(r'https?://[^\s"\'<>]+?\.m3u8[^\s"\'<>]*', html)
        return m.group(0) if m else ''

    def crawl(self, pages=2, max_details=60, skip=None):
        items = []
        seq = 0

        for c in self.classes:
            tid = c['type_id']
            for page in range(1, pages + 1):
                if max_details and seq >= max_details:
                    break
                try:
                    rows = self._list_page(tid, page)
                except Exception as e:
                    print(f'  [{self.key}] 列表失败 tid={tid} p{page}: {e}')
                    break
                if not rows:
                    break
                print(f'  [{self.key}] {c["type_name"]} p{page} 列表 {len(rows)} 条')

                for r in rows:
                    if max_details and seq >= max_details:
                        return items
                    name = r['vod_name']
                    if skip and skip(name, r.get('vod_remarks', '')):
                        continue

                    try:
                        lines = self._lines_and_episodes(r['detail_link'])
                    except Exception as e:
                        print(f'  [{self.key}] 详情失败 {name}: {e}')
                        continue

                    if not lines:
                        print(f'  [{self.key}] 详情页没找到线路: {name}')
                        continue

                    groups = []
                    for line_name, ep_pairs in lines[:self.max_lines]:
                        ep_pairs = ep_pairs[:self.max_eps]
                        eps = []
                        for ep_title, play_url in ep_pairs:
                            try:
                                m3u8 = self._extract_m3u8(play_url)
                            except Exception as e:
                                print(f'  [{self.key}] 播放页失败 {play_url}: {e}')
                                continue
                            if not m3u8:
                                continue
                            ep_name = ep_title or f'第{len(eps) + 1}集'
                            eps.append((ep_name, m3u8))
                        cleaned = clean_episodes(eps)
                        if cleaned:
                            groups.append((line_name, cleaned))

                    if not groups:
                        print(f'  [{self.key}] 没拿到播放地址: {name}')
                        continue

                    item = make_item(
                        vod_id=self.id_base + seq,
                        name=name,
                        type_id=tid,
                        type_name=c['type_name'],
                        pic=r.get('vod_pic', ''),
                        remarks=r.get('vod_remarks', ''),
                        groups=groups,
                        source=self.key,
                    )
                    if item:
                        items.append(item)
                        seq += 1
                        print(f'  [{self.key}] ✓ {name} | {groups[0][0]} | {len(groups[0][1])} 集')

        return items