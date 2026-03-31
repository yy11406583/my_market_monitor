import yfinance as yf
import pandas_ta as ta
import requests
import time
import pandas as pd
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# --- 設定區 (只需填 Telegram) ---
TELEGRAM_TOKEN = "8228323704:AAHnYzsbkjm0QdBFb8Q7bcuSvAX6MTKSNDs"
CHAT_ID = "8275898854"

WATCHLIST = {
    "2800.HK": "盈富基金",
    "3466.HK": "恒生高息股",
    "0941.HK": "中移動",
    "0005.HK": "匯豐",
    "0939.HK": "建行",
    "VOO": "VOO",
    "QQQ": "QQQ"
}
# 海上意外關鍵字
MARITIME_KEYWORDS = ["水警", "海上意外", "船隻爆炸", "海上吸毒", "海上偷竊", "偷渡", "海上工業意外", "政府船塢", "跳海", "跳橋", "溺斃", "墮海"]
# 財經重要關鍵字 (用於 08-24 監控)
FINANCE_KEYWORDS = ["派息", "除淨", "業績", "回購", "超賣", "破底"]

def send_msg(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
    except: pass

def get_kdj_low(ticker_symbol, interval="1wk"):
    df = yf.Ticker(ticker_symbol).history(period="1y", interval=interval)
    if df.empty or len(df) < 20: return False, 0
    kdj = ta.kdj(df['High'], df['Low'], df['Close'])
    k_column = [col for col in kdj.columns if col.startswith('K_') or 'KDJ_K' in col]
    return kdj[k_column[0]].iloc[-1] < 20, kdj[k_column[0]].iloc[-1]

def get_stock_data(ticker_symbol):
    try:
        t = yf.Ticker(ticker_symbol)
        price = t.history(period="5d")['Close'].iloc[-1]
        actions = t.actions
        if not actions.empty and 'Dividends' in actions:
            one_year_ago = pd.Timestamp.now(tz='UTC') - pd.Timedelta(days=365)
            actions.index = pd.to_datetime(actions.index).tz_convert('UTC')
            dy = (actions[actions.index > one_year_ago]['Dividends'].sum() / price * 100)
        else: dy = 0
        return dy, price
    except: return 0, 0

def fetch_filtered_news(keywords):
    """純邏輯過濾：標題有關鍵字才回傳"""
    url = f"https://news.google.com/rss/search?q=香港+新聞&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    results = []
    try:
        r = requests.get(url, timeout=10)
        soup = BeautifulSoup(r.content, 'xml')
        for item in soup.find_all('item', limit=20):
            title = item.title.text
            if any(k in title for k in keywords):
                results.append(f"• {title}")
    except: pass
    return "\n".join(results)

def run_main():
    hkt_now = datetime.utcnow() + timedelta(hours=8)
    now_hour = hkt_now.hour
    
    # 執行過濾
    maritime_news = fetch_filtered_news(MARITIME_KEYWORDS)
    finance_news = fetch_filtered_news(FINANCE_KEYWORDS)

    # 1. 早上 08:00 全面報告
    if now_hour == 8:
        reports = [f"<b>📊 市場監控報告 ({hkt_now.strftime('%Y-%m-%d')})</b>\n"]
        # VIX 略過代碼... (保留你原本的 VIX 邏輯)
        reports.append("<b>【美股/港股報價】</b>")
        for s, name in WATCHLIST.items():
            dy, price = get_stock_data(s)
            reports.append(f"• {name}: <b>{price:.2f}</b> (息: {dy:.1f}%)")
        
        # 水域總結
        m_status = f"\n⚠️ <b>水域警報：</b>\n{maritime_news}" if maritime_news else "\n⚓️ 香港水域安全"
        reports.append(m_status)
        send_msg("\n".join(reports))
        return

    # 2. 海上突發 (24小時，只要有新聞就發)
    if maritime_news:
        send_msg(f"🚨 <b>突發海上訊息 ({now_hour}:00)</b>\n\n{maritime_news}")

    # 3. 財經重要訊息 (08-24 運行)
    if 8 < now_hour < 24 and finance_news:
        send_msg(f"🔔 <b>重要財經訊息 ({now_hour}:00)</b>\n\n{finance_news}")

if __name__ == "__main__":
    run_main()
