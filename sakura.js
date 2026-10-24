var rule = {
    title: '樱花影院',
    host: 'https://www.dcjyb.com',
    url: '/vodtype/fyclass-fypage.html',
    searchUrl: '/vodsearch/**----------fypage---.html',
    searchable: 2,
    quickSearch: 0,
    headers: {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'
    },
    class_name: '电影&连续剧&综艺节目&短剧&动漫',
    class_url: '20&35&43&55&48',
    play_parse: true,
    lazy: '',
    limit: 6,
    推荐: '.hl-vod-list;li;a&&title;img&&data-original;.remarks&&Text;a&&href',
    一级: '.hl-vod-list li;a&&title;img&&data-original;.remarks&&Text;a&&href',
    二级: {
        "title": "h2&&Text",
        "img": ".hl-item-thumb&&data-original",
        "desc": ".hl-infos-content&&Text",
        "content": ".hl-infos-content&&Text",
        "tabs": ".hl-plays-from a",
        "lists": ".hl-plays-list:eq(#id) li"
    },
    搜索: '.hl-vod-list li;a&&title;img&&data-original;.remarks&&Text;a&&href'
};
