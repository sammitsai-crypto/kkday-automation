#!/usr/bin/env python3
"""
be2 每日報告腳本
每天早上 9:30 自動執行，或隨時手動跑。
設定檔：~/.be2report/config.json
"""

import asyncio
import json
import os
import subprocess
import webbrowser
from datetime import datetime
from playwright.async_api import async_playwright

# ── 讀取設定檔（~/.be2report/config.json）──────────
_CONFIG_PATH = os.path.expanduser("~/.be2report/config.json")
if os.path.exists(_CONFIG_PATH):
    with open(_CONFIG_PATH) as _f:
        _cfg = json.load(_f)
    EMAIL      = _cfg.get("email", "")
    PASSWORD   = _cfg.get("password", "")
    GROUP_OID  = int(_cfg.get("group_oid", 6))
    USER_NAME  = _cfg.get("user_name", "")
else:
    print("❌ 找不到設定檔，請先執行安裝程式：安裝be2每日報告.command")
    exit(1)

REPORT_DIR = os.path.expanduser("~/Desktop/be2 報告")

# ════════════════════════════════════════════════
# macOS 通知
# ════════════════════════════════════════════════
def notify(title, message):
    script = f'display notification "{message}" with title "{title}" sound name "Glass"'
    subprocess.run(["osascript", "-e", script])

# ════════════════════════════════════════════════
# 登入
# ════════════════════════════════════════════════
async def login(context):
    page = await context.new_page()
    await page.goto("https://be2.kkday.com/v2/auth/login")
    await page.wait_for_load_state("networkidle")
    await asyncio.sleep(4)
    await page.wait_for_selector(".kkday-auth-svc-login-button", timeout=20000)
    async with context.expect_page(timeout=20000) as popup_info:
        await page.click(".kkday-auth-svc-login-button")
    popup = await popup_info.value
    await popup.wait_for_load_state("networkidle")
    await asyncio.sleep(2)
    await popup.wait_for_selector("input[type='email']", timeout=10000)
    await popup.fill("input[type='email']", EMAIL)
    await popup.fill("input[type='password']", PASSWORD)
    await popup.press("input[type='password']", "Enter")
    await asyncio.sleep(6)
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except:
        pass
    await page.bring_to_front()
    return page

# ════════════════════════════════════════════════
# 取得 JWT Token
# ════════════════════════════════════════════════
async def get_jwt_token(page):
    token_holder = {}
    async def capture(route, req):
        auth = req.headers.get("authorization", "")
        if auth.startswith("Bearer ") and not token_holder.get("token"):
            token_holder["token"] = auth.replace("Bearer ", "")
        await route.continue_()
    await page.route("**/*", capture)
    await page.goto("https://be2.kkday.com/v3/crm/ticket-list")
    await page.wait_for_load_state("networkidle")
    await asyncio.sleep(3)
    await page.unroute("**/*")
    return token_holder.get("token")

# ════════════════════════════════════════════════
# 工單：待處理 / 東南亞
# ════════════════════════════════════════════════
async def get_tickets(page, jwt_token):
    if "be2.kkday.com/v3/crm" not in page.url:
        await page.goto("https://be2.kkday.com/v3/crm/ticket-list")
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(3)

    js_code = f"""
        async () => {{
            try {{
                const resp = await fetch(
                    "https://api-gateway.kkday.com/bluemountain/api/v1/ticket-event/search",
                    {{
                        method: "POST",
                        headers: {{
                            "Content-Type": "application/json",
                            "Authorization": "Bearer {jwt_token}"
                        }},
                        body: JSON.stringify({{
                            "authKey": "BCS", "serviceName": "BCS",
                            "data": {{
                                "page": {{"currentPage": 1, "pageSize": 100}},
                                "taskStatus": [2],
                                "currentGroupOid": {GROUP_OID}
                            }}
                        }})
                    }}
                );
                const data = await resp.json();
                if (!data.data) return {{count: 0, items: [], error: data.metadata}};
                return {{
                    count: data.data.length,
                    items: data.data.map(t => ({{
                        oid: t.taskOid,
                        order: t.orderMid,
                        status: t.taskStatusCode,
                        created: t.createTime,
                        handler: t.currentUuid
                    }}))
                }};
            }} catch(e) {{
                return {{count: 0, items: [], error: e.message}};
            }}
        }}
    """
    return await page.evaluate(js_code)

# ════════════════════════════════════════════════
# 預存金：讀取所有頁的供應商資料
# ════════════════════════════════════════════════
async def get_prepaid_suppliers(page, jwt_token=""):
    await page.goto("https://be2.kkday.com/v2/supplier/prepaid/account/search")
    await page.wait_for_load_state("networkidle")
    await asyncio.sleep(3)

    # 設狀態 = 啟用
    selects = await page.query_selector_all("select")
    if selects:
        await selects[0].select_option(value="true")
        await asyncio.sleep(0.3)

    # ── 攔截頁面載入時的 API，找用戶列表（select2 預載）────────────
    op_oid = None
    op_param_name = None
    pageload_apis = []

    async def capture_pageload(response):
        if response.status == 200 and 'kkday.com' in response.url:
            skip = ['.js', '.css', '.png', '.woff', 'analytics', 'gtm', 'prepaid/account/list']
            if not any(s in response.url for s in skip):
                try:
                    body = await response.body()
                    text = body.decode('utf-8', errors='ignore')
                    if text.startswith('{') or text.startswith('['):
                        pageload_apis.append({"url": response.url, "body": text})
                except Exception:
                    pass

    page.on("response", capture_pageload)

    # 等頁面載入完，再從 DOM 和 API 讀取用戶 OID
    await asyncio.sleep(2)
    page.remove_listener("response", capture_pageload)

    # 從頁面載入 API 找含 sammi/蔡宜珊 的用戶資料
    for api in pageload_apis:
        if 'sammi' in api['body'].lower() or '蔡宜珊' in api['body']:
            try:
                d = json.loads(api['body'])
                items = d.get("data") or (d if isinstance(d, list) else [])
                for it in (items if isinstance(items, list) else []):
                    s = json.dumps(it, ensure_ascii=False)
                    if 'sammi' in s.lower() or '蔡宜珊' in s:
                        for key in ['oid','uuid','id','user_oid','userOid']:
                            if it.get(key):
                                op_oid = str(it[key])
                                break
                    if op_oid:
                        break
            except Exception:
                pass

    # ── OP select2 互動 ──────────────────────────────────────────────
    s2_wrappers = await page.query_selector_all(".select2-list-wrapper")
    if len(s2_wrappers) >= 3:
        await s2_wrappers[2].click()
        await asyncio.sleep(1.5)
        search_input = await page.query_selector("input[type='search']")
        if search_input:
            await page.keyboard.type("sammi", delay=80)
            await asyncio.sleep(2.5)
            try:
                option = await page.wait_for_selector("li:has-text('蔡宜珊')", timeout=4000)
                # 讀 option 完整 outer HTML 找 OID
                outer = await option.evaluate("el => el.outerHTML")
                import re as _re2
                # 找常見 OID 屬性
                m = _re2.search(r'(?:data-value|data-id|data-oid|value|:value)=["\']?(\d+)["\']?', outer)
                if m and not op_oid:
                    op_oid = m.group(1)
                await option.click()
            except Exception as e:
                print(f"  ⚠ option click: {e}")
                await page.evaluate("""
                    () => { document.querySelectorAll('li').forEach(li => {
                        const t = (li.textContent||'').trim();
                        const rect = li.getBoundingClientRect();
                        if (t.includes('蔡宜珊') && rect.width>0 && rect.height>0) li.click();
                    }); }
                """)
            await asyncio.sleep(0.5)

    # 從 Vue app root 找 OP 選項的 OID（選完後讀 store）
    # 從 Vue billingOpList 找蔡宜珊的 userUuid
    billing_op_list = await page.evaluate("""
        () => {
            const results = [];
            document.querySelectorAll('*').forEach(el => {
                const vk = Object.keys(el).find(k => k.startsWith('__vue'));
                if (!vk) return;
                try {
                    const vm = el[vk];
                    const src = vm._ || vm;
                    const d = src.data ? src.data() : (vm.$data || {});
                    if (d.billingOpList && Array.isArray(d.billingOpList)) {
                        results.push(...d.billingOpList);
                    }
                } catch(e) {}
            });
            return results;
        }
    """)

    my_uuid = None
    if billing_op_list:
        for u in billing_op_list:
            if u.get("userEmail","").lower() == EMAIL.lower():
                my_uuid = u.get("userUuid")
                break

    # 試找正確的 API param（用 UUID 試各種名稱，看哪個讓結果 < 200）
    import ssl as _ssl_mod, urllib.request as _ureq
    _ssl_ctx0 = _ssl_mod.create_default_context()
    _ssl_ctx0.check_hostname = False
    _ssl_ctx0.verify_mode = _ssl_mod.CERT_NONE

    def _api_get(url, token=""):
        try:
            req = _ureq.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})
            with _ureq.urlopen(req, context=_ssl_ctx0, timeout=10) as r:
                return json.loads(r.read().decode())
        except Exception:
            return None

    if my_uuid and not op_oid:
        base_test = "https://api-gateway.kkday.com/be2/api/v1/prepaid/account/list/1?is_active=true"
        param_candidates = [
            "billing_op_uuid","charge_user_uuid","op_user_uuid",
            "billing_op","charge_uuid","user_uuid","op_uuid",
            "charge_user_oid","op_user_oid","billing_op_oid"
        ]
        for pname in param_candidates:
            test_url = f"{base_test}&{pname}={my_uuid}&page=1"
            d = _api_get(test_url, jwt_token)
            if d:
                total = (d.get("metadata") or {}).get("pagination", {}).get("total", -1)
                if 0 < total < 300:
                    op_oid = my_uuid
                    op_param_name = pname
                    break

    if not op_oid and my_uuid:
        op_oid = my_uuid
    elif not op_oid:
        print(f"  ⚠ 無法取得 {EMAIL} 的 UUID，查詢全部帳戶")

    # 填可用餘額（必填）
    await page.evaluate("""
        () => {
            const inputs = Array.from(document.querySelectorAll('input')).filter(i => {
                const r = i.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && i.type !== 'hidden';
            });
            for (const inp of inputs) {
                if (['text','number',''].includes(inp.type)) {
                    inp.value = '9999999';
                    inp.dispatchEvent(new Event('input', {bubbles: true}));
                    inp.dispatchEvent(new Event('change', {bubbles: true}));
                    break;
                }
            }
        }
    """)
    await asyncio.sleep(0.3)

    # 攔截查詢後的所有 API request，找出帶 OP 篩選的真實 URL
    all_query_requests = []
    api_responses = []
    query_fired = [False]

    async def capture_request(request):
        if query_fired[0] and 'kkday.com' in request.url:
            skip = ['.js', '.css', '.png', '.woff', '.ico', 'analytics', 'gtm', 'google']
            if not any(s in request.url for s in skip):
                all_query_requests.append({
                    "url": request.url,
                    "method": request.method,
                    "post": request.post_data
                })

    async def capture_response(response):
        if query_fired[0] and 'prepaid' in response.url and response.status == 200:
            try:
                body = await response.body()
                text = body.decode('utf-8', errors='ignore')
                if text.startswith('{'):
                    data = json.loads(text)
                    if data.get("data") or data.get("metadata"):
                        api_responses.append({"url": response.url, "data": data})
            except Exception:
                pass

    page.on("request",  capture_request)
    page.on("response", capture_response)

    # 查詢
    query_fired[0] = True
    await page.evaluate("() => { document.querySelectorAll('button').forEach(b => { if ((b.textContent||'').trim()==='查詢') b.click(); }); }")
    await asyncio.sleep(5)

    page.remove_listener("request",  capture_request)
    page.remove_listener("response", capture_response)


    def parse_api_row(item):
        """把 API JSON 物件轉成顯示用 dict（欄位名稱依 be2 API 實際回傳）"""
        def fmt(v):
            if v is None:
                return ''
            try:
                f = float(v)
                if f == int(f):
                    return f"{int(f):,}"
                return f"{f:,.2f}"
            except Exception:
                return str(v)
        return {
            "id":           str(item.get("supplier_account_oid", "")),
            "name":         str(item.get("supplier_account_name", "")),
            "group":        str(item.get("supplier_group_name", "")),
            "status":       "啟用" if item.get("is_active") else "停用",
            "currency":     str(item.get("currency", "")),
            "balance":      fmt(item.get("account_margin")),
            "kkday_wip":    fmt(item.get("account_kkday_wip")),
            "supp_wip":     fmt(item.get("account_supplier_wip")),
            "min_level":    fmt(item.get("safe_credit")),
            "realtime_bal": fmt(item.get("instant_balance")),
            "replenish":    fmt(item.get("estimated_supplementary_amount")),
            "avg7d":        fmt(item.get("daily_average_usage")),
            "growth":       fmt(item.get("past_weeks_usage_growth")),
            "avg7d_future": fmt(item.get("future_daily_average_usage")),
        }

    # 若有找到 OP filter，直接用有篩選的 URL 重新查第一頁
    import re as _re, ssl as _ssl, urllib.request as _req
    _ssl_ctx = _ssl.create_default_context()
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = _ssl.CERT_NONE
    _auth_headers = {"Authorization": f"Bearer {jwt_token}"} if jwt_token else {}

    def _get_json(url):
        try:
            req = _req.Request(url, headers=_auth_headers)
            with _req.urlopen(req, context=_ssl_ctx, timeout=15) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            print(f"  fetch 失敗: {e}")
            return None

    # 組成有 OP filter 的基礎 URL
    op_base = "https://api-gateway.kkday.com/be2/api/v1/prepaid/account/list/1?is_active=true"
    if op_oid and op_param_name:
        op_base = f"{op_base}&{op_param_name}={op_oid}"
    else:
        print("  ⚠ 無 OP filter，查詢全部帳戶")

    first_page_data = _get_json(f"{op_base}&page=1")

    if first_page_data:
        pagination = (first_page_data.get("metadata") or {}).get("pagination") or {}
        total_count = pagination.get("total", 0)
        per_page    = pagination.get("per_page", 10) or 10
        total_pages = (total_count + per_page - 1) // per_page if total_count else 1
        items = first_page_data.get("data", [])
        all_rows = [parse_api_row(it) for it in items] if items else []

        for pg in range(2, min(total_pages + 1, 200)):
            pg_data = _get_json(f"{op_base}&page={pg}")
            if not pg_data:
                break
            pg_items = pg_data.get("data") or []
            if not pg_items:
                break
            all_rows.extend(parse_api_row(it) for it in pg_items)
            await asyncio.sleep(0.1)

        return all_rows

    # 備用：從 DOM 讀取（只有第一頁）
    print("  警告：未攔截到 API 回應，改從 DOM 讀取（僅第一頁）")
    rows = await page.evaluate("""
        () => {
            const result = [];
            document.querySelectorAll('tbody tr').forEach(tr => {
                const cells = Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim());
                if (cells.length >= 11) {
                    result.push({
                        id:           cells[0],
                        name:         cells[1],
                        group:        cells[2],
                        status:       cells[3],
                        currency:     cells[4],
                        balance:      cells[5],
                        kkday_wip:    cells[6],
                        supp_wip:     cells[7],
                        min_level:    cells[8],
                        realtime_bal: cells[9],
                        replenish:    cells[10],
                        avg7d:        cells[11] || '',
                        growth:       cells[12] || '',
                        avg7d_future: cells[13] || ''
                    });
                }
            });
            return result;
        }
    """)
    print(f"  DOM 讀取：{len(rows)} 筆")
    return rows

# ════════════════════════════════════════════════
# 產生 Dark Dashboard HTML 報告
# ════════════════════════════════════════════════
def build_html(now, tickets, prepaid_all):
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    weekday  = ["一","二","三","四","五","六","日"][now.weekday()]

    ticket_count = tickets.get("count", 0)

    def parse_num(s):
        try:
            return float(str(s).replace(",","").replace(" ",""))
        except:
            return 0.0

    # ── 去重合併：同供應商＋同幣別 → 加總，只保留需補款的 ──────────
    def merge_accounts(rows):
        """把同名稱+同幣別的帳戶合併，數值加總"""
        from collections import defaultdict
        groups = defaultdict(list)
        for r in rows:
            key = (r["name"], r["currency"])
            groups[key].append(r)

        merged = []
        for (name, currency), items in groups.items():
            total_replenish  = sum(parse_num(r["replenish"])  for r in items)
            total_realtime   = sum(parse_num(r["realtime_bal"]) for r in items)
            total_min_level  = sum(parse_num(r["min_level"])  for r in items)
            total_balance    = sum(parse_num(r["balance"])    for r in items)
            total_avg7d      = sum(parse_num(r["avg7d"])      for r in items)
            cnt = len(items)

            def fmt(v):
                if v == int(v):
                    return f"{int(v):,}"
                return f"{v:,.2f}"

            merged.append({
                "name":         name,
                "group":        items[0]["group"],
                "currency":     currency,
                "balance":      fmt(total_balance),
                "realtime_bal": fmt(total_realtime),
                "min_level":    fmt(total_min_level),
                "replenish":    fmt(total_replenish),
                "avg7d":        fmt(total_avg7d),
                "accounts":     cnt,   # 帳戶數
            })
        return merged

    # 篩出需補款（replenish > 0 或即時餘額 < 最低水位），去重後排序
    raw_needs = [
        r for r in prepaid_all
        if parse_num(r["realtime_bal"]) < parse_num(r["min_level"])
        or parse_num(r["replenish"]) > 0
    ]
    needs_replenish = merge_accounts(raw_needs)
    # 排除：7日均量為 0（未使用）、越南盾（VND）供應商
    needs_replenish = [
        r for r in needs_replenish
        if parse_num(r["avg7d"]) > 0 and r["currency"] != "VND"
    ]
    needs_replenish.sort(key=lambda r: parse_num(r["replenish"]), reverse=True)

    urgent_count = sum(1 for r in needs_replenish
                       if parse_num(r["realtime_bal"]) < 0
                       or parse_num(r["replenish"]) > 50000)

    # 同樣對全部帳戶去重（用於卡片的帳戶總數）
    all_merged = merge_accounts(prepaid_all)

    # ── 前 8 大補款橫條圖 ──────────────────────────
    top8 = needs_replenish[:8]
    max_val = max((parse_num(r["replenish"]) for r in top8), default=1) or 1
    chart_rows = ""
    for r in top8:
        val   = parse_num(r["replenish"])
        pct   = min(val / max_val * 100, 100)
        rt    = parse_num(r["realtime_bal"])
        color = "#e74c3c" if rt < 0 else ("#e67e22" if val > 50000 else "#26bec9")
        name  = r["name"][:30] + ("…" if len(r["name"]) > 30 else "")
        chart_rows += f"""
        <div class="chart-row">
          <div class="chart-label" title="{r['name']}">{name}</div>
          <div class="chart-track">
            <div class="chart-bar" style="width:{pct:.1f}%;background:{color};">
              <span class="chart-val">{r['replenish']} {r['currency']}</span>
            </div>
          </div>
        </div>"""

    # ── 供應商表格 ────────────────────────────────
    supplier_rows_html = ""
    for i, r in enumerate(needs_replenish, 1):
        replenish_val = parse_num(r["replenish"])
        realtime_val  = parse_num(r["realtime_bal"])
        minlevel_val  = parse_num(r["min_level"])

        # 健康度進度條
        if minlevel_val > 0:
            health_pct = max(0, min(realtime_val / minlevel_val * 100, 100))
        else:
            health_pct = 100 if realtime_val >= 0 else 0
        if realtime_val < 0:
            bar_color = "#e74c3c"
            row_cls   = "row-critical"
            badge     = '<span class="badge critical">透支</span>'
        elif replenish_val > 50000 or health_pct < 30:
            bar_color = "#e67e22"
            row_cls   = "row-urgent"
            badge     = '<span class="badge urgent">緊急</span>'
        elif health_pct < 60:
            bar_color = "#f1c40f"
            row_cls   = "row-warn"
            badge     = '<span class="badge warn">注意</span>'
        else:
            bar_color = "#2ecc71"
            row_cls   = ""
            badge     = '<span class="badge ok">補款</span>'

        health_bar = f"""<div class="hcell">
              <div class="htrack"><div class="hfill" style="width:{health_pct:.0f}%;background:{bar_color};"></div></div>
              <span class="hpct" style="color:{bar_color};">{health_pct:.0f}%</span>
            </div>"""

        supplier_rows_html += f"""
        <tr class="{row_cls}" data-name="{r['name'].lower()}">
          <td class="center muted small">{i}</td>
          <td>{badge}</td>
          <td class="supplier-name">
            <div>{r['name']}{f' <span class="acct-cnt">({r["accounts"]} 帳戶)</span>' if r.get("accounts", 1) > 1 else ''}</div>
            <div class="supplier-group">{r['group']}</div>
          </td>
          <td class="center"><span class="currency-pill">{r['currency']}</span></td>
          <td class="right">{r['realtime_bal']}</td>
          <td class="right muted">{r['min_level']}</td>
          <td>{health_bar}</td>
          <td class="right replenish-num">{r['replenish']}</td>
          <td class="right muted small">{r['avg7d']}</td>
        </tr>"""

    # ── 工單表格 ──────────────────────────────────
    ticket_rows_html = ""
    for i, t in enumerate(tickets.get("items", []), 1):
        ticket_rows_html += f"""
        <tr>
          <td class="center muted small">{i}</td>
          <td><a href="https://be2.kkday.com/crm/ticket/detail/{t['oid']}" target="_blank" class="tlink">{t['order']}</a></td>
          <td class="center muted">{t['oid']}</td>
          <td>{t['handler']}</td>
          <td class="muted small">{t['created']}</td>
        </tr>"""

    # 顏色配置（依排名循環）
    bar_colors = ["#ff6b6b","#ffa94d","#ffe066","#69db7c","#4dabf7","#da77f2","#f783ac","#63e6be"]

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>be2 每日報告 {date_str}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: "SF Mono", "JetBrains Mono", "Fira Code", "Menlo", monospace;
  background: #0d1117; color: #e6edf3; font-size: 13px; min-height: 100vh;
}}

/* ── HEADER ── */
.header {{
  padding: 28px 48px 20px;
  border-bottom: 1px solid #21262d;
}}
.header-top {{
  display: flex; align-items: flex-start; justify-content: space-between;
  margin-bottom: 6px;
}}
.cmd-line {{ color: #8b949e; font-size: 13px; margin-bottom: 8px; }}
.cmd-line span {{ color: #58a6ff; }}
.header h1 {{ font-size: 26px; font-weight: 800; color: #ffffff; letter-spacing: -.3px; }}
.header .tagline {{ color: #8b949e; font-size: 12px; margin-top: 5px; }}
.header-badge {{
  background: #161b22; border: 1px solid #30363d;
  border-radius: 8px; padding: 8px 14px; text-align: right;
  font-size: 11px; color: #8b949e; line-height: 1.7;
}}
.header-badge strong {{ color: #58a6ff; display: block; font-size: 13px; }}

/* ── STATS ROW ── */
.stats {{
  display: flex; gap: 0; padding: 24px 48px;
  border-bottom: 1px solid #21262d;
}}
.stat {{
  flex: 1; padding: 0 24px 0 0; margin: 0 24px 0 0;
  border-right: 1px solid #21262d;
}}
.stat:first-child {{ padding-left: 0; margin-left: 0; }}
.stat:last-child  {{ border-right: none; }}
.stat-num {{
  font-size: 38px; font-weight: 900; line-height: 1;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}}
.stat-num.red    {{ color: #ff7b72; }}
.stat-num.orange {{ color: #ffa657; }}
.stat-num.yellow {{ color: #e3b341; }}
.stat-num.green  {{ color: #3fb950; }}
.stat-label {{ font-size: 11px; color: #8b949e; margin-top: 4px; text-transform: uppercase; letter-spacing: .5px; }}
.stat-sub   {{ font-size: 11px; color: #ff7b72; margin-top: 2px; font-weight: 600; }}

/* ── SECTION ── */
.section {{ padding: 28px 48px; border-bottom: 1px solid #21262d; }}
.section-title {{
  font-size: 14px; font-weight: 700; color: #f0f6fc;
  margin-bottom: 16px; display: flex; align-items: center;
  justify-content: space-between;
}}
.section-title .cnt {{ color: #8b949e; font-size: 12px; font-weight: 400; }}

/* ── CHART ── */
.chart {{ display: flex; flex-direction: column; gap: 10px; }}
.chart-row {{ display: flex; align-items: center; gap: 14px; }}
.chart-rank {{
  width: 20px; text-align: right; color: #8b949e;
  font-size: 11px; flex-shrink: 0;
}}
.chart-name {{
  width: 220px; flex-shrink: 0; font-size: 12px; color: #c9d1d9;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}}
.chart-track {{
  flex: 1; background: #161b22; border-radius: 4px;
  overflow: hidden; height: 20px; border: 1px solid #21262d;
}}
.chart-fill {{
  height: 100%; border-radius: 3px;
  display: flex; align-items: center; padding: 0 8px;
  transition: width .5s ease;
}}
.chart-fill-text {{
  font-size: 10px; font-weight: 700; color: rgba(0,0,0,.75);
  white-space: nowrap; overflow: hidden;
}}
.chart-amt {{ width: 130px; text-align: right; font-size: 11px; color: #8b949e; flex-shrink: 0; }}

/* ── TABLE ── */
.tbl-wrap {{ overflow-x: auto; border-radius: 8px; border: 1px solid #21262d; }}
table {{ width: 100%; border-collapse: collapse; }}
th {{
  background: #161b22; padding: 10px 14px;
  font-size: 10px; font-weight: 700; color: #8b949e;
  border-bottom: 1px solid #21262d; white-space: nowrap;
  text-align: left; text-transform: uppercase; letter-spacing: .5px;
}}
td {{
  padding: 10px 14px; border-bottom: 1px solid #161b22;
  vertical-align: middle; color: #c9d1d9;
}}
tr:last-child td {{ border-bottom: none; }}
tr:hover td {{ background: #161b22; }}

.row-critical td {{ background: rgba(255,123,114,.05); }}
.row-urgent  td {{ background: rgba(255,166,87,.04); }}
.row-critical:hover td {{ background: rgba(255,123,114,.10); }}
.row-urgent:hover  td {{ background: rgba(255,166,87,.08); }}

.center  {{ text-align: center; }}
.right   {{ text-align: right; font-variant-numeric: tabular-nums; }}
.muted   {{ color: #8b949e; }}
.small   {{ font-size: 11px; }}

.supplier-name {{ font-weight: 600; color: #f0f6fc; max-width: 250px; }}
.supplier-group {{ font-size: 10px; color: #8b949e; margin-top: 2px; font-weight: 400; }}
.acct-cnt {{ font-size: 10px; color: #8b949e; font-weight: 400; }}
.replenish-num  {{ color: #ff7b72; font-weight: 800; font-size: 14px; }}
.currency-pill {{
  background: #1c2128; border: 1px solid #30363d;
  color: #79c0ff; font-size: 10px; font-weight: 700;
  padding: 2px 7px; border-radius: 20px;
}}

/* ── HEALTH BAR ── */
.hcell {{ display: flex; align-items: center; gap: 6px; min-width: 90px; }}
.htrack {{
  flex: 1; height: 4px; background: #21262d; border-radius: 2px; overflow: hidden;
}}
.hfill  {{ height: 100%; border-radius: 2px; }}
.hpct   {{ font-size: 10px; font-weight: 700; width: 28px; text-align: right; flex-shrink: 0; }}

/* ── BADGES ── */
.badge {{
  display: inline-block; padding: 2px 8px; border-radius: 20px;
  font-size: 10px; font-weight: 700; white-space: nowrap;
}}
.badge.critical {{ background: rgba(255,123,114,.15); color: #ff7b72; border: 1px solid rgba(255,123,114,.3); }}
.badge.urgent   {{ background: rgba(255,166,87,.15);  color: #ffa657; border: 1px solid rgba(255,166,87,.3); }}
.badge.warn     {{ background: rgba(227,179,65,.15);  color: #e3b341; border: 1px solid rgba(227,179,65,.3); }}
.badge.ok       {{ background: rgba(63,185,80,.12);   color: #3fb950; border: 1px solid rgba(63,185,80,.25); }}

/* ── SEARCH ── */
.search {{
  background: #161b22; border: 1px solid #30363d; border-radius: 6px;
  padding: 5px 12px; font-size: 12px; color: #c9d1d9;
  font-family: inherit; outline: none; width: 200px;
}}
.search::placeholder {{ color: #8b949e; }}
.search:focus {{ border-color: #388bfd; }}

/* ── TICKET LINK ── */
.tlink {{ color: #58a6ff; font-weight: 600; text-decoration: none; }}
.tlink:hover {{ text-decoration: underline; }}

/* ── EMPTY / FOOTER ── */
.empty  {{ padding: 40px; text-align: center; color: #8b949e; font-size: 13px; }}
.footer {{
  text-align: center; padding: 24px; font-size: 11px;
  color: #484f58; border-top: 1px solid #21262d;
}}
.hidden {{ display: none !important; }}
</style>
</head>
<body>

<!-- HEADER -->
<div class="header">
  <div class="cmd-line">$ be2 <span>--report daily</span> --op {USER_NAME or EMAIL} --group SEA</div>
  <div class="header-top">
    <div>
      <h1>be2 每日營運報告</h1>
      <div class="tagline">{date_str}（週{weekday}）· 產生時間 {time_str} · 資料來源 be2.kkday.com</div>
    </div>
    <div class="header-badge">
      <strong>{USER_NAME or EMAIL.split("@")[0]} OP</strong>
      東南亞 / SEA 組<br>
      {date_str}
    </div>
  </div>
</div>

<!-- STATS -->
<div class="stats">
  <div class="stat">
    <div class="stat-num red">{ticket_count}</div>
    <div class="stat-label">待處理工單</div>
    <div class="stat-label" style="margin-top:1px;">東南亞 / SEA</div>
  </div>
  <div class="stat">
    <div class="stat-num orange">{len(needs_replenish)}</div>
    <div class="stat-label">需補款供應商</div>
    {f'<div class="stat-sub">其中 {urgent_count} 個緊急</div>' if urgent_count else '<div class="stat-label">預估補款 &gt; 0</div>'}
  </div>
  <div class="stat">
    <div class="stat-num yellow">{urgent_count}</div>
    <div class="stat-label">緊急 / 透支</div>
    <div class="stat-label">replenish &gt; 50K 或 透支</div>
  </div>
  <div class="stat">
    <div class="stat-num green">{len(all_merged)}</div>
    <div class="stat-label">供應商總數</div>
    <div class="stat-label">啟用中（去重後）</div>
  </div>
</div>

<!-- 補款排行橫條圖 -->
{"" if not top8 else f"""
<div class="section">
  <div class="section-title">
    補款金額排行（Top {len(top8)}）
    <span class="cnt">預估補款需求最高</span>
  </div>
  <div class="chart">
    {"".join(f'''
    <div class="chart-row">
      <div class="chart-rank">{i+1}</div>
      <div class="chart-name" title="{r["name"]}">{r["name"][:28] + ("…" if len(r["name"])>28 else "")}</div>
      <div class="chart-track">
        <div class="chart-fill" style="width:{min(parse_num(r["replenish"])/(max((parse_num(x["replenish"]) for x in top8),default=1) or 1)*100,100):.1f}%;background:{bar_colors[i%len(bar_colors)]};">
          <span class="chart-fill-text">{r["currency"]}</span>
        </div>
      </div>
      <div class="chart-amt">{r["replenish"]}</div>
    </div>''' for i,r in enumerate(top8))}
  </div>
</div>"""}

<!-- 供應商明細 -->
<div class="section">
  <div class="section-title">
    需補款供應商明細
    <div style="display:flex;gap:10px;align-items:center;">
      <span class="cnt">{len(needs_replenish)} 筆</span>
      <input class="search" id="suppSearch" placeholder="搜尋供應商…" oninput="filterTable(this,'suppTbl')">
    </div>
  </div>
  {"<div class='empty'>✓ 目前無需補款供應商</div>" if not needs_replenish else f"""
  <div class="tbl-wrap">
  <table id="suppTbl">
    <thead>
      <tr>
        <th class="center">#</th>
        <th>狀態</th>
        <th>供應商</th>
        <th class="center">幣別</th>
        <th class="right">即時餘額</th>
        <th class="right">最低水位</th>
        <th>健康度</th>
        <th class="right">預估補款金額</th>
        <th class="right muted">7日均量</th>
      </tr>
    </thead>
    <tbody>
      {supplier_rows_html}
    </tbody>
  </table>
  </div>"""}
</div>

<!-- 工單 -->
<div class="section">
  <div class="section-title">
    待處理工單 <span style="color:#8b949e;font-weight:400;">東南亞 / SEA</span>
    <span class="cnt">{ticket_count} 筆</span>
  </div>
  {"<div class='empty'>✓ 目前無待處理工單</div>" if not tickets.get('items') else f"""
  <div class="tbl-wrap">
  <table>
    <thead>
      <tr>
        <th class="center">#</th>
        <th>訂單 MID</th>
        <th class="center">工單 OID</th>
        <th>負責人</th>
        <th>建立時間</th>
      </tr>
    </thead>
    <tbody>
      {ticket_rows_html}
    </tbody>
  </table>
  </div>"""}
</div>

<div class="footer">be2 daily report · generated {date_str} {time_str} · be2.kkday.com</div>

<script>
function filterTable(input, tableId) {{
  const q = input.value.toLowerCase();
  document.querySelectorAll('#' + tableId + ' tbody tr').forEach(tr => {{
    tr.classList.toggle('hidden', q && !(tr.dataset.name||'').includes(q));
  }});
}}
</script>
</body>
</html>"""
    return html

# ════════════════════════════════════════════════
# 主程式
# ════════════════════════════════════════════════
async def main():
    now = datetime.now()
    print(f"be2 每日報告開始 {now.strftime('%Y-%m-%d %H:%M')}...")

    os.makedirs(REPORT_DIR, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})

        try:
            print("登入中...")
            page = await login(context)
            print(f"✓ 登入成功")

            print("取得 token...")
            jwt_token = await get_jwt_token(page)
            if not jwt_token:
                raise Exception("無法取得 JWT token")
            print("✓ Token 取得成功")

            print("查詢工單（待處理 / 東南亞）...")
            tickets = await get_tickets(page, jwt_token)
            print(f"✓ 工單：{tickets.get('count', 0)} 件")

            print("查詢預存金帳戶（啟用 / 蔡宜珊）...")
            prepaid_all = await get_prepaid_suppliers(page, jwt_token)
            needs = [r for r in prepaid_all if float(r["replenish"].replace(",","") or 0) > 0]
            print(f"✓ 預存金：共 {len(prepaid_all)} 筆，其中 {len(needs)} 筆需補款")

        except Exception as e:
            print(f"❌ 錯誤: {e}")
            notify("be2 報告錯誤", str(e))
            await browser.close()
            return
        finally:
            await browser.close()

    # 產生 HTML 報告
    html = build_html(now, tickets, prepaid_all)
    report_file = os.path.join(REPORT_DIR, f"{now.strftime('%Y-%m-%d_%H%M')}.html")
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✓ 報告已存：{report_file}")

    # 開啟報告
    webbrowser.open(f"file://{report_file}")

    # macOS 通知
    ticket_count = tickets.get("count", 0)
    msg = f"工單待處理：{ticket_count} 件｜需補款供應商：{len(needs)} 筆\n報告已存到桌面「be2 報告」"
    notify(f"be2 每日報告 {now.strftime('%m/%d')}", msg)
    print(f"\n✅ 完成！報告已開啟，通知已發送。")

if __name__ == "__main__":
    asyncio.run(main())
