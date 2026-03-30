import yfinance as yf
import pandas_ta as ta
import requests
import time
import pandas as pd

# --- 設定區 ---
TELEGRAM_TOKEN = "8228323704:AAHnYzsbkjm0QdBFb8Q7bcuSvAX6MTKSNDs"
CHAT_ID = "8275898854"

# 監控清單
HK_STOCKS = {"2800.HK": "盈富基金", "3466.HK": "恒生高息股", "0005.HK": "匯豐", "0939.HK": "建行"}
US_STOCKS = {"VOO": "VOO", "QQQ": "QQQ"}

def send_msg(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=10)
    except Exception as e:
        print(f"發送失敗: {e}")

def get_kdj_low(ticker_symbol, interval="1wk"):
    period = "1y" if interval == "1wk" else "5y"
    ticker = yf.Ticker(ticker_symbol)
    df = ticker.history(period=period, interval=interval)
    
    if df.empty or len(df) < 20:
        return False, 0
    
    # 計算 KDJ
    kdj = ta.kdj(df['High'], df['Low'], df['Close'])
    
    # 智能尋找 K 值的欄位名稱 (處理 KDJ_9_3 或 K_9_3_2 等變體)
    k_column = [col for col in kdj.columns if col.startswith('K_') or 'KDJ_K' in col or col == 'KDJ_9_3']
    
    if not k_column:
        # 如果找不到，嘗試取第一欄作為 K 值
        current_k = kdj.iloc[-1, 0]
    else:
        current_k = kdj[k_column[0]].iloc[-1]
        
    return current_k < 20, current_k

def get_dividend_yield(ticker_symbol):
    try:
        t = yf.Ticker(ticker_symbol)
        info = t.info
        dy = info.get('dividendYield', 0)
        if dy is None: dy = 0
        dy *= 100 
        price = info.get('currentPrice') or info.get('regularMarketPrice') or 0
        return dy, price
    except:
        return 0, 0

def check_all():
    print(f"--- 執行全面掃描 {time.ctime()} ---")
    reports = []

    # 1. 檢查 VIX
    try:
        vix_df = yf.Ticker("^VIX").history(period="1d")
        if not vix_df.empty:
            vix = vix_df['Close'].iloc[-1]
            if vix >= 45: reports.append(f"⚠️ VIX 恐慌警告: {vix:.2f}")
    except:
        pass

    # 2. 檢查 KDJ (週K & 月K)
    for symbol, name in {**HK_STOCKS, **US_STOCKS}.items():
        if symbol in ["0005.HK", "0939.HK"]: continue
        
        try:
            wk_low, wk_val = get_kdj_low(symbol, "1wk")
            mo_low, mo_val = get_kdj_low(symbol, "1mo")
            
            if wk_low or mo_low:
                status = f"【{name}】KDJ探底: "
                if wk_low: status += f"週K({wk_val:.1f}) "
                if mo_low: status += f"月K({mo_val:.1f}) "
                reports.append(status)
        except Exception as e:
            print(f"處理 {name} 時出錯: {e}")

    # 3. 檢查 匯豐/建行 股息率
    for symbol in ["0005.HK", "0939.HK"]:
        dy, price = get_dividend_yield(symbol)
        name = HK_STOCKS[symbol]
        if dy > 0:
            reports.append(f"💰 {name} 股息率: {dy:.2f}% (現價: {price})")

    if reports:
        final_msg = "\n".join(reports)
        send_msg(f"📊 市場監控報告 ({time.strftime('%Y-%m-%d')})\n\n{final_msg}")
        print("✅ 報告已發送")
    else:
        print("ℹ️ 未達到提醒門檻，不發送訊息")

if __name__ == "__main__":
    check_all()
