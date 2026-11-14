import re
import requests
import logging
from collections import OrderedDict
from datetime import datetime
import gzip
import io
import os
import xml.etree.ElementTree as ET

# ===================== 手动主映射【央视固定，EPG不会覆盖】 =====================
MANUAL_TVG_MAP = {
    "CCTV1":    "1",
    "CCTV2":    "2",
    "CCTV3":    "3",
    "CCTV4":    "CCTV4",
    "CCTV5":    "5",
    "CCTV6":    "7",
    "CCTV7":    "8",
    "CCTV8":    "CCTV8",
    "CCTV9":    "10",
    "CCTV10":   "11",
    "CCTV11":   "12",
    "CCTV12":   "13",
    "CCTV13":   "14",
    "CCTV14":   "CCTV14",
    "CCTV15":   "16",
    "CCTV16":   "17",
    "CCTV17":   "18",
    "CCTV4K":   "19",
    "CCTV5+":   "6",
    "CCTV8K":   "20",
    "浙江钱江都市":   "172",
    "北京淘电影":   "114",
    "北京淘剧场":   "112",
    "北京淘娱乐":   "113",
    "北京淘Baby":   "111",
}
CCTV_SET = set(MANUAL_TVG_MAP.keys())

# ===================== EPG配置，只用kuke31源 =====================
EPG_URLS = [
    "https://raw.githubusercontent.com/kuke31/xmlgz/main/all.xml.gz",
    "https://epg.112114.xyz/pp.xml",
    "http://epg.51zmt.top:8000/e.xml.gz",
]

# ===================== 环境变量读取M3U_URL_LIST secret =====================
source_url_env = os.getenv("M3U_URL_LIST", "")
source_urls = [u.strip() for u in source_url_env.splitlines() if u.strip()]

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

def clean_channel_name(name):
    return re.sub(r"[-_\s高清|超清|HD|4K|标清]", "", name).strip().upper()

def load_epg_tvg_map(epg_url):
    logging.info(f"尝试加载EPG：{epg_url}")
    try:
        resp = requests.get(epg_url, timeout=30)
        resp.raise_for_status()
        raw_data = resp.content

        # 自动识别gz压缩包
        if raw_data[:2] == b'\x1f\x8b':
            with gzip.GzipFile(fileobj=io.BytesIO(raw_data)) as gz:
                xml_bytes = gz.read()
        else:
            xml_bytes = raw_data

        xml_str = xml_bytes.decode("utf-8", errors="ignore")
        # 清除xml命名空间前缀
        xml_str = re.sub(r'xmlns[^"]*"[^"]*"', "", xml_str)
        xml_str = re.sub(r'\w+:(\w+)', r'\1', xml_str)
        root = ET.fromstring(xml_str)

        epg_backup_map = {}
        for channel in root.findall("channel"):
            tvg_id = channel.get("id")
            if not tvg_id:
                continue
            dn_nodes = channel.findall("display-name")
            for dn_node in dn_nodes:
                if dn_node is None or not dn_node.text:
                    continue
                name = dn_node.text.strip()
                clean_name = clean_channel_name(name)
                # 央视全部跳过，不读入备份映射，防止错误别名污染
                if clean_name in CCTV_SET:
                    continue
                epg_backup_map[clean_name] = tvg_id

        logging.info(f"✅ EPG加载完成，非央视备用映射数量：{len(epg_backup_map)}")
        return epg_backup_map
    except Exception as e:
        logging.error(f"❌ EPG加载失败: {e}")
        return {}

def load_epg_with_fallback(epg_url_list):
    total_backup_map = {}
    for url in epg_url_list:
        tmp = load_epg_tvg_map(url)
        if tmp:
            for k, v in tmp.items():
                if k not in total_backup_map:
                    total_backup_map[k] = v
    if len(total_backup_map) == 0:
        logging.warning("EPG备用映射为空，非央视频道无法匹配tvg‑id")
    return total_backup_map

epg_backup_mapping = load_epg_with_fallback(EPG_URLS)

def get_tvgid_by_name(channel_name):
    clean_name = clean_channel_name(channel_name)
    # 优先手动央视映射
    if clean_name in MANUAL_TVG_MAP:
        return MANUAL_TVG_MAP[clean_name]
    # 其他频道使用epg备份映射
    return epg_backup_mapping.get(clean_name, "")

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

    with open("zubo.m3u", "w", encoding="utf-8") as f_m3u:
        f_m3u.write(f"""#EXTM3U x-tvg-url={",".join(f'"{epg_url}"' for epg_url in config["epg_urls"])}\n""")
        with open("zubo.txt", "w", encoding="utf-8") as f_txt:
            for group in config["announcements"]:
                f_txt.write(f"{group['channel']},#genre#\n")
                for announcement in group['entries']:
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
                            # ==========重点：同频道所有线路，tvg-id完全不变，序号只加到url后缀，不碰tvg-id==========
                            real_tvgid = get_tvgid_by_name(channel_name)
                            for index, url in enumerate(filtered_urls, start=1):
                               # if is_ipv6(url):
                               #     url_suffix = f"$LR•IPV6" if total_urls == 1 else f"$LR•IPV6『线路{index}』"
                               # else:
                               #     url_suffix = f"" if total_urls == 1 else f"$『线路{index}』"
                                url_suffix = ""
                                if '$' in url:
                                    base_url = url.split('$', 1)[0]
                                else:
                                    base_url = url
                                new_url = f"{base_url}{url_suffix}"
                                # 这里 real_tvgid 在循环外一次性获取！！所有线路共用同一个tvg-id
                                f_m3u.write(f"#EXTINF:-1 tvg-id=\"{real_tvgid}\" tvg-name=\"{channel_name}\" tvg-logo=\"https://proxy.lalifeier.eu.org/https://raw.githubusercontent.com/zjyktcyfy/zj-fy/main/tv/{channel_name}.png\" group-title=\"{category}\",{channel_name}\n")
                                f_m3u.write(new_url + "\n")
                                f_txt.write(f"{channel_name},{new_url}\n")
            f_txt.write("\n")

if __name__ == "__main__":
    template_file = "demo.txt"
    channels, template_channels = filter_source_urls(template_file)
    updateChannelUrlsM3U(channels, template_channels)
