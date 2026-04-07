import yfinance as yf
import requests
import pandas as pd
import os
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup
import urllib.parse
import email.utils
import re

# --- 1. 配置區 ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
HISTORY_FILE = "sent_news.txt"

WATCHLIST = {
    "2800.HK": "盈富基金", "3466.HK": "恒生高息股", "0941.HK": "中移動",
    "0005.HK": "匯豐", "0939.HK": "建行", "VOO": "VOO", "QQQ": "QQQ"
}

# 突發關鍵字
MARITIME_KEYWORDS = [
    "水警", "走私", "截獲", "快艇", "內河船", "非法入境", "墮海", "船隻", 
    "警方", "警區", "警署", "警察", "警員", "反爆竊", "失蹤", "尋人", "淋紅油", "撞車"
]

FINANCE_KEYWORDS = ["派息", "業績", "回購", "盈喜", "盈警", "股息", "減息", "加息", "聯儲局", "美股"]

# 徹底封殺：加入更多台灣、海外地標及媒體
EXCLUDE_KEYWORDS = [
    "高雄", "台中", "屏東", "新莊", "龜山", "蘇花", "加州", "澳洲", "波士頓", "多倫多", "韓國", "雲南", 
    "沙加緬度", "密大", "金門", "楠梓", "交通部長", "郭艾倫", "俄黑客", "車道騙局", "隨身攝錄", "海巡", "螺絲釘"
]
HK_DISTRICTS = [
    "香港", "港聞", "新界", "九龍", "港島", "屯門", "元朗", "機場", "旺角", "油麻地", "深水埗", 
    "西貢", "觀塘", "東涌", "大嶼山", "長沙灣", "灣仔", "中環", "半山", "南區", "沙田", "大角咀", "麥理浩徑"
]
INTL_SOURCES = ["自由時報", "聯合報", "中時", "ETtoday", "三立", "TVBS", "韓星網", "發燒車訊", "細說燊語", "RFI", "共同網"]

# --- 2. 核心功能 (KDJ & 市場數據) ---

def calculate_kdj(df, n=9, m1=3, m2=3):
    try:
        low_list = df['Low'].rolling(window=n, min_periods=n).min()
        high_list = df['High'].rolling(window=n, min_periods=n).max()
        rsv = (df['Close'] - low_list) / (high_list - low_list) * 100
        k = rsv.ewm(com=m1-1, adjust=False).mean()
        d = k.ewm(com=m2-1, adjust=False).mean()
        return k.iloc[-1], d.iloc[-1]
    except: return 50, 50

def get_kdj_signal(ticker_symbol, interval="1wk"):
    try:
        df = yf.Ticker(ticker_symbol).history(period="2y", interval=interval)
        if len(df) < 12: return False, 0
        k, d = calculate_kdj(df)
        return k < 20, k
    except: return False, 0

def get_volatility_indices():
    results = {"VIX": 0.0, "VHSI": 0.0}
    try:
        results["VIX"] = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
        vhsi_df = yf.Ticker("^VHSI").history(period="60d")
        if not vhsi_df.empty:
            valid_closes = vhsi_df['Close'][vhsi_df['Close'] > 0]
            if not valid_closes.empty: results["VHSI"] = valid_closes.iloc[-1]
    except: pass
    return results

def get_stock_data(ticker_symbol):
    try:
        t = yf.Ticker(ticker_symbol)
        hist = t.history(period="7d")
        if hist.empty: return 0.0, 0.0
        price = hist['Close'].iloc[-1]
        dy = 0.0
        actions = t.actions
        if not actions.empty and 'Dividends' in actions:
            one_year_ago = pd.Timestamp.now(tz='UTC') - pd.Timedelta(days=365)
            actions.index = pd.to_datetime(actions.index).tz_convert('UTC')
            div_sum = actions[actions.index > one_year_ago]['Dividends'].sum()
            dy = (div_sum / price * 100) if price > 0 else 0.0
        return (0.0 if pd.isna(dy) else dy), (0.0 if pd.isna(price) else price)
    except: return 0.0, 0.0

def clean_title(title):
    title = re.sub(r'\(附圖\)|- 港聞|- 香港|- 時事|\| 生活', '', title)
    title = re.split(r' - | \| | – ', title)[0]
    return title.strip()

def is_duplicate_story(new_title, history_list):
    t1 = clean_title(new_title)
    # 提取核心特徵：數字 + 地名 (如 70歲, 沙田, 失蹤)
    features = set(re.findall(r'\d+|沙田|失蹤|元朗|警方|走私|投資騙案', t1))
    for old_raw in history_list:
        t2 = clean_title(old_raw)
        if t1 == t2: return True
        # 如果兩個標題嘅核心特徵重疊超過 80%，視為重覆
        old_features = set(re.findall(r'\d+|沙田|失蹤|元朗|警方|走私|投資騙案', t2))
        if features and old_features and len(features & old_features) / len(features) > 0.8:
            return True
    return False

def fetch_filtered_news(keywords, history, custom_query=None):
    base_query = custom_query if custom_query else "香港 新聞"
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(base_query)}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    found, new_sent_titles = [], []
    now_utc = datetime.now(timezone.utc)
    try:
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.content, 'xml')
        for item in soup.find_all('item'):
            title = item.title.text
            source = item.source.text if item.source else ""
            pub_date_utc = email.utils.parsedate_to_datetime(item.pubDate.text)
            if pub_date_utc.tzinfo is None: pub_date_utc = pub_date_utc.replace(tzinfo=timezone.utc)
            if (now_utc - pub_date_utc).total_seconds() > 86400: continue 
            
            # 強制地理過濾：有排除詞直接殺
            if any(ex in title for ex in EXCLUDE_KEYWORDS): continue
            
            # 港區校驗：非本地媒體必須有香港地標才過關
            has_hk_place = any(loc in title for loc in HK_DISTRICTS)
            if any(intl in source for intl in INTL_SOURCES) and not has_hk_place: continue
            
            if any(k in title for k in keywords):
                if title not in history and not is_duplicate_story(title, list(history) + new_sent_titles):
                    cleaned = clean_title(title)
                    emoji = "🚨"
                    if any(k in cleaned for k in ["走私", "內河船"]): emoji = "📦"
                    if any(k in cleaned for k in ["水警", "墮海"]): emoji = "⚓️"
                    if "失蹤" in cleaned: emoji = "🔍"
                    found.append(f"{emoji} {cleaned}")
                    new_sent_titles.append(title)
            if len(found) >= 10: break
    except: pass
    return found, new_sent_titles

def send_tg(text):
    if not text: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try: requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
    except: pass

def run_main():
    hk_tz = timezone(timedelta(hours=8))
    hkt_now = datetime.now(hk_tz)
    now_hour, now_min = hkt_now.hour, hkt_now.minute
    history = []
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = [line.strip() for line in f]

    m_list, m_new = fetch_filtered_news(MARITIME_KEYWORDS, history, custom_query="水警 OR 走私 OR 警方 OR 元朗 OR 沙田 OR 麥理浩徑")

    if now_hour == 8 and now_min < 30:
        vol = get_volatility_indices()
        reports = [f"<b>📊 市場監控報告 ({hkt_now.strftime('%H:%M')})</b>"]
        reports.append(f"• VIX: {vol['VIX']:.2f} | VHSI: {vol['VHSI']:.2f}\n")
        reports.append("<b>【核心持倉報價】</b>")
        for s, name in WATCHLIST.items():
            dy, price = get_stock_data(s)
            wk_low, wk_v = get_kdj_signal(s, "1wk")
            mo_low, mo_v = get_kdj_signal(s, "1mo")
            k_msg = ""
            if wk_low: k_msg += f" 🔥 <b>週K({wk_v:.1f})</b>"
            if mo_low: k_msg += f" 💎 <b>月K({mo_v:.1f})</b>"
            reports.append(f"• {name}: <b>{price:.2f}</b> (息:{dy:.1f}%){k_msg}")
        
        f_today, f_new = fetch_filtered_news(FINANCE_KEYWORDS, set(), custom_query="港股 派息 業績 盈喜 VOO QQQ")
        if f_today: reports.append(f"\n💰 <b>財經焦點：</b>\n" + "\n".join(f_today))
        m_today, _ = fetch_filtered_news(MARITIME_KEYWORDS, set())
        reports.append(f"\n⚠️ <b>24H 突發焦點：</b>\n" + "\n\n".join(m_today[:8]) if m_today else "\n⚓️ 暫無突發")
        send_tg("\n".join(reports))
        m_new = list(set(m_new + f_new))
    else:
        if m_list: send_tg(f"🚨 <b>突發報告 ({hkt_now.strftime('%H:%M')})</b>\n\n" + "\n\n".join(m_list))
    
    if m_new:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            for t in m_new: f.write(t + "\n")

if __name__ == "__main__":
    run_main()
