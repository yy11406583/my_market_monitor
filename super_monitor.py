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

# 財經：移除盈富基金
WATCHLIST = {
    "3466.HK": "恒生高息股", "0941.HK": "中移動",
    "0005.HK": "匯豐", "0939.HK": "建行", "VOO": "VOO", "QQQ": "QQQ"
}

# 核心動作字眼 (必須包含其中之一)
ACTION_KEYWORDS = ["水警", "走私", "快艇", "大飛", "非法入境", "截獲", "警方", "警察", "警員", "反爆竊", "墮海", "淋紅油", "拘捕", "偵破"]

# 連結地名 (僅作為輔助匹配)
LOCATION_KEYWORDS = ["大嶼山", "南丫島", "長洲", "後海灣", "吐露港", "昂船洲", "元朗", "屯門", "梅窩", "大欖涌", "深水埗"]

# 政治：美伊戰爭主線
POLITICS_KEYWORDS = ["特朗普", "川普", "伊朗", "美伊戰爭", "霍爾木茲海峽", "停火協議"]

# 排除名單 (地產、美容、生活雜訊)
EXCLUDE_KEYWORDS = ["2房", "3房", "沽出", "易手", "地產", "公屋", "成交", "零議價", "房委會", "美容", "食店", "雞蛋仔", "NBA", "足球", "螺絲粉", "台灣", "高雄"]

# --- 2. 核心計算 ---

def get_v_indices():
    res = {"VIX": 0.0, "VHSI": 0.0}
    try:
        res["VIX"] = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
        v_df = yf.Ticker("^VHSI").history(period="30d")
        if not v_df.empty:
            valid = v_df['Close'][v_df['Close'] > 0]
            if not valid.empty: res["VHSI"] = valid.iloc[-1]
    except: pass
    return res

def get_kdj(ticker, interval):
    try:
        df = yf.Ticker(ticker).history(period="2y", interval=interval)
        low, high = df['Low'].rolling(9).min(), df['High'].rolling(9).max()
        rsv = (df['Close'] - low) / (high - low) * 100
        k = rsv.ewm(com=2, adjust=False).mean().iloc[-1]
        return k
    except: return 50.0

# --- 3. 強化版新聞過濾 ---

def fetch_safe_news(history, mode="MARITIME"):
    # 根據模式設定搜尋字眼
    if mode == "MARITIME":
        query = "水警 OR 走私 OR 警方 OR 警察"
        target_keywords = ACTION_KEYWORDS + LOCATION_KEYWORDS
    elif mode == "POLITICS":
        query = "特朗普 伊朗 戰爭"
        target_keywords = POLITICS_KEYWORDS
    else: # FINANCE
        query = " OR ".join(WATCHLIST.values())
        target_keywords = list(WATCHLIST.values())

    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    found, raw_t = [], []
    
    try:
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.content, 'xml')
        for item in soup.find_all('item'):
            t = item.title.text
            src = item.source.text if item.source else "未知"
            
            # 1. 基本排除
            if any(ex in t for ex in EXCLUDE_KEYWORDS): continue
            
            # 2. 邏輯校驗
            is_valid = False
            if mode == "MARITIME":
                # 必須包含「動作」關鍵字，不能只有地名
                if any(act in t for act in ACTION_KEYWORDS):
                    is_valid = True
            else:
                if any(tk in t for tk in target_keywords):
                    is_valid = True

            if is_valid:
                clean = t.split(' - ')[0].strip()
                # 3. 去重 (標題前10字)
                if not any(clean[:10] in h for h in history + raw_t):
                    emoji = "⚓️" if mode == "MARITIME" else "🌍" if mode == "POLITICS" else "💰"
                    found.append(f"{emoji} {clean} ({src})")
                    raw_t.append(t)
            
            if len(found) >= 8: break
    except: pass
    return found, raw_t

# --- 4. 運行 ---

def run_main():
    hk_tz = timezone(timedelta(hours=8))
    now = datetime.now(hk_tz)
    
    # 加載歷史與狀態
    hist = []
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f: hist = [l.strip() for l in f]
    
    status = {"last_p_date": str(now.date())}
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, "r") as f: status = json.load(f)

    # 執行分類抓取
    m_list, m_raw = fetch_safe_news(hist, "MARITIME")
    
    p_active = (now.date() - datetime.strptime(status["last_p_date"], "%Y-%m-%d").date()).days <= 14
    p_list, p_raw = (fetch_safe_news(hist, "POLITICS") if p_active else ([], []))
    if p_list:
        status["last_p_date"] = str(now.date())
        with open(STATUS_FILE, "w") as f: json.dump(status, f)

    f_list, f_raw = fetch_safe_news(hist, "FINANCE")

    # A. 08:00 市場大報告
    if now.hour == 8 and now.minute < 30:
        v_idx = get_v_indices()
        rep = [f"<b>📊 市場監控報告 ({now.strftime('%H:%M')})</b>"]
        rep.append(f"• VIX: {v_idx['VIX']:.2f} | VHSI: {v_idx['VHSI']:.2f}\n")
        rep.append("<b>【持倉 KDJ 監控】</b>")
        for s, name in WATCHLIST.items():
            t_obj = yf.Ticker(s)
            price = t_obj.history(period="1d")['Close'].iloc[-1]
            wk_v, mo_v = get_kdj(s, "1wk"), get_kdj(s, "1mo")
            rep.append(f"• {name}: <b>{price:.2f}</b> | 週:{wk_v:.1f} 月:{mo_v:.1f}")
        
        if f_list: rep.append(f"\n💰 <b>持倉動態：</b>\n" + "\n".join(f_list))
        if p_list: rep.append(f"\n🌍 <b>美伊局勢：</b>\n" + "\n".join(p_list))
        if m_list: rep.append(f"\n⚓️ <b>突發焦點：</b>\n" + "\n".join(m_list))
        send_tg("\n".join(rep))
    else:
        # B. 日間通知
        urgent = m_list + p_list + f_list
        if urgent:
            send_tg(f"🔔 <b>即時情報 ({now.strftime('%H:%M')})</b>\n\n" + "\n\n".join(urgent))

    # 紀錄
    all_raw = m_raw + p_raw + f_raw
    if all_raw:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            for t in set(all_raw): f.write(t + "\n")

def send_tg(m):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                       data={"chat_id": CHAT_ID, "text": m, "parse_mode": "HTML"}, timeout=15)
    except: pass

if __name__ == "__main__":
    run_main()
