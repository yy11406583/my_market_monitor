import yfinance as yf
import pandas_ta as ta
import requests
import time
import pandas as pd

# --- 設定區 ---
TELEGRAM_TOKEN = "你的_API_TOKEN"
CHAT_ID = "你的_CHAT_ID"

# 監控清單 (Ticker: 顯示名稱)
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
        requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=15)
    except Exception as e:
        print(f"發送失敗: {e}")

def get_kdj_low(ticker_symbol, interval="1wk"):
    period = "1y" if interval == "1wk" else "5y"
    df = yf.Ticker(ticker_symbol).history(period=period, interval=interval)
    if df.empty or len(df) < 20: return False, 0
    kdj = ta.kdj(df['High'], df['Low'], df['Close'])
    k_column = [col for col in kdj.columns if col.startswith('K_') or 'KDJ_K' in col or col == 'KDJ_9_3']
    current_k = kdj[k_column[0]].iloc[-1] if k_column else kdj.iloc[-1, 0]
    return current_k < 20, current_k

def get_stock_data(ticker_symbol):
    try:
        t = yf.Ticker(ticker_symbol)
        info = t.info
        # 優先抓取現價
        price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose') or 0
        
        # 準確計算股息率：年度股息 / 現價
        div_rate = info.get('trailingAnnualDividendRate') or 0
        if div_rate == 0:
            dy = (info.get('trailingAnnualDividendYield') or 0) * 100
        else:
            dy = (div_rate / price) * 100 if price > 0 else 0
            
        return dy, price
    except:
        return 0, 0

def check_all():
    print(f"--- 執行全面掃描 {time.ctime()} ---")
    reports = []

    # 1. 檢查 VIX
    try:
        vix = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
        if vix >= 45: reports.append(f"⚠️ VIX 恐慌警告: {vix:.2f}")
    except: pass

    # 2. 遍歷清單檢查 KDJ 同 股息
    for symbol, name in WATCHLIST.items():
        try:
            dy, price = get_stock_data(symbol)
            
            # 只有美股或指數才檢查 KDJ
            kdj_msg = ""
            if symbol in ["2800.HK", "3466.HK", "VOO", "QQQ"]:
                wk_low, wk_val = get_kdj_low(symbol, "1wk")
                mo_low, mo_val = get_kdj_low(symbol, "1mo")
                if wk_low or mo_low:
                    kdj_msg = " | KDJ探底: "
                    if wk_low: kdj_msg += f"週K({wk_val:.1f}) "
                    if mo_low: kdj_msg += f"月K({mo_val:.1f}) "
            
            # 格式化輸出
            if symbol in ["VOO", "QQQ"]:
                reports.append(f"📈 {name}: {price:.2f}{kdj_msg}")
            else:
                reports.append(f"💰 {name}: {price:.2f} (息: {dy:.2f}%){kdj_msg}")

        except Exception as e:
            print(f"處理 {name} 時出錯: {e}")

    if reports:
        final_msg = "\n".join(reports)
        send_msg(f"📊 市場監控報告 ({time.strftime('%Y-%m-%d')})\n\n{final_msg}")
        print("✅ 報告已發送")

if __name__ == "__main__":
    check_all()
