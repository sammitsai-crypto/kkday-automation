#!/bin/bash
# ════════════════════════════════════════════════════════════
# be2 每日報告 — 一鍵安裝腳本
# 使用方式：雙擊此檔案，依提示輸入 be2 帳號資訊即可
# ════════════════════════════════════════════════════════════

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MAIN_PY="$SCRIPT_DIR/be2_daily_report.py"
CONFIG_DIR="$HOME/.be2report"
CONFIG_FILE="$CONFIG_DIR/config.json"
PLIST_PATH="$HOME/Library/LaunchAgents/com.kkday.be2dailyreport.plist"
PYTHON3="$(which python3 2>/dev/null || echo '')"

clear
echo "================================================"
echo "  be2 每日報告 — 安裝程式"
echo "================================================"
echo ""

# ── 確認主程式存在 ───────────────────────────────
if [ ! -f "$MAIN_PY" ]; then
    echo "❌ 找不到 be2_daily_report.py"
    echo "   請確認此安裝檔與 be2_daily_report.py 放在同一個資料夾。"
    echo ""
    read -p "按 Enter 關閉..."
    exit 1
fi

# ── 確認 Python3 ────────────────────────────────
if [ -z "$PYTHON3" ]; then
    echo "❌ 找不到 python3，請先安裝 Python 3："
    echo "   https://www.python.org/downloads/macos/"
    read -p "按 Enter 關閉..."
    exit 1
fi
echo "✓ Python3：$PYTHON3"

# ── 確認 Playwright ─────────────────────────────
if ! "$PYTHON3" -c "from playwright.async_api import async_playwright" 2>/dev/null; then
    echo ""
    echo "正在安裝 Playwright（首次需要幾分鐘）..."
    "$PYTHON3" -m pip install playwright --quiet --break-system-packages 2>/dev/null || \
    "$PYTHON3" -m pip install playwright --quiet
    "$PYTHON3" -m playwright install chromium
fi
echo "✓ Playwright 已就緒"

# ── 輸入帳號資訊 ────────────────────────────────
echo ""
echo "請輸入你的 be2 登入資訊："
echo ""
read -p "  Email：" INPUT_EMAIL
read -s -p "  密碼：" INPUT_PASSWORD
echo ""
read -p "  你的中文姓名（顯示在報告上，可留空）：" INPUT_NAME
echo ""

# 組別 OID（東南亞=6，可之後修改 config.json）
INPUT_GROUP=6

# ── 寫入設定檔 ──────────────────────────────────
mkdir -p "$CONFIG_DIR"
cat > "$CONFIG_FILE" <<EOF
{
  "email":      "$INPUT_EMAIL",
  "password":   "$INPUT_PASSWORD",
  "group_oid":  $INPUT_GROUP,
  "user_name":  "$INPUT_NAME"
}
EOF
chmod 600 "$CONFIG_FILE"
echo "✓ 設定檔已建立：$CONFIG_FILE"

# ── 建立 launchd 排程（每天 9:30）──────────────
cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.kkday.be2dailyreport</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON3</string>
        <string>$MAIN_PY</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$SCRIPT_DIR</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>9</integer>
        <key>Minute</key>
        <integer>30</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$SCRIPT_DIR/be2_report.log</string>
    <key>StandardErrorPath</key>
    <string>$SCRIPT_DIR/be2_report_error.log</string>
    <key>RunAtLoad</key>
    <false/>
    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key>
        <string>$HOME</string>
        <key>PATH</key>
        <string>$(dirname "$PYTHON3"):/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
EOF
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"
echo "✓ 排程已設定：每天 09:30 自動執行"

# ── 建立桌面捷徑 ────────────────────────────────
LAUNCHER="$HOME/Desktop/be2每日報告.command"
cat > "$LAUNCHER" <<EOF
#!/bin/bash
"$PYTHON3" "$MAIN_PY"
EOF
chmod +x "$LAUNCHER"

OPENER="$HOME/Desktop/開啟最新報告.command"
cat > "$OPENER" <<'EOFOPENSCRIPT'
#!/bin/bash
latest=$(ls -t ~/Desktop/be2\ 報告/*.html 2>/dev/null | head -1)
if [ -z "$latest" ]; then
    osascript -e 'display alert "找不到報告" message "請先執行「be2每日報告.command」產生報告。"'
else
    open "$latest"
fi
EOFOPENSCRIPT
chmod +x "$OPENER"
echo "✓ 桌面捷徑已建立"

# ── 完成 ────────────────────────────────────────
echo ""
echo "================================================"
echo "  安裝完成！"
echo "================================================"
echo ""
echo "  桌面上有兩個圖示："
echo "  · be2每日報告.command    → 手動立即產生報告"
echo "  · 開啟最新報告.command   → 開啟最近一份報告"
echo ""
echo "  每天 09:30 會自動執行並開啟報告。"
echo ""

read -p "現在要立即跑一次看看嗎？(y/n) " RUN_NOW
if [[ "$RUN_NOW" =~ ^[Yy]$ ]]; then
    echo ""
    echo "執行中，請稍候（約 1-2 分鐘）..."
    "$PYTHON3" "$MAIN_PY"
fi
