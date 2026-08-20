import os
import requests
import pandas as pd
from fredapi import Fred
import datetime

# 1. 讀取金鑰與安全檢查
FRED_KEY = os.getenv("FRED_API_KEY")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

if not FRED_KEY:
    raise ValueError("找不到 FRED_API_KEY！請確認 GitHub Secrets 設定。")

fred = Fred(api_key=FRED_KEY)

def get_clean_series(code):
    try:
        s = fred.get_series(code).dropna()
        return s
    except Exception as e:
        print(f"❌ 抓取指標 {code} 失敗: {e}")
        return pd.Series(dtype=float)

# 2. 抓取時間序列
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
s_pce = get_clean_series('PCEPILFE')
s_fedrate = get_clean_series('FEDFUNDS')

# 輔助函式：格式化變動標記
def format_diff(curr, prev, fmt="{:+.2f}", unit=""):
    diff = curr - prev
    if abs(diff) < 1e-5:
        return f"{prev}{unit} (持平)"
    symbol = "🔺" if diff > 0 else "🔻"
    return f"{prev}{unit} ({symbol} {fmt.format(diff)}{unit})"

# 3. 模組指標安全計算 (含當期 vs 前期)
# --- 模組 A：領先警訊池 ---
# 1. 房市雙指標 (3MMA)
housing_avg = (s_permit + s_houst) / 2
h_3mma = housing_avg.rolling(3).mean().dropna()
h_curr = h_3mma.iloc[-1]
h_prev = h_3mma.iloc[-2]
h_peak = h_3mma.tail(12).max()
h_drop = (h_peak - h_curr) / h_peak
trig_a1 = bool(h_drop >= 0.12)
h_diff_str = format_diff(h_curr/1000, h_prev/1000, fmt="{:+.1f}", unit=" 萬戶")

# 2. 核心耐久財新訂單
orders_3mma = s_orders.rolling(3).mean().dropna()
orders_yoy_curr = (orders_3mma.iloc[-1] - orders_3mma.iloc[-13]) / orders_3mma.iloc[-13] * 100 if len(orders_3mma) >= 13 else 0.0
orders_yoy_prev = (orders_3mma.iloc[-2] - orders_3mma.iloc[-14]) / orders_3mma.iloc[-14] * 100 if len(orders_3mma) >= 14 else 0.0
trig_a2 = bool(orders_yoy_curr < 0.0)
orders_diff_str = format_diff(orders_yoy_curr, orders_yoy_prev, fmt="{:+.2f}", unit="%")

# 3. JOLTS 職位空缺數
jolts_curr = s_jolts.iloc[-1]
jolts_prev = s_jolts.iloc[-2]
trig_a3 = bool(jolts_curr < 7000)
jolts_diff_str = format_diff(jolts_curr, jolts_prev, fmt="{:+.0f}", unit=" 千人")

# 4. 10Y-2Y 倒掛轉正陡峭化 (納入60天時序校準)
t10y2y_curr = s_t10y2y.iloc[-1]
t10y2y_prev = s_t10y2y.iloc[-2]
inversion_in_60d = bool(s_t10y2y.tail(60).min() < -0.05)
currently_steep = bool(s_t10y2y.tail(10).min() > 0.10)
trig_a4 = bool(inversion_in_60d and currently_steep)
t10y2y_diff_str = format_diff(t10y2y_curr*100, t10y2y_prev*100, fmt="{:+.0f}", unit=" bps")

count_lead = sum([trig_a1, trig_a2, trig_a3, trig_a4])

# --- 模組 B：衰退確認池 ---
# 1. 初領失業金 4W
claims_curr = s_claims.iloc[-1]
claims_prev = s_claims.iloc[-2]
claims_52w_low = s_claims.tail(52).min()
claims_rebound = (claims_curr - claims_52w_low) / claims_52w_low
trig_b1 = bool(claims_rebound >= 0.18)
claims_diff_str = format_diff(claims_curr/1000, claims_prev/1000, fmt="{:+.2f}", unit=" 萬人")

# 2. 短期失業人數 (15週以下)
uemp_3mma = s_uemp15.rolling(3).mean().dropna()
uemp_curr = uemp_3mma.iloc[-1]
uemp_prev = uemp_3mma.iloc[-2]
uemp_min = uemp_3mma.tail(12).min()
uemp_rebound = (uemp_curr - uemp_min) / uemp_min
trig_b2 = bool(uemp_rebound >= 0.12 and uemp_curr > uemp_prev)
uemp_diff_str = format_diff(uemp_curr, uemp_prev, fmt="{:+.0f}", unit=" 千人")

# 3. 實質零售銷售年增率
retail_yoy_curr = (s_retail.iloc[-1] - s_retail.iloc[-13]) / s_retail.iloc[-13] * 100 if len(s_retail) >= 13 else 0.0
retail_yoy_prev = (s_retail.iloc[-2] - s_retail.iloc[-14]) / s_retail.iloc[-14] * 100 if len(s_retail) >= 14 else 0.0
trig_b3 = bool(retail_yoy_curr < 0.0)
retail_diff_str = format_diff(retail_yoy_curr, retail_yoy_prev, fmt="{:+.2f}", unit="%")

# 4. 實質個人可支配所得年增率
dpi_yoy_curr = (s_dpi.iloc[-1] - s_dpi.iloc[-13]) / s_dpi.iloc[-13] * 100 if len(s_dpi) >= 13 else 0.0
dpi_yoy_prev = (s_dpi.iloc[-2] - s_dpi.iloc[-14]) / s_dpi.iloc[-14] * 100 if len(s_dpi) >= 14 else 0.0
trig_b4 = bool(dpi_yoy_curr < 0.0)
dpi_diff_str = format_diff(dpi_yoy_curr, dpi_yoy_prev, fmt="{:+.2f}", unit="%")

# 5. 企業存貨/銷售比
inv_curr = s_isratio.iloc[-1]
inv_prev = s_isratio.iloc[-2]
trig_b5 = bool(len(s_isratio) >= 3 and s_isratio.iloc[-1] > s_isratio.iloc[-2] > s_isratio.iloc[-3])
inv_diff_str = format_diff(inv_curr, inv_prev, fmt="{:+.2f}", unit="")

# 6. 高收益債信用利差
hy_curr = s_hy.iloc[-1]
hy_prev = s_hy.iloc[-2]
trig_b6 = bool(hy_curr >= 4.50)
hy_diff_str = format_diff(hy_curr*100, hy_prev*100, fmt="{:+.0f}", unit=" bps")

count_conf = sum([trig_b1, trig_b2, trig_b3, trig_b4, trig_b5, trig_b6])

# --- 模組 C & D ---
fed_cut = (s_fedrate.tail(12).max() - s_fedrate.iloc[-1])
hy_drop_val = (s_hy.tail(252).max() - hy_curr)
claims_peak_12m = s_claims.tail(52).max()
pce_yoy_curr = (s_pce.iloc[-1] - s_pce.iloc[-13]) / s_pce.iloc[-13] * 100 if len(s_pce) >= 13 else 0.0
pce_yoy_prev = (s_pce.iloc[-2] - s_pce.iloc[-14]) / s_pce.iloc[-14] * 100 if len(s_pce) >= 14 else 0.0
pce_diff_str = format_diff(pce_yoy_curr, pce_yoy_prev, fmt="{:+.2f}", unit="%")

fed_funds_curr = s_fedrate.iloc[-1]
fed_funds_prev = s_fedrate.iloc[-2]
fed_diff_str = format_diff(fed_funds_curr, fed_funds_prev, fmt="{:+.2f}", unit="%")
real_rate = fed_funds_curr - pce_yoy_curr

# 4. 定位判定
if count_conf >= 4:
    regime = "🚨 衰退期 (Recession)"
    stock_w, def_w, cash_w = "0%", "60% (TLT+GLD+XLU)", "40%"
    note = "實體消費與就業全面惡化，全數撤退清倉防禦"
elif count_lead >= 3:
    regime = "⚠️ 榮景尾聲 (Late Boom)"
    stock_w, def_w, cash_w = "50%", "50% (TLT+GLD+XLU)", "0%"
    note = "領先警訊多數觸發，啟動 50% 規模化買保險機制"
else:
    regime = "🚀 榮景前期 (Early Boom)"
    stock_w, def_w, cash_w = "85%", "5%", "10%"
    note = "實體數據健康，維持高 Beta 做多享受主升段"

update_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

# 5. 生成精美 HTML 網頁 (含前值比對欄位)
html_content = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>愛榭克總體經濟景氣循環量化監控看板</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; margin: 30px; background-color: #f8f9fa; color: #212529; }}
        h1, h2, h3 {{ color: #1a202c; }}
        .card {{ background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.08); margin-bottom: 25px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 15px; margin-bottom: 20px; }}
        .metric {{ background: #eef2f7; padding: 15px; border-radius: 6px; border-left: 5px solid #0d6efd; }}
        .metric-title {{ font-size: 0.9em; color: #6c757d; margin-bottom: 5px; }}
        .metric-value {{ font-size: 1.3em; font-weight: bold; color: #0f172a; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
        th, td {{ padding: 12px; border: 1px solid #dee2e6; text-align: left; }}
        th {{ background-color: #f1f5f9; font-weight: 600; }}
        tr:hover {{ background-color: #f8fafc; }}
        .badge-red {{ color: #dc3545; font-weight: bold; }}
        .badge-green {{ color: #198754; font-weight: bold; }}
        .diff-tag {{ font-size: 0.9em; color: #475569; }}
        a {{ color: #0d6efd; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <h1>📊 愛榭克（Izaax）總體經濟景氣循環量化監控看板</h1>
    <p style="color: #6c757d;">更新時間：{update_time}</p>

    <div class="card">
        <h2>🎯 當前景氣階段定位與資產配置</h2>
        <div class="grid">
            <div class="metric">
                <div class="metric-title">景氣循環定位</div>
                <div class="metric-value">{regime}</div>
                <div style="font-size:0.85em; color:#475569; margin-top:4px;">{note}</div>
            </div>
            <div class="metric">
                <div class="metric-title">成長型股票配置 (QQQ/SOXX/SPY)</div>
                <div class="metric-value">{stock_w}</div>
            </div>
            <div class="metric">
                <div class="metric-title">防禦籃子 (TLT+GLD+XLU) / 現金</div>
                <div class="metric-value">{def_w} / {cash_w}</div>
            </div>
        </div>
    </div>

    <div class="card">
        <h2>⚠️ 模組 A：領先警訊池 (觸發: {count_lead}/4 ｜ 門檻: >= 3項)</h2>
        <table>
            <tr><th>指標名稱</th><th>最新數據 (現況)</th><th>前值 (前期變動)</th><th>判斷門檻</th><th>狀態燈號</th><th>FRED 連結</th></tr>
            <tr><td>房市雙指標 (3MMA)</td><td>{h_curr/1000:.1f} 萬戶 (回落 {h_drop*100:.1f}%)</td><td class="diff-tag">{h_diff_str}</td><td>自高點回落 >= 12%</td><td class="{'badge-red' if trig_a1 else 'badge-green'}">{'🔴 觸發' if trig_a1 else '🟢 正常'}</td><td><a href="https://fred.stlouisfed.org/series/PERMIT" target="_blank">PERMIT</a> / <a href="https://fred.stlouisfed.org/series/HOUST" target="_blank">HOUST</a></td></tr>
            <tr><td>核心耐久財新訂單 (3MMA YoY)</td><td>YoY {orders_yoy_curr:+.2f}%</td><td class="diff-tag">{orders_diff_str}</td><td>年增率 < 0%</td><td class="{'badge-red' if trig_a2 else 'badge-green'}">{'🔴 觸發' if trig_a2 else '🟢 正常'}</td><td><a href="https://fred.stlouisfed.org/series/ANDENO" target="_blank">ANDENO</a></td></tr>
            <tr><td>JOLTS 職位空缺數</td><td>{jolts_curr:,.0f} 千人</td><td class="diff-tag">{jolts_diff_str}</td><td>跌破常態 (< 7,000 千人)</td><td class="{'badge-red' if trig_a3 else 'badge-green'}">{'🔴 觸發' if trig_a3 else '🟢 正常'}</td><td><a href="https://fred.stlouisfed.org/series/JTSJOL" target="_blank">JTSJOL</a></td></tr>
            <tr><td>10Y-2Y 殖利率曲線陡峭化</td><td>{t10y2y_curr*100:.0f} bps</td><td class="diff-tag">{t10y2y_diff_str}</td><td>近60天倒掛轉正且>10bps</td><td class="{'badge-red' if trig_a4 else 'badge-green'}">{'🔴 觸發' if trig_a4 else '🟢 正常'}</td><td><a href="https://fred.stlouisfed.org/series/T10Y2Y" target="_blank">T10Y2Y</a></td></tr>
        </table>
    </div>

    <div class="card">
        <h2>🚨 模組 B：衰退確認池 (觸發: {count_conf}/6 ｜ 門檻: >= 4項)</h2>
        <table>
            <tr><th>指標名稱</th><th>最新數據 (現況)</th><th>前值 (前期變動)</th><th>判斷門檻</th><th>狀態燈號</th><th>FRED 連結</th></tr>
            <tr><td>初領失業金 4週均線</td><td>{claims_curr/1000:.2f} 萬人 (反彈 {claims_rebound*100:.1f}%)</td><td class="diff-tag">{claims_diff_str}</td><td>自低點反彈 >= 18%</td><td class="{'badge-red' if trig_b1 else 'badge-green'}">{'🔴 觸發' if trig_b1 else '🟢 正常'}</td><td><a href="https://fred.stlouisfed.org/series/IC4WSA" target="_blank">IC4WSA</a></td></tr>
            <tr><td>短期失業人數 (15週以下)</td><td>{uemp_curr:,.0f} 千人 (反彈 {uemp_rebound*100:.1f}%)</td><td class="diff-tag">{uemp_diff_str}</td><td>自低點反彈 >= 12% 且向上</td><td class="{'badge-red' if trig_b2 else 'badge-green'}">{'🔴 觸發' if trig_b2 else '🟢 正常'}</td><td><a href="https://fred.stlouisfed.org/series/UEMP15T26" target="_blank">UEMP15T26</a></td></tr>
            <tr><td>實質零售銷售年增率</td><td>實質 YoY {retail_yoy_curr:+.2f}%</td><td class="diff-tag">{retail_diff_str}</td><td>年增率 < 0.0%</td><td class="{'badge-red' if trig_b3 else 'badge-green'}">{'🔴 觸發' if trig_b3 else '🟢 正常'}</td><td><a href="https://fred.stlouisfed.org/series/RRSFS" target="_blank">RRSFS</a></td></tr>
            <tr><td>實質個人可支配所得年增率</td><td>實質 DPI YoY {dpi_yoy_curr:+.2f}%</td><td class="diff-tag">{dpi_diff_str}</td><td>年增率 < 0.0%</td><td class="{'badge-red' if trig_b4 else 'badge-green'}">{'🔴 觸發' if trig_b4 else '🟢 正常'}</td><td><a href="https://fred.stlouisfed.org/series/DSPIC96" target="_blank">DSPIC96</a></td></tr>
            <tr><td>企業存貨 / 銷售比</td><td>{inv_curr:.2f}</td><td class="diff-tag">{inv_diff_str}</td><td>連續 3 個月被動積壓飆升</td><td class="{'badge-red' if trig_b5 else 'badge-green'}">{'🔴 觸發' if trig_b5 else '🟢 正常'}</td><td><a href="https://fred.stlouisfed.org/series/ISRATIO" target="_blank">ISRATIO</a></td></tr>
            <tr><td>高收益債信用利差 (HY OAS)</td><td>{hy_curr*100:.0f} bps</td><td class="diff-tag">{hy_diff_str}</td><td>利差突破 450 bps</td><td class="{'badge-red' if trig_b6 else 'badge-green'}">{'🔴 觸發' if trig_b6 else '🟢 正常'}</td><td><a href="https://fred.stlouisfed.org/series/BAMLH0A0HYM2" target="_blank">BAMLH0A0HYM2</a></td></tr>
        </table>
    </div>

    <div class="card">
        <h2>🔄 模組 C & 💡 模組 D：復甦抄底與循環定性</h2>
        <table>
            <tr><th>分析項目</th><th>最新數據讀數</th><th>前值 (變動)</th><th>判斷條件 / 說明</th><th>FRED 連結</th></tr>
            <tr><td>核心 PCE 年增率</td><td>{pce_yoy_curr:.2f}%</td><td class="diff-tag">{pce_diff_str}</td><td>物價擴張度監控</td><td><a href="https://fred.stlouisfed.org/series/PCEPILFE" target="_blank">PCEPILFE</a></td></tr>
            <tr><td>聯邦基金利率 (Fed Funds)</td><td>{fed_funds_curr:.2f}%</td><td class="diff-tag">{fed_diff_str}</td><td>政策利率水準</td><td><a href="https://fred.stlouisfed.org/series/FEDFUNDS" target="_blank">FEDFUNDS</a></td></tr>
            <tr><td>實質基準利率 (Real Rate)</td><td>{real_rate:+.2f}%</td><td class="diff-tag">--</td><td>>1.5% 為限制性緊縮環境</td><td>--</td></tr>
            <tr><td>循環模式定性</td><td>生產力擴張循環 (Productivity-led)</td><td>--</td><td>AI Capex 與半導體盈餘增長主導</td><td>--</td></tr>
        </table>
    </div>

    <div class="card">
        <h2>📋 最新資產配置執行矩陣</h2>
        <table>
            <tr><th>資產類別</th><th>建議配置比例</th><th>具體標的</th><th>執行戰術與目的</th></tr>
            <tr><td>成長型股票 (Growth Equities)</td><td><strong>85%</strong></td><td>QQQ, SOXX, SPY</td><td>積極參與主升段：享受生產力循環盈餘爆發。</td></tr>
            <tr><td>防禦型資產籃子 (Defensive Basket)</td><td><strong>5%</strong></td><td>TLT (50%) + GLD (25%) + XLU (25%)</td><td>維持底倉觀察：暫不啟動 50% 規模化買保險。</td></tr>
            <tr><td>流動性現金 (Cash Equivalents)</td><td><strong>10%</strong></td><td>BIL / 貨幣市場基金</td><td>獲取高實質短端無風險收益，保留機動性。</td></tr>
        </table>
    </div>
</body>
</html>
"""

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html_content)

print("🎉 執行成功！已產出包含前值對照欄位的 index.html 報表！")
