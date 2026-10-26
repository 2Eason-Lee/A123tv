# -*- coding: utf-8 -*-
"""
A123TV 源（你原来 crawler.py 的移植版）

原逻辑保留，只是套进 v2 的 Source 基类：
  - 列表 /t/{tid}.html、/t/{tid}/p{page}.html，一页 36 条
  - 详情页里有 var pp = {"la": [...]}，extract_play() 已经能解
  - 同一 slug 只保留一次

2026-10 修正：a123tv 的 pp.la 不是「一集一条」，而是「一条线路一条」。
  la[i] = [线路ID, 线路名, 该线路总集数, 当前集序号, 当前集 m3u8]
详情页 HTML 里还有更关键的信息，旧解析全丢了：

  <a class="w4-line-item" href="/v/{slug}/{线路ID}z0.html" title="线路220">
    <img alt="欢迎来龙餐馆[TC]">
    <div class="i">共1集 / 720p</div>

以前的 extract_play() 把每条线路都当成一集，集名变成「线路220」，
并且完全看不到 [TC] / [正片] / 1080p 这些标签，所以经常只抓到枪版。
现在的做法：
  1. 解析详情页所有线路，带上版本标签（TC / 正片 / HD国语）和分辨率；
  2. 按「版本标签 > 分辨率 > 集数」排序，电影留 4 条、短剧 2 条、长剧 1 条；
  3. 每个 z{n} 播放页一次能拿到【所有线路】的第 n 集，
     所以 N 集只需要 N 次请求，而不是 线路数 × 集数。
"""

import re
import json
import html as _html
import threading
from concurrent.futures import ThreadPoolExecutor

from .base import (
    HttpClient, Source, abs_url, clean_episodes, extract_play, quality_score,
    probe_m3u8, stream_quality_score,
)


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

    max_lines_movie = 4    # 电影多留几条：同一部片常混着 TC / 抢先版 / 正片 / HD国语
    max_lines_series = 2   # 连续剧留两条兜底
    max_probe_lines = 10   # 电影线路动辄 30+ 条，只探测排名靠前的这些
    max_eps = 150          # 单条线路最多抓多少集
    workers = 6            # 并发抓播放页

    def __init__(self):
        super().__init__()
        self._seen = set()          # 跨页去重，和原 crawler.py 一致
        self._tls = threading.local()

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
            # 卡片上的 <span> 是「89个线路」，不是更新状态。右上角的 1080p 才是
            # 稳定、有用的信息；用它当备注，增量跳过也能正常比较。
            res = re.search(r'<div class="r">\s*([^<]*?)\s*</div>', block)
            remarks = res.group(1).strip() if res else ''

            rows.append({
                'vod_name': title.group(1).strip(),
                'vod_pic': abs_url(self.domain, img.group(1) if img else ''),
                'vod_remarks': remarks,
                'detail_link': f'/v/{slug}.html',
                'type_id': category['type_id'],
                'type_name': category['type_name'],
            })
        return rows

    # ---------------- 详情页：线路列表 ----------------
    @staticmethod
    def _version_tags(text):
        """从「欢迎来龙餐馆[正片]」里取出 [正片] 这类版本标签。"""
        tags = re.findall(r'[\[【]([^\]】]+)[\]】]', text or '')
        return ' '.join(tags)

    def _parse_lines(self, html):
        """
        解析详情页里的线路卡片。

        返回 [{'id','name','version','count','height','order','first_url'}]，
        按页面顺序排列；first_url 取自页面里的 var pp，是这条线路第 1 集的 m3u8。
        """
        la_map = {}
        m = re.search(r'var\s+pp\s*=\s*(\{[\s\S]*?\});', html)
        if m:
            try:
                for row in json.loads(m.group(1)).get('la', []):
                    if len(row) > 4 and row[0]:
                        la_map[str(row[0])] = row
            except Exception:
                pass

        lines = []
        for order, block in enumerate(re.split(r'<a[^>]*class="w4-line-item', html)[1:]):
            block = block.split('</a>', 1)[0]
            hm = re.search(r'href="([^"]+)"', block)
            tm = re.search(r'title="([^"]+)"', block)
            if not hm or not tm:
                continue
            href = _html.unescape(hm.group(1))
            mm = re.search(r'/([0-9A-Za-z]+)z(\d+)\.html', href)
            if not mm:
                continue
            line_id = mm.group(1)

            am = re.search(r'alt="([^"]*)"', block)
            alt = _html.unescape(am.group(1)) if am else ''
            cm = re.search(r'共\s*(\d+)\s*集', block)
            rm = re.search(r'(\d{3,4})\s*[pP]', block)

            la = la_map.get(line_id) or []
            count = int(cm.group(1)) if cm else (int(la[2]) if len(la) > 2 else 1)
            first_url = str(la[4]) if len(la) > 4 and la[4] else ''
            version = self._version_tags(alt) or self._version_tags(tm.group(1))

            lines.append({
                'id': line_id,
                'name': _html.unescape(tm.group(1)).strip() or f'线路{len(lines) + 1}',
                'version': version,
                'count': max(1, count),
                'height': int(rm.group(1)) if rm else 0,
                'order': order,
                'first_url': first_url,
            })
        return lines

    # ---------------- 播放页：一次拿到所有线路的第 n 集 ----------------
    def _thread_http(self):
        h = getattr(self._tls, 'http', None)
        if h is None:
            h = HttpClient(referer=self.domain, delay=0.02, timeout=15, retries=1)
            self._tls.http = h
        return h

    @staticmethod
    def _parse_la(html):
        m = re.search(r'var\s+pp\s*=\s*(\{[\s\S]*?\});', html)
        if not m:
            return {}
        try:
            rows = json.loads(m.group(1)).get('la', [])
        except Exception:
            return {}
        return {str(r[0]): r for r in rows if len(r) > 4 and r[0]}

    def _episodes(self, slug, line, z):
        """抓第 z 集的播放页，返回 {线路ID: (集序号, m3u8)}。"""
        url = f'{self.domain}/v/{slug}/{line["id"]}z{z}.html'
        try:
            return self._parse_la(self._thread_http().get(url))
        except Exception:
            return {}

    def _collect(self, slug, picked):
        """并发抓 N 个播放页；每个页面都带着所有线路在该集的真实地址。"""
        max_n = min(max(l['count'] for l in picked), self.max_eps)
        want = {l['id'] for l in picked}
        # 用集数最多的那条线路当页面锚点，避免拿短线路去请求超出它集数的页
        anchor = max(picked, key=lambda l: l['count'])
        pages = [{}] * max_n

        def work(i):
            pages[i] = self._episodes(slug, anchor, i)

        with ThreadPoolExecutor(max_workers=min(self.workers, max_n)) as ex:
            list(ex.map(work, range(max_n)))

        out = {l['id']: [] for l in picked}
        for z, page in enumerate(pages):
            for lid in want:
                row = page.get(lid)
                if not row or not row[4]:
                    continue
                # 短线路在超出集数的页面上会回到第 0 集，必须按集序号过滤
                if int(row[3]) != z:
                    continue
                out[lid].append((z, str(row[4])))
        return out

    def play(self, item):
        html = self.http.get(self.domain + item['detail_link'])
        lines = self._parse_lines(html)
        if not lines:
            # 极少数老页面没有线路卡片，退回旧的通用解析，别让整条片子丢掉
            return extract_play(html)

        is_movie = (item.get('type_name') == '电影'
                    or max(l['count'] for l in lines) <= 2)

        # 先按 HTML 标签排一遍，挑出要探测的候选：TC/抢先版永远最后，
        # 其次分辨率，再看版本标签（HD/正片/国语）和集数。
        lines.sort(key=lambda l: (
            1 if quality_score(l['version']) < 0 else 0,
            -l['height'],
            -quality_score(l['version']),
            -l['count'],
            l['order'],
        ))

        keep = self.max_lines_movie if is_movie else self.max_lines_series
        # 只在排名靠前的候选里读 m3u8，确认分辨率/码率，避免 HTML 的 1080p 标签虚标
        probes = min(len(lines), self.max_probe_lines, keep + 2)
        for line in lines[:probes]:
            if not line['first_url']:
                continue
            info = probe_m3u8(self.http, line['first_url'], deep=False)
            line['real_height'] = info.get('height') or 0
            line['stream'] = stream_quality_score(info)
        for line in lines:
            line.setdefault('real_height', 0)
            line.setdefault('stream', 0)

        lines.sort(key=lambda l: (
            1 if quality_score(l['version']) < 0 else 0,   # TC / 抢先版永远排最后
            -max(l['height'], l['real_height']),            # 其次看分辨率
            -l['stream'],                                   # 再看真实码率
            -quality_score(l['version']),                   # 同分辨率 HD/正片优先
            -l['count'],
            l['order'],
        ))
        picked = lines[:keep]

        slug = item['detail_link'].strip('/').split('/')[-1]
        slug = re.sub(r'\.html$', '', slug)
        eps_map = self._collect(slug, picked)

        groups = []
        for line in picked:
            eps = []
            for z, url in eps_map.get(line['id'], []):
                if line['count'] <= 2:
                    name = '正片' if not eps else f'正片({len(eps) + 1})'
                else:
                    name = f'第{z + 1:02d}集'
                eps.append((name, url))
            cleaned = clean_episodes(eps)
            if not cleaned:
                continue
            name = line['name']
            version = line['version'] or ''
            # 版本标签太长时多半是剧集标题（例如「20260918总决赛…」），不要拼进线路名
            if 0 < len(version) <= 12 and quality_score(version) > 0:
                name = f'{name} {version}'.strip()
            groups.append((name, cleaned))
        return groups
