import cheerio from 'assets://js/lib/cheerio.min.js';

let host = 'https://a123tv.com';
let headers = {
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
    'Referer': 'https://a123tv.com/'
};

async function request(reqUrl) {
    let res = await $fetch.get(reqUrl, { headers: headers });
    return res.data;
}

// 1. 初始化
async function init(cfg) {}

// 2. 首页分类
async function home(filter) {
    let classes = [
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
    let page = parseInt(pg) || 1;
    let targetUrl = page === 1 ? `${host}/t/${tid}.html` : `${host}/t/${tid}/p${page}.html`;
    let html = await request(targetUrl);
    
    let list = [];
    let itemRegex = /<div class="w4-item-wrap">([\s\S]*?)<\/div>\s*<\/div>/g;
    let match;

    while ((match = itemRegex.exec(html)) !== null) {
        let block = match[1];
        let linkMatch = block.match(/href="\/v\/([^"]+?)\.html"/);
        let imgMatch = block.match(/data-src="([^"]+?)"/);
        let titleMatch = block.match(/title="([^"]+?)"/);
        let remarksMatch = block.match(/<span>([^<]+?线路)<\/span>/);

        if (linkMatch && titleMatch) {
            let vod_pic = imgMatch ? imgMatch[1] : '';
            if (vod_pic.startsWith('//')) {
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

// 5. 详情页（解析 98 条 m3u8 线路）
async function detail(id) {
    let detailUrl = `${host}/v/${id}.html`;
    let html = await request(detailUrl);

    let titleMatch = html.match(/<li class="on"><h1>([^<]+?)<\/h1><\/li>/);
    let vod_name = titleMatch ? titleMatch[1] : id;

    let posterMatch = html.match(/data-poster="([^"]+?)"/);
    let vod_pic = posterMatch ? posterMatch[1] : '';
    if (vod_pic.startsWith('//')) {
        vod_pic = 'https:' + vod_pic;
    }

    let descMatch = html.match(/<meta name="description" content="([^"]+?)">/);
    let vod_content = descMatch ? descMatch[1] : '';

    let play_from = [];
    let play_url = [];

    // 正则提取 var pp 中的线路与直链
    let ppMatch = html.match(/var pp\s*=\s*(\{[\s\S]*?\});<\/script>/);
    if (ppMatch && ppMatch[1]) {
        try {
            let ppData = JSON.parse(ppMatch[1]);
            let lines = ppData.la;

            if (lines && lines.length > 0) {
                play_from.push("A123TV聚合");
                let episodes = [];
                for (let i = 0; i < lines.length; i++) {
                    let item = lines[i];
                    let lineName = item[1] || `线路${i + 1}`;
                    let m3u8Url = item[4];
                    if (m3u8Url) {
                        episodes.push(`${lineName}$${m3u8Url}`);
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
    let searchUrl = `${host}/s/${encodeURIComponent(wd)}.html`;
    let html = await request(searchUrl);
    let list = [];

    let itemRegex = /<div class="w4-item-wrap">([\s\S]*?)<\/div>\s*<\/div>/g;
    let match;

    while ((match = itemRegex.exec(html)) !== null) {
        let block = match[1];
        let linkMatch = block.match(/href="\/v\/([^"]+?)\.html"/);
        let imgMatch = block.match(/data-src="([^"]+?)"/);
        let titleMatch = block.match(/title="([^"]+?)"/);
        let remarksMatch = block.match(/<span>([^<]+?线路)<\/span>/);

        if (linkMatch && titleMatch) {
            let vod_pic = imgMatch ? imgMatch[1] : '';
            if (vod_pic.startsWith('//')) {
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

// 核心修正：导出 start() 函数，满足播放器环境校验
export function start() {
    return {
        init: init,
        home: home,
        homeVod: homeVod,
        category: category,
        detail: detail,
        play: play,
        search: search
    };
}

export default {
    init: init,
    home: home,
    homeVod: homeVod,
    category: category,
    detail: detail,
    play: play,
    search: search
};
