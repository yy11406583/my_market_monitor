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
    "水警", "海關", "走私", "截獲", "快艇", "內河船", "小艇分區", "非法入境",
    "大嶼山", "南丫島", "長洲", "後海灣", "吐露港", "昂船洲", "青馬大橋", 
    "海上意外", "船隻", "撞船", "沉沒", "墮海", "溺斃", "漂浮", "救起",
    "警方", "警區", "警崗", "警署", "吞槍", "自轟", "警察", "警員", "私煙", "凍肉"
]

FINANCE_KEYWORDS = ["派息", "除淨", "業績", "回購", "盈喜", "盈警", "股息", "KDJ", "超賣", "暴跌", "飆升"]

# --- 2. 核心功能 ---
def get_volatility_indices():
    results = {"VIX": 0.0, "VHSI": 0.0}
    try:
        # VIX 正常抓取
        results["VIX"] = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
        # VHSI 經常無數據，改用較長 period 確保拿到最後一個有效值
        vhsi_df = yf.Ticker("^VHSI").history(period="7d")
        if not vhsi_df.empty:
            results["VHSI"] = vhsi_df['Close'].iloc[-1]
    except: pass
    return results

def get_stock_data(ticker_symbol):
    try:
        t = yf.Ticker(ticker_symbol)
        hist = t.history(period="7d") # 擴大至 7 天，解決假期 0 數據問題
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

def fetch_filtered_news(keywords, history, custom_query=None):
    base_query = custom_query if custom_query else "香港 新聞"
    encoded_query = urllib.parse.quote(base_query)
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    
    found, new_sent_titles = [], []
    # 修正：全部統一使用 UTC 時間進行計算，避開時區混亂
    now_utc = datetime.now(timezone.utc)
    
    try:
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.content, 'xml')
        items = soup.find_all('item')
        for item in items:
            title = item.title.text
            pub_date_str = item.pubDate.text
            pub_date_utc = email.utils.parsedate_to_datetime(pub_date_str)
            
            # 如果新聞沒有時區資訊，強制補上 UTC 避免比較報錯
            if pub_date_utc.tzinfo is None:
                pub_date_utc = pub_date_utc.replace(tzinfo=timezone.utc)
            
            # 時間過濾：24 小時內 (86400秒)
            diff_seconds = (now_utc - pub_date_utc).total_seconds()
            
            # 如果 diff_seconds 是負數，代表新聞來自未來（通常是時區計算錯誤），我們依然讓它通過
            if diff_seconds > 86400:
                continue 
            
            if any(k in title for k in keywords) and title not in history:
                found.append(f"• {title}")
                new_sent_titles.append(title)
            
            if len(found) >= 15: break
    except: pass
    return found, new_sent_titles

def send_tg(text):
    if not text: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try: requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
    except: pass

def run_main():
    # 定義香港時間用於報告顯示與判斷
    hk_tz = timezone(timedelta(hours=8))
    hkt_now = datetime.now(hk_tz)
    now_hour = hkt_now.hour
    now_min = hkt_now.minute
    
    history = set()
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = {line.strip() for line in f}
    
    # 修正搜尋字串：移除括號組合，改用簡單的 OR 連接以擴大搜尋範圍
    maritime_query = "水警 OR 海關 OR 走私 OR 墮海 OR 警方 OR 吞槍 OR 自轟 OR 內河船"
    m_list, m_new = fetch_filtered_news(MARITIME_KEYWORDS, history, custom_query=maritime_query)
    
    finance_query = "港股 派息 業績 盈喜 盈警"
    f_list, f_new = fetch_filtered_news(FINANCE_KEYWORDS, history, custom_query=finance_query)
    vol = get_volatility_indices()

    # 1. 08:00 大報告 (僅發送一次)
    if now_hour == 8 and now_min < 30:
        reports = [f"<b>📊 市場監控報告 ({hkt_now.strftime('%Y-%m-%d %H:%M')})</b>"]
        reports.append(f"• VIX: {vol['VIX']:.2f} | VHSI: {vol['VHSI']:.2f}\n")
        reports.append("<b>【核心持倉報價】</b>")
        for s, name in WATCHLIST.items():
            dy, price = get_stock_data(s)
            reports.append(f"• {name}: <b>{price:.2f}</b> (息: {dy:.1f}%)")
        
        m_today, _ = fetch_filtered_news(MARITIME_KEYWORDS, set(), custom_query=maritime_query)
        reports.append(f"\n⚠️ <b>24H 突發焦點：</b>\n" + "\n".join(m_today[:10]) if m_today else "\n⚓️ 暫無突發")
        send_tg("\n".join(reports))
    
    # 2. 即時突發報警 (VIX/VHSI)
    emergency = []
    if vol["VIX"] >= 45: emergency.append(f"🔴 VIX 恐慌: {vol['VIX']:.2f}")
    if vol["VHSI"] >= 35: emergency.append(f"⚠️ VHSI 提醒: {vol['VHSI']:.2f}")
    if emergency: send_tg("🚨 <b>市場警告</b>\n" + "\n".join(emergency))

    # 3. 非 8 點時段的新聞通知
    if not (now_hour == 8 and now_min < 30):
        if m_list: send_tg(f"🚨 <b>突發 ({now_hour}:{now_min:02d})</b>\n\n" + "\n".join(m_list))
        if 8 < now_hour < 24 and f_list: send_tg(f"🔔 <b>財經 ({now_hour}:{now_min:02d})</b>\n\n" + "\n".join(f_list))
    
    # 4. 儲存紀錄
    final_new = list(set(m_new + f_new))
    if final_new:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            for t in final_new: f.write(t + "\n")

if __name__ == "__main__":
    run_main()
