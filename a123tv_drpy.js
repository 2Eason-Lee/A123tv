var rule = {
    title: 'A123TV',
    host: 'https://a123tv.com',
    url: '/t/fyclass/pfypage.html',
    searchUrl: '/s/**.html',
    searchable: 2,
    quickSearch: 0,
    class_name: '电影&连续剧&综艺&动漫',
    class_url: '10&11&12&13',
    headers: {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
        'Referer': 'https://a123tv.com/'
    },
    一级: '.w4-item; .t&&title; .w4-item-cover img&&data-src; .w4-item-info .i&&Text; a&&href',
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
                    lines.forEach(function(line) {
                        let lineName = line[1]; 
                        let m3u8Url = line[4];  
                        playUrls.push(lineName + '$' + m3u8Url);
                    });
                    LISTS = [playUrls.join('#')];
                } catch (e) {
                    LISTS = [];
                }
            } else {
                LISTS = [];
            }
        `
    },
    搜索: '*'
};
