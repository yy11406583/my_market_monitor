import yfinance as yf
import requests
import pandas as pd
import os
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# --- 1. 配置區 ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
HISTORY_FILE = "sent_news.txt"

WATCHLIST = {
    "2800.HK": "盈富基金", "3466.HK": "恒生高息股", "0941.HK": "中移動",
    "0005.HK": "匯豐", "0939.HK": "建行", "VOO": "VOO", "QQQ": "QQQ"
}

MARITIME_KEYWORDS = ["船上", "水警", "海上意外", "船隻爆炸", "海上吸毒", "海上偷竊", "偷渡", "海上工業意外", "政府船塢", "漂浮", "撞船", "青馬大橋", "昂船洲", "噴射船", "沉沒", "跳海", "跳橋", "溺斃", "墮海", "警察", "警隊", "警員"]
FINANCE_KEYWORDS = ["派息", "除淨", "業績", "回購", "盈喜", "盈警", "股息", "KDJ", "超賣", "暴跌", "飆升"]

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
    # VIX: ^VIX, VHSI: ^VHSI (或透過恒指數據模擬)
    results = {"VIX": 0.0, "VHSI": 0.0}
    try:
        results["VIX"] = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
        results["VHSI"] = yf.Ticker("^VHSI").history(period="1d")['Close'].iloc[-1]
    except: pass
    return results

def get_stock_data(ticker_symbol):
    try:
        t = yf.Ticker(ticker_symbol)
        hist = t.history(period="5d")
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

def fetch_filtered_news(keywords, history):
    url = "https://news.google.com/rss/search?q=香港+新聞&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    found, new_sent_titles = [], []
    try:
        r = requests.get(url, timeout=10)
        soup = BeautifulSoup(r.content, 'xml')
        for item in soup.find_all('item', limit=50):
            title = item.title.text
            if any(k in title for k in keywords) and title not in history:
                found.append(f"• {title}")
                new_sent_titles.append(title)
    except: pass
    return "\n".join(found[:5]), new_sent_titles

def send_tg(text):
    if not text: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try: requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
    except: pass

def run_main():
    hkt_now = datetime.utcnow() + timedelta(hours=8)
    now_hour = hkt_now.hour
    history = []
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = [line.strip() for line in f]
    
    # 1. 獲取波動率與新聞
    vol = get_volatility_indices()
    m_hits, m_new = fetch_filtered_news(MARITIME_KEYWORDS, set(history))
    f_hits, f_new = fetch_filtered_news(FINANCE_KEYWORDS, set(history))

    # 2. 即時突發報警 (VIX > 45, VHSI > 35/45/60)
    emergency = []
    if vol["VIX"] >= 45: emergency.append(f"🔴🔴 <b>VIX 極端恐慌: {vol['VIX']:.2f}</b> (血流成河必入信號)")
    if vol["VHSI"] >= 60: emergency.append(f"🔥🔴 <b>VHSI 崩盤級別: {vol['VHSI']:.2f}</b> (歷史級買入點)")
    elif vol["VHSI"] >= 45: emergency.append(f"🔴 <b>VHSI 極端恐慌: {vol['VHSI']:.2f}</b> (強烈買入信號)")
    elif vol["VHSI"] >= 35: emergency.append(f"⚠️ <b>VHSI 高恐慌: {vol['VHSI']:.2f}</b> (必入提醒)")
    
    if emergency:
        send_tg("🚨 <b>【市場極端報警】</b>\n\n" + "\n".join(emergency))

    # 3. 定時報告 (08:00)
    if now_hour == 8:
        m_all, _ = fetch_filtered_news(MARITIME_KEYWORDS, set())
        reports = [f"<b>📊 市場監控報告 ({hkt_now.strftime('%Y-%m-%d %H:%M')})</b>"]
        
        # 波動率提醒
        v_msg = f"• VIX: <b>{vol['VIX']:.2f}</b>" + (" (高風險)" if vol["VIX"] > 30 else "")
        vh_msg = f"• VHSI: <b>{vol['VHSI']:.2f}</b>" + (" (高恐慌)" if vol["VHSI"] > 30 else "")
        reports.append(f"{v_msg}\n{vh_msg}\n")
        
        reports.append("<b>【核心持倉報價】</b>")
        for s, name in WATCHLIST.items():
            dy, price = get_stock_data(s)
            wk_low, wk_v = get_kdj_signal(s, "1wk")
            mo_low, mo_v = get_kdj_signal(s, "1mo")
            kdj_msg = ""
            if wk_low: kdj_msg += f" 🔥 <b>週K低({wk_v:.1f})</b>"
            if mo_low: kdj_msg += f" 💎 <b>月K低({mo_v:.1f})</b>"
            reports.append(f"• {name}: <b>{price:.2f}</b> (息: {dy:.1f}%){kdj_msg}")
            
        reports.append(f"\n⚠️ <b>發現相關新聞：</b>\n{m_all}" if m_all else "\n⚓️ 今日暫無突發關鍵字")
        send_tg("\n".join(reports))
    else:
        # 非 8 點的新聞報警
        if m_hits: send_tg(f"🚨 <b>突發訊息 ({now_hour}:00)</b>\n\n{m_hits}")
        if 8 < now_hour < 24 and f_hits: send_tg(f"🔔 <b>財經動態 ({now_hour}:00)</b>\n\n{f_hits}")
    
    # 4. 儲存歷史
    if m_new + f_new:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            for t in (m_new + f_new): f.write(t + "\n")

if __name__ == "__main__":
    run_main()
