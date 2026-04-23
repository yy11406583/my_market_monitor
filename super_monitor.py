import yfinance as yf
import requests
import os
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from bs4 import BeautifulSoup
import urllib.parse
from difflib import SequenceMatcher

# ==================== 1. 配置區 ====================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
HISTORY_FILE = "sent_news.txt"
LINK_HISTORY_FILE = "sent_links.txt"
MAX_HISTORY_DAYS = 7

WATCHLIST = {
    "3466.HK": "恒生高息股", "0941.HK": "中移動", "0005.HK": "匯豐",
    "0939.HK": "建行", "VOO": "VOO", "QQQ": "QQQ",
    "TSLA": "Tesla", "MSFT": "微軟"
}

WAR_TRUSTED_SOURCES = [
    "reuters.com", "bloomberg.com", "bbc.com", "cnn.com", "wsj.com", "nytimes.com", 
    "apnews.com", "aljazeera.com", "ft.com", "hk01.com", "news.now.com", "rthk.hk", 
    "news.tvb.com", "stheadline.com", "orientaldaily.on.cc", "wenweipo.com", "hket.com", 
    "am730.com.hk", "scmp.com", "cabletv.com.hk"
]

WAR_NOISE_EXCLUDE = ["分析", "評論", "網評", "觀點", "專家", "學者", "專欄", "社評", "社論", "解讀", "啟示", "警示"]
HARD_ACTIONS = ["走私", "截獲", "拘捕", "偵破", "跳海", "墮海", "遇溺", "漂浮", "浮屍", "救起", "開火", "封鎖", "扣押", "通緝", "命案", "車禍", "昏迷", "不治"]
POLICE_KEYWORDS = ["水警", "警方", "警察", "警員"]
HK_MEDIA_DOMAINS = ["hk01.com", "news.mingpao.com", "scmp.com", "stheadline.com", "orientaldaily.on.cc", "hket.com", "news.tvb.com", "now.com", "rthk.hk"]
WAR_KEYWORDS = ["伊朗戰爭", "美以伊戰爭", "美伊戰爭", "以伊戰爭"]

# 完整地名庫 (200+ 完整名單已保留)
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

# ==================== 2. 輔助功能 ====================

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

def get_market_indices():
    res = {"VIX": 0.0}
    try:
        v_val = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
        res["VIX"] = v_val
    except: pass
    return res

def get_kdj_data(ticker, interval):
    try:
        df = yf.Ticker(ticker).history(period="2y", interval=interval)
        low, high = df['Low'].rolling(9).min(), df['High'].rolling(9).max()
        rsv = (df['Close'] - low) / (high - low) * 100
        k = rsv.ewm(com=2, adjust=False).mean()
        return k.iloc[-1]
    except: return 50.0

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

# ==================== 3. 新聞引擎 ====================

def fetch_news_engine(mode, title_history, link_history):
    if mode == "MARITIME":
        base = "水警 OR 走私 OR 警察 OR 遇溺 OR 墮海 OR 檢獲 OR 命案"
        sites = " OR ".join([f"site:{d}" for d in HK_MEDIA_DOMAINS])
        query = f"({base}) AND ({sites})"
    elif mode == "WAR":
        # 方案 B：移除查詢中的 site: 限制，改用後過濾以提高穩定性
        query = " OR ".join([f'"{k}"' for k in WAR_KEYWORDS])
    else:
        query = " OR ".join(WATCHLIST.values())

    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    found, cur_t, cur_l = [], [], []
    hk_now = datetime.now(timezone(timedelta(hours=8)))

    try:
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.content, 'xml')
        for item in soup.find_all('item'):
            title = item.title.text.split(' - ')[0].strip()
            link = item.link.text
            if link in link_history: continue
            
            p_date = parsedate_to_datetime(item.pubDate.text).astimezone(timezone(timedelta(hours=8)))
            if hk_now - p_date > timedelta(hours=24): continue
            if is_duplicate_ai(title, title_history + cur_t): continue

            valid = False
            if mode == "MARITIME":
                if any(hk in title for hk in HK_STRONG_INDICATORS):
                    if any(pk in title for pk in POLICE_KEYWORDS) or any(ha in title for ha in HARD_ACTIONS):
                        valid = True
            elif mode == "WAR":
                # 後過濾機制：確保鏈接來自權威源且不含分析噪音
                if any(src in link for src in WAR_TRUSTED_SOURCES):
                    if not any(noise in title for noise in WAR_NOISE_EXCLUDE):
                        # 確保標題真的提及關鍵字
                        if any(wk in title for wk in WAR_KEYWORDS):
                            valid = True
            elif mode == "FINANCE":
                if any(s in title for s in WATCHLIST.values()): valid = True

            if valid:
                emoji = "⚓️" if mode == "MARITIME" else "🌍" if mode == "WAR" else "💰"
                map_info = get_map_url(title) if mode == "MARITIME" else ""
                found.append(f"{emoji} <b>{title}</b>{map_info}\n🔗 <a href='{link}'>閱讀全文</a>")
                cur_t.append(title); cur_l.append(link)
            if len(found) >= 5: break
    except: pass
    return found, cur_t, cur_l

# ==================== 4. 執行與報告 ====================

def run_monitor():
    hk_tz = timezone(timedelta(hours=8)); now = datetime.now(hk_tz)
    t_hist, l_hist = load_history(HISTORY_FILE), load_history(LINK_HISTORY_FILE)

    m_news, mt, ml = fetch_news_engine("MARITIME", t_hist, l_hist)
    f_news, ft, fl = fetch_news_engine("FINANCE", t_hist, l_hist)
    w_news, wt, wl = fetch_news_engine("WAR", t_hist, l_hist)

    if now.hour == 8 and now.minute < 30:
        v_idx = get_market_indices()
        report = [f"<b>📊 市場監控報告 ({now.strftime('%H:%M')})</b>"]
        report.append(f"• VIX: {v_idx['VIX']:.2f}\n")
        report.append("<b>【持倉 KDJ 預警】</b>")
        
        for sym, name in WATCHLIST.items():
            price_val = 0.0
            try:
                p_data = yf.Ticker(sym).history(period="1d")
                if not p_data.empty: price_val = p_data['Close'].iloc[-1]
            except: pass
            
            wk_k, mo_k = get_kdj_data(sym, "1wk"), get_kdj_data(sym, "1mo")
            status = ""
            if wk_k < 20 and mo_k < 20: status = " ⚠️ 極度超賣"
            elif wk_k > 80 and mo_k > 80: status = " 🔥 極度超買"
            elif wk_k < 20: status = " 📈 週線超賣"
            elif wk_k > 80: status = " 📉 週線超買"
            
            # 恢復價格數據顯示
            report.append(f"• {name}: <b>{price_val:.2f}</b> | 週:{wk_k:.1f} 月:{mo_k:.1f}{status}")
        
        if f_news: report.append(f"\n💰 <b>持倉動態：</b>\n" + "\n".join(f_news))
        if w_news: report.append(f"\n🌍 <b>戰爭實時：</b>\n" + "\n".join(w_news))
        if m_news: report.append(f"\n⚓️ <b>突發焦點：</b>\n" + "\n".join(m_news))
        
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                      data={"chat_id": CHAT_ID, "text": "\n".join(report), "parse_mode": "HTML", "disable_web_page_preview": "True"})
    else:
        urgent = m_news + w_news
        if urgent:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                          data={"chat_id": CHAT_ID, "text": f"🔔 <b>即時情報 ({now.strftime('%H:%M')})</b>\n\n" + "\n\n".join(urgent), "parse_mode": "HTML"})

    save_history(HISTORY_FILE, mt + wt + ft)
    save_history(LINK_HISTORY_FILE, ml + wl + fl)

if __name__ == "__main__":
    run_monitor()
