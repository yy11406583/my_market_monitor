import yfinance as yf
import requests
import time
import pandas as pd
import os
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# --- 1. 配置區 ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

WATCHLIST = {
    "2800.HK": "盈富基金", "3466.HK": "恒生高息股", "0941.HK": "中移動",
    "0005.HK": "匯豐", "0939.HK": "建行", "VOO": "VOO", "QQQ": "QQQ"
}
MARITIME_KEYWORDS = ["水警", "海上意外", "船隻爆炸", "海上吸毒", "海上偷竊", "偷渡", "海上工業意外", "政府船塢", "漂浮", "撞船", "青馬大橋", "昂船洲", "噴射船", "沉沒", "跳海", "跳橋", "溺斃", "墮海"]
FINANCE_KEYWORDS = ["派息", "除淨", "業績", "回購", "盈喜", "盈警", "股息", "KDJ", "超賣", "暴跌", "飆升"]

# --- 2. 核心功能 (自建 KDJ 計算) ---

def calculate_kdj(df, n=9, m1=3, m2=3):
    """自建 KDJ 計算，完全取代 pandas-ta"""
    low_list = df['Low'].rolling(window=n, min_periods=n).min()
    high_list = df['High'].rolling(window=n, min_periods=n).max()
    rsv = (df['Close'] - low_list) / (high_list - low_list) * 100
    df['K'] = rsv.ewm(com=m1-1, adjust=False).mean()
    df['D'] = df['K'].ewm(com=m2-1, adjust=False).mean()
    df['J'] = 3 * df['K'] - 2 * df['D']
    return df['K'].iloc[-1], df['D'].iloc[-1], df['J'].iloc[-1]

def send_msg(text):
    if not text: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try: requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
    except: pass

def get_kdj_signal(ticker_symbol, interval="1wk"):
    period = "1y" if interval == "1wk" else "5y"
    try:
        df = yf.Ticker(ticker_symbol).history(period=period, interval=interval)
        if len(df) < 20: return False, 0
        k, d, j = calculate_kdj(df)
        return k < 20, k
    except: return False, 0

def get_stock_data(ticker_symbol):
    try:
        t = yf.Ticker(ticker_symbol)
        price = t.history(period="5d")['Close'].iloc[-1]
        actions = t.actions
        dy = 0
        if not actions.empty and 'Dividends' in actions:
            one_year_ago = pd.Timestamp.now(tz='UTC') - pd.Timedelta(days=365)
            actions.index = pd.to_datetime(actions.index).tz_convert('UTC')
            dy = (actions[actions.index > one_year_ago]['Dividends'].sum() / price * 100)
        return dy, price
    except: return 0, 0

def fetch_filtered_news(keywords):
    url = "https://news.google.com/rss/search?q=香港+新聞&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    found = []
    try:
        r = requests.get(url, timeout=10)
        soup = BeautifulSoup(r.content, 'xml')
        for item in soup.find_all('item', limit=50):
            title = item.title.text
            if any(k in title for k in keywords):
                found.append(f"• {title}")
    except: pass
    return "\n".join(found[:5])

def run_main():
    hkt_now = datetime.utcnow() + timedelta(hours=8)
    now_hour = hkt_now.hour
    maritime_hits = fetch_filtered_news(MARITIME_KEYWORDS)
    finance_hits = fetch_filtered_news(FINANCE_KEYWORDS)

    if now_hour == 8:
        reports = [f"<b>📊 市場監控報告 ({hkt_now.strftime('%Y-%m-%d')})</b>\n"]
        try:
            vix = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
            if vix >= 45: reports.append(f"🔴 <b>VIX 恐慌: {vix:.2f}</b>")
        except: pass
        reports.append("<b>【核心持倉報價】</b>")
        for s, name in WATCHLIST.items():
            dy, price = get_stock_data(s)
            wk_low, wk_v = get_kdj_signal(s, "1wk")
            kdj_str = f" 🔥 <b>低位: 週K({wk_v:.1f})</b>" if wk_low else ""
            reports.append(f"• {name}: <b>{price:.2f}</b> (息: {dy:.1f}%){kdj_str}")
        m_status = f"\n⚠️ <b>發現水域相關新聞：</b>\n{maritime_hits}" if maritime_hits else "\n⚓️ 香港水域安全"
        reports.append(m_status)
        send_msg("\n".join(reports))
    else:
        if maritime_hits: send_msg(f"🚨 <b>突發海上訊息 ({now_hour}:00)</b>\n\n{maritime_hits}")
        if 8 < now_hour < 24 and finance_hits: send_msg(f"🔔 <b>監測到財經動態 ({now_hour}:00)</b>\n\n{finance_hits}")

if __name__ == "__main__":
    run_main()
