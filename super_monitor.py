import yfinance as yf
import requests
import pandas as pd
import os
import json
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup
import urllib.parse
import email.utils
import re

# --- 1. 配置區 ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
HISTORY_FILE = "sent_news.txt"
STATUS_FILE = "monitor_status.json"

WATCHLIST = {
    "2800.HK": "盈富基金", "3466.HK": "恒生高息股", "0941.HK": "中移動",
    "0005.HK": "匯豐", "0939.HK": "建行", "VOO": "VOO", "QQQ": "QQQ"
}

# --- 補回完整 MARITIME 關鍵字 ---
MARITIME_KEYWORDS = [
    "水警", "走私", "快艇", "大飛", "內河船", "小艇分區", "非法入境", "截獲", "大嶼山", "南丫島", 
    "長洲", "後海灣", "吐露港", "昂船洲", "海上意外", "撞船", "沉沒", "墮海", "溺斃", "救起",
    "警方", "警署", "警察", "警員", "反爆竊", "失蹤", "尋人", "淋紅油", "撞車", "元朗", "屯門"
]

FINANCE_KEYWORDS = ["派息", "業績", "回購", "盈喜", "盈警", "股息", "減息", "加息", "聯儲局"]
POLITICS_KEYWORDS = ["特朗普", "川普", "伊朗", "戰爭", "核協議", "無人機", "導彈", "美軍", "中東局勢"]

EXCLUDE_KEYWORDS = ["台東", "台人", "甘肅", "川崎", "螺絲粉", "食安", "台灣好報", "高雄", "台中"]
HK_DISTRICTS = ["香港", "港聞", "新界", "九龍", "港島", "屯門", "元朗", "機場", "旺角", "深水埗", "西貢", "觀塘", "灣仔", "中環", "南區", "沙田", "大角咀", "梅窩", "大欖涌"]

# --- 2. 核心功能 ---

def get_volatility_indices():
    results = {"VIX": 0.0, "VHSI": 0.0}
    try:
        results["VIX"] = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
        # 回溯 30 天尋找非 0 VHSI
        vhsi_df = yf.Ticker("^VHSI").history(period="30d")
        if not vhsi_df.empty:
            valid = vhsi_df['Close'][vhsi_df['Close'] > 0]
            if not valid.empty: results["VHSI"] = valid.iloc[-1]
    except: pass
    return results

def get_kdj_val(ticker, interval):
    try:
        df = yf.Ticker(ticker).history(period="2y", interval=interval)
        if len(df) < 9: return 50.0
        low = df['Low'].rolling(9).min()
        high = df['High'].rolling(9).max()
        rsv = (df['Close'] - low) / (high - low) * 100
        k = rsv.ewm(com=2, adjust=False).mean().iloc[-1]
        return k
    except: return 50.0

def get_stock_data(ticker_symbol):
    try:
        t = yf.Ticker(ticker_symbol)
        hist = t.history(period="7d")
        price = hist['Close'].iloc[-1]
        actions = t.actions
        dy = 0.0
        if not actions.empty and 'Dividends' in actions:
            one_yr = pd.Timestamp.now(tz='UTC') - pd.Timedelta(days=365)
            actions.index = pd.to_datetime(actions.index).tz_convert('UTC')
            dy = (actions[actions.index > one_yr]['Dividends'].sum() / price * 100)
        return dy, price
    except: return 0.0, 0.0

def fetch_news(keywords, history, query, limit=10):
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    found, raw_titles = [], []
    try:
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.content, 'xml')
        for item in soup.find_all('item'):
            t = item.title.text
            src = item.source.text if item.source else "未知"
            if any(ex in t for ex in EXCLUDE_KEYWORDS): continue
            if any(k in t for k in keywords):
                clean_t = t.split(' - ')[0].strip()
                # 去重邏輯：取標題前12個字
                if not any(clean_t[:12] in h for h in history + raw_titles):
                    found.append(f"{clean_t} ({src})")
                    raw_titles.append(t)
            if len(found) >= limit: break
    except: pass
    return found, raw_titles

def send_tg(msg):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                       data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=15)
    except: pass

# --- 3. 執行 ---

def run_main():
    hk_tz = timezone(timedelta(hours=8))
    now = datetime.now(hk_tz)
    
    # 讀取歷史與政治功能狀態
    history = []
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = [l.strip() for l in f]
            
    status = {"last_p_date": str(now.date())}
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, "r") as f: status = json.load(f)

    # 14日停火邏輯
    last_p_date = datetime.strptime(status["last_p_date"], "%Y-%m-%d").date()
    p_active = (now.date() - last_p_date).days <= 14

    # 抓取各類新聞 (加強搜尋關鍵字組合)
    m_list, m_raw = fetch_news(MARITIME_KEYWORDS, history, "水警 OR 走私 OR 快艇 OR 非法入境 OR 警方 OR 墮海")
    p_list, p_raw = (fetch_news(POLITICS_KEYWORDS, history, "特朗普 OR 伊朗戰爭 OR 中東局勢") if p_active else ([], []))
    f_list, f_raw = fetch_news(FINANCE_KEYWORDS, history, "港股 派息 業績 盈喜")

    # 更新政治狀態
    if p_list:
        status["last_p_date"] = str(now.date())
        with open(STATUS_FILE, "w") as f: json.dump(status, f)

    # A. 08:00 市場大報告
    if now.hour == 8 and now.minute < 30:
        vol = get_volatility_indices()
        rep = [f"<b>📊 市場監控報告 ({now.strftime('%H:%M')})</b>"]
        rep.append(f"• VIX: {vol['VIX']:.2f} | VHSI: {vol['VHSI']:.2f}\n")
        rep.append("<b>【核心持倉 KDJ 監控】</b>")
        for s, name in WATCHLIST.items():
            dy, price = get_stock_data(s)
            wk_v = get_kdj_val(s, "1wk")
            mo_v = get_kdj_val(s, "1mo")
            wk_s = f"🔥<b>{wk_v:.1f}</b>" if wk_v < 20 else f"{wk_v:.1f}"
            mo_s = f"💎<b>{mo_k:.1f}</b>" if mo_v < 20 else f"{mo_v:.1f}"
            rep.append(f"• {name}: <b>{price:.2f}</b> (息:{dy:.1f}%) | 週:{wk_s} 月:{mo_s}")
        
        if f_list: rep.append(f"\n💰 <b>財經焦點：</b>\n" + "\n".join(f_list[:5]))
        if p_list: rep.append(f"\n🌍 <b>地緣政治：</b>\n" + "\n".join(p_list[:5]))
        m_today, _ = fetch_news(MARITIME_KEYWORDS, set(), "水警 OR 走私 OR 警方", limit=5)
        rep.append(f"\n⚓️ <b>24H 突發焦點：</b>\n" + ("\n".join(m_today) if m_today else "暫無突發"))
        
        send_tg("\n".join(rep))
        all_new = m_raw + p_raw + f_raw
    else:
        # B. 日間即時通知
        urgent = []
        for x in m_list: urgent.append(f"⚓️ {x}")
        for x in p_list: urgent.append(f"🌍 {x}")
        for x in f_list: urgent.append(f"💰 {x}")
        
        if urgent:
            send_tg(f"🔔 <b>即時情報 ({now.strftime('%H:%M')})</b>\n\n" + "\n\n".join(urgent))
        all_new = m_raw + p_raw + f_raw

    # 紀錄
    if all_new:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            for t in set(all_new): f.write(t + "\n")

if __name__ == "__main__":
    run_main()
