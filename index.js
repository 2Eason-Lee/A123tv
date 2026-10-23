// ==UserScript==
// @name         A123TV(CF云端加速版)
// @type         drpy
// ==/UserScript==

var rule = {
    title: 'A123TV',
    host: 'https://a123tv.com',
    homeUrl: 'https://a123tv.com/',
    url: 'https://a123tv.com/t/fyclass/pfypage.html',
    searchUrl: 'https://a123tv.com/s/**.html',
    searchable: 2,
    quickSearch: 1,
    filterable: 0,
    headers: {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15',
        'Referer': 'https://a123tv.com/'
    },
    class_name: '电影&连续剧&综艺&动漫&4K电影&动作片&喜剧片&爱情片&科幻片&恐怖片&剧情片&战争片&纪录片&动画片&犯罪片&悬疑片&古装片&历史片',
    class_url: '10&11&12&13&1027&1001&1002&1003&1004&1005&1006&1007&1008&1013&1014&1016&1025&1026',
    play_parse: true,
    
    // 【核心修改】：接入 CF Worker，并保留原逻辑作为防崩兜底
    lazy: `js:
        if (/\\.m3u8|\\.mp4/.test(input)) {
            input = { parse: 0, url: input };
        } else {
            var cf_worker = "https://a123-proxy.eason-lee89750.workers.dev/?url=";
            try {
                // 1. 优先尝试让 CF Worker 在云端去抓取直链
                var res = request(cf_worker + input, {timeout: 8000});
                var json = JSON.parse(res);
                
                if (json.code === 200 && json.url) {
                    input = { parse: 0, url: json.url, header: rule.headers };
                } else {
                    // 2. 如果 CF 没抓到，走原来的老代码兜底
                    let html = request(input, {headers: {'Referer': 'https://a123tv.com/'}});
                    let m = html.match(/data-src="(https?:\\/\\/[^"]+\\.m3u8[^"]*)"/);
                    input = m ? { parse: 0, url: m[1] } : { parse: 1, url: input };
                }
            } catch(e) {
                // 3. 如果 CF 请求超时或报错，也走原来的老代码兜底
                let html = request(input, {headers: {'Referer': 'https://a123tv.com/'}});
                let m = html.match(/data-src="(https?:\\/\\/[^"]+\\.m3u8[^"]*)"/);
                input = m ? { parse: 0, url: m[1] } : { parse: 1, url: input };
            }
        }
    `,
    
    limit: 20,
    推荐: '.w4-list;.w4-item-wrap;.t&&Text;img&&data-src;.s&&Text;a&&href',
    一级: '.w4-item-wrap;.t&&Text;img&&data-src;.s&&Text;a&&href',
    二级: `js:
        let html = request(input, {headers: {'Referer': 'https://a123tv.com/'}});
        let vod = {
            vod_id: input,
            vod_name: (html.match(/<h1>([^<]+)<\\/h1>/) || [,'未知片名'])[1],
            vod_pic: (html.match(/property="og:image"\\s+content="([^"]+)"/) || [,''])[1],
            vod_content: (html.match(/name="description"\\s+content="([^"]+)"/) || [,''])[1]
        };
        if (vod.vod_pic.startsWith('//')) vod.vod_pic = 'https:' + vod.vod_pic;

        let playFrom = [];
        let playUrl = [];

        let epBlock = html.match(/<div class="w4-episode-list[^>]*>([\\s\\S]*?)<\\/div>\\s*<\\/div>\\s*<\\/div>/);
        let epList = [];
        if (epBlock) {
            let reg = /<a[^>]+href="([^"]+)"[^>]*>([^<]+)<\\/a>/g;
            let m;
            while ((m = reg.exec(epBlock[1])) !== null) {
                epList.push({ name: m[2].trim(), href: 'https://a123tv.com' + m[1] });
            }
        }
        if (epList.length > 1) {
            playFrom.push('A123选集');
            playUrl.push(epList.map(e => e.name + '$' + e.href).join('#'));
        }

        let ppMatch = html.match(/var\\s+pp\\s*=\\s*(\\{[\\s\\S]*?\\});\\s*<\\/script>/);
        if (ppMatch) {
            try {
                let pp = JSON.parse(ppMatch[1]);
                if (pp.la) {
                    let groups = {};
                    let seen = {};
                    pp.la.forEach(item => {
                        let ln = item[1] || '默认线路';
                        let u = item[4];
                        if (u && u.startsWith('http') && !seen[ln + u]) {
                            seen[ln + u] = 1;
                            if (!groups[ln]) groups[ln] = [];
                            let idx = groups[ln].length + 1;
                            groups[ln].push((idx === 1 ? '正片' : '正片(源' + idx + ')') + '$' + u);
                        }
                    });
                    for (let k in groups) {
                        playFrom.push(k);
                        playUrl.push(groups[k].join('#'));
                    }
                }
            } catch(e) {}
        }

        if (playFrom.length === 0) {
            let dm = html.match(/data-src="(https?:\\/\\/[^"]+\\.m3u8[^"]*)"/);
            if (dm) {
                playFrom.push('A123直连');
                playUrl.push('正片$' + dm[1]);
            }
        }

        vod.vod_play_from = playFrom.join('$$$');
        vod.vod_play_url = playUrl.join('$$$');
        VOD = vod;
    `,
    搜索: '.w4-item-wrap;.t&&Text;img&&data-src;.s&&Text;a&&href'
};
