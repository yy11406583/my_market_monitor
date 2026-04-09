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

MARITIME_KEYWORDS = ["水警", "走私", "快艇", "大飛", "內河船", "小艇分區", "非法入境", "截獲", "大嶼山", "南丫島", "長洲", "後海灣", "海上意外", "墮海", "警方", "警察", "警員", "反爆竊", "失蹤", "元朗"]
POLITICS_KEYWORDS = ["特朗普", "川普", "伊朗", "美伊戰爭", "霍爾木茲海峽", "導彈"]

EXCLUDE_KEYWORDS = ["台東", "大馬", "日本", "澳洲", "川崎", "螺絲粉", "NBA", "台灣", "高雄", "台中"]
BLACKLIST_SOURCES = ["Yahoo運動", "LINE TODAY", "自由時報", "聯合報", "中時", "ETtoday"]

# --- 2. 核心計算 (VIX, KDJ, 股價) ---

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
        if len(df) < 9: return 50.0
        low = df['Low'].rolling(9).min()
        high = df['High'].rolling(9).max()
        rsv = (df['Close'] - low) / (high - low) * 100
        k = rsv.ewm(com=2, adjust=False).mean().iloc[-1]
        return k
    except: return 50.0

def get_stock_info(ticker):
    try:
        t = yf.Ticker(ticker)
        h = t.history(period="5d")
        price = h['Close'].iloc[-1]
        dy = 0.0
        # 簡易股息計算
        acts = t.actions
        if not acts.empty and 'Dividends' in acts:
            one_yr = pd.Timestamp.now(tz='UTC') - pd.Timedelta(days=365)
            acts.index = pd.to_datetime(acts.index).tz_convert('UTC')
            dy = (acts[acts.index > one_yr]['Dividends'].sum() / price * 100)
        return price, dy
    except: return 0.0, 0.0

# --- 3. 新聞過濾 ---

def fetch_safe_news(keywords, history, query, limit=10):
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    found, raw_t = [], []
    try:
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.content, 'xml')
        for item in soup.find_all('item'):
            t = item.title.text
            src = item.source.text if item.source else "未知"
            if any(ex in t for ex in EXCLUDE_KEYWORDS) or any(bl in src for bl in BLACKLIST_SOURCES): continue
            if any(k in t for k in keywords):
                clean = t.split(' - ')[0].strip()
                # 強化重覆檢查 (前10個字)
                if not any(clean[:10] in h for h in history + raw_t):
                    found.append(f"{clean} ({src})")
                    raw_t.append(t)
            if len(found) >= limit: break
    except: pass
    return found, raw_t

# --- 4. 執行邏輯 ---

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

    # 14日政治新聞期限檢查
    last_p = datetime.strptime(status["last_p_date"], "%Y-%m-%d").date()
    p_active = (now.date() - last_p).days <= 14

    # 執行新聞抓取
    m_list, m_raw = fetch_safe_news(MARITIME_KEYWORDS, hist, "水警 OR 走私 OR 警方 OR 元朗")
    p_list, p_raw = (fetch_safe_news(POLITICS_KEYWORDS, hist, "特朗普 伊朗 戰爭", limit=5) if p_active else ([], []))
    # 財經只搜持倉股名
    stock_q = " OR ".join(WATCHLIST.values())
    f_list, f_raw = fetch_safe_news(list(WATCHLIST.values()), hist, stock_q, limit=5)

    # 更新政治時間
    if p_list:
        status["last_p_date"] = str(now.date())
        with open(STATUS_FILE, "w") as f: json.dump(status, f)

    # A. 08:00 市場大報告
    if now.hour == 8 and now.minute < 30:
        v_idx = get_v_indices()
        rep = [f"<b>📊 市場監控報告 ({now.strftime('%H:%M')})</b>"]
        rep.append(f"• VIX: {v_idx['VIX']:.2f} | VHSI: {v_idx['VHSI']:.2f}\n")
        rep.append("<b>【持倉 KDJ 監控】</b>")
        for s, name in WATCHLIST.items():
            price, dy = get_stock_info(s)
            wk_v, mo_v = get_kdj(s, "1wk"), get_kdj(s, "1mo")
            wk_s = f"🔥<b>{wk_v:.1f}</b>" if wk_v < 20 else f"{wk_v:.1f}"
            mo_s = f"💎<b>{mo_v:.1f}</b>" if mo_v < 20 else f"{mo_v:.1f}"
            rep.append(f"• {name}: <b>{price:.2f}</b> (息:{dy:.1f}%) | 週:{wk_s} 月:{mo_s}")
        
        if f_list: rep.append(f"\n💰 <b>持倉動態：</b>\n" + "\n".join(f_list))
        if p_list: rep.append(f"\n🌍 <b>美伊局勢：</b>\n" + "\n".join(p_list))
        if m_list: rep.append(f"\n⚓️ <b>突發焦點：</b>\n" + "\n".join(m_list[:5]))
        send_tg("\n".join(rep))
        all_news = m_raw + p_raw + f_raw
    else:
        # B. 日間即時通知 (水警/政治/持倉)
        urgent = [f"⚓️ {x}" for x in m_list] + [f"🌍 {x}" for x in p_list] + [f"💰 {x}" for x in f_list]
        if urgent:
            send_tg(f"🔔 <b>即時情報 ({now.strftime('%H:%M')})</b>\n\n" + "\n\n".join(urgent))
        all_news = m_raw + p_raw + f_raw

    # 紀錄歷史
    if all_news:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            for t in set(all_news): f.write(t + "\n")

def send_tg(m):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": m, "parse_mode": "HTML"}, timeout=15)
    except: pass

if __name__ == "__main__":
    run_main()
