var rule = {
    title: 'A123TV',
    host: 'https://a123tv.com',
    // 列表分页地址规则
    url: '/t/fyclass/pfypage.html',
    // 搜索页地址规则
    searchUrl: '/s/**.html',
    searchable: 2,
    quickSearch: 0,
    filterable: 0,
    class_name: '电影&连续剧&综艺&动漫',
    class_url: '10&11&12&13',
    // 伪装标准桌面浏览器请求头，规避反爬检测与403拦截
    headers: {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Referer': 'https://a123tv.com/'
    },
    // 一级列表与搜索页面解析规则
    // 截取元素：卡片容器; 影片标题; 海报地址; 线路/清晰度备注; 详情页链接
    一级: '.w4-item; .t&&title; .w4-item-cover img&&data-src; .w4-item-info .i&&Text; a&&href',
    
    // 二级详情页解析与多线路 m3u8 直链提取
    二级: {
        title: 'h1&&Text',
        img: '.w4-player&&data-poster',
        desc: '.w4-meta&&Text',
        content: 'meta[name="description"]&&content',
        tabs: 'js:TABS=["全部线路"]',
        lists: `js:
            let html = request(input);
            let match = html.match(/var pp=(.*?);<\\/script>/);
            if (match && match[1]) {
                try {
                    let ppData = JSON.parse(match[1]);
                    let lines = ppData.la; 
                    let playUrls = [];
                    // 遍历网页中的 la 线路数据，拼接成 "线路名称$播放直链"
                    lines.forEach(function(line) {
                        let lineName = line[1]; 
                        let m3u8Url = line[4];  
                        if (m3u8Url) {
                            playUrls.push(lineName + '$' + m3u8Url);
                        }
                    });
                    // 输出所有可用线路供播放器直链秒播
                    LISTS = [playUrls.join('#')];
                } catch (e) {
                    LISTS = [];
                }
            } else {
                LISTS = [];
            }
        `
    },
    // 搜索结果直接复用一级的提取规则
    搜索: '*'
};
