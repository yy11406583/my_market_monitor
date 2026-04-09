import yfinance as yf
import requests
import pandas as pd
import os
import json
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup
import urllib.parse

# --- 1. 配置區 ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
HISTORY_FILE = "sent_news.txt"
STATUS_FILE = "monitor_status.json"

WATCHLIST = {
    "3466.HK": "恒生高息股", "0941.HK": "中移動",
    "0005.HK": "匯豐", "0939.HK": "建行", "VOO": "VOO", "QQQ": "QQQ"
}

# 執法、救援與【毒品】關鍵字 (全集)
ACTION_KEYWORDS = [
    "水警", "走私", "快艇", "大飛", "內河船", "截獲", "警方", "警察", "警員", 
    "拘捕", "偵破", "淋紅油", "跳海", "墮海", "浮屍", "救起", "失蹤",
    "毒品", "大麻", "冰毒", "可卡因", "海洛英", "吸毒", "販毒", "毒梟", "製毒"
]

# 僅限香港相關地名 (確保與動作連結)
HK_LOCATIONS = ["大嶼山", "南丫島", "長洲", "後海灣", "吐露港", "昂船洲", "青衣", "梅窩", "大欖涌", "元朗", "屯門", "天水圍", "深水埗", "西貢", "荃灣", "灣仔", "香港"]

# 戰爭精確字眼
WAR_KEYWORDS = ["伊朗戰爭", "美以伊戰爭", "美伊戰爭", "以伊戰爭"]

# 雜訊排除
EXCLUDE_KEYWORDS = ["2房", "沽出", "地產", "美容", "雞蛋仔", "NBA", "足球", "日本警察", "印度", "柬埔寨", "安徽"]

# --- 2. 數據計算 ---

def get_market_indices():
    res = {"VIX": 0.0, "VHSI": 0.0}
    try:
        res["VIX"] = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
        v_df = yf.Ticker("^VHSI").history(period="30d")
        if not v_df.empty:
            valid = v_df['Close'][v_df['Close'] > 0]
            if not valid.empty: res["VHSI"] = valid.iloc[-1]
    except: pass
    return res

def get_kdj_data(ticker, interval):
    try:
        df = yf.Ticker(ticker).history(period="2y", interval=interval)
        low, high = df['Low'].rolling(9).min(), df['High'].rolling(9).max()
        rsv = (df['Close'] - low) / (high - low) * 100
        k = rsv.ewm(com=2, adjust=False).mean().iloc[-1]
        return k
    except: return 50.0

# --- 3. 新聞過濾引擎 ---

def fetch_news_engine(history, mode="MARITIME"):
    if mode == "MARITIME":
        # 增加毒品相關搜尋詞
        query = "水警 OR 走私 OR 警方 OR 警察 OR 跳海 OR 毒品 OR 販毒"
    elif mode == "WAR":
        query = " OR ".join([f'"{k}"' for k in WAR_KEYWORDS])
    else: # FINANCE
        query = " OR ".join(WATCHLIST.values())

    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    found, raw_t = [], []
    
    try:
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.content, 'xml')
        for item in soup.find_all('item'):
            t = item.title.text
            if any(ex in t for ex in EXCLUDE_KEYWORDS): continue
            
            valid = False
            if mode == "MARITIME":
                # 必須有動作字眼（含毒品）且涉及香港地名
                if any(act in t for act in ACTION_KEYWORDS) and any(loc in t for loc in HK_LOCATIONS):
                    valid = True
            elif mode == "WAR":
                if any(wk in t for wk in WAR_KEYWORDS): valid = True
            elif mode == "FINANCE":
                if any(stock in t for stock in WATCHLIST.values()): valid = True

            if valid:
                clean = t.split(' - ')[0].strip()
                if not any(clean[:10] in h for h in history + raw_t):
                    emoji = "⚓️" if mode == "MARITIME" else "🌍" if mode == "WAR" else "💰"
                    found.append(f"{emoji} {clean}")
                    raw_t.append(t)
            if len(found) >= 10: break
    except: pass
    return found, raw_t

# --- 4. 主流程 ---

def run_monitor():
    hk_tz = timezone(timedelta(hours=8))
    now = datetime.now(hk_tz)
    
    hist = []
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f: hist = [l.strip() for l in f]

    m_list, m_raw = fetch_news_engine(hist, "MARITIME")
    w_list, w_raw = fetch_news_engine(hist, "WAR")
    f_list, f_raw = fetch_news_engine(hist, "FINANCE")

    # 08:00 綜合報告
    if now.hour == 8 and now.minute < 30:
        v_idx = get_market_indices()
        rep = [f"<b>📊 市場監控報告 ({now.strftime('%H:%M')})</b>"]
        rep.append(f"• VIX: {v_idx['VIX']:.2f} | VHSI: {v_idx['VHSI']:.2f}\n")
        rep.append("<b>【持倉 KDJ 監控】</b>")
        for s, name in WATCHLIST.items():
            t_obj = yf.Ticker(s)
            p = t_obj.history(period="1d")['Close'].iloc[-1]
            wk_v, mo_v = get_kdj_data(s, "1wk"), get_kdj_data(s, "1mo")
            rep.append(f"• {name}: <b>{p:.2f}</b> | 週:{wk_v:.1f} 月:{mo_v:.1f}")
        
        if f_list: rep.append(f"\n💰 <b>持倉動態：</b>\n" + "\n".join(f_list))
        if w_list: rep.append(f"\n🌍 <b>戰爭局勢：</b>\n" + "\n".join(w_list))
        if m_list: rep.append(f"\n⚓️ <b>突發焦點：</b>\n" + "\n".join(m_list))
        send_tg("\n".join(rep))
    else:
        # 日間通知：剔除💰，保留⚓️和🌍
        urgent = m_list + w_list
        if urgent:
            send_tg(f"🔔 <b>即時情報 ({now.strftime('%H:%M')})</b>\n\n" + "\n\n".join(urgent))

    all_raw = m_raw + w_raw + f_raw
    if all_raw:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            for t in set(all_raw): f.write(t + "\n")

def send_tg(m):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": m, "parse_mode": "HTML"}, timeout=15)
    except: pass

if __name__ == "__main__":
    run_monitor()
