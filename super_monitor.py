import yfinance as yf
import pandas_ta as ta
import requests
import time
import pandas as pd

# --- 設定區 ---
TELEGRAM_TOKEN = "8228323704:AAHnYzsbkjm0QdBFb8Q7bcuSvAX6MTKSNDs"
CHAT_ID = "8275898854"

WATCHLIST = {
    "2800.HK": "盈富基金",
    "3466.HK": "恒生高息股",
    "0941.HK": "中移動",
    "0005.HK": "匯豐",
    "0939.HK": "建行",
    "VOO": "VOO",
    "QQQ": "QQQ"
}

def send_msg(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
    except Exception as e:
        print(f"發送失敗: {e}")

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
        # 抓取最新成交價，唔用 info 嘅 price
        hist = t.history(period="5d")
        if hist.empty: return 0, 0
        price = hist['Close'].iloc[-1]
        
        # 強制計算法：抓取過去一年的實際派息紀錄
        actions = t.actions
        if not actions.empty and 'Dividends' in actions:
            # 獲取過去 365 天的總派息
            one_year_ago = pd.Timestamp.now(tz='UTC') - pd.Timedelta(days=365)
            # 確保 index 是 datetime 格式且有時區
            actions.index = pd.to_datetime(actions.index).tz_convert('UTC')
            last_year_divs = actions[actions.index > one_year_ago]['Dividends'].sum()
            dy = (last_year_divs / price * 100) if price > 0 else 0
        else:
            dy = 0

        # 特殊處理：如果計算結果太離譜（例如匯豐得 0.6），嘗試從 info 補救
        if dy < 1.0:
            info = t.info
            div_rate = info.get('trailingAnnualDividendRate') or info.get('dividendRate') or 0
            dy = (div_rate / price * 100) if price > 0 else dy

        return dy, price
    except Exception as e:
        print(f"Error fetching {ticker_symbol}: {e}")
        return 0, 0

def check_all():
    print(f"--- 執行全面掃描 {time.ctime()} ---")
    reports = ["<b>📊 市場監控報告 ({})</b>\n".format(time.strftime('%Y-%m-%d'))]
    
    # 1. 檢查 VIX
    try:
        vix = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
        if vix >= 45: reports.append("🔴 <b>VIX 恐慌警告: {:.2f}</b>".format(vix))
    except: pass

    reports.append("<b>【美股指數】</b>")
    for symbol in ["VOO", "QQQ"]:
        dy, price = get_stock_data(symbol)
        wk_low, wk_val = get_kdj_low(symbol, "1wk")
        mo_low, mo_val = get_kdj_low(symbol, "1mo")
        kdj_str = ""
        if wk_low or mo_low:
            kdj_str = " 🔥 <b>入貨訊號:</b>"
            if wk_low: kdj_str += " 週K({})".format(round(wk_val,1))
            if mo_low: kdj_str += " 月K({})".format(round(mo_val,1))
        reports.append("📈 {}: <b>{:.2f}</b>{}".format(WATCHLIST[symbol], price, kdj_str))

    reports.append("\n<b>【港股及高息股】</b>")
    for symbol in ["2800.HK", "3466.HK", "0941.HK", "0005.HK", "0939.HK"]:
        dy, price = get_stock_data(symbol)
        name = WATCHLIST[symbol]
        emoji = "🟢" if dy >= 6 else "💰"
        kdj_str = ""
        if symbol in ["2800.HK", "3466.HK"]:
            wk_low, wk_val = get_kdj_low(symbol, "1wk")
            if wk_low: kdj_str = " 🔥 <b>低位: 週K({})</b>".format(round(wk_val,1))
        reports.append("{} {}: <b>{:.2f}</b> (息: <b>{:.2f}%</b>){}".format(emoji, name, price, dy, kdj_str))

    send_msg("\n".join(reports))
    print("✅ 報告已發送")

if __name__ == "__main__":
    check_all()
