import yfinance as yf
import akshare as ak
import requests
import os
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from bs4 import BeautifulSoup
import urllib.parse
from difflib import SequenceMatcher

# ==================== 1. 配置區 ====================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
HISTORY_FILE = "sent_news.txt"
LINK_HISTORY_FILE = "sent_links.txt"
MAX_HISTORY_DAYS = 7

WATCHLIST = {
    "3466.HK": "恒生高息股", "0941.HK": "中移動",
    "0005.HK": "匯豐", "0939.HK": "建行", "VOO": "VOO", "QQQ": "QQQ"
}

HARD_ACTIONS = [
    "走私", "截獲", "拘捕", "偵破", "跳海", "墮海", "浮屍", "救起", "毒品", "販毒",
    "搶劫", "劫案", "贓款", "開火", "封鎖", "現場", "衝擊", "搜索", "查獲",
    "檢獲", "搗破", "瓦解", "通緝", "命案", "車禍", "受傷", "強姦", "非禮", "失蹤"
]
POLICE_KEYWORDS = ["水警", "警方", "警察", "警員"]
WAR_KEYWORDS = ["伊朗戰爭", "美以伊戰爭", "美伊戰爭", "以伊戰爭"]

# 外地排除黑名單（新增澳門、新疆等，防止外地警察新聞誤報）
GLOBAL_EXCLUDE = [
    "日本", "台灣", "台北", "高雄", "柬埔寨", "馬來西亞", "泰國", "新加坡",
    "安徽", "廣州", "深圳", "珠海", "上海", "北京", "天津", "重慶", "成都",
    "印度", "韓國", "加拿大", "美國", "英國", "澳洲", "新西蘭",
    "內地", "大陸", "中國內地", "中国内地",
    "澳門", "澳门", "新疆", "西藏"
]

# 噪音排除（新增就職、儀式、外媒，剔除公關類、政治敏感類內容）
NOISE_EXCLUDE = [
    "年報", "招募", "推廣", "App", "課程", "演習", "比賽", "典禮", "講座",
    "展覽", "慶祝", "紀念", "心得", "分享", "投考", "委任", "晉升", "2房",
    "沽出", "地產", "警察隊員佐級協會", "警察儲蓄互助社", "遮仔會",
    "就職", "儀式", "法新社", "路透社"
]

# ==================== 2. 輔助函數 ====================

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
        # 如果前 10 個中文字完全一樣，直接判定為重複
        if new_norm[:10] == old_norm[:10]: return True
        # 相似度閾值 0.65
        if SequenceMatcher(None, new_norm, old_norm).ratio() > 0.65: return True
    return False

def send_tg(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
        requests.post(url, data=payload, timeout=15)
    except: pass

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
                    if now - datetime.fromisoformat(ts_str) <= timedelta(days=MAX_HISTORY_DAYS):
                        valid.append(content)
                else: valid.append(line)
    except: pass
    return valid[-300:]

def save_history(file_path, items):
    hk_tz = timezone(timedelta(hours=8))
    now = datetime.now(hk_tz).isoformat()
    with open(file_path, "a", encoding="utf-8") as f:
        for item in items: f.write(f"{now}||{item}\n")

# ==================== 3. 數據抓取邏輯 ====================

def get_market_indices():
    res = {"VIX": 0.0, "VHSI": 0.0}
    # VIX (yfinance)
    for _ in range(3):
        try:
            v_val = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
            if v_val > 0:
                res["VIX"] = v_val
                break
        except: time.sleep(2)

    # VHSI (akshare)
    for _ in range(3):
        try:
            df = ak.index_vhsi()
            if not df.empty:
                col = ('close' if 'close' in df.columns 
                       else '收盤價' if '收盤價' in df.columns 
                       else df.columns[-1])
                val = df[col].iloc[-1]
                if val > 0:
                    res["VHSI"] = val
                    break
        except: time.sleep(2)
    return res

def get_kdj_data(ticker, interval):
    for _ in range(3):
        try:
            df = yf.Ticker(ticker).history(period="2y", interval=interval)
            low = df['Low'].rolling(9).min()
            high = df['High'].rolling(9).max()
            rsv = (df['Close'] - low) / (high - low) * 100
            k = rsv.ewm(com=2, adjust=False).mean().iloc[-1]
            return k
        except: time.sleep(1)
    return 50.0

def fetch_news_engine(mode, title_history, link_history):
    if mode == "MARITIME":
        query = "水警 OR 走私 OR 警察 OR 毒品 OR 劫案"
    elif mode == "WAR":
        query = " OR ".join([f'"{k}"' for k in WAR_KEYWORDS])
    else:
        query = " OR ".join(WATCHLIST.values())

    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    found, current_titles, current_links = [], [], []
    hk_now = datetime.now(timezone(timedelta(hours=8)))
    is_daytime = (8 <= hk_now.hour < 23)

    try:
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.content, 'xml')
        for item in soup.find_all('item'):
            title = item.title.text.split(' - ')[0].strip()
            link = item.link.text if item.link else ""

            # 1. 基礎過濾
            if link in link_history: continue
            if any(ex in title for ex in NOISE_EXCLUDE): continue

            # 2. 時效性：24 小時內
            pub_date_tag = item.pubDate
            if pub_date_tag:
                try:
                    pub_date = parsedate_to_datetime(pub_date_tag.text)
                    if pub_date.tzinfo is None:
                        pub_date = pub_date.replace(tzinfo=timezone(timedelta(hours=8)))
                    if hk_now - pub_date > timedelta(hours=24):
                        continue
                except: pass

            # 3. AI 語意去重
            keep_en = (mode == "FINANCE")
            if is_duplicate_ai(title, title_history + current_titles, keep_en): continue

            valid = False
            if mode == "MARITIME":
                # 外地排除
                if any(gx in title for gx in GLOBAL_EXCLUDE): continue
                
                has_authority = any(pk in title for pk in POLICE_KEYWORDS)
                has_action = any(ha in title for ha in HARD_ACTIONS)
                
                if has_authority:
                    if is_daytime: valid = True 
                    elif has_action: valid = True
            
            elif mode == "WAR":
                if any(wk in title for wk in WAR_KEYWORDS) and any(
                        v in title for v in ["談判", "開火", "停火", "協議", "簽署", "死", "擊落"]):
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

# ==================== 4. 主程序運行 ====================

def run_monitor():
    hk_tz = timezone(timedelta(hours=8))
    now = datetime.now(hk_tz)

    t_hist = load_history(HISTORY_FILE)
    l_hist = load_history(LINK_HISTORY_FILE)

    m_news, m_t, m_l = fetch_news_engine("MARITIME", t_hist, l_hist)
    f_news, f_t, f_l = fetch_news_engine("FINANCE", t_hist, l_hist)
    w_news_all, w_t_all, w_l_all = fetch_news_engine("WAR", t_hist, l_hist)

    # 戰爭新聞睡覺過濾
    w_news, w_t, w_l = [], [], []
    is_sleep_time = (now.hour >= 23 or now.hour < 8)
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
            price_val = 0.0
            for _ in range(3):
                try:
                    p_data = yf.Ticker(sym).history(period="1d")
                    if not p_data.empty:
                        price_val = p_data['Close'].iloc[-1]
                        break
                except: time.sleep(1)
            report.append(f"• {name}: <b>{price_val:.2f}</b> | 週:{get_kdj_data(sym, '1wk'):.1f} 月:{get_kdj_data(sym, '1mo'):.1f}")
        
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
