var rule = {
    title: 'AIKAN影院',
    host: 'https://www.aikanbot.vip', 
    url: '/vodshow/fyclass--------fypage---.html',
    searchUrl: '/vodsearch/**----------fypage---.html',
    searchable: 2,
    quickSearch: 0,
    headers: {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'
    },
    class_name: '电影&连续剧&综艺&动漫',
    class_url: '1&2&3&4',
    play_parse: true,
    lazy: '',
    limit: 6,
    推荐: '.stui-vodlist;li;a&&title;a&&data-original;.pic-text&&Text;a&&href',
    一级: '.stui-vodlist li;a&&title;a&&data-original;.pic-text&&Text;a&&href',
    二级: {
        "title": "h1&&Text",
        "img": ".picture img&&data-original",
        "desc": ".data:eq(0)&&Text",
        "content": ".detail-content&&Text",
        "tabs": ".nav-tabs li",
        "lists": ".stui-content__playlist:eq(#id) li"
    },
    搜索: '.stui-vodlist__media li;a&&title;a&&data-original;.pic-text&&Text;a&&href'
};
