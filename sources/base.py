# -*- coding: utf-8 -*-
"""
公共工具层：HTTP 请求、播放地址规范化、去重、敏感词过滤。

所有源都只负责「拿到原始数据」，清洗和规范化统一在这里做，
这样以后加新站不用重复写一遍去重逻辑。
"""

import re
import time
import json
import random
import urllib.parse
import requests

# 统一 UA：手机端 UA 更容易拿到完整页面
UA = ('Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
      'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 '
      'Mobile/15E148 Safari/604.1')

# 敏感词黑名单（在爬虫端过滤，不要指望 Worker）
SENSITIVE_WORDS = ["伦理", "福利", "三级", "风月", "情色", "成人", "伦理片", "无码"]


class HttpClient:
    """带重试、超时、限速的简易客户端。"""

    def __init__(self, referer='', timeout=15, retries=2, delay=0.3):
        self.referer = referer
        self.timeout = timeout
        self.retries = retries
        self.delay = delay
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({
            'User-Agent': UA,
            'Accept': 'text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        })
        if referer:
            self.session.headers['Referer'] = referer

    def get(self, url, **kwargs):
        """返回文本，失败抛异常（由调用方决定是否吞掉）。"""
        last_err = None
        for attempt in range(self.retries + 1):
            try:
                r = self.session.get(url, timeout=self.timeout, **kwargs)
                r.encoding = r.apparent_encoding or 'utf-8'
                time.sleep(self.delay)
                return self._unwrap(r.text)
            except Exception as e:
                last_err = e
                time.sleep(1 + attempt)
        raise RuntimeError(f'请求失败 {url}: {last_err}')

    @staticmethod
    def _unwrap(text):
        """
        有些站会把整页 HTML / JSON 再包一层 JSON 字符串返回
        （"<!DOCTYPE html>\\n<html..." 或 "{\\"code\\":1,...}"），
        不还原的话所有正则和 json.loads 都会失效。这里循环解包。
        """
        s = text.strip()
        for _ in range(3):
            if not (s.startswith('"') and s.endswith('"')):
                break
            try:
                val = json.loads(s)
            except Exception:
                break
            if not isinstance(val, str):
                break
            s = val.strip()
        return s

    def get_json(self, url, **kwargs):
        """返回 JSON。源站偶尔返回 BOM 或前后杂质，这里做一次容错。"""
        text = self.get(url, **kwargs)
        text = text.strip().lstrip('\ufeff')
        try:
            return json.loads(text)
        except Exception:
            # 有些站会包一层 jsonp: callback({...})
            m = re.search(r'\{[\s\S]*\}', text)
            if not m:
                raise
            return json.loads(m.group(0))


def abs_url(base, url):
    """补全 // 开头、/ 开头的图片/链接。"""
    if not url:
        return ''
    url = url.strip()
    if url.startswith('//'):
        return 'https:' + url
    if url.startswith('/'):
        return base.rstrip('/') + url
    return url


def probe_m3u8(http, url, deep=True):
    """
    读一次 m3u8，返回线路的「真实清晰度」信息。

    很多站同一部片有十几条线路，线路名（无印云 / 优质云）和集名（第01集）
    都不带 HD/TC 标签，光看 HTML 分不出好坏。这里直接看播放列表：
      - master playlist：RESOLUTION=1920x1080 / BANDWIDTH / 3000k 这类码率
      - media playlist：直接数片段，确认不是空壳

    deep=False 时不追进子播放列表（子列表可能有几千个片段，很慢）；
    只是排序用的话，master 里的分辨率/码率已经够了。

    返回 {'ok', 'height', 'bandwidth', 'kbps', 'segments', 'encrypted'}。
    任何一步失败都返回 ok=False，调用方按「未知质量」处理，不会因此丢线路。
    """
    info = {'ok': False, 'height': 0, 'bandwidth': 0, 'kbps': 0,
            'segments': 0, 'encrypted': False}
    if not url or not str(url).startswith('http'):
        return info

    try:
        text = http.get(url)
    except Exception:
        return info
    if not text or '#EXTM3U' not in text:
        return info

    info['ok'] = True
    info['encrypted'] = '#EXT-X-KEY' in text

    heights = [int(x) for x in re.findall(r'RESOLUTION=\d+x(\d+)', text)]
    bandwidths = [int(x) for x in re.findall(r'BANDWIDTH=(\d+)', text)]
    if heights:
        info['height'] = max(heights)
    if bandwidths:
        info['bandwidth'] = max(bandwidths)

    if '#EXT-X-STREAM-INF' not in text:
        info['segments'] = text.count('#EXTINF')
        return info

    # master playlist：优先选码率最高 / 路径里带 3000k 的那一路
    best_uri, best_score = '', -1
    lines = [ln.strip() for ln in text.splitlines()]
    for i, line in enumerate(lines):
        if not line.startswith('#EXT-X-STREAM-INF'):
            continue
        bw_m = re.search(r'BANDWIDTH=(\d+)', line)
        bw = int(bw_m.group(1)) if bw_m else 0
        for nxt in lines[i + 1:]:
            if not nxt or nxt.startswith('#'):
                continue
            kbps_m = re.search(r'(\d{3,5})k', nxt, re.I)
            kbps = int(kbps_m.group(1)) if kbps_m else 0
            score = kbps * 1000 + bw
            if score > best_score:
                best_score, best_uri = score, nxt
            break

    if best_uri:
        kbps_m = re.search(r'(\d{3,5})k', best_uri, re.I)
        if kbps_m:
            info['kbps'] = int(kbps_m.group(1))
        if deep:
            try:
                sub = http.get(urllib.parse.urljoin(url, best_uri))
                info['segments'] = sub.count('#EXTINF')
                info['encrypted'] = info['encrypted'] or '#EXT-X-KEY' in sub
            except Exception:
                pass

    return info


# 片名末尾常见的清晰度 / 语言标签。站点会把它们当片名的一部分，
# 例如「给阿嬷的情书 TC」「欢迎来龙餐馆 HD国语」，入库前统一清掉。
_QUALITY_TAGS = (
    'TC', 'TS', 'CAM', 'HDTS', 'HDTC', '枪版', '抢先版', '清晰版', '偷录', '盗摄',
    'HD', 'BD', '蓝光', '高清', '超清', '4K', '1080P', '720P', '正片', '完整版',
    '国语', '普通话', '粤语', '潮汕话', '闽南语', '原声', '中字', '中文字幕', '双语', '英语',
)
_QUALITY_TAIL_RE = re.compile(
    r'[\s\-_·|/]*[\(\[（【]?\s*(?:'
    + '|'.join(re.escape(t) for t in _QUALITY_TAGS)
    + r')(?:版|版本)?(?:v\d+)?\s*[\)\]）】]?\s*$',
    re.I,
)


def clean_title_suffix(name):
    """去掉片名末尾的 TC / HD / HD国语 / 正片 等版本标签（可叠加，循环剥离）。

    整串都是标签（例如备注里只写「TC国语」）时返回空字符串，调用方自行兜底。
    """
    s = (name or '').strip()
    for _ in range(5):
        new = _QUALITY_TAIL_RE.sub('', s).strip()
        if new == s:
            break
        s = new
        if not s:
            break
    return s


def norm_name(name):
    """用于跨源去重的名称归一化：去掉季数/年份/空格/标点。"""
    if not name:
        return ''
    s = str(name).lower()
    s = re.sub(r'[\s\-_·:：,，.。!！?？()（）\[\]【】"\'“”‘’]', '', s)
    s = re.sub(r'(第[一二三四五六七八九十\d]+季|season\d+|s\d{1,2})', '', s)
    s = re.sub(r'(19|20)\d{2}', '', s)
    return s


# ---- 清晰度/版本评分：所有源共用一套，避免各写一份还写得不一样 ----
_LOW_VERSION_RE = re.compile(r'(?<![A-Z])(?:HD)?(?:TC|TS|CAM)|枪版|抢先版|清晰版|偷录|盗摄')
_HIGH_VERSION_RE = re.compile(r'(?:HD|BD|蓝光|高清|超清|4K|1080P|720P|正片|完整版)', re.I)
_LANG_VERSION_RE = re.compile(r'(?:国语|普通话|粤语|潮汕话|闽南语|原声|中字|中文字幕|双语|英语)', re.I)


def quality_score(text):
    """版本/清晰度评分：HD/正片 +50，TC/枪版 -100，纯集数不计分。"""
    s = (text or '').strip()
    if not s:
        return 0
    if s.isdigit() or re.fullmatch(r'第\s*\d+\s*集', s):
        return 0
    if _LOW_VERSION_RE.search(s):
        return -100
    score = 50 if _HIGH_VERSION_RE.search(s) else 0
    if _LANG_VERSION_RE.search(s):
        score += 3
    return score


def stream_quality_score(info):
    """把 probe_m3u8 的结果压成一个可比较的数字：分辨率优先，其次码率。"""
    if not info or not info.get('ok'):
        return 0
    height = info.get('height') or 0
    kbps = info.get('kbps') or 0
    bandwidth = info.get('bandwidth') or 0
    return height * 10000 + kbps * 10 + min(bandwidth // 1000, 20000)


def is_blocked(*texts):
    """命中敏感词就返回 True。"""
    blob = ' '.join(str(t or '') for t in texts)
    return any(w in blob for w in SENSITIVE_WORDS)


def clean_episodes(pairs):
    """
    清洗剧集列表。

    pairs: [(集名, 播放地址), ...]
    规则：
      - 地址必须以 http 开头
      - 同一地址只保留第一次出现（你现在 vod.json 里重复十几次就是这个原因）
      - 集名去空格，空的自动补「第N集」
    """
    seen = set()
    out = []
    for idx, (name, url) in enumerate(pairs):
        if not url or not str(url).startswith('http'):
            continue
        url = str(url).strip().replace(' ', '')
        if url in seen:
            continue
        seen.add(url)
        name = (str(name) if name else f'第{idx + 1}集').strip().replace('$', '').replace('#', '')
        out.append(f'{name}${url}')
    return out


def build_play(groups):
    """
    groups: [(线路名, [集名字符串, ...]), ...]
    返回 (vod_play_from, vod_play_url)，保证两边组数严格一致。
    """
    froms, urls = [], []
    for line_name, episodes in groups:
        if not episodes:
            continue
        line_name = (line_name or f'线路{len(froms) + 1}').replace('$$$', '').replace('$', '')
        froms.append(line_name)
        urls.append('#'.join(episodes))
    return '$$$'.join(froms), '$$$'.join(urls)


def make_item(vod_id, name, type_id, type_name, pic='', remarks='',
              groups=None, source=''):
    """构造一条标准影片数据，组数不一致的直接丢弃。"""
    if not name or not groups:
        return None
    play_from, play_url = build_play(groups)
    if not play_from or not play_url:
        return None
    return {
        'vod_id': vod_id,
        'vod_name': name.strip(),
        'type_id': type_id,
        'type_name': type_name,
        'vod_pic': pic or '',
        'vod_remarks': (remarks or '').strip(),
        'vod_play_from': play_from,
        'vod_play_url': play_url,
        'vod_source': source,
    }


def extract_play(html):
    """
    从详情页 HTML 里抠播放地址，返回 [(线路名, [集, ...]), ...]。

    按可靠性从高到低依次尝试，任何一个成功就返回：
      1. var pp = {"la": [...]}          —— 苹果CMS 常见播放器数据
      2. MacPlayer / player_aaaa 里的 url
      3. 页面里裸的 .m3u8 地址
    """
    groups = []

    # 1) var pp = {...}
    m = re.search(r'var\s+pp\s*=\s*(\{[\s\S]*?\});', html)
    if m:
        try:
            data = json.loads(m.group(1))
            episodes = []
            for idx, line in enumerate(data.get('la', [])):
                if len(line) > 4 and line[4] and str(line[4]).startswith('http'):
                    episodes.append((line[1] if line[1] else f'线路{idx + 1}', line[4]))
            cleaned = clean_episodes(episodes)
            if cleaned:
                groups.append(('线路1', cleaned))
        except Exception:
            pass

    # 2) player 配置里的 url
    if not groups:
        for pattern in (r'"url"\s*:\s*"([^"]+?\.m3u8[^"]*)"',
                        r"url\s*:\s*'([^']+?\.m3u8[^']*)'"):
            m = re.search(pattern, html)
            if m:
                cleaned = clean_episodes([('正片', m.group(1).replace('\\/', '/'))])
                if cleaned:
                    groups.append(('线路1', cleaned))
                    break

    # 3) 裸 m3u8
    if not groups:
        urls = re.findall(r'https?://[^\s"\'<>\\]+?\.m3u8[^\s"\'<>\\]*', html)
        cleaned = clean_episodes([(f'第{i + 1}集', u) for i, u in enumerate(urls)])
        if cleaned:
            groups.append(('线路1', cleaned))

    return groups


def random_ua():
    return random.choice([
        UA,
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    ])


class Source:
    """
    声明式源基类：子类只实现 list_page() 和 play() 两个方法。

    适合「列表页 + 详情页」结构简单、想快速填坑的站（见 sources/stubs.py）。
    比 jsard.py 那种全手写的源少写很多，但灵活性也低一些。

    子类要设：
        key / name / domain / offset（vod_id 段位）/ categories
    """

    enabled = False
    key = ''
    name = ''
    domain = ''
    offset = 0
    categories = []      # [{'type_id': 1, 'type_name': '电影'}, ...]
    delay = 0.3

    def __init__(self):
        self._http = None

    @property
    def http(self):
        """第一次用到时才建连接，这样 stubs.py 先构造再改 domain 也没问题。"""
        if self._http is None:
            self._http = HttpClient(referer=self.domain, delay=self.delay)
        return self._http

    def list_page(self, category, page):
        """返回 [{'vod_name','vod_pic','vod_remarks','detail_link',...}, ...]"""
        raise NotImplementedError(f'{self.key}: 还没实现列表解析')

    def play(self, item):
        """返回 [(线路名, [集字符串, ...]), ...]"""
        raise NotImplementedError(f'{self.key}: 还没实现播放地址解析')

    def crawl(self, pages=1, max_details=20, skip=None):
        items, seq = [], 0
        base = getattr(self, 'id_base', 0) or self.offset

        for c in self.categories:
            done = 0
            for page in range(1, pages + 1):
                if max_details and done >= max_details:
                    break
                try:
                    rows = self.list_page(c, page) or []
                except Exception as e:
                    print(f'  [{self.key}] 列表失败 {c.get("type_name")} p{page}: {e}')
                    break
                if not rows:
                    break

                for r in rows:
                    if max_details and done >= max_details:
                        break
                    # 已抓过且备注没变 → 跳过详情请求
                    if skip and skip(r.get('vod_name', ''), r.get('vod_remarks', '')):
                        continue
                    done += 1
                    try:
                        groups = self.play(r) or []
                    except Exception as e:
                        print(f'  [{self.key}] 详情失败 {r.get("vod_name")}: {e}')
                        continue
                    item = make_item(
                        vod_id=base + seq,
                        name=r.get('vod_name', ''),
                        type_id=c['type_id'],
                        type_name=c['type_name'],
                        pic=r.get('vod_pic', ''),
                        remarks=r.get('vod_remarks', ''),
                        groups=groups,
                        source=self.key,
                    )
                    if item:
                        items.append(item)
                        seq += 1
        return items