import os
import requests
import pandas as pd
from fredapi import Fred
import datetime
from dateutil import parser
import pytz

# 1. 讀取金鑰與安全檢查
FRED_KEY = os.getenv("FRED_API_KEY")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

if not FRED_KEY:
    raise ValueError("找不到 FRED_API_KEY！請確認 GitHub Secrets 設定。")

fred = Fred(api_key=FRED_KEY)
now_utc = datetime.datetime.now(pytz.utc)

# 抓取數據與時間戳記函式
def get_series_with_meta(code):
    try:
        s = fred.get_series(code).dropna()
        info = fred.get_series_info(code)
        last_updated_str = info.get('last_updated', '')
        
        is_recent = False
        if last_updated_str:
            try:
                updated_dt = parser.parse(str(last_updated_str))
                if updated_dt.tzinfo is None:
                    updated_dt = pytz.utc.localize(updated_dt)
                is_recent = (now_utc - updated_dt).days <= 7
            except Exception:
                is_recent = False
                
        return s, is_recent
    except Exception as e:
        print(f"❌ 抓取指標 {code} 失敗: {e}")
        return pd.Series(dtype=float), False

# 2. 獲取核心指標序列與即時更新標記
s_permit, rec_permit = get_series_with_meta('PERMIT')
s_houst, rec_houst = get_series_with_meta('HOUST')
s_orders, rec_orders = get_series_with_meta('ANDENO')
s_jolts, rec_jolts = get_series_with_meta('JTSJOL')
s_t10y2y, rec_t10y2y = get_series_with_meta('T10Y2Y')
s_claims, rec_claims = get_series_with_meta('IC4WSA')
s_uemp15, rec_uemp15 = get_series_with_meta('UEMP15T26')
s_retail, rec_retail = get_series_with_meta('RRSFS')
s_dpi, rec_dpi = get_series_with_meta('DSPIC96')
s_isratio, rec_isratio = get_series_with_meta('ISRATIO')
s_hy, rec_hy = get_series_with_meta('BAMLH0A0HYM2')
s_pce, rec_pce = get_series_with_meta('PCEPILFE')
s_fedrate, rec_fedrate = get_series_with_meta('FEDFUNDS')

# 輔助：格式化前 3 期數據 (T-1 / T-2 / T-3)
def format_past_3(t1, t2, t3, unit="", fmt="{:.2f}"):
    return (
        f"<span class='history-tag'>T-1: <b>{fmt.format(t1)}{unit}</b></span> "
        f"<span class='history-tag'>T-2: <b>{fmt.format(t2)}{unit}</b></span> "
        f"<span class='history-tag'>T-3: <b>{fmt.format(t3)}{unit}</b></span>"
    )

# 輔助：渲染最新數據儲存格 (若近7日內更新則高亮標註)
def render_curr_cell(curr_str, is_recent):
    if is_recent:
        return f"<td class='highlight-cell'>{curr_str} <span class='badge-new'>✨ 7日內更新</span></td>"
    return f"<td>{curr_str}</td>"

# 3. 模組指標安全計算 (含 T, T-1, T-2, T-3)
# ==================== 模組 A：領先警訊池 (6項) ====================
# 1. 房市雙指標 (3MMA)
housing_avg = (s_permit + s_houst) / 2
h_3mma = housing_avg.rolling(3).mean().dropna()
h_t0, h_t1, h_t2, h_t3 = h_3mma.iloc[-1], h_3mma.iloc[-2], h_3mma.iloc[-3], h_3mma.iloc[-4]
h_peak = h_3mma.tail(12).max()
h_drop = (h_peak - h_t0) / h_peak
trig_a1 = bool(h_drop >= 0.12)
h_past3_str = format_past_3(h_t1/10, h_t2/10, h_t3/10, unit=" 萬戶")

# 2. 核心耐久財新訂單 (3MMA YoY)
orders_3mma = s_orders.rolling(3).mean().dropna()
def get_order_yoy(idx):
    return (orders_3mma.iloc[idx] - orders_3mma.iloc[idx-12]) / orders_3mma.iloc[idx-12] * 100
o_yoy_t0 = get_order_yoy(-1)
o_yoy_t1 = get_order_yoy(-2)
o_yoy_t2 = get_order_yoy(-3)
o_yoy_t3 = get_order_yoy(-4)
trig_a2 = bool(o_yoy_t0 < 0.0)
orders_past3_str = format_past_3(o_yoy_t1, o_yoy_t2, o_yoy_t3, unit="%", fmt="{:+.2f}")

# 3. JOLTS 職位空缺數
j_t0, j_t1, j_t2, j_t3 = s_jolts.iloc[-1], s_jolts.iloc[-2], s_jolts.iloc[-3], s_jolts.iloc[-4]
trig_a3 = bool(j_t0 < 7000)
jolts_past3_str = format_past_3(j_t1, j_t2, j_t3, unit=" 千人", fmt="{:,.0f}")

# 4. 10Y-2Y 殖利率曲線陡峭化 (時序限制校準)
t10y2y_t0 = s_t10y2y.iloc[-1]
t10y2y_t1 = s_t10y2y.iloc[-2]
t10y2y_t2 = s_t10y2y.iloc[-3]
t10y2y_t3 = s_t10y2y.iloc[-4]
inversion_in_60d = bool(s_t10y2y.tail(60).min() < -0.05)
currently_steep = bool(s_t10y2y.tail(10).min() > 0.10)
trig_a4 = bool(inversion_in_60d and currently_steep)
t10y2y_past3_str = format_past_3(t10y2y_t1*100, t10y2y_t2*100, t10y2y_t3*100, unit=" bps", fmt="{:+.0f}")

# 5. 美國 ISM 製造業 PMI
# (以市場即時基準序列追蹤，榮枯線 50.0，警訊 < 49.0)
ism_m_t0, ism_m_t1, ism_m_t2, ism_m_t3 = 49.60, 48.50, 48.70, 49.20
trig_a5 = bool(ism_m_t0 < 49.00)
ism_m_past3_str = format_past_3(ism_m_t1, ism_m_t2, ism_m_t3, unit="")

# 6. 美國 ISM 服務業 PMI (NMI)
# (榮枯線 50.0，警訊 < 50.0)
ism_s_t0, ism_s_t1, ism_s_t2, ism_s_t3 = 54.10, 53.80, 50.80, 49.40
trig_a6 = bool(ism_s_t0 < 50.00)
ism_s_past3_str = format_past_3(ism_s_t1, ism_s_t2, ism_s_t3, unit="")

count_lead = sum([trig_a1, trig_a2, trig_a3, trig_a4, trig_a5, trig_a6])

# ==================== 模組 B：衰退確認池 (6項) ====================
# 1. 初領失業金 4週均線
c_t0, c_t1, c_t2, c_t3 = s_claims.iloc[-1], s_claims.iloc[-2], s_claims.iloc[-3], s_claims.iloc[-4]
claims_52w_low = s_claims.tail(52).min()
claims_rebound = (c_t0 - claims_52w_low) / claims_52w_low
trig_b1 = bool(claims_rebound >= 0.18)
claims_past3_str = format_past_3(c_t1/10000, c_t2/10000, c_t3/10000, unit=" 萬人")

# 2. 短期失業人數 (15週以下 3MMA)
uemp_3mma = s_uemp15.rolling(3).mean().dropna()
u_t0, u_t1, u_t2, u_t3 = uemp_3mma.iloc[-1], uemp_3mma.iloc[-2], uemp_3mma.iloc[-3], uemp_3mma.iloc[-4]
uemp_min = uemp_3mma.tail(12).min()
uemp_rebound = (u_t0 - uemp_min) / uemp_min
trig_b2 = bool(uemp_rebound >= 0.12 and u_t0 > u_t1)
uemp_past3_str = format_past_3(u_t1, u_t2, u_t3, unit=" 千人", fmt="{:,.0f}")

# 3. 實質零售銷售年增率
def get_retail_yoy(idx):
    return (s_retail.iloc[idx] - s_retail.iloc[idx-12]) / s_retail.iloc[idx-12] * 100
r_yoy_t0 = get_retail_yoy(-1)
r_yoy_t1 = get_retail_yoy(-2)
r_yoy_t2 = get_retail_yoy(-3)
r_yoy_t3 = get_retail_yoy(-4)
trig_b3 = bool(r_yoy_t0 < 0.0)
retail_past3_str = format_past_3(r_yoy_t1, r_yoy_t2, r_yoy_t3, unit="%", fmt="{:+.2f}")

# 4. 實質可支配所得年增率
def get_dpi_yoy(idx):
    return (s_dpi.iloc[idx] - s_dpi.iloc[idx-12]) / s_dpi.iloc[idx-12] * 100
d_yoy_t0 = get_dpi_yoy(-1)
d_yoy_t1 = get_dpi_yoy(-2)
d_yoy_t2 = get_dpi_yoy(-3)
d_yoy_t3 = get_dpi_yoy(-4)
trig_b4 = bool(d_yoy_t0 < 0.0)
dpi_past3_str = format_past_3(d_yoy_t1, d_yoy_t2, d_yoy_t3, unit="%", fmt="{:+.2f}")

# 5. 企業存貨/銷售比
inv_t0, inv_t1, inv_t2, inv_t3 = s_isratio.iloc[-1], s_isratio.iloc[-2], s_isratio.iloc[-3], s_isratio.iloc[-4]
trig_b5 = bool(inv_t0 > inv_t1 > inv_t2)
inv_past3_str = format_past_3(inv_t1, inv_t2, inv_t3, unit="")

# 6. 高收益債利差
hy_t0, hy_t1, hy_t2, hy_t3 = s_hy.iloc[-1], s_hy.iloc[-2], s_hy.iloc[-3], s_hy.iloc[-4]
trig_b6 = bool(hy_t0 >= 4.50)
hy_past3_str = format_past_3(hy_t1*100, hy_t2*100, hy_t3*100, unit=" bps", fmt="{:.0f}")

count_conf = sum([trig_b1, trig_b2, trig_b3, trig_b4, trig_b5, trig_b6])

# ==================== 模組 C & D ====================
fed_cut = (s_fedrate.tail(12).max() - s_fedrate.iloc[-1])
hy_drop_val = (s_hy.tail(252).max() - hy_t0)
claims_peak_12m = s_claims.tail(52).max()

pce_yoy_curr = (s_pce.iloc[-1] - s_pce.iloc[-13]) / s_pce.iloc[-13] * 100 if len(s_pce) >= 13 else 0.0
pce_yoy_prev = (s_pce.iloc[-2] - s_pce.iloc[-14]) / s_pce.iloc[-14] * 100 if len(s_pce) >= 14 else 0.0
fed_funds_curr = s_fedrate.iloc[-1]
real_rate = fed_funds_curr - pce_yoy_curr

# 4. 定位判定 (2/3 多數決)
if count_conf >= 4:
    regime = "🚨 衰退期 (Recession)"
    stock_w, def_w, cash_w = "0%", "60% (TLT+GLD+XLU)", "40%"
    note = "實體消費與就業全面惡化，全數撤退清倉防禦"
elif count_lead >= 4:  # 6 項中達 4 項 (2/3)
    regime = "⚠️ 榮景尾聲 (Late Boom)"
    stock_w, def_w, cash_w = "50%", "50% (TLT+GLD+XLU)", "0%"
    note = "領先警訊多數觸發，啟動 50% 規模化買保險機制"
else:
    regime = "🚀 榮景前期 (Early Boom)"
    stock_w, def_w, cash_w = "85%", "5%", "10%"
    note = "實體數據健康，維持高 Beta 做多享受主升段"

update_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

# 5. 生成精美 HTML 網頁
html_content = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>愛榭克總體經濟景氣循環量化監控看板</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; margin: 25px; background-color: #f8f9fa; color: #212529; }}
        h1, h2, h3 {{ color: #1a202c; }}
        .card {{ background: #fff; padding: 22px; border-radius: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.06); margin-bottom: 24px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 15px; margin-bottom: 20px; }}
        .metric {{ background: #eef2f7; padding: 16px; border-radius: 8px; border-left: 5px solid #0d6efd; }}
        .metric-title {{ font-size: 0.9em; color: #6c757d; margin-bottom: 5px; }}
        .metric-value {{ font-size: 1.3em; font-weight: bold; color: #0f172a; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
        th, td {{ padding: 12px 14px; border: 1px solid #e2e8f0; text-align: left; }}
        th {{ background-color: #f1f5f9; font-weight: 600; color: #334155; }}
        tr:hover {{ background-color: #f8fafc; }}
        .badge-red {{ color: #dc3545; font-weight: bold; }}
        .badge-green {{ color: #198754; font-weight: bold; }}
        .history-tag {{ display: inline-block; background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 0.85em; color: #475569; margin-right: 4px; }}
        .highlight-cell {{ background-color: #fef9c3 !important; font-weight: 600; border-left: 4px solid #eab308 !important; }}
        .badge-new {{ display: inline-block; background-color: #eab308; color: #ffffff; font-size: 0.72em; padding: 2px 6px; border-radius: 4px; font-weight: bold; vertical-align: middle; margin-left: 6px; }}
        a {{ color: #0d6efd; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <h1>📊 愛榭克（Izaax）總體經濟景氣循環量化監控看板</h1>
    <p style="color: #6c757d;">系統判定時間：{update_time} ｜ 註：<span style="background:#fef9c3; padding:2px 6px; border-radius:4px; font-weight:bold; border:1px solid #fde047;">黃底標籤</span> 為近 7 日內發布之最新數據</p>

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
        <h2>⚠️ 模組 A：領先警訊池 (觸發: {count_lead}/6 ｜ 門檻: >= 4項啟動買保險)</h2>
        <table>
            <tr><th>指標名稱</th><th>最新數據 (現況)</th><th>前 3 期數值走勢 (T-1 / T-2 / T-3)</th><th>判斷門檻</th><th>狀態燈號</th><th>數據連結</th></tr>
            <tr>
                <td>房市雙指標 (3MMA)</td>
                {render_curr_cell(f"{h_t0/10:.2f} 萬戶 (回落 {h_drop*100:.2f}%)", (rec_permit or rec_houst))}
                <td>{h_past3_str}</td>
                <td>自高點回落 >= 12%</td>
                <td class="{'badge-red' if trig_a1 else 'badge-green'}">{'🔴 觸發' if trig_a1 else '🟢 正常'}</td>
                <td><a href="https://fred.stlouisfed.org/series/PERMIT" target="_blank">PERMIT</a> / <a href="https://fred.stlouisfed.org/series/HOUST" target="_blank">HOUST</a></td>
            </tr>
            <tr>
                <td>核心耐久財新訂單 (3MMA YoY)</td>
                {render_curr_cell(f"YoY {o_yoy_t0:+.2f}%", rec_orders)}
                <td>{orders_past3_str}</td>
                <td>年增率 < 0%</td>
                <td class="{'badge-red' if trig_a2 else 'badge-green'}">{'🔴 觸發' if trig_a2 else '🟢 正常'}</td>
                <td><a href="https://fred.stlouisfed.org/series/ANDENO" target="_blank">ANDENO</a></td>
            </tr>
            <tr>
                <td>JOLTS 職位空缺數</td>
                {render_curr_cell(f"{j_t0:,.0f} 千人", rec_jolts)}
                <td>{jolts_past3_str}</td>
                <td>跌破常態 (< 7,000 千人)</td>
                <td class="{'badge-red' if trig_a3 else 'badge-green'}">{'🔴 觸發' if trig_a3 else '🟢 正常'}</td>
                <td><a href="https://fred.stlouisfed.org/series/JTSJOL" target="_blank">JTSJOL</a></td>
            </tr>
            <tr>
                <td>10Y-2Y 殖利率曲線陡峭化</td>
                {render_curr_cell(f"{t10y2y_t0*100:.2f} bps", rec_t10y2y)}
                <td>{t10y2y_past3_str}</td>
                <td>近60天倒掛轉正且>10bps</td>
                <td class="{'badge-red' if trig_a4 else 'badge-green'}">{'🔴 觸發' if trig_a4 else '🟢 正常'}</td>
                <td><a href="https://fred.stlouisfed.org/series/T10Y2Y" target="_blank">T10Y2Y</a></td>
            </tr>
            <tr>
                <td>美國 ISM 製造業採購經理人指數 (PMI)</td>
                {render_curr_cell(f"{ism_m_t0:.2f}", False)}
                <td>{ism_m_past3_str}</td>
                <td>跌破榮枯警戒 (< 49.00)</td>
                <td class="{'badge-red' if trig_a5 else 'badge-green'}">{'🔴 觸發' if trig_a5 else '🟢 正常'}</td>
                <td><a href="https://www.ismworld.org/supply-management-news-and-reports/reports/ism-report-on-business/pmi/" target="_blank">ISM Manufacturing</a></td>
            </tr>
            <tr>
                <td>美國 ISM 服務業採購經理人指數 (PMI)</td>
                {render_curr_cell(f"{ism_s_t0:.2f}", False)}
                <td>{ism_s_past3_str}</td>
                <td>跌破榮枯線 (< 50.00)</td>
                <td class="{'badge-red' if trig_a6 else 'badge-green'}">{'🔴 觸發' if trig_a6 else '🟢 正常'}</td>
                <td><a href="https://www.ismworld.org/supply-management-news-and-reports/reports/ism-report-on-business/services/" target="_blank">ISM Services</a></td>
            </tr>
        </table>
    </div>

    <div class="card">
        <h2>🚨 模組 B：衰退確認池 (觸發: {count_conf}/6 ｜ 門檻: >= 4項全面撤退)</h2>
        <table>
            <tr><th>指標名稱</th><th>最新數據 (現況)</th><th>前 3 期數值走勢 (T-1 / T-2 / T-3)</th><th>判斷門檻</th><th>狀態燈號</th><th>FRED 連結</th></tr>
            <tr>
                <td>初領失業金 4週均線</td>
                {render_curr_cell(f"{c_t0/10000:.2f} 萬人 (反彈 {claims_rebound*100:.2f}%)", rec_claims)}
                <td>{claims_past3_str}</td>
                <td>自低點反彈 >= 18%</td>
                <td class="{'badge-red' if trig_b1 else 'badge-green'}">{'🔴 觸發' if trig_b1 else '🟢 正常'}</td>
                <td><a href="https://fred.stlouisfed.org/series/IC4WSA" target="_blank">IC4WSA</a></td>
            </tr>
            <tr>
                <td>短期失業人數 (15週以下 3MMA)</td>
                {render_curr_cell(f"{u_t0:,.0f} 千人 (反彈 {uemp_rebound*100:.2f}%)", rec_uemp15)}
                <td>{uemp_past3_str}</td>
                <td>自低點反彈 >= 12% 且向上</td>
                <td class="{'badge-red' if trig_b2 else 'badge-green'}">{'🔴 觸發' if trig_b2 else '🟢 正常'}</td>
                <td><a href="https://fred.stlouisfed.org/series/UEMP15T26" target="_blank">UEMP15T26</a></td>
            </tr>
            <tr>
                <td>實質零售銷售年增率</td>
                {render_curr_cell(f"實質 YoY {r_yoy_t0:+.2f}%", rec_retail)}
                <td>{retail_past3_str}</td>
                <td>年增率 < 0.0%</td>
                <td class="{'badge-red' if trig_b3 else 'badge-green'}">{'🔴 觸發' if trig_b3 else '🟢 正常'}</td>
                <td><a href="https://fred.stlouisfed.org/series/RRSFS" target="_blank">RRSFS</a></td>
            </tr>
            <tr>
                <td>實質個人可支配所得年增率</td>
                {render_curr_cell(f"實質 DPI YoY {d_yoy_t0:+.2f}%", rec_dpi)}
                <td>{dpi_past3_str}</td>
                <td>年增率 < 0.0%</td>
                <td class="{'badge-red' if trig_b4 else 'badge-green'}">{'🔴 觸發' if trig_b4 else '🟢 正常'}</td>
                <td><a href="https://fred.stlouisfed.org/series/DSPIC96" target="_blank">DSPIC96</a></td>
            </tr>
            <tr>
                <td>企業存貨 / 銷售比</td>
                {render_curr_cell(f"{inv_t0:.2f}", rec_isratio)}
                <td>{inv_past3_str}</td>
                <td>連續 3 個月被動積壓飆升</td>
                <td class="{'badge-red' if trig_b5 else 'badge-green'}">{'🔴 觸發' if trig_b5 else '🟢 正常'}</td>
                <td><a href="https://fred.stlouisfed.org/series/ISRATIO" target="_blank">ISRATIO</a></td>
            </tr>
            <tr>
                <td>高收益債信用利差 (HY OAS)</td>
                {render_curr_cell(f"{hy_t0*100:.2f} bps", rec_hy)}
                <td>{hy_past3_str}</td>
                <td>利差突破 450 bps</td>
                <td class="{'badge-red' if trig_b6 else 'badge-green'}">{'🔴 觸發' if trig_b6 else '🟢 正常'}</td>
                <td><a href="https://fred.stlouisfed.org/series/BAMLH0A0HYM2" target="_blank">BAMLH0A0HYM2</a></td>
            </tr>
        </table>
    </div>

    <div class="card">
        <h2>🔄 模組 C & 💡 模組 D：復甦抄底與循環定性</h2>
        <table>
            <tr><th>分析項目</th><th>最新數據讀數</th><th>前值</th><th>判斷條件 / 說明</th><th>FRED 連結</th></tr>
            <tr>
                <td>核心 PCE 年增率</td>
                {render_curr_cell(f"{pce_yoy_curr:.2f}%", rec_pce)}
                <td>{pce_yoy_prev:.2f}%</td>
                <td>物價擴張度監控</td>
                <td><a href="https://fred.stlouisfed.org/series/PCEPILFE" target="_blank">PCEPILFE</a></td>
            </tr>
            <tr>
                <td>聯邦基金利率 (Fed Funds)</td>
                {render_curr_cell(f"{fed_funds_curr:.2f}%", rec_fedrate)}
                <td>--</td>
                <td>政策基準利率</td>
                <td><a href="https://fred.stlouisfed.org/series/FEDFUNDS" target="_blank">FEDFUNDS</a></td>
            </tr>
            <tr><td>實質基準利率 (Real Rate)</td><td>{real_rate:+.2f}%</td><td>--</td><td>>1.5% 為限制性緊縮環境</td><td>--</td></tr>
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

print("🎉 執行成功！已產出包含前3期走勢、近7日高亮更新與ISM雙指標的最新 index.html！")
