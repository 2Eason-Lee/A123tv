var rule = {
    title: 'A123TV_Static',
    host: 'https://fastly.jsdelivr.net/gh/2Eason-Lee/A123tv@main',
    homeUrl: '/vod.json',
    url: '/vod.json?cate=fyclass',
    searchUrl: '/vod.json?wd=**',
    searchable: 2,
    quickSearch: 0,
    class_name: '电影&连续剧&综艺&动漫',
    class_url: '10&11&12&13',
    推荐: `js:
        let res = request(HOST + '/vod.json');
        VODS = JSON.parse(res).list;
    `,
    一级: `js:
        let res = request(HOST + '/vod.json');
        let list = JSON.parse(res).list;
        let filtered = [];
        for(let i=0; i<list.length; i++){
            if(list[i].type_id.toString() === MY_CATE.toString()){
                filtered.push(list[i]);
            }
        }
        VODS = filtered;
    `,
    二级: `js:
        let res = request(HOST + '/vod.json');
        let list = JSON.parse(res).list;
        for(let i=0; i<list.length; i++){
            if(list[i].vod_id.toString() === fyId.toString()){
                VOD = list[i];
                break;
            }
        }
    `,
    搜索: `js:
        let res = request(HOST + '/vod.json');
        let list = JSON.parse(res).list;
        let filtered = [];
        for(let i=0; i<list.length; i++){
            if(list[i].vod_name.indexOf(KEY) !== -1){
                filtered.push(list[i]);
            }
        }
        VODS = filtered;
    `
};
