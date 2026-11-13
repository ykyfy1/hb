import os
# 从Github Secrets的M3U_URL_LIST读取远端m3u链接
source_urls = [line.strip() for line in os.getenv("M3U_URL_LIST","").splitlines() if line.strip()]

# EPG地址，自行修改
epg_urls = [
    "https://proxy.lalifeier.eu.org/https://raw.githubusercontent.com/zjyktcyfy/j-m-d/refs/heads/main/JMD.xml"
]

# IP版本优先级 ipv6 / ipv4
ip_version_priority = "ipv6"

# URL黑名单，包含下面字符直接过滤
url_blacklist = []

# 公告栏
announcements = [
    {
        "channel": "公告",
        "entries": [ {"name": "直播源均来自网络，不得商用，仅供学习交流使用。", "url": "http://ali-xwl.cztv.com/live/channel061080Plxw.m3u8", "logo": "https://proxy.lalifeier.eu.org/https://raw.githubusercontent.com/zjyktcyfy/zj-fy/main/tv/武术台.png"},
            {"name": "更新日期", "url": "http://ali-xwl.cztv.com/live/channel061080Plxw.m3u8", "logo": "https://proxy.lalifeier.eu.org/https://raw.githubusercontent.com/zjyktcyfy/zj-fy/main/tv/武术台.png"},
            {"name": None, "url": "https://live-auth.51kandianshi.com/szgd/csztv4.m3u8", "logo": "https://proxy.lalifeier.eu.org/https://raw.githubusercontent.com/zjyktcyfy/zj-fy/main/tv/武术台.png"},
            {
                "name": None,
                "logo": "",
                "url": ""
            }
        ]
    }
]
