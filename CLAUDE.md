# KKday SEA OP 自動化工具集

本 repo 存放東南亞 OP 組的自動化工具，由組員共同維護。

## 工具總覽

| 工具 | 類型 | 說明 |
|------|------|------|
| be2 每日報告 | 本機安裝 | 每天 09:30 自動抓取預存金補款資料，產生報告 |
| Disney Cruise 客服知識庫 | 網頁工具 | 貼訊息自動辨識類型，帶出 OP 步驟與 CS 回覆 |

工具總覽網頁：https://sammitsai-crypto.github.io/kkday-automation/

---

## 安裝說明（請 Claude Code 照以下步驟執行）

### 🌐 Disney Cruise 客服知識庫（無需安裝）
直接開啟：https://sammitsai-crypto.github.io/disney-cruise-kb/
書籤儲存即可，不需要在電腦安裝任何東西。

---

### 📊 be2 每日報告（需本機安裝）

**適用系統：** macOS  
**需求：** Python 3

#### 安裝步驟

1. 確認 Python 3 已安裝：
   ```bash
   python3 --version
   ```
   若未安裝，從 https://www.python.org 下載。

2. 安裝 Playwright（瀏覽器自動化套件）：
   ```bash
   pip3 install playwright
   python3 -m playwright install chromium
   ```

3. 建立設定檔（填入自己的帳號資料）：
   ```bash
   mkdir -p ~/.be2report
   ```
   然後建立 `~/.be2report/config.json`，內容如下：
   ```json
   {
     "email": "你的KKday帳號信箱",
     "password": "你的KKday密碼",
     "group_oid": 6,
     "user_name": "你的名字"
   }
   ```

4. 複製腳本到桌面：
   ```bash
   mkdir -p ~/Desktop/"My project"
   cp be2-daily-report/be2_daily_report.py ~/Desktop/"My project"/
   ```

5. 設定每天 09:30 自動執行：
   ```bash
   mkdir -p ~/Library/LaunchAgents
   ```
   建立 `~/Library/LaunchAgents/com.kkday.be2report.plist`，然後執行：
   ```bash
   launchctl load ~/Library/LaunchAgents/com.kkday.be2report.plist
   ```

6. 建立桌面快捷鍵：
   ```bash
   cat > ~/Desktop/be2每日報告.command << 'EOF'
   #!/bin/bash
   python3 ~/Desktop/"My project"/be2_daily_report.py
   EOF
   chmod +x ~/Desktop/be2每日報告.command
   ```

安裝完成後，雙擊桌面的 `be2每日報告.command` 可隨時手動執行，或等每天 09:30 自動執行。

---

## 新增自己的工具

如果你有新工具想分享給組員：

1. 在 `tools.json` 新增一筆：
   ```json
   {
     "icon": "🔧",
     "name": "工具名稱",
     "desc": "一句話說明這個工具做什麼",
     "tag": "適用組別",
     "author": "你的名字",
     "link": "工具網址或相對路徑"
   }
   ```

2. 如果是本機工具，建一個新資料夾放腳本和安裝說明。

3. 在這份 `CLAUDE.md` 的「安裝說明」區塊補上安裝步驟。

---

*KKday SEA OP Team*
