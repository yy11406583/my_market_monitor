import yfinance as yf
import requests
import os
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup
import urllib.parse
from difflib import SequenceMatcher

# --- 1. 配置區 ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
HISTORY_FILE = "sent_news.txt"

WATCHLIST = {
    "3466.HK": "恒生高息股", "0941.HK": "中移動",
    "0005.HK": "匯豐", "0939.HK": "建行", "VOO": "VOO", "QQQ": "QQQ"
}

# 執法與救援關鍵字 (包含毒品、搶劫、水警)
ACTION_KEYWORDS = ["水警", "走私", "快艇", "大飛", "截獲", "警方", "警察", "警員", "拘捕", "偵破", "淋紅油", "跳海", "墮海", "浮屍", "救起", "失蹤", "毒品", "販毒", "搶劫", "劫案", "氣槍", "贓款"]
HK_LOCATIONS = ["大嶼山", "南丫島", "長洲", "後海灣", "吐露港", "昂船洲", "青衣", "梅窩", "大欖涌", "元朗", "屯門", "天水圍", "深水埗", "西貢", "荃灣", "灣仔", "香港", "柴灣", "機場"]
WAR_KEYWORDS = ["伊朗戰爭", "美以伊戰爭", "美伊戰爭", "以伊戰爭"]

# 嚴格排除
GLOBAL_EXCLUDE = ["日本", "台灣", "台北", "柬埔寨", "馬來西亞", "泰國", "安徽", "廣州", "深圳", "印度", "韓國", "加拿大"]
NOISE_EXCLUDE = ["2房", "沽出", "地產", "美容", "雞蛋仔", "NBA", "足球", "食評", "監控流出"]

# --- 2. 數據修復與計算 ---

def get_market_indices():
    res = {"VIX": 0.0, "VHSI": 0.0}
    try:
        # VIX
        res["VIX"] = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
        # VHSI 數據修復邏輯 (若今日為0，回溯最多7天尋找有效值)
        v_data = yf.Ticker("^VHSI").history(period="7d")
        if not v_data.empty:
            valid_vals = v_data['Close'][v_data['Close'] > 0]
            if not valid_vals.empty:
                res["VHSI"] = valid_vals.iloc[-1]
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

# --- 3. 內置「AI式」去重邏輯 (免費且高效) ---

def is_duplicate(new_title, pool):
    """
    使用模糊匹配算法，防止同一個事件(如灣仔劫案)以不同標題重複推送。
    """
    for h in pool:
        # 1. 前綴匹配 (前10個字一樣就當重複)
        if new_title[:10] in h or h[:10] in new_title: return True
        # 2. 相似度匹配 (超過 0.5 相似度即過濾)
        if SequenceMatcher(None, new_title, h).ratio() > 0.5: return True
    return False

def fetch_news_engine(history, mode="MARITIME"):
    if mode == "MARITIME":
        query = "水警 OR 走私 OR 警方 OR 警察 OR 毒品 OR 劫案"
    elif mode == "WAR":
        query = " OR ".join([f'"{k}"' for k in WAR_KEYWORDS])
    else: # FINANCE
        query = " OR ".join(WATCHLIST.values())

    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    found, current_pool = [], []
    
    try:
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.content, 'xml')
        for item in soup.find_all('item'):
            t = item.title.text
            clean = t.split(' - ')[0].strip()
            
            # 過濾雜訊與非本地新聞
            if any(ex in clean for ex in NOISE_EXCLUDE): continue
            if mode == "MARITIME" and any(gx in clean for gx in GLOBAL_EXCLUDE): continue
            
            # 強力去重
            if is_duplicate(clean, history + current_pool): continue
            
            valid = False
            if mode == "MARITIME":
                if any(act in clean for act in ACTION_KEYWORDS) and any(loc in clean for loc in HK_LOCATIONS):
                    valid = True
            elif mode == "WAR":
                if any(wk in clean for wk in WAR_KEYWORDS):
                    # 戰爭新聞二次篩選：只抓有動態進展的
                    if any(v in clean for v in ["談判", "開火", "停火", "死", "擊落", "關鎖", "協議", "賠償"]):
                        valid = True
            elif mode == "FINANCE":
                if any(stock in clean for stock in WATCHLIST.values()):
                    valid = True

            if valid:
                emoji = "⚓️" if mode == "MARITIME" else "🌍" if mode == "WAR" else "💰"
                found.append(f"{emoji} {clean}")
                current_pool.append(clean)
            
            if len(found) >= 3: break # 每類僅取前3條最關鍵的
    except: pass
    return found, current_pool

# --- 4. 執行流程 ---

def run_monitor():
    hk_tz = timezone(timedelta(hours=8))
    now = datetime.now(hk_tz)
    hr = now.hour
    
    # 睡眠模式：23:00 - 08:00
    is_sleep_time = (hr >= 23 or hr < 8)

    hist = []
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            hist = [l.strip() for l in f][-150:] # 擴大對比池到150條

    m_list, m_raw = fetch_news_engine(hist, "MARITIME")
    f_list, f_raw = fetch_news_engine(hist, "FINANCE")
    
    # 戰爭新聞處理
    w_list_all, w_raw = fetch_news_engine(hist, "WAR")
    w_list = []
    if is_sleep_time:
        # 睡眠時間：僅限極端突發
        for n in w_list_all:
            if any(k in n for k in ["核", "爆發", "緊急", "開火"]): w_list.append(n)
    else:
        w_list = w_list_all

    # 08:00 綜合報告
    if hr == 8 and now.minute < 30:
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
        # 日間即時通知 (不含財經)
        urgent = m_list + w_list
        if urgent:
            send_tg(f"🔔 <b>即時情報 ({now.strftime('%H:%M')})</b>\n\n" + "\n\n".join(urgent))

    # 存入歷史
    all_raw = m_raw + w_raw + f_raw
    if all_raw:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            for t in all_raw: f.write(t + "\n")

def send_tg(m):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                       data={"chat_id": CHAT_ID, "text": m, "parse_mode": "HTML"}, timeout=15)
    except: pass

if __name__ == "__main__":
    run_monitor()
