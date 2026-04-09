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
    "3466.HK": "恒生高息股", "0941.HK": "中移動",
    "0005.HK": "匯豐", "0939.HK": "建行", "VOO": "VOO", "QQQ": "QQQ"
}

# --- 徹底補完：執法、罪案、救援關鍵字 ---
ACTION_KEYWORDS = [
    "水警", "走私", "快艇", "大飛", "內河船", "小艇分區", "非法入境", "截獲", "私煙", "毒品", 
    "警方", "警察", "警員", "反爆竊", "拘捕", "偵破", "掃黃", "黑工", "淋紅油", "收數", 
    "跳海", "墮海", "自殺", "浮屍", "救起", "救生", "溺斃", "失蹤", "尋人", "撞船", "意外"
]

# --- 徹底補完：監控區域 ---
LOCATION_KEYWORDS = [
    "大嶼山", "南丫島", "長洲", "後海灣", "吐露港", "昂船洲", "青衣", "梅窩", 
    "大欖涌", "元朗", "屯門", "天水圍", "深水埗", "西貢", "荃灣", "灣仔"
]

# 政治與財經
POLITICS_KEYWORDS = ["特朗普", "川普", "伊朗", "美伊戰爭", "霍爾木茲海峽", "停火協議", "開火行動"]
EXCLUDE_KEYWORDS = ["2房", "3房", "沽出", "易手", "地產", "公屋", "成交", "零議價", "房委會", "美容", "食店", "雞蛋仔", "NBA", "足球"]

# --- 2. 指標計算 (VIX, KDJ) ---

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
        query = "水警 OR 走私 OR 警方 OR 警察 OR 跳海 OR 墮海 OR 拘捕"
    elif mode == "POLITICS":
        query = "特朗普 伊朗 戰爭"
    else: # FINANCE
        query = " OR ".join(WATCHLIST.values())

    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    found, raw_t = [], []
    
    try:
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.content, 'xml')
        for item in soup.find_all('item'):
            t = item.title.text
            src = item.source.text if item.source else "未知"
            if any(ex in t for ex in EXCLUDE_KEYWORDS): continue
            
            valid = False
            if mode == "MARITIME":
                # 關鍵邏輯：標題必須含有「動作」字眼
                if any(act in t for act in ACTION_KEYWORDS):
                    valid = True
            elif mode == "POLITICS":
                if any(pk in t for pk in POLITICS_KEYWORDS): valid = True
            else:
                if any(stock in t for stock in WATCHLIST.values()): valid = True

            if valid:
                clean = t.split(' - ')[0].strip()
                if not any(clean[:10] in h for h in history + raw_t):
                    emoji = "⚓️" if mode == "MARITIME" else "🌍" if mode == "POLITICS" else "💰"
                    found.append(f"{emoji} {clean} ({src})")
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
    
    status = {"last_p_date": str(now.date())}
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, "r") as f: status = json.load(f)
    p_active = (now.date() - datetime.strptime(status["last_p_date"], "%Y-%m-%d").date()).days <= 14

    m_list, m_raw = fetch_news_engine(hist, "MARITIME")
    p_list, p_raw = (fetch_news_engine(hist, "POLITICS") if p_active else ([], []))
    f_list, f_raw = fetch_news_engine(hist, "FINANCE")

    if p_list:
        status["last_p_date"] = str(now.date())
        with open(STATUS_FILE, "w") as f: json.dump(status, f)

    # 08:00 報告
    if now.hour == 8 and now.minute < 30:
        v_idx = get_market_indices()
        rep = [f"<b>📊 市場監控報告 ({now.strftime('%H:%M')})</b>"]
        rep.append(f"• VIX: {v_idx['VIX']:.2f} | VHSI: {v_idx['VHSI']:.2f}\n")
        rep.append("<b>【持倉 KDJ 監控】</b>")
        for s, name in WATCHLIST.items():
            t_obj = yf.Ticker(s)
            p = t_obj.history(period="1d")['Close'].iloc[-1]
            wk_v, mo_v = get_kdj_data(s, "1wk"), get_kdj_data(s, "1mo")
            wk_s = f"🔥<b>{wk_v:.1f}</b>" if wk_v < 20 else f"{wk_v:.1f}"
            mo_s = f"💎<b>{mo_v:.1f}</b>" if mo_v < 20 else f"{mo_v:.1f}"
            rep.append(f"• {name}: <b>{p:.2f}</b> | 週:{wk_s} 月:{mo_s}")
        if f_list: rep.append(f"\n💰 <b>持倉動態：</b>\n" + "\n".join(f_list))
        if p_list: rep.append(f"\n🌍 <b>美伊局勢：</b>\n" + "\n".join(p_list))
        if m_list: rep.append(f"\n⚓️ <b>突發焦點：</b>\n" + "\n".join(m_list))
        send_tg("\n".join(rep))
    else:
        # 日間通知
        urgent = m_list + p_list + f_list
        if urgent:
            send_tg(f"🔔 <b>即時情報 ({now.strftime('%H:%M')})</b>\n\n" + "\n\n".join(urgent))

    all_raw = m_raw + p_raw + f_raw
    if all_raw:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            for t in set(all_raw): f.write(t + "\n")

def send_tg(m):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": m, "parse_mode": "HTML"}, timeout=15)
    except: pass

if __name__ == "__main__":
    run_monitor()
