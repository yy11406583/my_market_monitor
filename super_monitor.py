import yfinance as yf
import pandas_ta as ta
import requests
import time
import pandas as pd
import google.generativeai as genai
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# --- 設定區 ---
TELEGRAM_TOKEN = "8228323704:AAHnYzsbkjm0QdBFb8Q7bcuSvAX6MTKSNDs"
CHAT_ID = "8275898854"
GEMINI_API_KEY = "你的_GEMINI_KEY"

WATCHLIST = {
    "2800.HK": "盈富基金",
    "3466.HK": "恒生高息股",
    "0941.HK": "中移動",
    "0005.HK": "匯豐",
    "0939.HK": "建行",
    "VOO": "VOO",
    "QQQ": "QQQ"
}
MARITIME_KEYWORDS = ["水警", "海上意外", "船隻爆炸", "政府船塢", "跳海", "跳橋", "溺斃"]

# 初始化 AI
genai.configure(api_key=GEMINI_API_KEY)
ai_model = genai.GenerativeModel('gemini-pro')

# --- 核心功能函數 (保留你原本的邏輯) ---

def send_msg(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
    except Exception as e: print(f"發送失敗: {e}")

def get_kdj_low(ticker_symbol, interval="1wk"):
    period = "1y" if interval == "1wk" else "5y"
    df = yf.Ticker(ticker_symbol).history(period=period, interval=interval)
    if df.empty or len(df) < 20: return False, 0
    kdj = ta.kdj(df['High'], df['Low'], df['Close'])
    k_column = [col for col in kdj.columns if col.startswith('K_') or 'KDJ_K' in col]
    current_k = kdj[k_column[0]].iloc[-1] if k_column else kdj.iloc[-1, 0]
    return current_k < 20, current_k

def get_stock_data(ticker_symbol):
    try:
        t = yf.Ticker(ticker_symbol)
        hist = t.history(period="5d")
        if hist.empty: return 0, 0
        price = hist['Close'].iloc[-1]
        actions = t.actions
        if not actions.empty and 'Dividends' in actions:
            one_year_ago = pd.Timestamp.now(tz='UTC') - pd.Timedelta(days=365)
            actions.index = pd.to_datetime(actions.index).tz_convert('UTC')
            last_year_divs = actions[actions.index > one_year_ago]['Dividends'].sum()
            dy = (last_year_divs / price * 100) if price > 0 else 0
        else: dy = 0
        if dy < 1.0:
            info = t.info
            div_rate = info.get('trailingAnnualDividendRate') or info.get('dividendRate') or 0
            dy = (div_rate / price * 100) if price > 0 else dy
        return dy, price
    except: return 0, 0

def get_news_raw(query):
    url = f"https://news.google.com/rss/search?q={query}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    try:
        r = requests.get(url, timeout=10)
        soup = BeautifulSoup(r.content, 'xml')
        return "\n".join([f"- {i.title.text}" for i in soup.find_all('item', limit=5)])
    except: return ""

# --- 執行邏輯 ---

def run_main():
    hkt_now = datetime.utcnow() + timedelta(hours=8)
    now_hour = hkt_now.hour
    
    # 抓取新聞原始資料
    finance_news_raw = get_news_raw(" OR ".join(WATCHLIST.keys()) + " 股息 技術分析")
    maritime_news_raw = get_news_raw(" OR ".join(MARITIME_KEYWORDS))
    
    # AI 處理
    prompt = f"""
    分析以下資訊並以繁體中文回報：
    1. 財經：摘要重要股息變動或技術指標新聞。若無重要變動回報「無」。
    2. 海上：檢查是否有香港水警、海上意外或爆炸新聞。若完全無相關新聞，回報「NONE」。
    
    財經資料：{finance_news_raw}
    海上資料：{maritime_news_raw}
    """
    ai_report = ai_model.generate_content(prompt).text
    has_maritime = "NONE" not in ai_report.upper()

    # --- 判斷發送 ---
    
    # 1. 早上 08:00 (全面報價報告 + 新聞)
    if now_hour == 8:
        reports = ["<b>📊 市場監控報告 ({})</b>\n".format(hkt_now.strftime('%Y-%m-%d'))]
        # VIX 檢查
        try:
            vix = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
            if vix >= 45: reports.append("🔴 <b>VIX 恐慌警告: {:.2f}</b>".format(vix))
        except: pass

        reports.append("<b>【美股指數】</b>")
        for s in ["VOO", "QQQ"]:
            dy, price = get_stock_data(s)
            wk_low, wk_v = get_kdj_low(s, "1wk"); mo_low, mo_v = get_kdj_low(s, "1mo")
            kdj_str = f" 🔥 <b>入貨:</b>{' 週K('+str(round(wk_v,1))+')' if wk_low else ''}{' 月K('+str(round(mo_v,1))+')' if mo_low else ''}" if (wk_low or mo_low) else ""
            reports.append(f"📈 {WATCHLIST[s]}: <b>{price:.2f}</b>{kdj_str}")

        reports.append("\n<b>【港股高息股】</b>")
        for s in ["2800.HK", "3466.HK", "0941.HK", "0005.HK", "0939.HK"]:
            dy, price = get_stock_data(s); kdj_str = ""
            if s in ["2800.HK", "3466.HK"]:
                wk_l, wk_v = get_kdj_low(s, "1wk")
                if wk_l: kdj_str = f" 🔥 <b>低位: 週K({round(wk_v,1)})</b>"
            reports.append(f"{'🟢' if dy >= 6 else '💰'} {WATCHLIST[s]}: <b>{price:.2f}</b> (息: <b>{dy:.2f}%</b>){kdj_str}")
        
        # 附加新聞與海上安全
        maritime_status = "⚓️ 香港水域安全" if not has_maritime else f"⚠️ <b>水域警報：</b>\n{ai_report}"
        reports.append(f"\n<b>【今日焦點摘要】</b>\n{ai_report}\n\n{maritime_status}")
        send_msg("\n".join(reports))
        return

    # 2. 其他時段：海上安全 (24小時無限制)
    if has_maritime:
        send_msg(f"🚨 <b>突發海上意外 ({now_hour}:00)</b>\n\n{ai_report}")
        return

    # 3. 其他時段：財經新聞 (08-24 運行，深夜靜音)
    if 8 < now_hour < 24 and "無" not in ai_report:
        send_msg(f"🔔 <b>定時資訊更新 ({now_hour}:00)</b>\n\n{ai_report}")

if __name__ == "__main__":
    run_main()
