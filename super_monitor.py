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

# 監察名單 (財經新聞將僅以此名單為準)
WATCHLIST = {
    "2800.HK": "盈富基金", "3466.HK": "恒生高息股", "0941.HK": "中移動",
    "0005.HK": "匯豐", "0939.HK": "建行", "VOO": "VOO", "QQQ": "QQQ"
}

# 補回最完整 MARITIME 關鍵字
MARITIME_KEYWORDS = [
    "水警", "走私", "快艇", "大飛", "內河船", "小艇分區", "非法入境", "截獲", "大嶼山", "南丫島", 
    "長洲", "後海灣", "吐露港", "昂船洲", "海上意外", "撞船", "沉沒", "墮海", "警方", "警察", "警員", "反爆竊", "失蹤", "尋人", "淋紅油", "元朗"
]

# 僅關注美伊戰爭
POLITICS_KEYWORDS = ["特朗普", "川普", "伊朗", "美伊戰爭", "霍爾木茲海峽", "美軍", "導彈"]

# 排除雜訊來源及地標
EXCLUDE_KEYWORDS = ["台東", "大馬", "日本", "澳洲", "川崎", "螺絲粉", "NBA", "Leonard", "馬拉松", "台灣", "高雄", "台中"]
BLACKLIST_SOURCES = ["Yahoo運動", "LINE TODAY", "自由時報", "聯合報", "中時", "ETtoday", "三立", "TVBS"]

# --- 2. 核心功能 ---

def get_volatility_indices():
    results = {"VIX": 0.0, "VHSI": 0.0}
    try:
        results["VIX"] = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
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

def fetch_news(keywords, history, query, limit=10):
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    found, raw_titles = [], []
    try:
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.content, 'xml')
        for item in soup.find_all('item'):
            t = item.title.text
            src = item.source.text if item.source else "未知"
            if any(ex in t for ex in EXCLUDE_KEYWORDS) or any(bl in src for bl in BLACKLIST_SOURCES): continue
            
            if any(k in t for k in keywords):
                clean_t = t.split(' - ')[0].strip()
                # 強化去重：檢查標題前10個字，避免重覆報導走私案
                fingerprint = clean_t[:10]
                if not any(fingerprint in h for h in history + raw_titles):
                    emoji = "⚓️" if any(k in t for k in MARITIME_KEYWORDS) else "🌍" if any(k in t for k in POLITICS_KEYWORDS) else "💰"
                    found.append(f"{emoji} {clean_t} ({src})")
                    raw_titles.append(t)
            if len(found) >= limit: break
    except: pass
    return found, raw_titles

def run_main():
    hk_tz = timezone(timedelta(hours=8))
    now = datetime.now(hk_tz)
    
    history = []
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = [l.strip() for l in f]

    # 1. 抓取突發及政治 (24小時監控)
    m_list, m_raw = fetch_news(MARITIME_KEYWORDS, history, "水警 OR 走私 OR 警方 OR 元朗")
    p_list, p_raw = fetch_news(POLITICS_KEYWORDS, history, "特朗普 伊朗 戰爭 OR 霍爾木茲海峽", limit=5)
    
    # 2. 08:00 大報告
    if now.hour == 8 and now.minute < 30:
        vol = get_volatility_indices()
        rep = [f"<b>📊 市場監控報告 ({now.strftime('%H:%M')})</b>"]
        rep.append(f"• VIX: {vol['VIX']:.2f} | VHSI: {vol['VHSI']:.2f}\n")
        rep.append("<b>【持倉 KDJ 監控】</b>")
        
        # 只抓取 Watchlist 相關新聞
        stock_queries = " OR ".join(WATCHLIST.values())
        f_list, f_raw = fetch_news(list(WATCHLIST.values()), history, stock_queries, limit=5)

        for s, name in WATCHLIST.items():
            t = yf.Ticker(s)
            price = t.history(period="1d")['Close'].iloc[-1]
            wk_k = get_kdj_val(s, "1wk")
            mo_k = get_kdj_val(s, "1mo")
            wk_s = f"🔥<b>{wk_k:.1f}</b>" if wk_k < 20 else f"{wk_k:.1f}"
            mo_s = f"💎<b>{mo_k:.1f}</b>" if mo_k < 20 else f"{mo_k:.1f}"
            rep.append(f"• {name}: <b>{price:.2f}</b> | 週:{wk_s} 月:{mo_s}")
        
        if f_list: rep.append(f"\n💰 <b>持倉相關新聞：</b>\n" + "\n".join(f_list))
        if p_list: rep.append(f"\n🌍 <b>美伊局勢：</b>\n" + "\n".join(p_list))
        if m_list: rep.append(f"\n⚓️ <b>突發焦點：</b>\n" + "\n".join(m_list[:5]))
        
        send_tg("\n".join(rep))
        all_new = m_raw + p_raw + f_raw
    else:
        # 日間即時推送 (突發/政治/持倉)
        # 額外檢查持倉相關即時新聞
        f_list, f_raw = fetch_news(list(WATCHLIST.values()), history, " OR ".join(WATCHLIST.values()), limit=3)
        urgent = m_list + p_list + f_list
        if urgent:
            send_tg(f"🔔 <b>即時情報 ({now.strftime('%H:%M')})</b>\n\n" + "\n\n".join(urgent))
        all_new = m_raw + p_raw + f_raw

    if all_new:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            for t in set(all_new): f.write(t + "\n")

def send_tg(msg):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                       data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=15)
    except: pass

if __name__ == "__main__":
    run_main()
