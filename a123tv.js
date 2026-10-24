/**
 * A123TV 专版 Bundle 兼容脚本
 */
var host = 'https://a123tv.com';
var headers = {
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
    'Referer': 'https://a123tv.com/'
};

async function request(reqUrl) {
    try {
        if (typeof $fetch !== 'undefined' && $fetch.get) {
            var res = await $fetch.get(reqUrl, { headers: headers });
            return res.data || '';
        }
    } catch (e) {}
    return '';
}

// 1. 初始化
async function init(cfg) {
    return {};
}

// 2. 首页分类
async function home(filter) {
    var classes = [
        {"type_id": "10", "type_name": "电影"},
        {"type_id": "11", "type_name": "连续剧"},
        {"type_id": "12", "type_name": "综艺"},
        {"type_id": "13", "type_name": "动漫"}
    ];
    return { class: classes };
}

// 3. 首页推荐
async function homeVod() {
    return { list: [] };
}

// 4. 分类列表页抓取
async function category(tid, pg, filter, extend) {
    var page = parseInt(pg) || 1;
    var targetUrl = page === 1 ? (host + '/t/' + tid + '.html') : (host + '/t/' + tid + '/p' + page + '.html');
    var html = await request(targetUrl);
    
    var list = [];
    var itemRegex = /<div class="w4-item-wrap">([\s\S]*?)<\/div>\s*<\/div>/g;
    var match;

    while ((match = itemRegex.exec(html)) !== null) {
        var block = match[1];
        var linkMatch = block.match(/href="\/v\/([^"]+?)\.html"/);
        var imgMatch = block.match(/data-src="([^"]+?)"/);
        var titleMatch = block.match(/title="([^"]+?)"/);
        var remarksMatch = block.match(/<span>([^<]+?线路)<\/span>/);

        if (linkMatch && titleMatch) {
            var vod_pic = imgMatch ? imgMatch[1] : '';
            if (vod_pic.indexOf('//') === 0) {
                vod_pic = 'https:' + vod_pic;
            }
            list.push({
                vod_id: linkMatch[1],
                vod_name: titleMatch[1],
                vod_pic: vod_pic,
                vod_remarks: remarksMatch ? remarksMatch[1] : ''
            });
        }
    }

    return {
        page: page,
        pagecount: 99,
        limit: 36,
        total: 999,
        list: list
    };
}

// 5. 详情页（解析 m3u8 直链线路）
async function detail(id) {
    var detailUrl = host + '/v/' + id + '.html';
    var html = await request(detailUrl);

    var titleMatch = html.match(/<li class="on"><h1>([^<]+?)<\/h1><\/li>/);
    var vod_name = titleMatch ? titleMatch[1] : id;

    var posterMatch = html.match(/data-poster="([^"]+?)"/);
    var vod_pic = posterMatch ? posterMatch[1] : '';
    if (vod_pic.indexOf('//') === 0) {
        vod_pic = 'https:' + vod_pic;
    }

    var descMatch = html.match(/<meta name="description" content="([^"]+?)">/);
    var vod_content = descMatch ? descMatch[1] : '';

    var play_from = [];
    var play_url = [];

    var ppMatch = html.match(/var pp\s*=\s*(\{[\s\S]*?\});<\/script>/);
    if (ppMatch && ppMatch[1]) {
        try {
            var ppData = JSON.parse(ppMatch[1]);
            var lines = ppData.la;

            if (lines && lines.length > 0) {
                play_from.push("A123TV聚合");
                var episodes = [];
                for (var i = 0; i < lines.length; i++) {
                    var item = lines[i];
                    var lineName = item[1] || ('线路' + (i + 1));
                    var m3u8Url = item[4];
                    if (m3u8Url) {
                        episodes.push(lineName + '$' + m3u8Url);
                    }
                }
                play_url.push(episodes.join('#'));
            }
        } catch (e) {}
    }

    return {
        list: [{
            vod_id: id,
            vod_name: vod_name,
            vod_pic: vod_pic,
            vod_content: vod_content,
            vod_play_from: play_from.join('$$$'),
            vod_play_url: play_url.join('$$$')
        }]
    };
}

// 6. 播放直链输出
async function play(flag, id, flags) {
    return {
        parse: 0,
        url: id,
        header: headers
    };
}

// 7. 搜索功能
async function search(wd, quick) {
    var searchUrl = host + '/s/' + encodeURIComponent(wd) + '.html';
    var html = await request(searchUrl);
    var list = [];

    var itemRegex = /<div class="w4-item-wrap">([\s\S]*?)<\/div>\s*<\/div>/g;
    var match;

    while ((match = itemRegex.exec(html)) !== null) {
        var block = match[1];
        var linkMatch = block.match(/href="\/v\/([^"]+?)\.html"/);
        var imgMatch = block.match(/data-src="([^"]+?)"/);
        var titleMatch = block.match(/title="([^"]+?)"/);
        var remarksMatch = block.match(/<span>([^<]+?线路)<\/span>/);

        if (linkMatch && titleMatch) {
            var vod_pic = imgMatch ? imgMatch[1] : '';
            if (vod_pic.indexOf('//') === 0) {
                vod_pic = 'https:' + vod_pic;
            }
            list.push({
                vod_id: linkMatch[1],
                vod_name: titleMatch[1],
                vod_pic: vod_pic,
                vod_remarks: remarksMatch ? remarksMatch[1] : ''
            });
        }
    }

    return { list: list };
}

// 爬虫对象
var spider = {
    init: init,
    home: home,
    homeVod: homeVod,
    category: category,
    detail: detail,
    play: play,
    search: search
};

function start() {
    return spider;
}

// 多层出口绑定，确保捕获 bundle.start()
if (typeof exports === 'object') {
    exports.start = start;
    exports.default = spider;
}
if (typeof module === 'object' && module.exports) {
    module.exports.start = start;
    module.exports.default = spider;
}
if (typeof window !== 'undefined') {
    window.start = start;
}
if (typeof globalThis !== 'undefined') {
    globalThis.start = start;
}
