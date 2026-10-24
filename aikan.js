var rule = {
    title: 'AIKAN影院',
    host: 'https://aikan.example.com', 
    url: '/index.php/vod/show/id/fyclass/page/fypage.html',
    searchUrl: '/index.php/vod/search/page/fypage/wd/**.html',
    searchable: 2,
    quickSearch: 0,
    class_parse: '.nav-menu li;a&&Text;a&&href;.*/(.*?).html',
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
