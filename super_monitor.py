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

# 突發關鍵字 (需嚴格過濾)
MARITIME_KEYWORDS = [
    "水警", "海關", "走私", "截獲", "快艇", "內河船", "小艇分區", "非法入境",
    "大嶼山", "南丫島", "長洲", "後海灣", "吐露港", "昂船洲", "青馬大橋", 
    "海上意外", "船隻", "撞船", "沉沒", "墮海", "溺斃", "漂浮", "救起",
    "警方", "警區", "警崗", "警署", "吞槍", "自轟", "警察", "警員", "私煙", "凍肉"
]

# 財經關鍵字 (放寬過濾，接受國際新聞)
FINANCE_KEYWORDS = ["派息", "除淨", "業績", "回購", "盈喜", "盈警", "股息", "KDJ", "超賣", "暴跌", "飆升", "減息", "加息", "聯儲局", "美股"]

# 排除名單 (僅針對「突發新聞」生效)
EXCLUDE_KEYWORDS = ["南京", "東京", "斯里蘭卡", "泰國", "緬甸", "柬埔寨", "日本", "北京", "上海", "深圳", "馬來西亞", "台灣", "羅馬尼亞", "美超微"]
INTL_SOURCES = ["RFI", "共同網", "法廣", "路透", "美聯", "德新社"]

# --- 2. 核心功能 ---
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
        vhsi_df = yf.Ticker("^VHSI").history(period="7d")
        results["VHSI"] = vhsi_df['Close'].iloc[-1] if not vhsi_df.empty else 0.0
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
    title = re.split(r' - | \| | – ', title)[0]
    return title.strip()

def fetch_filtered_news(keywords, history, custom_query=None, is_finance=False):
    base_query = custom_query if custom_query else "香港 新聞"
    encoded_query = urllib.parse.quote(base_query)
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    
    found, new_sent_titles = [], []
    now_utc = datetime.now(timezone.utc)
    HK_LANDMARKS = ["香港", "港聞", "新界", "九龍", "港島", "屯門", "元朗", "機場", "旺角", "油麻地"]

    try:
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.content, 'xml')
        for item in soup.find_all('item'):
            title = item.title.text
            source = item.source.text if item.source else ""
            pub_date_str = item.pubDate.text
            pub_date_utc = email.utils.parsedate_to_datetime(pub_date_str)
            if pub_date_utc.tzinfo is None: pub_date_utc = pub_date_utc.replace(tzinfo=timezone.utc)
            
            if (now_utc - pub_date_utc).total_seconds() > 86400: continue 
            
            # --- 核心邏輯區分 ---
            if is_finance:
                # 財經新聞：只要中關鍵字就報，不執行地名過濾
                if any(k in title for k in keywords) and title not in history:
                    cleaned = clean_title(title)
                    found.append(f"💰 {cleaned}")
                    new_sent_titles.append(title)
            else:
                # 突發新聞：執行嚴格過濾
                if any(ex in title for ex in EXCLUDE_KEYWORDS): continue
                has_hk_place = any(loc in title for loc in HK_LANDMARKS)
                is_intl_wire = any(intl in source for intl in INTL_SOURCES)
                if is_intl_wire and not has_hk_place: continue
                
                if any(k in title for k in keywords) and title not in history:
                    cleaned = clean_title(title)
                    emoji = "📦" if "海關" in cleaned or "走私" in cleaned else "🚨"
                    if "水警" in cleaned or "墮海" in cleaned: emoji = "⚓️"
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
    history = set()
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = {line.strip() for line in f}
    
    # 執行分類搜尋
    m_list, m_new = fetch_filtered_news(MARITIME_KEYWORDS, history, 
                                        custom_query="水警 OR 海關 OR 走私 OR 墮海 OR 警方 OR 內河船", 
                                        is_finance=False)
    
    f_list, f_new = fetch_filtered_news(FINANCE_KEYWORDS, history, 
                                        custom_query="港股 派息 業績 盈喜 VOO QQQ 聯儲局", 
                                        is_finance=True)
    
    vol = get_volatility_indices()

    # 1. 08:00 大報告
    if now_hour == 8 and now_min < 30:
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
        
        m_today, _ = fetch_filtered_news(MARITIME_KEYWORDS, set(), is_finance=False)
        reports.append(f"\n⚠️ <b>24H 突發焦點：</b>\n\n" + "\n\n".join(m_today[:8]) if m_today else "\n⚓️ 暫無突發")
        send_tg("\n".join(reports))
    
    # 2. 突發通知
    else:
        if m_list:
            send_tg(f"🚨 <b>突發報告 ({hkt_now.strftime('%H:%M')})</b>\n\n" + "\n\n".join(m_list))
        if 8 < now_hour < 24 and f_list:
            send_tg(f"🔔 <b>財經/持倉動態 ({hkt_now.strftime('%H:%M')})</b>\n\n" + "\n\n".join(f_list))
    
    # 3. 儲存
    final_new = list(set(m_new + f_new))
    if final_new:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            for t in final_new: f.write(t + "\n")

if __name__ == "__main__":
    run_main()
