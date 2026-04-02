import yfinance as yf
import requests
import pandas as pd
import os
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup
import urllib.parse
import email.utils

# --- 1. 配置區 ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
HISTORY_FILE = "sent_news.txt"

WATCHLIST = {
    "2800.HK": "盈富基金", "3466.HK": "恒生高息股", "0941.HK": "中移動",
    "0005.HK": "匯豐", "0939.HK": "建行", "VOO": "VOO", "QQQ": "QQQ"
}

MARITIME_KEYWORDS = [
    "水警", "海關", "走私", "偷運", "快艇", "小艇分區", "截獲", "非法入境",
    "大嶼山", "南丫島", "長洲", "後海灣", "吐露港", "昂船洲", "青馬大橋", 
    "海上意外", "船隻", "撞船", "沉沒", "墮海", "溺斃", "漂浮", "救起",
    "政府船塢", "噴射船", "私煙", "凍肉", "警察", "警員", "船上"
]

FINANCE_KEYWORDS = ["派息", "除淨", "業績", "回購", "盈喜", "盈警", "股息", "KDJ", "超賣", "暴跌", "飆升", "減息", "加息"]

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
        vhsi_data = yf.Ticker("^VHSI").history(period="1d")
        results["VHSI"] = vhsi_data['Close'].iloc[-1] if not vhsi_data.empty else 0.0
    except: pass
    return results

def get_stock_data(ticker_symbol):
    try:
        t = yf.Ticker(ticker_symbol)
        hist = t.history(period="5d")
        price = hist['Close'].iloc[-1] if not hist.empty else 0.0
        dy = 0.0
        actions = t.actions
        if not actions.empty and 'Dividends' in actions:
            one_year_ago = pd.Timestamp.now(tz='UTC') - pd.Timedelta(days=365)
            actions.index = pd.to_datetime(actions.index).tz_convert('UTC')
            div_sum = actions[actions.index > one_year_ago]['Dividends'].sum()
            dy = (div_sum / price * 100) if price > 0 else 0.0
        return (0.0 if pd.isna(dy) else dy), (0.0 if pd.isna(price) else price)
    except: return 0.0, 0.0

def fetch_filtered_news(keywords, history, custom_query=None):
    base_query = custom_query if custom_query else "香港 新聞"
    encoded_query = urllib.parse.quote(base_query)
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    
    found, new_sent_titles = [], []
    # 修正：正確定義香港時區
    hk_tz = timezone(timedelta(hours=8))
    now = datetime.now(hk_tz)
    
    try:
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.content, 'xml')
        for item in soup.find_all('item', limit=100):
            title = item.title.text
            pub_date_str = item.pubDate.text
            
            # 解析 RSS 時間並確保它有時區資訊進行比較
            pub_date = email.utils.parsedate_to_datetime(pub_date_str)
            
            # 如果新聞在 24 小時前發布，則跳過
            if (now - pub_date).total_seconds() > 86400:
                continue 
            
            if any(k in title for k in keywords) and title not in history:
                found.append(f"• {title}")
                new_sent_titles.append(title)
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
    now_hour = hkt_now.hour
    
    history = set()
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = {line.strip() for line in f}
    
    maritime_query = "水警 OR 走私 OR 墮海 OR 海關 OR (快艇 截獲) OR (小艇分區 拘捕)"
    m_list, m_new = fetch_filtered_news(MARITIME_KEYWORDS, history, custom_query=maritime_query)
    
    finance_query = "港股 派息 業績 盈喜 盈警 VOO QQQ"
    f_list, f_new = fetch_filtered_news(FINANCE_KEYWORDS, history, custom_query=finance_query)
    
    vol = get_volatility_indices()

    # 1. 突發報警
    emergency = []
    if vol["VIX"] >= 45: emergency.append(f"🔴🔴 <b>VIX 極端恐慌: {vol['VIX']:.2f}</b>")
    if vol["VHSI"] >= 35: emergency.append(f"⚠️ <b>VHSI 恐慌提醒: {vol['VHSI']:.2f}</b>")
    if emergency: send_tg("🚨 <b>【市場波動警告】</b>\n\n" + "\n".join(emergency))

    # 2. 報告邏輯
    if now_hour == 8:
        reports = [f"<b>📊 市場監控報告 ({hkt_now.strftime('%Y-%m-%d %H:%M')})</b>"]
        reports.append(f"• VIX: {vol['VIX']:.2f} | VHSI: {vol['VHSI']:.2f}\n")
        reports.append("<b>【核心持倉報價】</b>")
        for s, name in WATCHLIST.items():
            dy, price = get_stock_data(s)
            wk_low, wk_v = get_kdj_signal(s, "1wk")
            mo_low, mo_v = get_kdj_signal(s, "1mo")
            msg = ""
            if wk_low: msg += f" 🔥 <b>週K({wk_v:.1f})</b>"
            if mo_low: msg += f" 💎 <b>月K({mo_v:.1f})</b>"
            reports.append(f"• {name}: <b>{price:.2f}</b> (息: {dy:.1f}%){msg}")
        
        m_today, _ = fetch_filtered_news(MARITIME_KEYWORDS, set(), custom_query=maritime_query)
        reports.append(f"\n⚠️ <b>24小時內海上/突發焦點：</b>\n" + "\n".join(m_today[:10]) if m_today else "\n⚓️ 暫無突發")
        send_tg("\n".join(reports))
    else:
        if m_list: send_tg(f"🚨 <b>突發訊息 ({now_hour}:00)</b>\n\n" + "\n".join(m_list[:5]))
        if 8 < now_hour < 24 and f_list: send_tg(f"🔔 <b>財經動態 ({now_hour}:00)</b>\n\n" + "\n".join(f_list[:5]))
    
    final_new = list(set(m_new + f_new))
    if final_new:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            for t in final_new: f.write(t + "\n")

if __name__ == "__main__":
    run_main()
