# -*- coding: utf-8 -*-
"""
fdzys.com / 饭搭子影视

取数链路（2026-10 实测）：

  1. 列表页（服务端渲染，翻页用 ?page=N）：
       /movie/all?page=N      电影
       /tv/all?page=N         连续剧
       /zongyi/all?page=N     综艺
       /dongman/all?page=N    动漫
     每张卡片是 div.myui-vodbox-content，里面有详情链接、片名、封面、备注。

  2. 详情页 /tv/{slug} 或 /movie/{slug}
     页面里的 div#playlist{sid} 已经列出「每条线路 × 每一集」的播放页链接，
     线路名在 data-name-for 属性旁边（天堂云 / 无印云 / 优质云……）。

  3. 播放页 /tv/{slug}/{nid}?sid={sid}
     内联 player_aaaa 里有 url，分三种：
       - 直接是 .m3u8                → 直接用（大部分云线路）
       - 是 /share/{hash} 分享页     → 再抓一次分享页，取 var main / const url 里的 m3u8
       - 优酷/爱奇艺等网页地址        → 跳过（TVBox 播不了网页）

  所以一个片子的请求数 = 1 详情 + 探测几条线路 + 每集 1 次播放页（分享页线路每集 2 次）。
  为了控制耗时，默认只保留 max_lines 条线路、最多 max_eps 集，并优先选直接 m3u8 的线路。
"""

import re
import json
import html as _html
import urllib.parse

from .base import HttpClient, make_item, clean_episodes, abs_url


class FdzysSource:
    key = 'fdzys'
    name = '饭搭子影视'
    enabled = True

    host = 'https://fdzys.com'
    id_base = 60_000_000
    delay = 0.15

    max_lines = 1          # 每部片保留几条线路（多一条线路，请求数差不多翻倍）
    max_eps = 40           # 单条线路最多抓多少集，防止几百集的短剧吃光时间
    max_probe_lines = 5    # 最多探测几条线路，找到够用的直接 m3u8 线路就停

    classes = [
        {'type_id': 1, 'type_name': '电影', 'path': 'movie/all'},
        {'type_id': 2, 'type_name': '连续剧', 'path': 'tv/all'},
        {'type_id': 3, 'type_name': '综艺', 'path': 'zongyi/all'},
        {'type_id': 4, 'type_name': '动漫', 'path': 'dongman/all'},
    ]

    # 指定片单：列表页翻不到（或排序靠后）时，也保证这些片子始终在源里。
    # 你点名要的嫁金钗就在这里，每次跑都会重新检查剧集有没有更新。
    seed_urls = [
        'https://fdzys.com/tv/jia-jin-cha/1',
    ]

    def __init__(self):
        self.http = HttpClient(referer=self.host, delay=self.delay)
        self._player_cache = {}
        self._seen = set()

    # ---------------- 列表 ----------------
    def _list_page(self, path, page):
        url = f'{self.host}/{path}'
        if page > 1:
            url += f'?page={page}'
        html = self.http.get(url)

        rows = []
        for block in re.split(r'<div class="myui-vodbox-content">', html)[1:]:
            link_m = re.search(
                r'<a[^>]+href="(https://fdzys\.com/(?:tv|movie|zongyi|dongman|duanju)/[^"?#]+)"',
                block,
            )
            if not link_m:
                continue
            detail_link = link_m.group(1)

            title_m = re.search(r'<div class="title">([^<]+)</div>', block)
            if not title_m:
                continue
            name = _html.unescape(title_m.group(1)).strip()
            if not name:
                continue

            pic_m = re.search(r'<img[^>]+data-src="([^"]+)"', block)
            tag_m = re.search(r'<div class="tag text-overflow">([^<]*)</div>', block)

            rows.append({
                'detail_link': detail_link,
                'vod_name': name,
                'vod_pic': abs_url(self.host, pic_m.group(1)) if pic_m else '',
                'vod_remarks': _html.unescape((tag_m.group(1) if tag_m else '')).strip(),
            })
        return rows

    # ---------------- 详情页 ----------------
    def _detail(self, detail_url):
        """
        返回 (片名, 封面, 备注, {sid: (线路名, [(集名, 播放页地址), ...])})。
        """
        html = self.http.get(detail_url)

        name = ''
        title_m = (re.search(r'<h1 class="title_name"[^>]*>([\s\S]*?)</h1>', html)
                   or re.search(r'<h1 class="title"[^>]*>([\s\S]*?)</h1>', html))
        if title_m:
            name = re.sub(r'<[^>]+>', '', title_m.group(1))
            name = re.sub(r'\s*第\s*\d+\s*集.*$', '', name)
            name = _html.unescape(name).strip()
        if not name:
            og = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html)
            if og:
                name = _html.unescape(og.group(1)).strip()

        pic = ''
        pic_m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html)
        if pic_m:
            pic = pic_m.group(1)

        remarks = ''
        box_start = html.find('class="detail-box"')
        if box_start >= 0:
            box_end = html.find('class="vod-content"', box_start)
            box = html[box_start: box_end if box_end > box_start else box_start + 1500]
            rm = re.search(r'(更新至[^<|\s]{1,10}|全\d+集|已完结)', box)
            if rm:
                remarks = rm.group(1)

        # 线路名：老模板 data-name-for="1">天堂云</span>
        #         新模板 <li class="player_name" data-sid="1"><a ...>天堂云<span ...
        names = {}
        for sid, line_name in re.findall(
                r'data-name-for="(\d+)"[^>]*>\s*([^<]+?)\s*</span>', html):
            names[sid] = _html.unescape(line_name).strip()
        for m in re.finditer(r'<li[^>]*data-sid="(\d+)"[^>]*>([\s\S]*?)</li>', html):
            sid, body = m.group(1), m.group(2)
            if sid in names:
                continue
            nm = (re.search(r'class="swiper-slide-text"[^>]*>\s*([^<]+?)\s*<', body)
                  or re.search(r'<span>([^<]+)</span>', body))
            if nm:
                names[sid] = _html.unescape(nm.group(1)).strip()

        # 每条线路的剧集：按 id="playlistXX" 切片，避免串到别的线路
        lines = {}
        starts = list(re.finditer(r'id="playlist\d+"[^>]*data-sid="(\d+)"[^>]*>', html))
        for idx, m in enumerate(starts):
            sid = m.group(1)
            start = m.end()
            end = starts[idx + 1].start() if idx + 1 < len(starts) else min(len(html), start + 80000)
            body = html[start:end]

            eps = []
            seen_urls = set()
            for href, ep_name in re.findall(
                    r'<a[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>', body):
                href = abs_url(self.host, _html.unescape(href.strip()))
                if not href.startswith('http') or href in seen_urls:
                    continue
                seen_urls.add(href)
                ep_name = re.sub(r'<[^>]+>', '', ep_name)
                ep_name = _html.unescape(ep_name).strip().strip('\t')
                if not ep_name:
                    ep_name = f'第{len(eps) + 1}集'
                elif ep_name.isdigit():
                    ep_name = f'第{int(ep_name):02d}集'
                eps.append((ep_name, href))

            if eps and sid not in lines:
                lines[sid] = (names.get(sid, f'线路{sid}'), eps)

        return name, pic, remarks, lines

    # ---------------- 播放页 / 分享页 ----------------
    def _player(self, play_url):
        if play_url in self._player_cache:
            return self._player_cache[play_url]

        cfg = {}
        try:
            html = self.http.get(play_url)
            m = re.search(r'player_aaaa\s*=\s*(\{[\s\S]*?\})\s*</script>', html)
            if m:
                cfg = json.loads(m.group(1))
        except Exception as e:
            print(f'  [{self.key}] 播放页失败 {play_url}: {e}')
        self._player_cache[play_url] = cfg
        return cfg

    def _share_m3u8(self, share_url):
        """分享页里 var main / const url 才是真正的 m3u8。"""
        try:
            html = self.http.get(share_url)
        except Exception as e:
            print(f'  [{self.key}] 分享页失败 {share_url}: {e}')
            return ''

        m = re.search(
            r'(?:const|let|var)\s+(?:url|main)\s*=\s*["\']([^"\']+?\.m3u8[^"\']*)["\']',
            html,
        )
        if not m:
            m = re.search(r'["\']([^"\']+?\.m3u8[^"\']*)["\']', html)
        if not m:
            return ''

        path = m.group(1).replace('\\/', '/').replace('\\u0026', '&')
        return urllib.parse.urljoin(share_url, path)

    def _episode_m3u8(self, play_url):
        raw = str(self._player(play_url).get('url') or '')
        if not raw:
            return ''
        if '.m3u8' in raw:
            return raw
        if '/share/' in raw:
            return self._share_m3u8(raw)
        return ''

    def _probe_line(self, eps):
        """返回 (类型, 第一集 m3u8)，类型是 direct / share；不可用返回 (None, '')。"""
        if not eps:
            return None, ''
        raw = str(self._player(eps[0][1]).get('url') or '')
        if '.m3u8' in raw:
            return 'direct', raw
        if '/share/' in raw:
            m3u8 = self._share_m3u8(raw)
            return ('share', m3u8) if m3u8 else (None, '')
        return None, ''

    # ---------------- 一部片 ----------------
    def _item(self, detail_url, fallback_name='', fallback_pic='', fallback_remarks='',
              type_name='连续剧'):
        name, pic, remarks, lines = self._detail(detail_url)
        name = name or fallback_name
        pic = pic or fallback_pic
        remarks = remarks or fallback_remarks
        if not name or not lines:
            print(f'  [{self.key}] 详情页没解析到线路: {detail_url}')
            return None

        direct, share = [], []
        probed = 0
        for sid, (line_name, eps) in lines.items():
            if probed >= self.max_probe_lines:
                break
            kind, first_m3u8 = self._probe_line(eps)
            probed += 1
            if kind == 'direct':
                direct.append((line_name, eps, first_m3u8))
            elif kind == 'share':
                share.append((line_name, eps, first_m3u8))
            if len(direct) >= self.max_lines:
                break

        picked = direct[:self.max_lines]
        if len(picked) < self.max_lines:
            picked += share[:self.max_lines - len(picked)]

        groups = []
        for line_name, eps, first_m3u8 in picked:
            out = []
            for idx, (ep_name, play_url) in enumerate(eps[:self.max_eps]):
                m3u8 = first_m3u8 if idx == 0 else self._episode_m3u8(play_url)
                if m3u8:
                    out.append((ep_name, m3u8))
            cleaned = clean_episodes(out)
            if cleaned:
                groups.append((line_name, cleaned))

        if not groups:
            print(f'  [{self.key}] 没拿到可用播放地址: {name}')
            return None

        print(f'  [{self.key}] ✓ {name} | {groups[0][0]} | {len(groups[0][1])} 集')
        return make_item(
            vod_id=0,               # crawler_v2 会统一重编号
            name=name,
            type_id=0,
            type_name=type_name,
            pic=pic,
            remarks=remarks,
            groups=groups,
            source=self.key,
        )

    # ---------------- 主流程 ----------------
    def crawl(self, pages=2, max_details=60, skip=None):
        items = []
        seq = 0

        def add(item):
            nonlocal seq
            if not item:
                return
            item['vod_id'] = self.id_base + seq
            items.append(item)
            seq += 1

        # 1) 指定片单：不受 skip 影响，保证点了名的片子一定重新检查
        for seed in self.seed_urls:
            base = re.sub(r'/\d+(?:\?.*)?$', '', seed)
            if base in self._seen:
                continue
            self._seen.add(base)
            type_name = '连续剧' if '/tv/' in base else ('电影' if '/movie/' in base else '其他')
            add(self._item(seed, type_name=type_name))

        # 2) 各分类列表
        for c in self.classes:
            done_cls = 0
            for page in range(1, pages + 1):
                if max_details and done_cls >= max_details:
                    break
                try:
                    rows = self._list_page(c['path'], page)
                except Exception as e:
                    print(f'  [{self.key}] 列表失败 {c["path"]} p{page}: {e}')
                    break
                if not rows:
                    break
                print(f'  [{self.key}] {c["type_name"]} p{page} 列表 {len(rows)} 条')

                for r in rows:
                    if max_details and done_cls >= max_details:
                        break
                    detail_url = r['detail_link']
                    if detail_url in self._seen:
                        continue
                    if skip and skip(r['vod_name'], r.get('vod_remarks', '')):
                        continue
                    self._seen.add(detail_url)
                    done_cls += 1

                    add(self._item(
                        detail_url,
                        fallback_name=r['vod_name'],
                        fallback_pic=r.get('vod_pic', ''),
                        fallback_remarks=r.get('vod_remarks', ''),
                        type_name=c['type_name'],
                    ))

        return items

    # ---------------- 调试 ----------------
    def probe(self):
        url = f'{self.host}/tv/all'
        print(f'列表页: {url}')
        rows = self._list_page('tv/all', 1)
        print(f'解析到 {len(rows)} 条')
        for r in rows[:3]:
            print('  ', r)

        seed = self.seed_urls[0]
        print(f'\n详情页: {seed}')
        name, pic, remarks, lines = self._detail(seed)
        print(f'片名: {name} | 备注: {remarks} | 封面: {pic[:80]}')
        for sid, (line_name, eps) in lines.items():
            print(f'  sid={sid} {line_name}: {len(eps)} 集，第一集 {eps[0][1]}')
