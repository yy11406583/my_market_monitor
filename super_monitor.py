import yfinance as yf
import requests
import os
import re
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup
import urllib.parse
from difflib import SequenceMatcher

# --- 配置區 ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
HISTORY_FILE = "sent_news.txt"
LINK_HISTORY_FILE = "sent_links.txt"
MAX_HISTORY_DAYS = 7  # 歷史記錄保留天數

WATCHLIST = {
    "3466.HK": "恒生高息股", "0941.HK": "中移動",
    "0005.HK": "匯豐", "0939.HK": "建行", "VOO": "VOO", "QQQ": "QQQ"
}

ACTION_KEYWORDS = ["水警", "走私", "快艇", "大飛", "截獲", "警方", "警察", "警員", "拘捕", "偵破", "淋紅油", "跳海", "墮海", "浮屍", "救起", "失蹤", "毒品", "販毒", "吸毒", "大麻", "冰毒", "可卡因", "海洛英", "搶劫", "劫案", "氣槍", "贓款"]
HK_LOCATIONS = ["大嶼山", "南丫島", "長洲", "後海灣", "吐露港", "昂船洲", "青衣", "梅窩", "大欖涌", "元朗", "屯門", "天水圍", "深水埗", "西貢", "荃灣", "灣仔", "香港", "柴灣", "機場", "告士打道"]
WAR_KEYWORDS = ["伊朗戰爭", "美以伊戰爭", "美伊戰爭", "以伊戰爭"]

GLOBAL_EXCLUDE = ["日本", "台灣", "台北", "柬埔寨", "馬來西亞", "泰國", "安徽", "廣州", "深圳", "印度", "韓國", "加拿大", "上海"]
NOISE_EXCLUDE = ["2房", "沽出", "地產", "美容", "雞蛋仔", "NBA", "足球", "食評", "監控流出", "有片", "黑衫變白T"]

# --- 1. 輔助函數 ---

def normalize_title(title, keep_alphanum=False):
    noise = ["突發", "有片", "更新", "最新", "快訊", "即時", "圖輯", "多圖"]
    for p in noise:
        title = title.replace(p, "")
    if keep_alphanum:
        title = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]+", " ", title)
    else:
        title = re.sub(r"[^\u4e00-\u9fa5]+", "", title)
    return title.strip().lower()

def is_duplicate_ai(new_title, pool, keep_en=False):
    new_norm = normalize_title(new_title, keep_alphanum=keep_en)
    if not new_norm: return False
    for old in pool:
        old_norm = normalize_title(old, keep_alphanum=keep_en)
        if not old_norm: continue
        if new_norm[:10] == old_norm[:10]: return True
        if SequenceMatcher(None, new_norm, old_norm).ratio() > 0.65: return True
    return False

def send_tg(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
        requests.post(url, data=payload, timeout=15)
    except:
        pass

# --- 2. 數據獲取與管理 ---

def load_history(file_path):
    if not os.path.exists(file_path): return []
    valid = []
    now = datetime.now(timezone(timedelta(hours=8)))
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "||" in line:
                    ts_str, content = line.split("||", 1)
                    # 自動清理超過 7 天的舊記錄
                    if now - datetime.fromisoformat(ts_str) <= timedelta(days=MAX_HISTORY_DAYS):
                        valid.append(content)
                else:
                    valid.append(line)
    except: pass
    return valid[-300:]

def save_history(file_path, items):
    hk_tz = timezone(timedelta(hours=8))
    now = datetime.now(hk_tz).isoformat()
    with open(file_path, "a", encoding="utf-8") as f:
        for item in items:
            f.write(f"{now}||{item}\n")

def get_market_indices():
    res = {"VIX": 0.0, "VHSI": 0.0}
    try:
        res["VIX"] = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
        v_hist = yf.Ticker("^VHSI").history(period="7d")
        if not v_hist.empty:
            valid = v_hist['Close'][v_hist['Close'] > 0]
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

# --- 3. 新聞引擎 ---

def fetch_news_engine(mode, title_history, link_history):
    if mode == "MARITIME": query = "水警 OR 走私 OR 警方 OR 警察 OR 毒品 OR 劫案"
    elif mode == "WAR": query = " OR ".join([f'"{k}"' for k in WAR_KEYWORDS])
    else: query = " OR ".join(WATCHLIST.values())

    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    found, current_titles, current_links = [], [], []

    try:
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.content, 'xml')
        for item in soup.find_all('item'):
            title = item.title.text.split(' - ')[0].strip()
            link = item.link.text if item.link else ""
            if link in link_history: continue
            if any(ex in title for ex in NOISE_EXCLUDE): continue
            if mode == "MARITIME" and any(gx in title for gx in GLOBAL_EXCLUDE): continue

            keep_en = (mode == "FINANCE")
            if is_duplicate_ai(title, title_history + current_titles, keep_en): continue

            valid = False
            if mode == "MARITIME":
                if any(act in title for act in ACTION_KEYWORDS) and any(loc in title for loc in HK_LOCATIONS):
                    valid = True
            elif mode == "WAR":
                if any(wk in title for wk in WAR_KEYWORDS) and any(v in title for v in ["談判", "開火", "停火", "死", "擊落"]):
                    valid = True
            elif mode == "FINANCE":
                if any(stock in title for stock in WATCHLIST.values()):
                    valid = True

            if valid:
                emoji = "⚓️" if mode == "MARITIME" else "🌍" if mode == "WAR" else "💰"
                found.append(f"{emoji} {title}")
                current_titles.append(title)
                if link: current_links.append(link)
            if len(found) >= 4: break
    except: pass
    return found, current_titles, current_links

# --- 4. 主程序 ---

def run_monitor():
    hk_tz = timezone(timedelta(hours=8))
    now = datetime.now(hk_tz)
    is_sleep_time = (now.hour >= 23 or now.hour < 8)

    t_hist = load_history(HISTORY_FILE)
    l_hist = load_history(LINK_HISTORY_FILE)

    m_news, m_t, m_l = fetch_news_engine("MARITIME", t_hist, l_hist)
    f_news, f_t, f_l = fetch_news_engine("FINANCE", t_hist, l_hist)
    w_news_all, w_t_all, w_l_all = fetch_news_engine("WAR", t_hist, l_hist)

    w_news, w_t, w_l = [], [], []
    for i, news in enumerate(w_news_all):
        if is_sleep_time:
            if any(k in news for k in ["核", "爆發", "緊急", "開火"]):
                w_news.append(news); w_t.append(w_t_all[i]); w_l.append(w_l_all[i])
        else:
            w_news.append(news); w_t.append(w_t_all[i]); w_l.append(w_l_all[i])

    if now.hour == 8 and now.minute < 30:
        v_idx = get_market_indices()
        report = [f"<b>📊 市場監控報告 ({now.strftime('%H:%M')})</b>"]
        report.append(f"• VIX: {v_idx['VIX']:.2f} | VHSI: {v_idx['VHSI']:.2f}\n")
        report.append("<b>【持倉 KDJ】</b>")
        for sym, name in WATCHLIST.items():
            try:
                # 修正：變量名統一為 p
                p = yf.Ticker(sym).history(period="1d")['Close'].iloc[-1]
            except:
                p = 0.0
            report.append(f"• {name}: <b>{p:.2f}</b> | 週:{get_kdj_data(sym, '1wk'):.1f} 月:{get_kdj_data(sym, '1mo'):.1f}")
        
        if f_news: report.append(f"\n💰 <b>持倉動態：</b>\n" + "\n".join(f_news))
        if w_news: report.append(f"\n🌍 <b>戰爭局勢：</b>\n" + "\n".join(w_news))
        if m_news: report.append(f"\n⚓️ <b>突發焦點：</b>\n" + "\n".join(m_news))
        send_tg("\n".join(report))
    else:
        urgent = m_news + w_news
        if urgent:
            send_tg(f"🔔 <b>即時情報 ({now.strftime('%H:%M')})</b>\n\n" + "\n\n".join(urgent))

    save_history(HISTORY_FILE, m_t + w_t + f_t)
    save_history(LINK_HISTORY_FILE, m_l + w_l + f_l)

if __name__ == "__main__":
    run_monitor()
