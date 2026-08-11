# 07 — 實測結果（`FU-01`）

實測於 2026-08-03。五項中**四項完成、一項在這台機器上跑不了**（§1）。
第 5 項不在原計畫的四項裡：實作寫入政策時順手量了它，而它的答案改變了風險評估。
原始輸出在下面各節；重跑的指令一併附上。

| # | 量測 | 閘門 | 結果 |
|---|---|---|---|
| 1 | `DataTransfer` 對資料夾的表現 | ✔ | **跑不了**（Chromium 缺系統函式庫、無 sudo）。**處置：改設計讓它失去閘門地位** —— 見 §1 |
| 2 | 非 ASCII 檔名的往返 | | 完成。**三個發現，其中一個直接決定安全審查第 3 題** |
| 3 | `Statfs` 的可用空間 | | 完成。`Bavail` 與 `df` 相符；`Bfree` 高估 7.9 GiB |
| 4 | 空檔案（`data: ""`）在三個 consumer | | 完成。三者都乾淨接受，pattern 要改成可選群組 |
| 5 | 敏感規則在寫入方向的誤擋率（計畫 §4） | | 完成。**誤擋為 0** —— 見 §5 |

---

## 1.（原閘門）`DataTransfer` 對資料夾的表現 —— 跑不了，而且不再是閘門

### 為什麼跑不了

```
$ node scripts/fu/datatransfer-probe.mjs
browserType.launch: Target page, context or browser has been closed
[pid=…][err] chrome-headless-shell: error while loading shared libraries:
             libatk-1.0.so.0: cannot open shared object file: No such file or directory
$ sudo -n true
sudo: a password is required
```

Playwright 1.61.1 與 chromium-1228 都已安裝，但 headless shell 缺
`libatk-1.0.so.0` 等系統函式庫，補齊需要 `apt`（`npx playwright install-deps`），
而這台機器沒有免密碼 sudo。與 `plan/13` 記錄的兩項 skip（需要 stack 的 e2e、
本機無 WebP 編碼器）同一類：**環境限制，不是結論**。

探測用的頁面與腳本已經寫好並留在 `scripts/fu/datatransfer-probe.mjs`，
在有瀏覽器的機器上一行就能跑。它會印出拖放與三種挑檔入口各自的
`items` / `webkitGetAsEntry()` / `files`，含一個零位元組無副檔名的檔案
與一個真實資料夾。

### 為什麼它不再是閘門

`00-…md` D9 原本的規則是「**偵測到資料夾就整批拒絕**」，
而它的正確性依賴 `webkitGetAsEntry().isDirectory` 真的會回 `true`。
既然量不到，就改成一條**不依賴那個答案**的規則：

> **只上傳能被正面確認為檔案的項目。任何一個項目無法被正面確認
> （沒有 `items`、`webkitGetAsEntry()` 回 `null`、或它自稱 `isDirectory`），
> 整批拒絕。**

這是 fail-closed 而不是 fail-open：在「偵測有效」的世界裡它與原規則等價；
在「偵測無效」的世界裡它仍然安全（拒絕），只是可能誤拒一些合法檔案 ——
而誤拒的代價是使用者改用挑檔按鈕，誤放的代價是把一個資料夾當成零位元組檔案上傳。

**兩條入口的規則因此不同，而這個差異是必要的：**

| 入口 | 規則 | 為什麼 |
|---|---|---|
| 拖放 | `dataTransfer.items` 必須存在，且**每一項**都要 `webkitGetAsEntry()?.isFile === true` | 只有拖放能帶進資料夾 |
| 挑檔（`<input type="file" multiple>`，**沒有** `webkitdirectory`） | 直接用 `files`，**不檢查 `items`** | 這種 input 選不到資料夾，而 `change` 事件本來就沒有 `items`。對它套用 items 檢查會讓挑檔完全不能用 |

**這是一項與計畫不同的實作決定**，已記進 `06-…md` 的差異表。
補測之後若證實偵測有效，這條規則不需要放寬 —— 它已經是對的。

---

## 2. 非 ASCII 檔名的往返 —— 三個發現

```
$ .venv/bin/python  (backend venv, starlette 0.4x)
query                                    -> value (bytes)
filename=a%2Bb%26c%3Dd.txt               -> 'a+b&c=d.txt'  (11B)
filename=a+b.txt                         -> 'a b.txt'  (7B)          ← 發現 A
filename=report%202026.pdf               -> 'report 2026.pdf'  (15B)
filename=%E6%B8%AC%E8%A9%A6.csv          -> '測試.csv'  (10B)
filename=caf%C3%A9.txt                   -> 'café.txt'  (9B)
filename=%2Fetc%2Fpasswd                 -> '/etc/passwd'  (11B)     ← 發現 B
filename=..%2F..%2Fetc%2Fpasswd          -> '../../etc/passwd'  (16B) ← 發現 B
```

### 發現 A：`+` 在 query string 裡是空白

Starlette 的 `QueryParams` 走 `parse_qsl`，所以 `a+b.txt` 會被解成 `a b.txt`。
**前端必須用 `encodeURIComponent`**（它把 `+` 編成 `%2B`），
不能自己組字串。這一點要寫進 `client.ts` 的註解，並有一條測試。

### 發現 B（**決定安全審查第 3 題**）：URL 編碼可以讓檔名夾帶路徑分隔符

`%2F` 解出 `/`，`..%2F..%2F` 解出 `../../`。所以：

> **`filename` 的驗證必須在 URL 解碼之後執行，而且必須擋 `/`。**

Central 拿到的已經是解碼後的值（Starlette 在 `QueryParams` 就解完了），
所以 `_reject_filename()` 放在 handler 裡就是正確的位置 ——
但這件事要在安全審查報告裡寫明「解碼與驗證的順序」，因為它是
**唯一**能讓 `filename` 變成路徑的途徑，而 wire 上的 schema pattern
只擋得住已經解碼的值。

### 發現 C：NFC 與 NFD 在 ext4 上是兩個不同的檔案

```
建立 NFC(9B) 與 NFD(10B) 之後，目錄裡有 2 個檔案
   'café.txt' -> nfd
   'café.txt' -> nfc
```

兩個看起來一模一樣的名字。處置：**不做任何正規化**，原樣傳遞位元組 ——
與使用者在自己機器上看到的一致。runbook 要記一句
「同一個看起來一樣的名字可能是兩個檔案」。

### 發現 D：`maxLength` 是 code point，不是位元組

```
'測'×84 + '.csv' : code points = 88, UTF-8 bytes = 256
maxLength:255（code points）會放行嗎? True
位元組上限 255 會放行嗎?              False
```

所以 schema 的 `maxLength: 255` 是一個**寬鬆的外圍**，
而 255 **位元組**的上限必須由 daemon 與前端各自明確檢查
（前端用 `new TextEncoder().encode(name).length`）。
這與 `03-…md` §1.2 對 `data` 的 `maxLength` 的處理是同一個道理：
schema 管形狀，實作管單位。

---

## 3. `Statfs` 的可用空間

```
$ go run statfs.go /home/ubuntu/workspace/cliora
/home/ubuntu/workspace/cliora  Bsize=4096  Bavail=134.1GiB  Bfree=142.0GiB
                               Blocks=154.5GiB  reserved(Bfree-Bavail)=7.9GiB
$ df -B1 /home/ubuntu/workspace/cliora
/dev/mapper/ubuntu--vg-ubuntu--lv  Available=144005238784  (= 134.1 GiB)
$ findmnt -T /home/ubuntu/workspace/cliora
/dev/mapper/ubuntu--vg-ubuntu--lv  /  ext4
```

- **`Bavail` 與 `df` 的 Available 完全相符。**
- **`Bfree` 高估 7.9 GiB**（ext4 給 root 的 5% 保留）。
  agentd 跑非 root（ADR 0023），拿不到那些區塊，所以**用 `Bavail` 是對的** ——
  這一格原本是「要特別看的」，現在有數字了。
- 這台機器不是容器、工作區沒有 submount，所以 overlayfs 與 submount 兩格
  **未量測**。它們不改變實作（都是 `Statfs` 的回傳值），只影響
  `min_free_bytes` 在那類節點上的意義；runbook 要提一句。

---

## 4. 空檔案（`data: ""`）在三個 consumer

```
Go   Strict.DecodeString("")     -> len=0 err=<nil>
Go   Strict.DecodeString("QQ")   -> err=illegal base64 data at input byte 0
Python b64decode('', validate=True) -> len=0
Python b64decode('QQ')              -> error Incorrect padding
Node  Buffer.from("", "base64").length = 0

pattern ^[A-Za-z0-9+/]+={0,2}$      matches "" : Go=false Python=False Node=false
pattern ^([A-Za-z0-9+/]+={0,2})?$   matches "" : Go=true  Python=True  Node=true
```

**結論：空檔案可以上傳，不必退讓。** 三個解碼器都乾淨接受空字串，
只要 schema 的 pattern 改成可選群組並把 `minLength` 設為 `0`：

```jsonc
"data": {"type": "string", "minLength": 0, "maxLength": 5592408,
         "pattern": "^([A-Za-z0-9+/]+={0,2})?$"}
```

順手確認的一件事：`"QQ"`（少 padding）在 Go 的 strict 與 Python 的
`validate=True` 上都被拒。所以**同一組位元組在 wire 上只有一種表示法**，
與契約 1.8.0 對 `filesystem.upload.data` 的既有承諾一致。

---

## 5. 敏感規則在寫入方向的誤擋率 —— 誤擋為 0

**為什麼要量：** 讀取面的 `denied_patterns` 現在也守寫入方向（`00-…md` D4）。
擔心的是誤擋：一個名字裡有關鍵字但完全無害的檔案（`secrets.example.json`
之類）會變成不能上傳，而使用者會覺得平台在跟他作對。

```
$ scripts/fu/write-policy-scan.sh .
scanned 34780 existing files under /home/ubuntu/workspace/cliora
  dotenv           2
  excluded_dir     31145
  git_metadata     910
  private_key      1
  writable         2722

refused as an upload destination or name:
  dotenv           deploy/compose/.env
  dotenv           deploy/compose/.env.example
  private_key      backend/.venv/lib/python3.12/site-packages/certifi/cacert.pem
```

**結論：本 repo 的誤擋是 0。** 敏感規則只擋到三個路徑，三個都名副其實
（兩個 `.env`、一個 `.pem`）。原本最擔心的 `*credentials*`／`*secret*`
兩個 glob **根本不在預設值裡** —— 已核對 `config.go:189`：
`.env`、`.env.*`、`*.pem`、`*.key`、`*.p12`、`*.pfx`、`id_rsa`、`id_ed25519`，
八個都是精確的名字或副檔名，沒有一個是寬鬆的字串包含。
（`research/tech.md` §11.7 的範例區塊列了 `*credentials*` 與 `*secret*`，
並且自己註明「不應過度寬鬆」—— 而實際出貨的預設值沒有採用它們。
**這個文件與程式碼的落差要留著記錄**，不要在本期順手改文件：
tech.md 那一段是設計討論而不是設定範本，改它需要它自己的理由。）

真正被大量擋掉的是 `excluded_dir`（31145 個，幾乎都是 `node_modules`
與 `.venv`）與 `git_metadata`（910 個）—— 兩者都是刻意的，
而且都不是使用者會想從瀏覽器上傳的目標。

**處置：不動預設值。** 若日後某個節點真的需要放寬，
`FR-FILE-005` 本來就寫著「系統應允許管理員調整規則」，
而那是設定而不是程式碼。

---

## 附：這一期沒有要量的東西

| 沒量的 | 為什麼不用 |
|---|---|
| 4 MiB base64 之後有沒有超過訊框上限 | 算得出來（5.33 MiB < 8 MiB），而且有 `TestUploadCapFitsFrameBound` 斷言它 |
| 使用者實際上會傳多大的檔案 | 上線前量不到。改為埋 `FILESYSTEM_STORE_REFUSED_TOTAL`（`03-…md` §2.6），用真實資料決定要不要做分塊上傳（`00-…md` D3） |
| 上傳 20 個檔案要多久 | 循序 × 4 MiB 的上界算得出來，而且使用者看得到每一檔的進度 |
| 拖放在觸控裝置上的行為 | 拖放在觸控上本來就不可用，所以有〔上傳檔案〕按鈕（`04-…md` §3）。量它不會改變任何決定 |
| overlayfs／submount 上的 `Statfs` | 這台機器兩者都沒有。它不改變實作，只影響 `min_free_bytes` 的意義（§3） |
