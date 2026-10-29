# -*- coding: utf-8 -*-
"""
4kvm.tv / 4K影视（https://www.4kvm.tv）

取数链路（2026-10 实测）：

  1. 列表页（服务端渲染，没有可用的翻页参数，每类只有首页）：
       /tv       连续剧
       /movie    电影
       /anime    动漫
     卡片是 div.movie-card[data-vod-id="{slug}"]，里面有：
       <a href="/play/{slug}">、<img alt="片名" data-src="封面">、
       备注 <span>更新至19集 / 全12集 / 已完结</span>
     同一张卡在页面里可能出现两次（hover 层），按 data-vod-id 去重。

  2. 详情页 /play/{slug}
     页面里直接列出剧集：
       <a href="/play/{secret}" data-line="1" data-episode="19" dataid="41409">
     备注在页面里是「更新至19/30集」，userlink 在导航栏的 x-data 里。

  3. 播放地址不是明文 m3u8，需要站点自己的 WASM 签名：
       build_play_url(dataid, secret, quality, userlink)
         -> /video/play?p=...&v=...&q=1080&s=...&t=...&k=...
     请求这个地址才返回 quality_urls，取其中 locked=false 且是 http 的地址。
     签名交给 sources/kvm_sign.mjs（官方 WASM）批量生成，避免每集
     启动一次进程。脚本 Deno / Node 18+ 都能跑：优先 Deno，没装就用 Node。

     拿到的 m3u8 直接写进 JSON。不要改成「播放时再签名」：Cloudflare Worker
     里 new WebAssembly.Module() 会被平台拒绝（Wasm codegen disallowed），
     动态签名那条路在 Worker 上根本跑不通。

  为什么单独做这个源：
    其它源更新慢半拍时（例如嫁金钗网页已经 19 集、别的源只有 18 集），
    这里能直接拿到网页当前集数，合并后会排在最前面。

  速度控制：
    - 每类只抓首页，详情数量由 classes[].limit 限制；
    - 单条线路最多 max_eps 集（超过时取最新的一批）；
    - 一次签名进程签完整条线路，再按 1.5 秒一集串行请求播放接口
      （接口限流很严，并发会直接 429）。
"""

import html as _html
import json
import os
import re
import shutil
import subprocess
import threading
import time

import requests
from .base import HttpClient, make_item, clean_episodes

HERE = os.path.dirname(os.path.abspath(__file__))
SIGN_JS = os.path.join(HERE, 'kvm_sign.mjs')

UA = ('Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
      'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 '
      'Mobile/15E148 Safari/604.1')


class KvmSource:
    key = 'kvm'
    name = '4K影视'
    enabled = True

    hosts = [
        'https://www.4kvm.tv',
        'https://www.4kvm.net',
        'https://www.4kvm.org',
    ]
    host = hosts[0]
    id_base = 70_000_000
    delay = 0.12

    max_lines = 1          # 每部片保留几条线路
    max_eps = 40           # 单条线路最多抓多少集
    # 播放接口有很严的限流：短时间内连续请求会返回 429「请求过于频繁」。
    # 实测 1.5 秒一个请求稳定，慢一点没关系，Action 有的是时间。
    api_interval = 1.5

    classes = [
        {'type_id': 1, 'type_name': '连续剧', 'path': 'tv', 'limit': 12},
        {'type_id': 2, 'type_name': '电影', 'path': 'movie', 'limit': 10},
        {'type_id': 4, 'type_name': '动漫', 'path': 'anime', 'limit': 8},
    ]

    # 点名要保证更新的片子：不受 skip 影响，每次跑都重新检查集数。
    # 只存路径，运行时会拼上本次探测到的可用域名。
    seed_urls = [
        {'path': '/play/ch4phdr82', 'type_name': '连续剧'},  # 嫁金钗
    ]

    CARD_RE = re.compile(
        r'<div class="[^"]*movie-card[^"]*"[^>]*data-vod-id="([^"]+)"'
    )

    def __init__(self):
        self.http = HttpClient(referer=self.host, delay=self.delay)
        self._local = threading.local()
        self._seen = set()
        self._signer_ok = None      # None=还没试过, False=deno/node 都不可用
        self._signer_cmd = None     # 已经确认能跑的签名命令
        self._api_lock = threading.Lock()
        self._last_api = 0.0
        self._interval = self.api_interval
        self._fail_logged = 0
        self._no_sign_logged = False  # 「没有签名运行时」只提示一次
        self._abort = False         # 连续 429 时本次直接放弃，保留旧数据

    # ---------------- HTTP ----------------
    def _session(self):
        """播放接口用的 Session（保留独立的 cookie/连接池）。"""
        s = getattr(self._local, 'session', None)
        if s is None:
            s = requests.Session()
            s.trust_env = False
            s.headers.update({
                'User-Agent': UA,
                'Accept': 'application/json,text/plain,*/*',
                'Accept-Language': 'zh-CN,zh;q=0.9',
                'Referer': self.host + '/',
            })
            self._local.session = s
        return s

    # ---------------- 列表 ----------------
    def _list_page(self, path):
        html = self.http.get(f'{self.host}/{path}')
        if 'movie-card' not in html:
            title = re.search(r'<title>(.*?)</title>', html)
            raise RuntimeError(
                f'列表页没有影片卡片（{title.group(1) if title else "空页面"}）'
                f'，站点可能维护/反爬')

        matches = list(self.CARD_RE.finditer(html))
        rows, seen = [], set()
        for idx, m in enumerate(matches):
            slug = m.group(1)
            if slug in seen:
                continue
            seen.add(slug)

            end = matches[idx + 1].start() if idx + 1 < len(matches) else min(
                len(html), m.start() + 4000)
            block = html[m.start():end]

            href_m = re.search(r'<a[^>]+href="(/play/[^"#?]+)"', block)
            if not href_m:
                continue

            name_m = (re.search(r'<img[^>]+alt="([^"]+)"', block)
                      or re.search(r'<h3[^>]*>\s*([^<\n]+?)\s*</h3>', block))
            if not name_m:
                continue
            name = _html.unescape(name_m.group(1)).strip()
            if not name:
                continue

            pic_m = re.search(r'<img[^>]+data-src="([^"]+)"', block)
            remark_m = re.search(
                r'<span[^>]*>\s*(更新至[^<]*?|全\s*\d+\s*集|已完结|HD[^<]*?)\s*</span>',
                block,
            )

            rows.append({
                'detail_link': self.host + href_m.group(1),
                'vod_name': name,
                'vod_pic': _html.unescape(pic_m.group(1)) if pic_m else '',
                'vod_remarks': _html.unescape(
                    remark_m.group(1) if remark_m else '').strip(),
            })
        return rows

    # ---------------- 详情页 ----------------
    @staticmethod
    def _norm_remarks(text):
        """把「更新至19/30集」统一成「更新至19集」，和列表卡片保持一致。"""
        if not text:
            return ''
        m = re.search(r'更新至\s*(\d+)', text)
        if m:
            return f'更新至{int(m.group(1))}集'
        m = re.search(r'全\s*(\d+)\s*集', text)
        if m:
            return f'全{int(m.group(1))}集'
        if '已完结' in text or '完结' in text:
            return '已完结'
        return text.strip()

    def _detail(self, detail_url):
        """
        返回 (片名, 封面, 备注, userlink, {line: [ {name, dataid, secret}, ... ]})
        """
        html = self.http.get(detail_url)

        name = ''
        h1 = re.search(r'<h1[^>]*>([\s\S]*?)</h1>', html)
        if h1:
            name = _html.unescape(re.sub(r'<[^>]+>', '', h1.group(1))).strip()
        if not name:
            og = re.search(
                r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html)
            if og:
                name = _html.unescape(og.group(1))
                name = re.sub(r'\s*-\s*第\s*\d+\s*集.*$', '', name).strip()
        if not name:
            t = re.search(r'<title>(.*?)</title>', html)
            if t:
                name = re.sub(r'\s*-\s*第\s*\d+\s*集.*$', '',
                              _html.unescape(t.group(1))).replace('-4k影视', '').strip()

        pic = ''
        pic_m = (re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html)
                 or re.search(r'data-poster="([^"]+)"', html))
        if pic_m:
            pic = _html.unescape(pic_m.group(1))

        remark = ''
        remark_m = re.search(r'(更新至[^<"\s]{1,12}|全\s*\d+\s*集|已完结)', html)
        if remark_m:
            remark = self._norm_remarks(remark_m.group(1))

        userlink = ''
        ul_m = (re.search(r"userlink\s*:\s*'([^']+)'", html)
                or re.search(r'userlink\s*:\s*"([^"]+)"', html)
                or re.search(r"window\.myuserlink\s*=\s*['\"]([^'\"]+)['\"]", html))
        if ul_m:
            userlink = ul_m.group(1)

        lines = {}
        seen = set()
        for tag in re.findall(r'<a\b[^>]*>', html):
            if 'dataid=' not in tag:
                continue
            attrs = dict(re.findall(r'([a-zA-Z][\w-]*)="([^"]*)"', tag))
            dataid = attrs.get('dataid', '').strip()
            href = attrs.get('href', '')
            secret = href.rstrip('/').split('/')[-1]
            if not dataid or not secret:
                continue
            line = attrs.get('data-line', '1').strip() or '1'
            ep_no = attrs.get('data-episode', '').strip()
            key = (line, ep_no or dataid)
            if key in seen:
                continue
            seen.add(key)
            lines.setdefault(line, []).append({
                'name': f'第{int(ep_no)}集' if ep_no.isdigit() else '正片',
                'dataid': dataid,
                'secret': secret,
            })

        # 单集（电影）显示「正片」更自然
        for eps in lines.values():
            if len(eps) == 1:
                eps[0]['name'] = '正片'
            else:
                eps.sort(key=lambda e: int(re.sub(r'\D', '', e['name']) or 0))

        return name, pic, remark, userlink, lines

    # ---------------- WASM 签名 ----------------
    @staticmethod
    def _signer_candidates():
        """
        能跑 kvm_sign.mjs 的运行时，按优先级排列：deno -> node。
        Actions 上装 denoland/setup-deno 就有 deno；本地/其它环境有 node 也行。
        """
        deno = shutil.which('deno')
        if not deno:
            for c in ('/usr/local/bin/deno', '/opt/homebrew/bin/deno',
                      os.path.expanduser('~/.deno/bin/deno')):
                if os.path.exists(c):
                    deno = c
                    break
        node = shutil.which('node')
        if not node:
            for c in ('/usr/local/bin/node', '/opt/homebrew/bin/node'):
                if os.path.exists(c):
                    node = c
                    break

        cmds = []
        if deno:
            cmds.append([deno, 'run', '--allow-read', SIGN_JS])
        if node:
            cmds.append([node, SIGN_JS])
        return cmds

    def _sign_batch(self, eps, userlink):
        """
        一次进程签完整条线路。返回和 eps 等长的列表，失败的位置是 ''。
        """
        if not eps:
            return []
        if self._signer_ok is False:
            return [''] * len(eps)

        payload = json.dumps({
            'userlink': userlink or '0',
            'quality': '1080',
            'items': [{'dataid': e['dataid'], 'secret': e['secret']} for e in eps],
        }, ensure_ascii=False)

        # 已经确认能跑的命令直接用，省掉重复探测
        cmds = ([self._signer_cmd] if self._signer_cmd
                else self._signer_candidates())
        if not cmds:
            self._signer_ok = False
            print(f'  [{self.key}] 没找到 deno/node，跳过播放地址校验'
                  f'（Actions 里需要 denoland/setup-deno，或自带的 node）')
            return [''] * len(eps)

        proc = None
        for cmd in cmds:
            try:
                proc = subprocess.run(
                    cmd, input=payload, capture_output=True, text=True,
                    timeout=180,
                )
            except FileNotFoundError:
                continue
            except Exception as e:
                print(f'  [{self.key}] 签名进程失败: {e}')
                return [''] * len(eps)

            if proc.returncode == 0:
                self._signer_cmd = cmd
                break
            print(f'  [{self.key}] 签名失败（{os.path.basename(cmd[0])}）: '
                  f'{(proc.stderr or "").strip()[:300]}')
            proc = None

        if proc is None:
            self._signer_ok = False
            return [''] * len(eps)

        out = []
        for line in (proc.stdout or '').splitlines():
            line = line.strip()
            if line.startswith('['):
                try:
                    out = json.loads(line)
                except Exception:
                    out = []
        if len(out) != len(eps):
            print(f'  [{self.key}] 签名返回数量不对: {len(out)}/{len(eps)}')
            return [''] * len(eps)

        self._signer_ok = True
        return [x.get('url', '') if x.get('ok') else '' for x in out]

    # ---------------- 播放接口 ----------------
    def _wait_slot(self):
        """全局节流：所有播放接口请求共用同一个最小间隔。"""
        with self._api_lock:
            wait = self._interval - (time.monotonic() - self._last_api)
            if wait > 0:
                time.sleep(wait)
            self._last_api = time.monotonic()

    @staticmethod
    def _pick_m3u8(data):
        if not isinstance(data, dict):
            return ''
        if data.get('code') not in (200, 1) or not data.get('data'):
            return ''
        cands = []
        for q in (data['data'].get('quality_urls') or []):
            u = str(q.get('url') or '')
            if not u.startswith('http'):
                continue
            if q.get('locked') or q.get('isvip'):
                continue
            cands.append((int(q.get('bitrate') or 0), u))
        if not cands:
            return ''
        return max(cands, key=lambda x: x[0])[1]

    def _resolve(self, signed_url, referer):
        """把签名地址换成真正的 m3u8。遇到 429 自动放慢并等待窗口重置。"""
        if not signed_url or self._abort:
            return ''
        url = self.host + signed_url if signed_url.startswith('/') else signed_url

        got_429 = False
        for attempt in range(3):
            self._wait_slot()
            try:
                r = self._session().get(url, headers={'Referer': referer}, timeout=20)
            except Exception:
                time.sleep(2 + attempt * 2)
                continue

            if r.status_code == 200:
                try:
                    data = r.json()
                except Exception:
                    return ''
                m3u8 = self._pick_m3u8(data)
                if not m3u8 and self._fail_logged < 3:
                    self._fail_logged += 1
                    print(f'  [{self.key}] 接口没有可用线路: '
                          f'{str(data)[:100]}')
                return m3u8
            if r.status_code == 429:
                got_429 = True
                # 触发限流：把间隔再拉长，并等限流窗口过去
                with self._api_lock:
                    self._interval = min(self._interval * 1.5, 8.0)
                wait = 60
                print(f'  [{self.key}] 播放接口限流，等 {wait}s 后重试'
                      f'（间隔调到 {self._interval:.1f}s）')
                time.sleep(wait)
                continue
            got_429 = False
            if r.status_code >= 500:
                time.sleep(3 + attempt * 2)
                continue
            if self._fail_logged < 3:
                self._fail_logged += 1
                print(f'  [{self.key}] 播放接口 {r.status_code}: '
                      f'{r.text[:80].strip()}')
            return ''

        if got_429:
            # 等了一轮还是 429，说明这次真被限流了。继续硬跑只会更糟，
            # 直接放弃本次剩余请求，分源缓存会原样保留。
            self._abort = True
            print(f'  [{self.key}] 仍被限流，本次放弃 4K影视，保留旧数据')
        return ''

    def _resolve_line(self, eps, userlink, referer):
        """
        签名 + 逐集取 m3u8（过滤掉 VIP/locked 的集），返回 [(集名, m3u8), ...]。

        走的是把 m3u8 直接写进 JSON 的老路子：Cloudflare Worker 里没有
        WebAssembly 运行时（new WebAssembly.Module() 会被平台拒绝），
        所以不能把签名留到播放时再做。
        """
        signed = self._sign_batch(eps, userlink)
        if self._signer_ok is False:
            # 没有 deno/node 就签不了名，也拿不到任何地址。宁可这次不出数据
            # （分源缓存保留旧的），也不要往 JSON 里塞一堆播不了的占位地址。
            if not self._no_sign_logged:
                self._no_sign_logged = True
                print(f'  [{self.key}] ⚠ 没有签名运行时（deno/node），'
                      f'拿不到播放地址，本次跳过 4K影视，保留旧数据')
            return []
        out = []
        for i, ep in enumerate(eps):
            if self._abort:
                break
            m3u8 = self._resolve(signed[i], referer)
            if m3u8:
                out.append((ep['name'], m3u8))
        return out

    # ---------------- 一部片 ----------------
    def _item(self, detail_url, type_name='', fallback_name='', fallback_pic='',
              fallback_remarks=''):
        name, pic, remark, userlink, lines = self._detail(detail_url)
        name = name or fallback_name
        pic = pic or fallback_pic
        remark = remark or self._norm_remarks(fallback_remarks)
        if not name or not lines:
            print(f'  [{self.key}] 详情页没解析到剧集: {detail_url}')
            return None

        picked = sorted(lines.items(), key=lambda kv: len(kv[1]),
                        reverse=True)[:self.max_lines]
        groups = []
        for line_no, eps in picked:
            if len(eps) > self.max_eps:
                eps = eps[-self.max_eps:]
            pairs = self._resolve_line(eps, userlink, detail_url)
            cleaned = clean_episodes(pairs)
            if not cleaned:
                print(f'  [{self.key}] 线路{line_no} 没拿到可用地址: {name}')
                continue
            line_name = '4K影视' if len(picked) == 1 else f'4K影视{line_no}'
            groups.append((line_name, cleaned))

        if not groups:
            print(f'  [{self.key}] 没拿到可用播放地址: {name}')
            return None

        # 备注按「实际拿到的集数」写，避免页面写 22 集、实际只解析到 20 集
        max_eps = max(len(u) for _, u in groups)
        if type_name in ('连续剧', '动漫', '综艺'):
            whole = re.search(r'全\s*(\d+)\s*集', remark or '')
            if not (whole and int(whole.group(1)) == max_eps):
                remark = f'更新至{max_eps}集'

        item = make_item(
            vod_id=0,
            name=name,
            type_id=0,
            type_name=type_name,
            pic=pic,
            remarks=remark,
            groups=groups,
            source=self.key,
        )

        print(f'  [{self.key}] ✓ {name} | {groups[0][0]} | {max_eps} 集 (直连 m3u8)')
        return item

    # ---------------- 主流程 ----------------
    def _pick_host(self):
        """站点换域名后自动选一个能用的，全都不行就返回 None（保留旧数据）。"""
        for h in self.hosts:
            try:
                r = self.http.session.get(f'{h}/tv', timeout=15)
                html = r.text or ''
            except Exception as e:
                print(f'  [kvm] {h} 打不开: {str(e)[:120]}')
                continue
            if 'movie-card' in html:
                if h != self.host:
                    print(f'  [kvm] 换用可用域名 {h}')
                self.host = h
                self.http.referer = h
                self.http.session.headers['Referer'] = h + '/'
                return h
            print(f'  [kvm] {h} 列表里没有影片卡片，换下一个域名')
        return None

    def crawl(self, pages=1, max_details=60, skip=None):
        items = []
        seq = 0

        if not self._pick_host():
            print(f'  [{self.key}] 所有域名都不可用，本次跳过，保留旧数据')
            return items

        def add(item):
            nonlocal seq
            if not item:
                return
            item['vod_id'] = self.id_base + seq
            items.append(item)
            seq += 1

        # 1) 指定片单：每次必抓，保证点名的剧更新能同步
        for seed in self.seed_urls:
            if self._abort:
                break
            url = self.host + seed['path']
            if url in self._seen:
                continue
            self._seen.add(url)
            add(self._item(url, type_name=seed.get('type_name', '连续剧')))

        # 2) 各分类首页
        for c in self.classes:
            if self._abort:
                break
            try:
                rows = self._list_page(c['path'])
            except Exception as e:
                print(f'  [{self.key}] 列表失败 {c["path"]}: {e}')
                continue
            print(f'  [{self.key}] {c["type_name"]} 列表 {len(rows)} 条')

            cap = c.get('limit') or 10
            if max_details:
                cap = min(cap, max_details)

            done = 0
            for r in rows:
                if done >= cap or self._abort:
                    break
                detail_url = r['detail_link']
                if detail_url in self._seen:
                    continue
                # 备注为空时不启用 skip，避免「空 == 空」把更新也跳掉
                if (skip and r.get('vod_remarks')
                        and skip(r['vod_name'], r['vod_remarks'])):
                    continue
                self._seen.add(detail_url)
                done += 1
                add(self._item(
                    detail_url,
                    type_name=c['type_name'],
                    fallback_name=r['vod_name'],
                    fallback_pic=r.get('vod_pic', ''),
                    fallback_remarks=r.get('vod_remarks', ''),
                ))

        return items

    # ---------------- 调试 ----------------
    def probe(self):
        if not self._pick_host():
            print('所有域名都不可用')
            return
        print(f'列表页: {self.host}/tv')
        rows = self._list_page('tv')
        print(f'解析到 {len(rows)} 条')
        for r in rows[:3]:
            print('  ', r)

        seed = self.host + self.seed_urls[0]['path']
        print(f'\n详情页: {seed}')
        name, pic, remark, userlink, lines = self._detail(seed)
        print(f'片名: {name} | 备注: {remark} | userlink: {userlink}')
        for line, eps in lines.items():
            print(f'  线路{line}: {len(eps)} 集，最后一集 {eps[-1]}')
        first = lines[max(lines, key=lambda k: len(lines[k]))][-1]
        signed = self._sign_batch([first], userlink)
        print(f'签名: {signed[0][:120]}...')
        print(f'm3u8: {self._resolve(signed[0], seed)}')