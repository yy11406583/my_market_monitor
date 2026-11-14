import yfinance as yf
import requests
import os
import re
import time
import json
import math
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from bs4 import BeautifulSoup
import urllib.parse
from difflib import SequenceMatcher
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

# ==================== 1. 配置区 ====================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
HISTORY_FILE = "sent_news.txt"
LINK_HISTORY_FILE = "sent_links.txt"
RTHK_HISTORY_FILE = "sent_rthk_links.txt"
ETF_CACHE_FILE = "etf_data_cache.json"
MAX_HISTORY_DAYS = 7

RTHK_RSS_URL = "https://news.rthk.hk/rthk/ch/rss/local.xml"

# 已移除匯豐、建行、微軟；加入 3145
WATCHLIST = {
    "3466.HK": "3466",
    "3145.HK": "3145",
    "VOO": "VOO",
    "QQQ": "QQQ",
    "TSLA": "Tesla",
}

# ETF 相关新闻关键词
ETF_NEWS_KEYWORDS = ["3466", "3145", "恒生高息股", "華夏亞洲高息", "恒生高股息"]
ETF_SPECIAL_KEYWORDS = ["成份股", "管理費", "派息", "股息", "分派", "指數調整", "經理費", "託管費"]

URGENT_KEYWORDS = [
    "水警", "命案", "劫案", "走私", "開火", "拘捕", "偵破", "不治", "通緝",
    "警署", "警員", "警方", "警察", "警拘", "警搗", "警破", "警逮", "被捕",
    "虐畜", "殘酷對待", "偷渡", "非法入境", "黑工", "偽鈔", "偷竊", "行劫",
    "太空油", "依托咪酯", "電子煙", "煙彈", "毒品", "冰毒", "海洛英", "可卡因", "大麻", "K仔",
    "傷人", "施襲", "打跤", "爭執", "持械", "Traffic Day", "交通日", "非法改裝", "醉駕", "毒駕",
    "爆竊", "盜竊", "扒竊", "搶手袋", "劫的", "車內盜竊",
    "斬人", "淋紅油", "刑毀", "毆打", "非禮", "強姦", "虐兒",
    "洗黑錢", "詐騙", "電騙", "騙案", "收數", "非法收債",
    "截查", "反黑", "放蛇", "搜獲", "檢獲", "搗破", "掃黃", "掃毒",
    "危駕", "拒捕", "衝燈", "非法賽車", "瘋狂駕駛", "超速",
    "非法勞工", "人蛇", "假結婚",
    "拘控", "還押",
    "命危", "墮樓", "浮屍", "跳海", "墮海", "遇溺", "火警", "縱火",
    "無牌", "違例", "票控", "高空墮物"
]

NOISE_EXCLUDE = ["年報", "招募", "推廣", "App", "課程", "演習", "比賽", "典禮", "講座", "展覽", "慶祝",
                 "心得", "分享", "投考", "委任", "晉升", "地產", "就職", "儀式",
                 "警察隊員佐級協會", "警察儲蓄互助社", "遮仔會"]

HARD_ACTIONS = ["走私", "截獲", "拘捕", "偵破", "跳海", "墮海", "遇溺", "漂浮", "浮屍", "救起", "開火", "封鎖", "扣押", "通緝", "命案", "車禍", "昏迷", "不治", "搜獲", "檢獲", "搗破", "淋紅油", "爆竊"]
POLICE_KEYWORDS = ["水警", "警方", "警察", "警員", "警署", "警拘", "交通部", "重案組", "反黑組"]
HK_MEDIA_DOMAINS = ["hk01.com", "news.mingpao.com", "scmp.com", "stheadline.com", "orientaldaily.on.cc", "hket.com", "news.tvb.com", "now.com", "rthk.hk"]
GLOBAL_EXCLUDE = ["澳門", "澳门", "台灣", "台湾", "日本", "美國", "英國", "加拿大", "澳洲", "新加坡", "泰國", "越南", "菲律賓"]

HK_STRONG_INDICATORS = [
    "香港", "尖沙咀", "尖東", "維港", "維多利亞港", "星光大道", "文化中心", "海港城", "天星碼頭",
    "西九", "西九文化區", "中環碼頭", "灣仔碼頭", "北角碼頭", "西環碼頭", "觀塘海濱", "蝴蝶灣",
    "石澳", "淺水灣", "赤柱", "青馬大橋", "汀九橋", "昂船洲大橋", "汲水門大橋", "將軍澳跨灣大橋",
    "深港西部通道", "港珠澳大橋", "汀九", "青馬", "青衣", "藍田", "馬鞍山", "大埔", "太和", "粉嶺",
    "上水", "元朗", "天水圍", "屯門", "荃灣", "葵涌", "葵芳", "東涌", "欣澳", "荔景", "南昌", "奧運",
    "九龍灣", "牛頭角", "黃埔", "何文田", "紅磡", "土瓜灣", "九龍塘", "樂富", "慈雲山", "彩虹", "鑽石山",
    "新蒲崗", "秀茂坪", "順利", "寶琳", "坑口", "調景嶺", "康城", "烏溪沙", "火炭", "大學", "科學園",
    "白石角", "錦上路", "八鄉", "洪水橋", "藍地", "掃管笏", "小欖", "大欖", "深井", "青龍頭", "油麻地",
    "佐敦", "太子", "大角咀", "長沙灣", "荔枝角", "美孚", "白虎山", "香園圍", "瓦窰", "松園下", "伯公坳",
    "沙頭角", "塘肚村", "山咀", "白石凹", "落馬洲", "大埔田", "山雞乙", "打鼓嶺", "梧桐山", "料壆",
    "蓮麻坑", "羅湖", "沙嶺", "較寮村", "簡頭圍", "鳳園", "信義新村", "老鼠嶺", "木湖", "石湖圍", "梅子林",
    "蛤塘", "馬草壟", "禾徑山", "白鶴洲", "蠔殼山", "鰲磡石", "下白泥", "上白泥", "白泥", "流浮山", "尖鼻咀",
    "龍鼓灘", "大蛇灣", "淡水灣", "大萬丈布", "長咀", "灣仔半島", "大灘", "深涌", "荔枝莊", "白沙洲",
    "罾棚角咀", "娥眉洲", "往灣洲", "破邊洲", "神仙井", "大浪頭", "蛇尖", "東灣山", "蚺蛇尖", "響螺角",
    "企嶺下海", "烏頭", "井頭", "大王爺頭", "黃石碼頭", "大癩痢", "小癩痢", "白沙澳", "下洋", "東平洲",
    "斬頸洲", "磨筆頭", "赤洲", "長沙排", "深灣", "蛇徑", "赤徑", "火石洲", "果洲群島", "米粉頂", "短咀",
    "蚺蛇灣", "白臘仔", "木棉洞", "鎖羅盆", "谷埔", "鳳坑", "大鵬灣", "黃茅洲", "大浪灣", "石壁", "牛牯塱",
    "大蠔灣", "下尾灣", "南丫島", "頭顱洲", "索罟群島", "草灣", "花坪", "籮箕灣", "水口", "老虎頭", "望東灣",
    "昂坪", "彌勒山", "長索", "陰澳", "大鴉洲", "小鴉洲", "石山", "圓角", "二澳", "狗嶺涌", "芝麻灣", "拾塱",
    "大浪村", "望渡坳", "煎魚灣", "萬丈布", "大小磨刀", "樟木頭", "圓洲", "深屈灣", "沙螺灣", "分流", "澄碧邨",
    "交椅洲", "小交椅洲", "周公島", "大澳", "坪洲", "長洲", "梅窩", "佛堂門", "東龍洲", "清水灣", "小蠔灣",
    "藍地石礦場", "醉酒灣", "貨櫃碼頭", "將軍澳", "工業邨", "大赤沙", "魔鬼山", "油塘", "三家村", "曾咀",
    "西草灣", "寮肚", "油柑頭", "第38區", "第40區", "避風塘", "貨物裝卸區"
]

# ==================== 2. 辅助功能 ====================

def normalize_title(title):
    title = re.sub(r"【.*?】|（.*?）", "", title)
    return re.sub(r"[^\u4e00-\u9fa5]+", "", title).strip().lower()

def is_duplicate_ai(new_title, pool):
    new_norm = normalize_title(new_title)
    if not new_norm: return False
    for old in pool:
        old_norm = normalize_title(old)
        if new_norm[:10] == old_norm[:10] or SequenceMatcher(None, new_norm, old_norm).ratio() > 0.65:
            return True
    return False

def get_map_url(title):
    for place in HK_STRONG_INDICATORS:
        if place in title and len(place) > 1:
            query = urllib.parse.quote(f"香港 {place}")
            return f"\n📍 <a href='https://www.google.com/maps/search/{query}'>查看地點: {place}</a>"
    return ""

def get_kdj_data(ticker, interval):
    try:
        df = yf.Ticker(ticker).history(period="2y", interval=interval)
        if df.empty or len(df) < 9: return 50.0
        df['Low'] = df['Low'].ffill().bfill()
        df['High'] = df['High'].ffill().bfill()
        df['Close'] = df['Close'].ffill().bfill()
        low, high = df['Low'].rolling(9).min(), df['High'].rolling(9).max()
        denom = (high - low).replace(0, 1)
        rsv = (df['Close'] - low) / denom * 100
        rsv = rsv.ffill().bfill().fillna(50.0)
        k = rsv.ewm(com=2, adjust=False).mean()
        val = k.iloc[-1]
        return 50.0 if math.isnan(val) else val
    except:
        return 50.0

def is_old_news_url(url):
    hk_now = datetime.now(timezone(timedelta(hours=8)))
    current_year = str(hk_now.year)
    current_month_2d = f"{hk_now.month:02d}"
    date_blocks = re.findall(r'\d{4,8}', url)
    for block in date_blocks:
        if len(block) == 4:
            if block != current_year and block in ["2022", "2023", "2024", "2025"]:
                return True
        elif len(block) >= 6:
            if block.startswith(("2022", "2023", "2024", "2025")):
                return True
            if block.startswith(current_year):
                month_part = block[4:6]
                if month_part.isdigit() and month_part != current_month_2d and month_part < current_month_2d:
                    return True
    slash_date = re.search(r'/(\d{4})-(\d{2})-\d{2}/', url)
    if slash_date:
        yr, mo = slash_date.group(1), slash_date.group(2)
        if yr != current_year or mo != current_month_2d:
            return True
    return False

def is_old_html_content(url):
    try:
        res = requests.get(url, timeout=4, headers={"User-Agent": "Mozilla/5.0"})
        if res.status_code != 200: return False
        soup = BeautifulSoup(res.content, 'html.parser')
        hk_now = datetime.now(timezone(timedelta(hours=8)))
        current_year = str(hk_now.year)
        current_month_2d = f"{hk_now.month:02d}"
        meta_tags = ["article:published_time", "published_time", "og:published_time", "release_date", "meta_publish_date"]
        for tag in meta_tags:
            meta = soup.find("meta", property=tag) or soup.find("meta", attrs={"name": tag})
            if meta and meta.get("content"):
                content = meta["content"]
                date_match = re.search(r'(\d{4})[-/](\d{2})[-/]\d{2}', content)
                if date_match:
                    yr, mo = date_match.group(1), date_match.group(2)
                    if yr != current_year or mo != current_month_2d: return True
                    return False
        tvb_time = soup.find(class_=re.compile("time|date|publish", re.I))
        if tvb_time:
            text = tvb_time.text.strip()
            date_match = re.search(r'(\d{4})[-/年](\d{1,2})[-/月]', text)
            if date_match:
                yr = date_match.group(1)
                mo = f"{int(date_match.group(2)):02d}"
                if yr != current_year or mo != current_month_2d: return True
    except:
        pass
    return False

def check_single_item(item, title_history, cur_t_list, link_history, mode, hk_now):
    try:
        title = item.title.text.split(' - ')[0].strip()
        link = item.link.text
        actual_url = link
        if "articles/" in link:
            try:
                actual_url = requests.head(link, timeout=1.5).headers.get('Location', link)
            except: pass
        if actual_url in link_history: return None
        if is_old_news_url(actual_url): return None
        if mode == "MARITIME" and is_old_html_content(actual_url): return None
        try:
            p_date_tag = item.pubDate
            if p_date_tag:
                p_date = parsedate_to_datetime(p_date_tag.text).astimezone(timezone(timedelta(hours=8)))
                if hk_now - p_date > timedelta(hours=24): return None
            else: return None
        except: return None
        if is_duplicate_ai(title, title_history + cur_t_list): return None
        valid = False
        if mode == "MARITIME":
            if any(noise in title for noise in NOISE_EXCLUDE): return None
            if any(gx in title for gx in GLOBAL_EXCLUDE): return None
            if any(uk in title for uk in URGENT_KEYWORDS) or (any(pk in title for pk in POLICE_KEYWORDS) and any(ha in title for ha in HARD_ACTIONS)):
                if any(hk in title for hk in HK_STRONG_INDICATORS):
                    valid = True
        elif mode == "FINANCE":
            if any(s in title for s in WATCHLIST.values()): valid = True
        if valid:
            emoji = "⚓️" if mode == "MARITIME" else "💰"
            map_info = get_map_url(title) if mode == "MARITIME" else ""
            msg = f"{emoji} <b>{title}</b>{map_info}\n🔗 <a href='{actual_url}'>閱讀全文</a>"
            return {"msg": msg, "title": title, "url": actual_url}
    except:
        pass
    return None

def load_history(file_path):
    if not os.path.exists(file_path): return []
    valid = []
    now = datetime.now(timezone(timedelta(hours=8)))
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                if "||" in line:
                    ts, content = line.strip().split("||", 1)
                    if now - datetime.fromisoformat(ts) <= timedelta(days=MAX_HISTORY_DAYS):
                        valid.append(content)
    except: pass
    return valid[-500:]

def save_history(file_path, items):
    now = datetime.now(timezone(timedelta(hours=8))).isoformat()
    with open(file_path, "a", encoding="utf-8") as f:
        for item in items: f.write(f"{now}||{item}\n")

# ==================== 3. ETF 自动抓取与比对模块 ====================

def load_etf_cache():
    if os.path.exists(ETF_CACHE_FILE):
        try:
            with open(ETF_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_etf_cache(data):
    try:
        with open(ETF_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except:
        pass

def fetch_dividends(symbol):
    """使用 yfinance 获取派息历史（最可靠来源）"""
    try:
        ticker = yf.Ticker(symbol)
        divs = ticker.dividends
        if divs.empty:
            return []
        records = []
        for date, amount in divs.items():
            records.append({
                "date": date.strftime("%Y-%m-%d"),
                "amount": round(float(amount), 4),
            })
        records.sort(key=lambda x: x["date"], reverse=True)
        return records[:12]
    except Exception as e:
        print(f"[Dividends {symbol}] 失败: {e}")
        return []

def fetch_3466_holdings():
    """抓取 3466 十大持仓：MoneyDJ 优先，yfinance 备援"""
    holdings = []
    # MoneyDJ 抓取
    try:
        url = "https://www.moneydj.com/etf/x/basic/basic0007.xdjhtm?etfid=3466.HK"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        tables = soup.find_all("table")
        for t in tables:
            if "個股" in t.text:
                rows = t.find_all("tr")[1:]
                for row in rows:
                    cols = row.find_all("td")
                    if len(cols) >= 2:
                        raw_name = cols[0].text.strip()
                        weight_text = cols[1].text.strip()
                        name = re.sub(r'\(.*?\)', '', raw_name).strip()
                        if name and re.match(r'[\d.]+', weight_text):
                            try:
                                holdings.append({"name": name, "weight": f"{float(weight_text):.2f}%"})
                            except ValueError:
                                pass
                    if len(holdings) >= 10:
                        break
                if holdings:
                    break
    except Exception as e:
        print(f"[3466 MoneyDJ] {e}")

    # yfinance 备援
    if not holdings:
        try:
            ticker = yf.Ticker("3466.HK")
            fund = ticker.funds_data
            if fund and fund.top_holdings is not None and not fund.top_holdings.empty:
                for _, row in fund.top_holdings.head(10).iterrows():
                    holdings.append({
                        "name": row.get("Name", row.name),
                        "weight": f"{row['Holding Percent']*100:.2f}%"
                    })
        except Exception as e:
            print(f"[3466 yfinance 备援] {e}")

    return holdings[:10]

def fetch_3145_data():
    """从 MoneyDJ 抓取 3145 的十大持仓和区域权重（原始数据，不做二次加工）"""
    result = {"holdings": [], "countries": []}

    NAME_MAP = {
        "BBRI": ("印尼人民銀行", "🏦🇮🇩"),
        "6181": ("老鋪黃金", "💎"),
        "1138": ("中遠海能", "🚢"),
        "BBNI": ("印尼國家銀行", "🏦🇮🇩"),
        "8299": ("群聯電子", "💾"),
        "3036": ("文曄科技", "📦"),
        "BMRI": ("印尼曼迪利銀行", "🏦🇮🇩"),
        "ANTM": ("印尼安塔姆礦業", "⛏️🇮🇩"),
        "1378": ("中國宏橋", "⛏️"),
        "3311": ("中國建築國際", "🏗️"),
        "0322": ("康師傅控股", "🍜"),
    }

    def get_cn_name(raw_name):
        upper = raw_name.upper()
        for code, (cn, icon) in NAME_MAP.items():
            if code.upper() in upper or cn in raw_name:
                return cn, icon
        cleaned = re.sub(r'\s+(PERSER|TBK|PT|LTD|NPV|HOLDINGS|INC).*$', '', raw_name, flags=re.I).strip()
        return cleaned or raw_name, "📊"

    try:
        url = "https://www.moneydj.com/etf/x/basic/basic0007.xdjhtm?etfid=3145.HK"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        tables = soup.find_all("table")

        # 1. 区域权重（查找含"區域"的表格，直接使用原始数据）
        for t in tables:
            if "區域" in t.text and "比例" in t.text:
                rows = t.find_all("tr")[1:]
                for row in rows:
                    cols = row.find_all("td")
                    if len(cols) >= 3:
                        country = cols[0].text.strip()
                        weight_text = cols[-1].text.strip()
                        if country and re.match(r'[\d.]+', weight_text):
                            try:
                                result["countries"].append({
                                    "country": country,
                                    "weight": float(weight_text)
                                })
                            except ValueError:
                                pass
                break

        # 2. 十大持仓
        for t in tables:
            if "個股" in t.text:
                rows = t.find_all("tr")[1:]
                for row in rows:
                    cols = row.find_all("td")
                    if len(cols) >= 2:
                        raw_name = cols[0].text.strip()
                        weight_text = cols[1].text.strip()
                        if raw_name and re.match(r'[\d.]+', weight_text):
                            cn, icon = get_cn_name(raw_name)
                            result["holdings"].append({
                                "name": cn, "icon": icon,
                                "weight": float(weight_text)
                            })
                    if len(result["holdings"]) >= 10:
                        break
                if result["holdings"]:
                    break
    except Exception as e:
        print(f"[3145 MoneyDJ] {e}")

    return result

def build_etf_section():
    cache = load_etf_cache()
    lines = []
    new_cache = dict(cache)

    # ========== 3466 ==========
    lines.append("🏛️ 3466 恒生高息股")

    divs_3466 = fetch_dividends("3466.HK")
    curr_3466 = divs_3466[0] if divs_3466 else None
    prev_3466 = cache.get("3466.HK", {}).get("latest")

    if curr_3466:
        line = f"  💰 派息：{curr_3466['amount']}（除息 {curr_3466['date']}）"
        if prev_3466 and prev_3466.get("date") != curr_3466["date"]:
            line += f"\n  🆕 新派息！上次 {prev_3466['amount']}（{prev_3466['date']}）"
        elif prev_3466 and prev_3466.get("amount") != curr_3466["amount"]:
            line += f"\n  ⚠️ 金額變動！上次 {prev_3466['amount']}"
        lines.append(line)
    else:
        lines.append("  💰 派息：獲取失敗")
    new_cache["3466.HK"] = {"latest": curr_3466} if curr_3466 else new_cache.get("3466.HK", {})

    h3466 = fetch_3466_holdings()
    if h3466:
        lines.append("  📊 十大持倉：")
        for h in h3466:
            lines.append(f"    · {h['name']}  {h['weight']}")
    else:
        lines.append("  📊 十大持倉：獲取失敗")

    # ========== 3145 ==========
    lines.append("\n🌏 3145 華夏亞洲高息股票ETF")

    divs_3145 = fetch_dividends("3145.HK")
    curr_3145 = divs_3145[0] if divs_3145 else None
    prev_3145 = cache.get("3145.HK", {}).get("latest")

    if curr_3145:
        line = f"  💰 派息：{curr_3145['amount']}（除息 {curr_3145['date']}）"
        if prev_3145 and prev_3145.get("date") != curr_3145["date"]:
            line += f"\n  🆕 新派息！上次 {prev_3145['amount']}（{prev_3145['date']}）"
        elif prev_3145 and prev_3145.get("amount") != curr_3145["amount"]:
            line += f"\n  ⚠️ 金額變動！上次 {prev_3145['amount']}"
        lines.append(line)
    else:
        lines.append("  💰 派息：獲取失敗")
    new_cache["3145.HK"] = {"latest": curr_3145} if curr_3145 else new_cache.get("3145.HK", {})

    data_3145 = fetch_3145_data()
    if data_3145["holdings"]:
        lines.append("  📊 十大持倉：")
        for h in data_3145["holdings"]:
            lines.append(f"    · {h['icon']} {h['name']}  {h['weight']:.2f}%")
    else:
        lines.append("  📊 十大持倉：獲取失敗")

    # 区域权重：直接展示 MoneyDJ 原始数据，不做任何加工
    if data_3145["countries"]:
        lines.append("  🌏 區域權重（MoneyDJ 原始數據）：")
        for c in data_3145["countries"]:
            lines.append(f"    · {c['country']}：{c['weight']:.2f}%")
    else:
        lines.append("  🌏 區域權重：獲取失敗")

    save_etf_cache(new_cache)
    return "\n".join(lines)

def fetch_etf_news(title_history, link_history):
    """抓取 3466 与 3145 的相关消息（成份股/管理费/派息/政策等）"""
    keywords_q = " OR ".join([f'"{k}"' for k in ETF_NEWS_KEYWORDS])
    special_q = " OR ".join(ETF_SPECIAL_KEYWORDS)
    base = f"({keywords_q}) AND ({special_q})"
    sites = " OR ".join([f"site:{d}" for d in HK_MEDIA_DOMAINS])
    query = f"({base}) AND ({sites})"

    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    found, cur_t, cur_l = [], [], []
    hk_now = datetime.now(timezone(timedelta(hours=8)))

    try:
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.content, 'xml')
        items = soup.find_all('item')[:10]

        def check_etf_item(item):
            try:
                title = item.title.text.split(' - ')[0].strip()
                link = item.link.text
                actual_url = link
                if "articles/" in link:
                    try:
                        actual_url = requests.head(link, timeout=1.5).headers.get('Location', link)
                    except: pass
                if actual_url in link_history: return None
                if is_old_news_url(actual_url): return None
                try:
                    p_date = parsedate_to_datetime(item.pubDate.text).astimezone(timezone(timedelta(hours=8)))
                    if hk_now - p_date > timedelta(hours=72): return None
                except: return None
                if is_duplicate_ai(title, title_history + cur_t): return None
                if not any(k in title for k in ETF_NEWS_KEYWORDS): return None
                msg = f"📢 <b>{title}</b>\n🔗 <a href='{actual_url}'>閱讀全文</a>"
                return {"msg": msg, "title": title, "url": actual_url}
            except:
                return None

        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(check_etf_item, item) for item in items]
            for future in futures:
                res = future.result()
                if res:
                    if not is_duplicate_ai(res["title"], title_history + cur_t):
                        found.append(res["msg"])
                        cur_t.append(res["title"])
                        cur_l.append(res["url"])
                if len(found) >= 3:
                    break
    except Exception as e:
        print(f"[ETF News] {e}")

    return found, cur_t, cur_l

# ==================== 4. 高速数据源：RTHK ====================

def fetch_rthk_news(rthk_history):
    found, cur_l, cur_t = [], [], []
    hk_now = datetime.now(timezone(timedelta(hours=8)))
    try:
        r = requests.get(RTHK_RSS_URL, timeout=10)
        if r.status_code == 200:
            root = ET.fromstring(r.content)
            for item in root.iter('item'):
                title = item.find('title').text.strip()
                link = item.find('link').text.strip()
                if link in rthk_history: continue
                if any(noise in title for noise in NOISE_EXCLUDE): continue
                if is_old_news_url(link): continue
                try:
                    p_date_tag = item.find('pubDate')
                    if p_date_tag is not None:
                        p_date = parsedate_to_datetime(p_date_tag.text).astimezone(timezone(timedelta(hours=8)))
                        if hk_now - p_date > timedelta(hours=24): continue
                    else: continue
                except: continue
                valid = False
                if any(uk in title for uk in URGENT_KEYWORDS) or any(ha in title for ha in HARD_ACTIONS):
                    valid = True
                if valid:
                    map_info = get_map_url(title)
                    found.append(f"🚨 <b>速報: {title}</b>{map_info}\n🔗 <a href='{link}'>閱讀全文 (RTHK)</a>")
                    cur_l.append(link)
                    cur_t.append(title)
                if len(found) >= 5: break
    except: pass
    return found, cur_l, cur_t

# ==================== 5. 常规引擎：Google News ====================

def fetch_news_engine(mode, title_history, link_history):
    if mode == "MARITIME":
        base = "水警 OR 警拘 OR 命案 OR 走私 OR 爆竊 OR 太空油 OR 電子煙"
        sites = " OR ".join([f"site:{d}" for d in HK_MEDIA_DOMAINS])
        query = f"({base}) AND ({sites})"
    else:
        query = " OR ".join(WATCHLIST.values())

    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    found, cur_t, cur_l = [], [], []
    hk_now = datetime.now(timezone(timedelta(hours=8)))

    try:
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.content, 'xml')
        items = soup.find_all('item')[:15]
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [
                executor.submit(check_single_item, item, title_history, cur_t, link_history, mode, hk_now)
                for item in items
            ]
            for future in futures:
                res = future.result()
                if res:
                    if not is_duplicate_ai(res["title"], title_history + cur_t):
                        found.append(res["msg"])
                        cur_t.append(res["title"])
                        cur_l.append(res["url"])
                if len(found) >= 5:
                    break
    except: pass
    return found, cur_t, cur_l

# ==================== 6. 执行与报告 ====================

def run_monitor():
    hk_tz = timezone(timedelta(hours=8))
    now = datetime.now(hk_tz)
    t_hist = load_history(HISTORY_FILE)
    l_hist = load_history(LINK_HISTORY_FILE)
    rthk_hist = load_history(RTHK_HISTORY_FILE)

    rthk_urgent, rl, rt = fetch_rthk_news(rthk_hist)
    m_news, mt, ml = fetch_news_engine("MARITIME", t_hist, l_hist)
    f_news, ft, fl = fetch_news_engine("FINANCE", t_hist, l_hist)

    final_m_news = rthk_urgent.copy()
    for m_item, m_title in zip(m_news, mt):
        if not is_duplicate_ai(m_title, rt):
            final_m_news.append(m_item)

    if now.hour == 8 and now.minute < 30:
        report = [f"📊 市場監控報告 ({now.strftime('%H:%M')})"]
        report.append("【持倉 KDJ 預警】")

        for sym, name in WATCHLIST.items():
            price_val = 0.0
            try:
                p_data = yf.Ticker(sym).history(period="1d")
                if not p_data.empty:
                    price_val = p_data['Close'].iloc[-1]
            except: pass
            wk_k = get_kdj_data(sym, "1wk")
            mo_k = get_kdj_data(sym, "1mo")
            status = ""
            if wk_k < 20 and mo_k < 20: status = " ⚠️ 極度超賣"
            elif wk_k > 80 and mo_k > 80: status = " 🔥 極度超買"
            elif wk_k < 20: status = " 📈 週線超賣"
            elif wk_k > 80: status = " 📉 週線超買"
            report.append(f"• {name}: {price_val:.2f} | 週:{wk_k:.1f} 月:{mo_k:.1f}{status}")

        # ETF 深度关注板块
        report.append("\n【3466 & 3145 深度關注】")
        try:
            etf_section = build_etf_section()
            report.append(etf_section)
        except Exception as e:
            report.append(f"數據抓取異常：{e}")

        # ETF 相关消息
        etf_news, etf_titles, etf_links = fetch_etf_news(t_hist, l_hist)
        if etf_news:
            report.append("\n📢 3466/3145 相關消息")
            report.extend(etf_news)
        else:
            report.append("\n📢 3466/3145 相關消息：暫無特別")

        if f_news:
            report.append(f"\n💰 其他持倉動態：\n" + "\n".join(f_news))
        if final_m_news:
            report.append(f"\n⚓️ 突發焦點：\n" + "\n".join(final_m_news))

        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": "\n".join(report), "parse_mode": "HTML", "disable_web_page_preview": "True"},
        )
    else:
        urgent = final_m_news
        if urgent:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                data={"chat_id": CHAT_ID, "text": f"🔔 即時情報 ({now.strftime('%H:%M')})\n\n" + "\n\n".join(urgent), "parse_mode": "HTML"},
            )

    save_history(HISTORY_FILE, mt + ft)
    save_history(LINK_HISTORY_FILE, ml + fl)
    save_history(RTHK_HISTORY_FILE, rl)

if __name__ == "__main__":
    run_monitor()
