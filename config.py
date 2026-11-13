import os
import re
import requests

# ========== 配置区 ==========
source_urls = [line.strip() for line in os.getenv("M3U_URL_LIST","").splitlines() if line.strip()]
epg_source_xml_url = "https://epg.112114.xyz/pp.xml"
output_m3u = "final.m3u"
demo_file = "demo.txt"  # 排序参考文件

ip_version_priority = "ipv6"
url_blacklist = []

announcements = [
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
# ============================

def clean_channel_name(raw_name: str) -> str:
    """频道名称清洗，用于模糊匹配"""
    raw_name = re.sub(r"(高清|超清|HD|4K|蓝光|标清|综合|频道)", "", raw_name, flags=re.IGNORECASE)
    raw_name = re.sub(r"[-_\s]", "", raw_name)
    return raw_name.upper().strip()

def load_demo_order(demo_path):
    """加载demo.txt，生成 清洗名称 -> 排序序号"""
    order_map = {}
    if os.path.exists(demo_path):
        with open(demo_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        for idx, name in enumerate(lines):
            key = clean_channel_name(name)
            order_map[key] = idx
        print(f"✅ 加载demo排序文件成功，共 {len(order_map)} 个预设频道")
    else:
        print(f"⚠️ 未找到 {demo_file}，将使用默认字母排序")
    return order_map

def build_epg_id_map(xml_url: str):
    print(f"正在拉取EPG源: {xml_url}")
    resp = requests.get(xml_url, timeout=30)
    xml_txt = resp.text
    name2id = {}
    pattern = re.compile(r'<channel id="([^"]+)".*?<display-name[^>]*>([^<]+)</display-name>', re.S)
    for ch_id, disp_name in pattern.findall(xml_txt):
        clean_key = clean_channel_name(disp_name.strip())
        name2id[clean_key] = ch_id
    print(f"✅ EPG频道映射加载完成，总频道数: {len(name2id)}")
    return name2id

def fetch_remote_m3u(url: str):
    print(f"拉取远端M3U: {url}")
    r = requests.get(url, timeout=30)
    return r.text

def parse_m3u_to_entries(m3u_text: str, name2id_map: dict):
    lines = m3u_text.splitlines()
    entries = []
    extinf_line = None
    for line in lines:
        line_strip = line.strip()
        if line_strip.startswith("#EXTINF"):
            extinf_line = line
        elif extinf_line and line_strip and not line_strip.startswith("#"):
            url_line = line_strip
            info_part, ch_name = extinf_line.split(",", 1)
            ch_name = ch_name.strip()
            key = clean_channel_name(ch_name)
            matched_id = name2id_map.get(key)

            info_part = re.sub(r'tvg-id="[^"]+"', "", info_part)
            info_part = re.sub(r'\s+', " ", info_part).strip()
            if matched_id:
                info_part += f' tvg-id="{matched_id}"'

            new_extinf = f"{info_part},{ch_name}"
            entries.append({
                "key": key,
                "name": ch_name,
                "extinf": new_extinf,
                "url": url_line
            })
            extinf_line = None
    return entries


if __name__ == "__main__":
    # 加载demo排序表
    demo_order_map = load_demo_order(demo_file)
    epg_name_id_map = build_epg_id_map(epg_source_xml_url)

    all_entries = []
    for m3u_url in source_urls:
        raw_m3u = fetch_remote_m3u(m3u_url)
        items = parse_m3u_to_entries(raw_m3u, epg_name_id_map)
        all_entries.extend(items)

    # 按清洗后的频道名分组，同频道全部线路放一组
    groups = {}
    for item in all_entries:
        if item["key"] not in groups:
            groups[item["key"]] = []
        groups[item["key"]].append(item)

    # 排序规则：demo.txt内频道按demo里顺序；不在demo的频道全部放末尾
    def sort_by_demo(group_key):
        if group_key in demo_order_map:
            return (0, demo_order_map[group_key])
        else:
            # demo不存在的频道，放到最后，按频道名字母排序
            return (1, group_key)

    sorted_group_keys = sorted(groups.keys(), key=sort_by_demo)

    # 组装最终m3u
    final_text = f'#EXTM3U x-tvg-url="{epg_source_xml_url}"\n'
    for gkey in sorted_group_keys:
        for entry in groups[gkey]:
            final_text += entry["extinf"] + "\n"
            final_text += entry["url"] + "\n"

    with open(output_m3u, "w", encoding="utf-8") as f:
        f.write(final_text)

    print(f"\n🎉 处理完成，输出文件: {output_m3u}")
    print("✅ 优先按demo.txt顺序排列频道，demo内同频道多线路聚合在一起，自动匹配tvg-id")
    print("⚠️ demo不存在的频道全部排在末尾；名称无法匹配的频道不会添加tvg-id")
