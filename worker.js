/**
 * Cloudflare Worker —— 苹果CMS 标准 JSON 接口
 *
 * 相比你原来的版本，改了 5 个地方：
 *   1. 分页/总数用「过滤后的列表」算，搜索和分类的分页数才正确
 *   2. 删掉「分类为空就返回全部」的兜底，避免空分类串台显示所有影片
 *   3. 加 Cache API，不再每个请求都回源 GitHub（快很多，也不容易被限流）
 *   4. 支持 ac=list（只返回分类，播放器首次加载更快）
 *   5. 敏感词过滤保留，但真正的过滤在 crawler_v2.py 里做
 *   6. KV 只在 GitHub 读取失败时兜底，正常请求永远先回源，避免一直返回旧数据
 *
 * 部署：Workers -> 编辑代码 -> 粘贴 -> Deploy
 * 可选绑定 KV：变量名 VOD_KV，用来做更长久的缓存（不绑定也能跑）
 *
 * 封面代理：/img?u=<原始图片地址>
 *   接口返回的 vod_pic 会自动改写成这个地址，由 Worker 去取图再回给播放器。
 *   好处：源站防盗链/国内打不开的图床都能显示（Worker 走 Cloudflare 网络）。
 *   想关掉：在 Worker 变量里加 PIC_PROXY=0。
 */

const BASE_URL = 'https://raw.githubusercontent.com/2Eason-Lee/A123tv/refs/heads/main/';

// 路径 → 数据文件：访问 /jsard 就是 jsard 单独的数据，/ 是合并版
const FILE_MAP = {
  'a123tv': 'vod-a123tv.json',
  'jsard': 'vod-jsard.json',
  'fdzys': 'vod-fdzys.json',
  'ncat21': 'vod-ncat21.json',
  'kvm': 'vod-kvm.json',
};

const CACHE_TTL = 300;          // 秒，5 分钟
const PAGE_SIZE = 30;

// 图片代理
const PIC_CACHE_TTL = 604800;   // 7 天，封面基本不会变
const PIC_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) '
  + 'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1';

const EXCLUDED = ['伦理', '福利', '三级', '风月', '情色', '成人', '色情', '偷拍'];

const JSON_HEADERS = {
  'Content-Type': 'application/json;charset=UTF-8',
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET,OPTIONS',
  'Access-Control-Allow-Headers': '*',
};

function json(obj, extra = {}) {
  return new Response(JSON.stringify(obj), {
    headers: { ...JSON_HEADERS, ...extra },
  });
}

function fail(msg) {
  return json({ code: 0, msg, list: [], class: [] });
}

/** 带缓存地读取数据文件（每个文件单独一份缓存） */
async function loadData(env, ctx, file) {
  const dataUrl = BASE_URL + file;
  const cache = caches.default;
  const cacheKey = new Request(dataUrl, { method: 'GET' });

  const cached = await cache.match(cacheKey);
  if (cached) return cached.json();

  // 正常路径永远先回源 GitHub，保证 Action 一提交就能读到新数据。
  // KV 只做「GitHub 挂了」时的兜底，不能挡在回源前面，否则会一直返回旧数据。
  try {
    const res = await fetch(dataUrl, { cf: { cacheTtl: CACHE_TTL } });
    if (!res.ok) throw new Error(`GitHub 数据读取失败: ${file} ${res.status}`);
    const data = await res.json();

    ctx.waitUntil(cache.put(cacheKey, new Response(JSON.stringify(data), {
      headers: { 'Content-Type': 'application/json', 'Cache-Control': `max-age=${CACHE_TTL}` },
    })));

    // 顺手刷新 KV 兜底副本（24 小时过期，过期后自然淘汰）
    if (env && env.VOD_KV) {
      ctx.waitUntil(env.VOD_KV.put('vod:' + file, JSON.stringify(data), {
        expirationTtl: 86400,
      }));
    }
    return data;
  } catch (err) {
    if (env && env.VOD_KV) {
      const kv = await env.VOD_KV.get('vod:' + file, 'json');
      if (kv) return kv;
    }
    throw err;
  }
}

/** 把原始封面地址换成 /img 代理地址（接口里所有 vod_pic 都会走这里） */
function picProxyUrl(pic, origin) {
  if (!pic || typeof pic !== 'string') return pic;
  if (!/^https?:\/\//i.test(pic)) return pic;
  // 已经是本 Worker 的地址就别二次套娃
  if (pic.startsWith(origin + '/img')) return pic;
  return `${origin}/img?u=${encodeURIComponent(pic)}`;
}

/** 内网/本机地址不代理，避免被当成跳板 */
function isBlockedHost(host) {
  const h = (host || '').toLowerCase();
  if (!h) return true;
  if (h === 'localhost' || h === '0.0.0.0' || h.endsWith('.local')) return true;
  return /^127\./.test(h)
    || /^10\./.test(h)
    || /^192\.168\./.test(h)
    || /^169\.254\./.test(h)
    || /^172\.(1[6-9]|2\d|3[01])\./.test(h)
    || h === '[::1]';
}

/**
 * 图片代理：/img?u=<urlencode 后的原图地址>&r=<可选 Referer>
 * 上游返回的不是图片（防盗链页/校验页）时回 404，客户端会显示占位图而不是坏图标。
 */
async function handleImage(ctx, url) {
  const raw = url.searchParams.get('u') || '';
  if (!raw) return new Response('missing u', { status: 400 });

  let target;
  try {
    target = new URL(raw);
  } catch {
    return new Response('bad u', { status: 400 });
  }
  if (!/^https?:$/.test(target.protocol)) {
    return new Response('bad protocol', { status: 400 });
  }
  if (isBlockedHost(target.hostname)) {
    return new Response('forbidden host', { status: 403 });
  }

  const cache = caches.default;
  const cacheKey = new Request(url.toString(), { method: 'GET' });
  const hit = await cache.match(cacheKey);
  if (hit) return hit;

  const referer = url.searchParams.get('r') || `${target.protocol}//${target.host}/`;

  // 先带 Referer 取；防盗链站点拒绝时再试一次不带 Referer
  const attempts = [
    { 'User-Agent': PIC_UA, Accept: 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8', Referer: referer },
    { 'User-Agent': PIC_UA, Accept: 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8' },
  ];

  let lastStatus = 0;
  for (const headers of attempts) {
    let res;
    try {
      res = await fetch(target.toString(), { headers, cf: { cacheTtl: PIC_CACHE_TTL } });
    } catch {
      lastStatus = 599;
      continue;
    }
    lastStatus = res.status;
    const type = (res.headers.get('content-type') || '').toLowerCase();
    if (!res.ok || !type.startsWith('image/')) continue;

    const body = await res.arrayBuffer();
    const out = new Response(body, {
      headers: {
        'Content-Type': type,
        'Content-Length': String(body.byteLength),
        'Cache-Control': `public, max-age=${PIC_CACHE_TTL}, immutable`,
        'Access-Control-Allow-Origin': '*',
        'X-Pic-Proxy': '1',
      },
    });
    ctx.waitUntil(cache.put(cacheKey, out.clone()));
    return out;
  }

  // 取不到图：短缓存 10 分钟，避免每次都去撞上游
  return new Response(`upstream not image: ${lastStatus}`, {
    status: 404,
    headers: {
      'Content-Type': 'text/plain;charset=UTF-8',
      'Cache-Control': 'public, max-age=600',
      'Access-Control-Allow-Origin': '*',
    },
  });
}

export default {
  async fetch(request, env, ctx) {
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: JSON_HEADERS });
    }

    try {
      const url = new URL(request.url);

      // 封面代理：/img?u=...
      if (url.pathname === '/img' || url.pathname === '/img/') {
        return await handleImage(ctx, url);
      }

      const pg = Math.max(1, parseInt(url.searchParams.get('pg') || '1', 10) || 1);
      const ac = url.searchParams.get('ac') || 'detail';
      const t = url.searchParams.get('t');
      const wd = (url.searchParams.get('wd') || '').trim();
      const ids = url.searchParams.get('ids');

      // 路径决定读哪个文件：/ 或 /all → 合并版，/a123tv、/jsard → 单源
      const path = url.pathname.replace(/^\/+|\/+$/g, '').toLowerCase();
      const file = FILE_MAP[path];
      if (!file) {
        return fail(`未知站点路径: ${path}，可选: ${Object.keys(FILE_MAP).join(', ')}`);
      }

      const data = await loadData(env, ctx, file);

      const cleanClass = (data.class || []).filter(
        (c) => !EXCLUDED.some((k) => (c.type_name || '').includes(k))
      );

      // 只要分类，不要列表（播放器首页加载用）
      if (ac === 'list') {
        return json({
          code: 1, msg: '成功', page: pg, pagecount: 1, limit: PAGE_SIZE,
          total: 0, class: cleanClass, list: [],
        });
      }

      const cleanList = (data.list || []).filter((item) => {
        const text = `${item.vod_name || ''}${item.vod_remarks || ''}`;
        return !EXCLUDED.some((k) => text.includes(k));
      });

      let filtered = cleanList;
      if (ids) {
        const want = new Set(ids.split(',').map((s) => s.trim()));
        filtered = cleanList.filter((it) => want.has(String(it.vod_id)));
      } else if (t) {
        filtered = cleanList.filter((it) => String(it.type_id) === String(t));
        // 注意：这里不再兜底返回全量，空分类就老老实实返回空
      } else if (wd) {
        const kw = wd.toLowerCase();
        filtered = cleanList.filter((it) =>
          (it.vod_name || '').toLowerCase().includes(kw) ||
          (it.vod_actor || '').toLowerCase().includes(kw) ||
          (it.vod_director || '').toLowerCase().includes(kw)
        );
      }

      const total = filtered.length;
      const pagecount = Math.max(1, Math.ceil(total / PAGE_SIZE));
      const start = (pg - 1) * PAGE_SIZE;

      // 封面统一走本 Worker 的 /img 代理，源站防盗链/国内打不开的图床也能显示。
      // PIC_PROXY=0 可以关掉（关掉就用源站原始地址）。
      const usePicProxy = !(env && String(env.PIC_PROXY) === '0');
      const list = filtered.slice(start, start + PAGE_SIZE).map((it) => (
        usePicProxy
          ? { ...it, vod_pic: picProxyUrl(it.vod_pic, url.origin) }
          : it
      ));

      return json({
        code: 1,
        msg: '成功',
        page: pg,
        pagecount,
        limit: PAGE_SIZE,
        total,
        class: cleanClass,
        list,
      });
    } catch (error) {
      return fail('接口异常: ' + error.message);
    }
  },
};