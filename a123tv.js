/**
 * A123TV 完整独立版猫源爬虫脚本
 */
var rule = {
    title: 'A123TV',
    host: 'https://a123tv.com',
    homeUrl: '/',
    url: '/t/fyclass/pfypage.html',
    detailUrl: '/v/fyid.html',
    searchUrl: '/s/**.html',
    headers: {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://a123tv.com/'
    }
};

// 1. 初始化方法
function init(ext) {}

// 2. 首页数据与分类定义
function home(filter) {
    var classes = [
        {"type_id": "10", "type_name": "电影"},
        {"type_id": "11", "type_name": "连续剧"},
        {"type_id": "12", "type_name": "综艺"},
        {"type_id": "13", "type_name": "动漫"}
    ];
    return JSON.stringify({
        "class": classes
    });
}

// 3. 首页推荐列表
function homeVod() {
    return JSON.stringify({
        "list": []
    });
}

// 4. 分类列表页（分页抓取）
function category(tid, pg, filter, extend) {
    var page = parseInt(pg) || 1;
    var targetUrl = '';
    
    if (page === 1) {
        targetUrl = rule.host + '/t/' + tid + '.html';
    } else {
        targetUrl = rule.host + '/t/' + tid + '/p' + page + '.html';
    }

    var html = request(targetUrl, { headers: rule.headers });
    var list = [];

    // 正则拆分每一个影片卡片 (.w4-item-wrap)
    var itemRegex = /<div class="w4-item-wrap">([\s\S]*?)<\/div>\s*<\/div>/g;
    var match;

    while ((match = itemRegex.exec(html)) !== null) {
        var block = match[1];
        
        // 提取影片 ID / 链接
        var linkMatch = block.match(/href="\/v\/([^"]+?)\.html"/);
        // 提取图片链接
        var imgMatch = block.match(/data-src="([^"]+?)"/);
        // 提取影片标题
        var titleMatch = block.match(/title="([^"]+?)"/);
        // 提取集数或线路备注
        var remarksMatch = block.match(/<span>([^<]+?线路)<\/span>/);

        if (linkMatch && titleMatch) {
            var vod_id = linkMatch[1];
            var vod_name = titleMatch[1];
            var vod_pic = imgMatch ? imgMatch[1] : '';
            if (vod_pic.indexOf('//') === 0) {
                vod_pic = 'https:' + vod_pic;
            }
            var vod_remarks = remarksMatch ? remarksMatch[1] : '';

            list.push({
                "vod_id": vod_id,
                "vod_name": vod_name,
                "vod_pic": vod_pic,
                "vod_remarks": vod_remarks
            });
        }
    }

    return JSON.stringify({
        "page": page,
        "pagecount": 99,
        "limit": 36,
        "total": 999,
        "list": list
    });
}

// 5. 影片详情与选集（解析所有的 m3u8 直链线路）
function detail(id) {
    var detailUrl = rule.host + '/v/' + id + '.html';
    var html = request(detailUrl, { headers: rule.headers });

    // 提取标题
    var titleMatch = html.match(/<li class="on"><h1>([^<]+?)<\/h1><\/li>/);
    var vod_name = titleMatch ? titleMatch[1] : id;

    // 提取海报封面
    var posterMatch = html.match(/data-poster="([^"]+?)"/);
    var vod_pic = posterMatch ? posterMatch[1] : '';
    if (vod_pic.indexOf('//') === 0) {
        vod_pic = 'https:' + vod_pic;
    }

    // 提取描述
    var descMatch = html.match(/<meta name="description" content="([^"]+?)">/);
    var vod_content = descMatch ? descMatch[1] : '';

    var play_from = [];
    var play_url = [];

    // 提取网页底部的 var pp 数据
    var ppMatch = html.match(/var pp\s*=\s*(\{[\s\S]*?\});<\/script>/);

    if (ppMatch && ppMatch[1]) {
        try {
            var ppData = JSON.parse(ppMatch[1]);
            var lines = ppData.la; // 获取线路数组

            if (lines && lines.length > 0) {
                play_from.push("A123TV聚合源");
                var episodes = [];

                for (var i = 0; i < lines.length; i++) {
                    var item = lines[i];
                    var lineName = item[1] || ("线路" + (i + 1));
                    var m3u8Url = item[4]; // 真实播放直链

                    if (m3u8Url) {
                        episodes.push(lineName + '$' + m3u8Url);
                    }
                }

                play_url.push(episodes.join('#'));
            }
        } catch (e) {
            // 解析失败时降级
        }
    }

    var vod = {
        "vod_id": id,
        "vod_name": vod_name,
        "vod_pic": vod_pic,
        "vod_content": vod_content,
        "vod_play_from": play_from.join('$$$'),
        "vod_play_url": play_url.join('$$$')
    };

    return JSON.stringify({
        "list": [vod]
    });
}

// 6. 播放直链输出解析（直链无需额外嗅探，直接交由播放器渲染）
function play(flag, id, flags) {
    return JSON.stringify({
        "parse": 0,
        "url": id,
        "header": rule.headers
    });
}

// 7. 搜索功能
function search(wd, quick) {
    var searchUrl = rule.host + '/s/' + encodeURIComponent(wd) + '.html';
    var html = request(searchUrl, { headers: rule.headers });
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
            var vod_id = linkMatch[1];
            var vod_name = titleMatch[1];
            var vod_pic = imgMatch ? imgMatch[1] : '';
            if (vod_pic.indexOf('//') === 0) {
                vod_pic = 'https:' + vod_pic;
            }
            var vod_remarks = remarksMatch ? remarksMatch[1] : '';

            list.push({
                "vod_id": vod_id,
                "vod_name": vod_name,
                "vod_pic": vod_pic,
                "vod_remarks": vod_remarks
            });
        }
    }

    return JSON.stringify({
        "list": list
    });
}
