# -*- coding: utf-8 -*-
"""
ncat21.com / 网飞猫（www.ncat21.com）

站点结构（2026-10 实测）：

  1. 列表页
       /channel/1.html   电影
       /channel/2.html   连续剧
       /channel/3.html   动漫
       /channel/4.html   综艺纪录
       /channel/6.html   短剧
     每页 48 条，服务端渲染。没有可靠的分页参数，按首页条目滚动更新即可。

  2. 详情页 /detail/{id}.html
     页面里同时列出所有线路（source-item）和每条线路的完整选集
     （episode-list，顺序与线路一致）。线路自带清晰度标签，例如
     4K / 超清 / 蓝光 / 高清 / 720P / 标清。

  3. 播放页 /play/{id}-{sid}-{nid}.html
     内联 `const playSource = { src: "https://....m3u8?..." }`。
     播放地址带 timestamp+sign，是抓取时现签的，所以 Action 每 6 小时
     重新生成一次；手机端长期不刷新订阅可能会过期。

  4. 反爬
     首次访问会返回一个 850 字节的 cdndefend JS 校验页：
     对「40 位 seed + 递增数字」做 SHA1，命中指定字节后写入
     cdndefend_js_cookie。这里用 Python 复刻，不执行站点 JS。

  线路选择：按清晰度标签排序，4K/超清/蓝光/高清优先，标清/TC/枪版最后；
  每部片只保留最好的 max_lines 条线路，避免 20 条线路 × 76 集把任务跑爆。
"""

import re
import html as _html
import hashlib
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from .base import (
    HttpClient, make_item, clean_episodes, abs_url, clean_title_suffix as clean_title,
)


class NcatHttp(HttpClient):
    """带 cdndefend 浏览器校验的 HTTP 客户端。"""

    def get(self, url, **kwargs):
        text = super().get(url, **kwargs)
        if 'cdndefend' in text and 'a0_0x' in text:
            if self._solve_challenge(text):
                text = super().get(url, **kwargs)
        return text

    def _solve_challenge(self, text):
        arr_m = re.search(r"const\s+a0_0x[0-9a-f]+\s*=\s*\[(.*?)\];", text, re.S)
        rot_m = re.search(r"\(a0_0x[0-9a-f]+\s*,\s*0x([0-9a-f]+)\)", text)
        if not arr_m or not rot_m:
            return False

        items = re.findall(r"'([^']*)'", arr_m.group(1))
        if not items:
            return False

        # 复刻 JS 里的数组轮转
        shift = int(rot_m.group(1), 16) % len(items)
        items = items[shift:] + items[:shift]

        seed = next((x for x in items if re.fullmatch(r'[0-9A-Fa-f]{40}', x)), '')
        if not seed:
            return False

        # JS: parseInt('0x' + c[0])，即 seed 首位的十六进制值
        try:
            pos = int(seed[0], 16)
        except ValueError:
            return False

        target = re.search(
            r"s\[n1\]===0x([0-9a-fA-F]+)&&s\[n1\+0x1\]===0x([0-9a-fA-F]+)",
            text,
        )
        if not target:
            return False
        b1, b2 = int(target.group(1), 16), int(target.group(2), 16)

        answer = ''
        for i in range(5_000_000):
            digest = hashlib.sha1((seed + str(i)).encode()).digest()
            if digest[pos] == b1 and digest[pos + 1] == b2:
                answer = seed + str(i)
                break
        if not answer:
            return False

        name = next((x for x in items if x.endswith('=') and x != 'array'), '')
        if not name:
            return False
        name = name.rstrip('=')

        host = urllib.parse.urlsplit(self.referer or 'https://www.ncat21.com').hostname or 'www.ncat21.com'
        self.session.cookies.set(name, answer, domain=host, path='/')
        print(f'  [ncat21] 已通过 cdndefend 校验（{i} 次 SHA1）')
        return True


class Ncat21Source:
    key = 'ncat21'
    name = '网飞猫'
    enabled = True

    host = 'https://www.ncat21.com'
    id_base = 80_000_000
    delay = 0.12

    max_lines = 2              # 保留质量最好的两条线路，避免只剩一条 TC/失效线路
    max_probe_lines = 99       # 探测所有线路；不能在前几条失败后就漏掉后面的 4K 线路
    max_eps = 120              # 单条线路最多抓多少集；超长剧只保留最新的一批
    max_details_per_class = 6  # 每轮每个分类最多解析多少条新详情
    workers = 5                # 每集播放页并发数；太高容易被站点限流

    classes = [
        {'type_id': 1, 'type_name': '电影', 'path': '/channel/1.html'},
        {'type_id': 2, 'type_name': '连续剧', 'path': '/channel/2.html'},
        {'type_id': 3, 'type_name': '动漫', 'path': '/channel/3.html'},
        {'type_id': 4, 'type_name': '综艺', 'path': '/channel/4.html'},
        {'type_id': 5, 'type_name': '连续剧', 'path': '/channel/6.html'},
    ]

    seed_urls = []

    def __init__(self):
        self.http = NcatHttp(referer=self.host, delay=self.delay, timeout=12, retries=1)
        self._seen = set()
        self._tls = threading.local()

    # ---------------- 列表 ----------------
    def _list_page(self, path):
        html = self.http.get(self.host + path)

        rows = []
        seen = set()
        for block in re.split(r'<div class="module-item">', html)[1:]:
            link_m = re.search(r'<a[^>]+href="(/detail/\d+\.html)"[^>]*class="v-item"', block)
            if not link_m:
                continue
            detail_link = abs_url(self.host, link_m.group(1))
            if detail_link in seen:
                continue
            seen.add(detail_link)

            title_m = re.search(r'<div class="v-item-title">([^<]+)</div>', block)
            if not title_m:
                continue
            name = _html.unescape(title_m.group(1)).strip()
            if not name:
                continue

            pics = [abs_url(self.host, p) for p in
                    re.findall(r'data-original="([^"]+)"', block)
                    if 'logo_placeholder' not in p]
            pic = pics[-1] if pics else ''

            remark_m = re.search(r'<div class="v-item-bottom">\s*<span>\s*([^<]*?)\s*</span>', block)
            remarks = _html.unescape(remark_m.group(1)).strip() if remark_m else ''

            rows.append({
                'detail_link': detail_link,
                'vod_name': name,
                'vod_pic': pic,
                'vod_remarks': remarks,
            })

        # 页面里可能同时有「最新上线」「热播榜」等区块，按链接去重
        return rows

    # ---------------- 详情 ----------------
    def _detail(self, detail_url):
        html = self.http.get(detail_url)

        # 片名：detail-title 里第二个 strong 才是可见的
        name = ''
        title_block = re.search(r'<div class="detail-title">([\s\S]*?)</div>', html)
        if title_block:
            strongs = [
                _html.unescape(re.sub(r'<[^>]+>', '', x)).strip()
                for x in re.findall(r'<strong[^>]*>([\s\S]*?)</strong>', title_block.group(1))
            ]
            strongs = [x for x in strongs if x]
            if strongs:
                name = strongs[1] if len(strongs) > 1 else strongs[0]
        if not name:
            tm = re.search(r'<title>([^<]+)</title>', html)
            if tm:
                name = re.split(r'[-_|]', _html.unescape(tm.group(1)))[0].strip()
        name = clean_title(name) or name

        pic = ''
        pic_block = re.search(r'<div class="detail-pic">([\s\S]*?)</div>', html)
        if pic_block:
            for p in re.findall(r'data-original="([^"]+)"', pic_block.group(1)):
                if 'logo_placeholder' not in p:
                    pic = abs_url(self.host, p)
                    break

        remarks = ''
        rm = re.search(
            r'<div class="detail-info-row-side">备注:</div>\s*'
            r'<div class="detail-info-row-main">([\s\S]*?)</div>',
            html,
        )
        if rm:
            remarks = _html.unescape(re.sub(r'<[^>]+>', '', rm.group(1))).strip()
        remarks = clean_title(remarks)

        # 线路：detail-play-box 里的 source-item，按页面顺序
        sources = []
        play_box = html.find('detail-play-box')
        src_block = html[play_box:] if play_box >= 0 else html
        for m in re.finditer(
            r'<a href="#" class="source-item[^"]*">\s*'
            r'<span class="source-item-label">([^<]*)</span>\s*'
            r'<span class="source-item-sublabel">([^<]*)</span>\s*'
            r'<i class="source-item-num">(\d+)</i>',
            src_block,
        ):
            label = _html.unescape(m.group(1)).strip()
            sublabel = _html.unescape(m.group(2)).strip()
            num = int(m.group(3))
            sources.append((label, sublabel, num))

        # 选集：每条线路一个 episode-list，顺序与 source-item 一致
        lists = re.findall(
            r'<div class="episode-list"[^>]*>([\s\S]*?)</div>',
            src_block,
        )

        detail_id = ''
        id_m = re.search(r'/detail/(\d+)\.html', detail_url)
        if id_m:
            detail_id = id_m.group(1)

        lines = []
        for idx, (label, sublabel, num) in enumerate(sources):
            if idx >= len(lists):
                break
            eps = []
            seen = set()
            for href, ep_name in re.findall(
                    r'<a[^>]+href="(/play/[^"]+)"[^>]*>\s*<span>([^<]*)</span>',
                    lists[idx]):
                if detail_id and f'/play/{detail_id}-' not in href:
                    continue
                href = abs_url(self.host, _html.unescape(href))
                if href in seen:
                    continue
                seen.add(href)
                ep_name = _html.unescape(ep_name).strip()
                if not ep_name:
                    ep_name = f'第{len(eps) + 1}集'
                eps.append((ep_name, href))
            if eps:
                lines.append((label, sublabel, num, eps))

        return name, pic, remarks, lines

    # ---------------- 播放页 ----------------
    @staticmethod
    def _parse_play_source(html):
        m = re.search(
            r'playSource\s*=\s*\{\s*src\s*:\s*["\']([^"\']+)["\']',
            html,
        )
        if not m:
            return ''
        url = m.group(1).replace('\\/', '/').replace('\\u0026', '&').strip()
        return url if url.startswith('http') else ''

    def _m3u8(self, play_url):
        try:
            html = self.http.get(play_url)
        except Exception as e:
            print(f'  [ncat21] 播放页失败 {play_url}: {e}')
            return ''
        return self._parse_play_source(html)

    def _thread_http(self):
        """每个线程一个 session，并复用主 session 的 cdndefend cookie。"""
        h = getattr(self._tls, 'http', None)
        if h is None:
            h = NcatHttp(referer=self.host, delay=0.02, timeout=12, retries=1)
            h.session.cookies.update(self.http.session.cookies)
            self._tls.http = h
        return h

    def _m3u8_many(self, play_urls):
        """并发抓多集播放页；一次拿一整条线路，比逐集串行快 5 倍以上。"""
        if not play_urls:
            return []
        results = [''] * len(play_urls)

        def work(i, url):
            try:
                results[i] = self._parse_play_source(self._thread_http().get(url))
            except Exception:
                pass

        workers = min(self.workers, len(play_urls))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(lambda pair: work(*pair), enumerate(play_urls)))

        # 并发被站点限流时（部分成功、部分失败），失败的再串行补一次
        failed = [i for i, u in enumerate(results) if not u]
        if failed and len(failed) < len(play_urls):
            for i in failed:
                try:
                    results[i] = self._parse_play_source(self.http.get(play_urls[i]))
                except Exception:
                    pass
        return results

    # ---------------- 线路质量 ----------------
    @staticmethod
    def _line_score(label, sublabel):
        text = f'{label} {sublabel}'.upper()
        score = 0
        if '4K' in text or '超清' in text:
            score += 60
        elif '蓝光' in text or '高清' in text or '1080' in text:
            score += 50
        elif '720' in text or re.search(r'\bHD\b', text):
            score += 30
        if '标清' in text or '流畅' in text or 'TC' in text or '枪版' in text or '抢先版' in text:
            score -= 60
        if '秒播' in text or '加速' in text or '播放快' in text:
            score += 5
        if '4K' in label.upper():
            score += 1
        return score

    # ---------------- 一部片 ----------------
    def _item(self, detail_url, fallback_name='', fallback_pic='', fallback_remarks='',
              type_name='电影'):
        name, pic, remarks, lines = self._detail(detail_url)
        raw_name = name or fallback_name
        name = clean_title(raw_name) or raw_name
        pic = pic or fallback_pic
        remarks = remarks or fallback_remarks
        if not name or not lines:
            print(f'  [ncat21] 详情页没解析到线路: {detail_url}')
            return None

        ordered = sorted(
            enumerate(lines),
            key=lambda x: (
                -self._line_score(x[1][0], x[1][1]),
                -x[1][2],
                x[0],
            ),
        )

        picked = []
        probed = 0
        max_line_eps = max((len(eps) for _, _, _, eps in lines), default=0)
        if max_line_eps <= 2:
            keep = 3
        elif max_line_eps <= 40:
            keep = self.max_lines
        else:
            keep = 1
        for _, (label, sublabel, num, eps) in ordered:
            if probed >= self.max_probe_lines:
                break
            probed += 1
            # 超长剧只保留最新的 max_eps 集，先对切片再探测第一集
            want = eps[-self.max_eps:]
            first_m3u8 = self._m3u8(want[0][1])
            if not first_m3u8:
                continue
            picked.append((label, sublabel, want, first_m3u8))
            if len(picked) >= keep:
                break

        # 并发抓每集播放页：线路 1 的第一集已经探测过，不再重复请求
        jobs = []
        per_line = []
        for li, (label, sublabel, eps, first_m3u8) in enumerate(picked):
            per_line.append([(eps[0][0], first_m3u8)])
            for idx, (ep_name, play_url) in enumerate(eps):
                if idx > 0:
                    jobs.append((li, idx, ep_name, play_url))

        found = self._m3u8_many([j[3] for j in jobs])
        for (li, idx, ep_name, _), m3u8 in zip(jobs, found):
            if m3u8:
                per_line[li].append((ep_name, m3u8))

        groups = []
        for li, (label, sublabel, eps, first_m3u8) in enumerate(picked):
            cleaned = clean_episodes(per_line[li])
            if cleaned:
                groups.append((label, cleaned))

        if not groups:
            print(f'  [ncat21] 没拿到可用播放地址: {name}')
            return None

        print(f'  [ncat21] ✓ {name} | {groups[0][0]} | {len(groups[0][1])} 集')
        return make_item(
            vod_id=0,
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
        per_class = min(self.max_details_per_class, max_details) if max_details else self.max_details_per_class

        for c in self.classes:
            try:
                rows = self._list_page(c['path'])
            except Exception as e:
                print(f'  [ncat21] 列表失败 {c["path"]}: {e}')
                continue
            if not rows:
                print(f'  [ncat21] {c["type_name"]} 列表为空: {c["path"]}')
                continue
            print(f'  [ncat21] {c["type_name"]} 列表 {len(rows)} 条')

            done = 0
            for r in rows:
                if done >= per_class:
                    break
                detail_url = r['detail_link']
                if detail_url in self._seen:
                    continue
                if skip and skip(r['vod_name'], r.get('vod_remarks', '')):
                    continue
                self._seen.add(detail_url)
                done += 1

                item = self._item(
                    detail_url,
                    fallback_name=r['vod_name'],
                    fallback_pic=r.get('vod_pic', ''),
                    fallback_remarks=r.get('vod_remarks', ''),
                    type_name=c['type_name'],
                )
                if item:
                    item['vod_id'] = self.id_base + seq
                    items.append(item)
                    seq += 1

        return items

    # ---------------- 调试 ----------------
    def probe(self):
        rows = self._list_page('/channel/1.html')
        print(f'列表解析到 {len(rows)} 条')
        for r in rows[:3]:
            print('  ', r)
        if rows:
            print(f'\n详情页: {rows[0]["detail_link"]}')
            name, pic, remarks, lines = self._detail(rows[0]['detail_link'])
            print(f'片名: {name} | 备注: {remarks} | 封面: {pic[:80]}')
            for label, sublabel, num, eps in lines[:5]:
                print(f'  {label} / {sublabel} / {num} 集: {eps[0][1]}')
            if lines:
                print('第一集 m3u8:', self._m3u8(lines[0][3][0][1]))
