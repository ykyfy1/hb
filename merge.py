import re
import requests
import logging
from collections import OrderedDict
from datetime import datetime
import gzip
import io
import os

# ===================== EPG配置 =====================
EPG_GZ_URL = "https://raw.githubusercontent.com/kuke31/xmlgz/main/all.xml.gz"
EPG_URLS = [EPG_GZ_URL]

# ===================== 从环境变量读取源链接M3U_URL_LIST，兼容Github Secret =====================
source_url_env = os.getenv("M3U_URL_LIST", "")
source_urls = [u.strip() for u in source_url_env.splitlines() if u.strip()]

# 模拟原来config，优先使用环境变量里的链接
config = {
    "source_urls": source_urls,
    "epg_urls": EPG_URLS,
    "ip_version_priority": "ipv6",
    "url_blacklist": [],
    "announcements": [
        {
            "channel": "公告",
            "entries": [
                {
                    "name": None,
                    "logo": "",
                    "url": ""
                }
            ]
        }
    ]
}
# ==============================================================================

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[logging.FileHandler("function.log", "w", encoding="utf-8"), logging.StreamHandler()])

def load_epg_tvg_map(epg_gz_url):
    """下载gz压缩EPG，构建 清理后的频道名 -> tvg-id 映射"""
    logging.info(f"开始加载EPG：{epg_gz_url}")
    try:
        resp = requests.get(epg_gz_url, timeout=30)
        resp.raise_for_status()
        with gzip.GzipFile(fileobj=io.BytesIO(resp.content)) as gz:
            xml = gz.read().decode("utf-8")
        tvg_map = {}
        pattern = re.compile(r'<channel id="([^"]+)".*?<display-name>([^<]+)</display-name>', re.S)
        for tvg_id, name in pattern.findall(xml):
            # 名称清洗：去除符号、高清，同时去掉横杠，兼容CCTV1 / CCTV-1
            clean_name = re.sub(r"[-_\s高清|超清|HD|4K|标清]", "", name).strip().upper()
            tvg_map[clean_name] = tvg_id
        logging.info(f"EPG加载完成，共读取 {len(tvg_map)} 个tvg-id")
        return tvg_map
    except Exception as e:
        logging.error(f"EPG下载失败: {e}")
        return {}

# 全局加载一次EPG映射
tvg_mapping = load_epg_tvg_map(EPG_GZ_URL)

def get_tvgid_by_name(channel_name):
    """根据频道名获取tvg-id，找不到返回空字符串，兼容CCTV-1/CCTV1"""
    clean_name = re.sub(r"[-_\s高清|超清|HD|4K|标清]", "", channel_name).strip().upper()
    return tvg_mapping.get(clean_name, "")

def parse_template(template_file):
    template_channels = OrderedDict()
    current_category = None

    with open(template_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                if "#genre#" in line:
                    current_category = line.split(",")[0].strip()
                    template_channels[current_category] = []
                elif current_category:
                    channel_name = line.split(",")[0].strip()
                    template_channels[current_category].append(channel_name)

    return template_channels

def fetch_channels(url):
    channels = OrderedDict()

    try:
        response = requests.get(url)
        response.raise_for_status()
        response.encoding = 'utf-8'
        lines = response.text.split("\n")
        current_category = None
        is_m3u = any("#EXTINF" in line for line in lines[:15])
        source_type = "m3u" if is_m3u else "txt"
        logging.info(f"url: {url} 获取成功，判断为{source_type}格式")

        if is_m3u:
            for line in lines:
                line = line.strip()
                if line.startswith("#EXTINF"):
                    match = re.search(r'group-title="(.*?)",(.*)', line)
                    if match:
                        current_category = match.group(1).strip()
                        channel_name = match.group(2).strip()
                        if current_category not in channels:
                            channels[current_category] = []
                elif line and not line.startswith("#"):
                    channel_url = line.strip()
                    if current_category and channel_name:
                        channels[current_category].append((channel_name, channel_url))
        else:
            for line in lines:
                line = line.strip()
                if "#genre#" in line:
                    current_category = line.split(",")[0].strip()
                    channels[current_category] = []
                elif current_category:
                    match = re.match(r"^(.*?),(.*?)$", line)
                    if match:
                        channel_name = match.group(1).strip()
                        channel_url = match.group(2).strip()
                        channels[current_category].append((channel_name, channel_url))
                    elif line:
                        channels[current_category].append((line, ''))
        if channels:
            categories = ", ".join(channels.keys())
            logging.info(f"url: {url} 爬取成功✅，包含频道分类: {categories}")
    except requests.RequestException as e:
        logging.error(f"url: {url} 爬取失败❌, Error: {e}")

    return channels

def match_channels(template_channels, all_channels):
    matched_channels = OrderedDict()

    for category, channel_list in template_channels.items():
        matched_channels[category] = OrderedDict()
        for channel_name in channel_list:
            for online_category, online_channel_list in all_channels.items():
                for online_channel_name, online_channel_url in online_channel_list:
                    if channel_name == online_channel_name:
                        matched_channels[category].setdefault(channel_name, []).append(online_channel_url)

    return matched_channels

def filter_source_urls(template_file):
    template_channels = parse_template(template_file)
    source_urls = config["source_urls"]
    logging.info(f"读取到源链接数量：{len(source_urls)}")

    all_channels = OrderedDict()
    for url in source_urls:
        fetched_channels = fetch_channels(url)
        for category, channel_list in fetched_channels.items():
            if category in all_channels:
                all_channels[category].extend(channel_list)
            else:
                all_channels[category] = channel_list

    matched_channels = match_channels(template_channels, all_channels)

    return matched_channels, template_channels

def is_ipv6(url):
    return re.match(r'^http:\/\/\[[0-9a-fA-F:]+\]', url) is not None

def updateChannelUrlsM3U(channels, template_channels):
    written_urls = set()

    current_date = datetime.now().strftime("%Y-%m-%d")
    for group in config["announcements"]:
        for announcement in group['entries']:
            if announcement['name'] is None:
                announcement['name'] = current_date

    # 修改输出文件名 zubo.m3u / zubo.txt
    with open("zubo.m3u", "w", encoding="utf-8") as f_m3u:
        f_m3u.write(f"""#EXTM3U x-tvg-url={",".join(f'"{epg_url}"' for epg_url in config["epg_urls"])}\n""")

        with open("zubo.txt", "w", encoding="utf-8") as f_txt:
            for group in config["announcements"]:
                f_txt.write(f"{group['channel']},#genre#\n")
                for announcement in group['entries']:
                    # 公告频道也尝试匹配tvg-id
                    ann_tvgid = get_tvgid_by_name(announcement['name'])
                    f_m3u.write(f"""#EXTINF:-1 tvg-id="{ann_tvgid}" tvg-name="{announcement['name']}" tvg-logo="{announcement['logo']}" group-title="{group['channel']}",{announcement['name']}\n""")
                    f_m3u.write(f"{announcement['url']}\n")
                    f_txt.write(f"{announcement['name']},{announcement['url']}\n")

            for category, channel_list in template_channels.items():
                f_txt.write(f"{category},#genre#\n")
                if category in channels:
                    for channel_name in channel_list:
                        if channel_name in channels[category]:
                            sorted_urls = sorted(channels[category][channel_name], key=lambda url: not is_ipv6(url) if config["ip_version_priority"] == "ipv6" else is_ipv6(url))
                            filtered_urls = []
                            for url in sorted_urls:
                                if url and url not in written_urls and not any(blacklist in url for blacklist in config["url_blacklist"]):
                                    filtered_urls.append(url)
                                    written_urls.add(url)

                            total_urls = len(filtered_urls)
                            for index, url in enumerate(filtered_urls, start=1):
                                if is_ipv6(url):
                                    url_suffix = f"$LR•IPV6" if total_urls == 1 else f"$LR•IPV6『线路{index}』"
                                else:
                                    url_suffix = f"" if total_urls == 1 else f""
                                if '$' in url:
                                    base_url = url.split('$', 1)[0]
                                else:
                                    base_url = url

                                new_url = f"{base_url}{url_suffix}"
                                # 获取真实EPG ID
                                real_tvgid = get_tvgid_by_name(channel_name)
                                f_m3u.write(f"#EXTINF:-1 tvg-id=\"{real_tvgid}\" tvg-name=\"{channel_name}\" tvg-logo=\"https://proxy.lalifeier.eu.org/https://raw.githubusercontent.com/zjyktcyfy/zj-fy/main/tv/{channel_name}.png\" group-title=\"{category}\",{channel_name}\n")
                                f_m3u.write(new_url + "\n")
                                f_txt.write(f"{channel_name},{new_url}\n")

            f_txt.write("\n")

if __name__ == "__main__":
    template_file = "demo.txt"
    channels, template_channels = filter_source_urls(template_file)
    updateChannelUrlsM3U(channels, template_channels)
