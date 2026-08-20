import os
import requests
import pandas as pd
from fredapi import Fred

# 1. 讀取環境變數 (由 GitHub Secrets 安全注入)
FRED_KEY = os.getenv("FRED_API_KEY")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

if not FRED_KEY:
    raise ValueError("找不到 FRED_API_KEY，請確認 GitHub Secrets 設定。")

fred = Fred(api_key=FRED_KEY)

# 2. 獲取核心指標數據
def get_clean_series(code):
    return fred.get_series(code).dropna()

s_permit = get_clean_series('PERMIT')
s_houst = get_clean_series('HOUST')
s_orders = get_clean_series('ANDENO')
s_jolts = get_clean_series('JTSJOL')
s_t10y2y = get_clean_series('T10Y2Y')
s_claims = get_clean_series('IC4WSA')
s_uemp15 = get_clean_series('UEMP15T26')
s_retail = get_clean_series('RRSFS')
s_dpi = get_clean_series('DSPIC96')
s_isratio = get_clean_series('ISRATIO')
s_hy = get_clean_series('BAMLH0A0HYM2')

# 3. 模組指標門檻計算
# 模組 A：領先警訊池 (4項)
housing_avg = (s_permit + s_houst) / 2
h_3mma = housing_avg.rolling(3).mean().dropna()
h_drop = (h_3mma.tail(12).max() - h_3mma.iloc[-1]) / h_3mma.tail(12).max()
trig_a1 = bool(h_drop >= 0.12)

orders_3mma = s_orders.rolling(3).mean().dropna()
orders_yoy = (orders_3mma.iloc[-1] - orders_3mma.iloc[-13]) / orders_3mma.iloc[-13] if len(orders_3mma) >= 13 else 0.0
trig_a2 = bool(orders_yoy < 0.0)

jolts_latest = s_jolts.iloc[-1]
trig_a3 = bool(jolts_latest < 7000)

t10y2y_2w_min = s_t10y2y.tail(10).min()
trig_a4 = bool(s_t10y2y.tail(252).min() < -0.20 and t10y2y_2w_min > 0.10)

count_lead = sum([trig_a1, trig_a2, trig_a3, trig_a4])

# 模組 B：衰退確認池 (6項)
claims_latest = s_claims.iloc[-1]
claims_52w_low = s_claims.tail(52).min()
claims_rebound = (claims_latest - claims_52w_low) / claims_52w_low
trig_b1 = bool(claims_rebound >= 0.18)

uemp_3mma = s_uemp15.rolling(3).mean().dropna()
uemp_rebound = (uemp_3mma.iloc[-1] - uemp_3mma.tail(12).min()) / uemp_3mma.tail(12).min()
trig_b2 = bool(uemp_rebound >= 0.12 and uemp_3mma.iloc[-1] > uemp_3mma.iloc[-2])

retail_yoy = (s_retail.iloc[-1] - s_retail.iloc[-13]) / s_retail.iloc[-13] if len(s_retail) >= 13 else 0.0
trig_b3 = bool(retail_yoy < 0.0)

dpi_yoy = (s_dpi.iloc[-1] - s_dpi.iloc[-13]) / s_dpi.iloc[-13] if len(s_dpi) >= 13 else 0.0
trig_b4 = bool(dpi_yoy < 0.0)

trig_b5 = bool(s_isratio.iloc[-1] > s_isratio.iloc[-2] > s_isratio.iloc[-3])

hy_latest = s_hy.iloc[-1]
trig_b6 = bool(hy_latest >= 4.50)

count_conf = sum([trig_b1, trig_b2, trig_b3, trig_b4, trig_b5, trig_b6])

# 4. 景氣循環狀態與配置判定
if count_conf >= 4:
    regime = "🚨 衰退期 (Recession)"
    action = "全數撤退清倉：股票 0% ｜ 防禦 60% ｜ 現金 40%"
elif count_lead >= 3:
    regime = "⚠️ 榮景尾聲 (Late Boom)"
    action = "啟動買保險：股票 50% ｜ 防禦 50% (TLT+GLD+XLU)"
else:
    regime = "🚀 榮景前期 (Early Boom)"
    action = "積極享受主升段：股票 85% ｜ 防禦 5% ｜ 現金 10%"

# 5. 組裝診斷文字訊息
msg = f"""📊 【愛榭克總經景氣循環 - 每週定期診斷】
━━━━━━━━━━━━━━━━━━
📌 當前定位：{regime}
🎯 戰術配置：{action}

【模組 A：領先警訊池 ({count_lead}/4 觸發)】
• 房市雙指標回落: {h_drop*100:.1f}% {'(🔴觸發)' if trig_a1 else '(🟢正常)'}
• 核心耐久財年增: {orders_yoy*100:+.2f}% {'(🔴觸發)' if trig_a2 else '(🟢正常)'}
• JOLTS 職位空缺: {jolts_latest:,.0f} 千人 {'(🔴觸發)' if trig_a3 else '(🟢正常)'}
• 殖利率倒掛陡峭化: {s_t10y2y.iloc[-1]:.2f}% {'(🔴觸發)' if trig_a4 else '(🟢正常)'}

【模組 B：衰退確認池 ({count_conf}/6 觸發)】
• 初領失業金4W: {claims_latest/1000:.1f}萬人 (反彈 {claims_rebound*100:.1f}%) {'(🔴觸發)' if trig_b1 else '(🟢正常)'}
• 實質零售年增: {retail_yoy*100:+.2f}% {'(🔴觸發)' if trig_b3 else '(🟢正常)'}
• 實質可支配所得: {dpi_yoy*100:+.2f}% {'(🔴觸發)' if trig_b4 else '(🟢正常)'}
• 高收益債利差: {hy_latest*100:.0f} bps {'(🔴觸發)' if trig_b6 else '(🟢正常)'}
━━━━━━━━━━━━━━━━━━"""

print(msg)

# 6. 發送 Telegram 訊息 (若有設定 Token)
if TG_BOT_TOKEN and TG_CHAT_ID:
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TG_CHAT_ID, "text": msg})
    except Exception as e:
        print(f"推播發送失敗: {e}")
