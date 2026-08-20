import os
import requests
import pandas as pd
from fredapi import Fred
import datetime

# 1. 讀取金鑰
FRED_KEY = os.getenv("FRED_API_KEY")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

if not FRED_KEY:
    raise ValueError("找不到 FRED_API_KEY，請確認 GitHub Secrets 設定。")

fred = Fred(api_key=FRED_KEY)

def get_clean_series(code):
    return fred.get_series(code).dropna()

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

# 3. 模組指標計算
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

t10y2y_latest = s_t10y2y.iloc[-1]
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

inv_latest = s_isratio.iloc[-1]
trig_b5 = bool(s_isratio.iloc[-1] > s_isratio.iloc[-2] > s_isratio.iloc[-3])

hy_latest = s_hy.iloc[-1]
trig_b6 = bool(hy_latest >= 4.50)

count_conf = sum([trig_b1, trig_b2, trig_b3, trig_b4, trig_b5, trig_b6])

# 模組 C：復甦抄底池 (3項)
fed_cut = s_fedrate.tail(12).max() - s_fedrate.iloc[-1]
trig_c1 = bool(fed_cut >= 1.0)

hy_drop_val = s_hy.tail(252).max() - hy_latest
trig_c2 = bool(hy_drop_val >= 1.50)

claims_peak_12m = s_claims.tail(52).max()
trig_c3 = bool(claims_latest < claims_peak_12m * 0.90 and s_claims.iloc[-1] < s_claims.iloc[-4])

count_rec = sum([trig_c1, trig_c2, trig_c3])

# 模組 D：循環定性模組
pce_yoy = (s_pce.iloc[-1] - s_pce.iloc[-13]) / s_pce.iloc[-13] * 100 if len(s_pce) >= 13 else 0.0
fed_funds_val = s_fedrate.iloc[-1]
real_rate = fed_funds_val - pce_yoy

# 4. 狀態判定
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

# 5. 生成靜態 HTML 網頁
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
            <tr><th>指標名稱</th><th>原始數據 / 現況</th><th>判斷門檻</th><th>狀態燈號</th><th>FRED 連結</th></tr>
            <tr><td>房市雙指標 (3MMA)</td><td>3MMA: {h_3mma.iloc[-1]:,.0f} 戶 (回落 {h_drop*100:.1f}%)</td><td>自12月高點回落 >= 12%</td><td class="{'badge-red' if trig_a1 else 'badge-green'}">{'🔴 觸發' if trig_a1 else '🟢 正常'}</td><td><a href="https://fred.stlouisfed.org/series/PERMIT" target="_blank">PERMIT</a> / <a href="https://fred.stlouisfed.org/series/HOUST" target="_blank">HOUST</a></td></tr>
            <tr><td>核心耐久財新訂單 (3MMA)</td><td>YoY: {orders_yoy*100:+.2f}%</td><td>3MMA 年增率 < 0%</td><td class="{'badge-red' if trig_a2 else 'badge-green'}">{'🔴 觸發' if trig_a2 else '🟢 正常'}</td><td><a href="https://fred.stlouisfed.org/series/ANDENO" target="_blank">ANDENO</a></td></tr>
            <tr><td>JOLTS 職位空缺數</td><td>最新職缺: {jolts_latest:,.0f} 千人</td><td>跌破疫情前基準 (< 7,000 千人)</td><td class="{'badge-red' if trig_a3 else 'badge-green'}">{'🔴 觸發' if trig_a3 else '🟢 正常'}</td><td><a href="https://fred.stlouisfed.org/series/JTSJOL" target="_blank">JTSJOL</a></td></tr>
            <tr><td>10Y-2Y 殖利率曲線陡峭化</td><td>最新利差: {t10y2y_latest:+.2f}%</td><td>倒掛後轉正連續2週 > +10 bps</td><td class="{'badge-red' if trig_a4 else 'badge-green'}">{'🔴 觸發' if trig_a4 else '🟢 正常'}</td><td><a href="https://fred.stlouisfed.org/series/T10Y2Y" target="_blank">T10Y2Y</a></td></tr>
        </table>
    </div>

    <div class="card">
        <h2>🚨 模組 B：衰退確認池 (觸發: {count_conf}/6 ｜ 門檻: >= 4項)</h2>
        <table>
            <tr><th>指標名稱</th><th>原始數據 / 現況</th><th>判斷門檻</th><th>狀態燈號</th><th>FRED 連結</th></tr>
            <tr><td>初領失業金 4週均線</td><td>最新: {claims_latest/1000:.1f} 萬人 (反彈 {claims_rebound*100:.1f}%)</td><td>自52週低點反彈 >= 18%</td><td class="{'badge-red' if trig_b1 else 'badge-green'}">{'🔴 觸發' if trig_b1 else '🟢 正常'}</td><td><a href="https://fred.stlouisfed.org/series/IC4WSA" target="_blank">IC4WSA</a></td></tr>
            <tr><td>短期失業人數 (15週以下)</td><td>最新: {uemp_3mma.iloc[-1]:,.0f} 千人 (反彈 {uemp_rebound*100:.1f}%)</td><td>自低點反彈 >= 12% 且向上</td><td class="{'badge-red' if trig_b2 else 'badge-green'}">{'🔴 觸發' if trig_b2 else '🟢 正常'}</td><td><a href="https://fred.stlouisfed.org/series/UEMP15T26" target="_blank">UEMP15T26</a></td></tr>
            <tr><td>實質零售銷售年增率</td><td>扣除通膨實質 YoY: {retail_yoy*100:+.2f}%</td><td>年增率 (YoY) < 0.0%</td><td class="{'badge-red' if trig_b3 else 'badge-green'}">{'🔴 觸發' if trig_b3 else '🟢 正常'}</td><td><a href="https://fred.stlouisfed.org/series/RRSFS" target="_blank">RRSFS</a></td></tr>
            <tr><td>實質個人可支配所得年增率</td><td>實質 DPI YoY: {dpi_yoy*100:+.2f}%</td><td>年增率 (YoY) < 0.0%</td><td class="{'badge-red' if trig_b4 else 'badge-green'}">{'🔴 觸發' if trig_b4 else '🟢 正常'}</td><td><a href="https://fred.stlouisfed.org/series/DSPIC96" target="_blank">DSPIC96</a></td></tr>
            <tr><td>企業存貨 / 銷售比</td><td>最新庫銷比: {inv_latest:.2f}</td><td>連續 3 個月被動積壓飆升</td><td class="{'badge-red' if trig_b5 else 'badge-green'}">{'🔴 觸發' if trig_b5 else '🟢 正常'}</td><td><a href="https://fred.stlouisfed.org/series/ISRATIO" target="_blank">ISRATIO</a></td></tr>
            <tr><td>高收益債信用利差 (HY OAS)</td><td>最新利差: {hy_latest*100:.0f} bps ({hy_latest:.2f}%)</td><td>利差擴大突破 450 bps</td><td class="{'badge-red' if trig_b6 else 'badge-green'}">{'🔴 觸發' if trig_b6 else '🟢 正常'}</td><td><a href="https://fred.stlouisfed.org/series/BAMLH0A0HYM2" target="_blank">BAMLH0A0HYM2</a></td></tr>
        </table>
    </div>

    <div class="card">
        <h2>🔄 模組 C & 💡 模組 D：復甦抄底與循環定性</h2>
        <table>
            <tr><th>分析項目</th><th>最新數據讀數</th><th>判斷條件 / 說明</th><th>FRED 連結</th></tr>
            <tr><td>聯準會累計降息幅度</td><td>已調降 {fed_cut*100:.0f} bps</td><td>累計降息 >= 100 bps</td><td><a href="https://fred.stlouisfed.org/series/FEDFUNDS" target="_blank">FEDFUNDS</a></td></tr>
            <tr><td>高收益債利差自峰值回落</td><td>自高點收斂 {hy_drop_val*100:.0f} bps</td><td>利差自峰值回落 >= 150 bps</td><td><a href="https://fred.stlouisfed.org/series/BAMLH0A0HYM2" target="_blank">BAMLH0A0HYM2</a></td></tr>
            <tr><td>初領失業金見頂回落</td><td>較峰值回落 {((claims_peak_12m-claims_latest)/claims_peak_12m)*100:.1f}%</td><td>4W均線連續回落且跌破峰值10%</td><td><a href="https://fred.stlouisfed.org/series/IC4WSA" target="_blank">IC4WSA</a></td></tr>
            <tr><td>核心 PCE 物價指數年增率</td><td>{pce_yoy:.2f}%</td><td>物價擴張度監控</td><td><a href="https://fred.stlouisfed.org/series/PCEPILFE" target="_blank">PCEPILFE</a></td></tr>
            <tr><td>實質基準利率 (Real Rate)</td><td>{real_rate:+.2f}%</td><td>>1.5% 為限制性緊縮環境</td><td>--</td></tr>
            <tr><td>循環模式定性</td><td>生產力擴張循環 (Productivity-led)</td><td>AI Capex 與半導體盈餘增長主導</td><td>--</td></tr>
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

# 儲存網頁檔
with open("index.html", "w", encoding="utf-8") as f:
    f.write(html_content)

print("✅ 已成功產出最新網頁 index.html！")
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TG_CHAT_ID, "text": msg})
    except Exception as e:
        print(f"推播發送失敗: {e}")
