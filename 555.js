// 这是 555电影 的本地解析规则
var rule = {
    title: '555电影',
    host: 'https://www.555dy.net',
    url: '/vodtype/fyclass-fypage.html',
    searchUrl: '/vodsearch/**----------fypage---.html',
    searchable: 2,
    quickSearch: 0,
    headers: {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'
    },
    class_name: '电影&连续剧&动漫&综艺纪录&擦边短剧',
    class_url: '1&2&4&3&126',
    play_parse: true,
    lazy: '',
    limit: 6,
    // 以下是用 CSS 选择器告诉 APP 怎么提取网页里的图片、标题和链接
    推荐: '.module-items;.module-item;a&&title;img&&data-src;.module-item-text&&Text;a&&href',
    一级: '.module-items .module-item;a&&title;img&&data-src;.module-item-text&&Text;a&&href',
    二级: {
        "title": "h1&&Text",
        "img": ".module-item-pic img&&data-src",
        "desc": ".module-info-item:eq(3)&&Text",
        "content": ".module-info-item:eq(4)&&Text",
        "tabs": ".module-tab-item",
        "lists": ".module-play-list-content:eq(#id) a"
    },
    搜索: '.module-search-item;h3&&Text;img&&data-src;.video-serial&&Text;a&&href'
};
