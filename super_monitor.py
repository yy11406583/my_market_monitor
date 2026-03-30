import yfinance as yf
import pandas_ta as ta
import requests
import time

# --- 設定區 ---
TELEGRAM_TOKEN = "8228323704:AAHnYzsbkjm0QdBFb8Q7bcuSvAX6MTKSNDs"
CHAT_ID = "8275898854"

# 監控清單
HK_STOCKS = {"2800.HK": "盈富基金", "3466.HK": "恒生高息股", "0005.HK": "匯豐", "0939.HK": "建行"}
US_STOCKS = {"VOO": "VOO", "QQQ": "QQQ"}

def send_msg(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": text})

def get_kdj_low(ticker_symbol, interval="wk"):
    # 下載數據：週線(1wk) 或 月線(1mo)
    period = "2y" if interval == "1wk" else "5y"
    df = yf.Ticker(ticker_symbol).history(period=period, interval=interval)
    if len(df) < 20: return False
    
    # 計算 KDJ (使用 pandas_ta)
    kdj = ta.kdj(df['High'], df['Low'], df['Close'])
    current_k = kdj['KDJ_9_3'].iloc[-1]
    return current_k < 20, current_k

def get_dividend_yield(ticker_symbol):
    t = yf.Ticker(ticker_symbol)
    info = t.info
    # 獲取當前股息率 (Dividend Yield)
    dy = info.get('dividendYield', 0) * 100 # 轉為百分比
    price = info.get('currentPrice', 0)
    return dy, price

def check_all():
    print(f"--- 執行全面掃描 {time.ctime()} ---")
    reports = []

    # 1. 檢查 VIX (基本黑天鵝)
    vix = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
    if vix >= 45: reports.append(f"⚠️ VIX 恐慌警告: {vix:.2f}")

    # 2. 檢查 KDJ (週K + 月K 低過 20)
    for symbol, name in {**HK_STOCKS, **US_STOCKS}.items():
        if symbol in ["0005.HK", "0939.HK"]: continue # 匯豐建行主要睇息，放後面
        
        wk_low, wk_val = get_kdj_low(symbol, "1wk")
        mo_low, mo_val = get_kdj_low(symbol, "1mo")
        
        if wk_low or mo_low:
            status = f"【{name}】KDJ探底: "
            if wk_low: status += f"週K({wk_val:.1f}) "
            if mo_low: status += f"月K({mo_val:.1f}) "
            reports.append(status)

    # 3. 檢查 匯豐/建行 股息率
    for symbol in ["0005.HK", "0939.HK"]:
        dy, price = get_dividend_yield(symbol)
        name = HK_STOCKS[symbol]
        reports.append(f"💰 {name} 股息率: {dy:.2f}% (現價: {price})")

    if reports:
        send_msg("\n".join(reports))
        print("✅ 報告已發送至 Telegram")

# 建議每日收市後執行一次即可 (高效率，不浪費伺服器資源)
check_all()
