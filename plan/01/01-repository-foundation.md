# 01 — P0-W1 Repository 與工具鏈

## 目標

讓乾淨 checkout 不依賴真實 Claude/Codex 帳號即可啟動、測試與重現 Terminal PoC。

## P0-01：版本與 topology ADR

建立：

- `.python-version`、`.go-version`、根目錄 `.nvmrc`（或在 ADR 說明只沿用 `frontend/.nvmrc`）。
- `docs/adr/0001-p0-toolchain-and-layout.md`，記錄 Python/Go/Node patch、套件管理器、lockfile owner、tmux 最低版本與不使用 Turborepo的原因。
- 根目錄 `README.md` prerequisites：Linux、tmux、三種 runtime、安裝與版本檢查命令。

驗收：CI 與本機讀取同一版本來源；package manifest 不使用無 lockfile 約束的 `latest`。

## P0-02：三元件 scaffold

建立預期結構：

```text
backend/app/{api,protocol}/
backend/tests/
daemon/cmd/agentd/
daemon/internal/{connection,protocol,session,terminal,tmux}/
daemon/testdata/
contracts/v1/{schemas,fixtures}/
tests/integration/
tests/e2e/
docs/adr/
```

根目錄提供單一任務入口（`Makefile` 或 `justfile`，ADR 二選一），至少包含：

```text
bootstrap  lint  typecheck  unit  contract  integration  e2e  build  check
dev-central  dev-daemon  dev-frontend
```

`check` 順序固定為 format-check → lint/vet → typecheck → unit → contract → build；integration/E2E 可在需要 tmux/browser 的 CI job 執行。不得以 Docker 作為唯一開發方式，因 daemon/PTY/tmux 必須能直接在 Linux host 測試。

## P0-03：deterministic Fake CLI

實作 `daemon/cmd/fakecli`，只供 development/test build：

- 啟動輸出固定 `FAKECLI_READY v1` 與目前 rows/columns。
- raw stdin 原樣回傳，輸出可辨識 frame boundary 但不可改變輸入 bytes。
- `SIGWINCH` 後輸出 `RESIZE rows=<n> cols=<n>`。
- Ctrl+C 由 TTY 產生 signal，輸出 `INTERRUPTED` 後繼續；Ctrl+D/EOF 正常結束。
- test-only 指令 `:ansi`、`:unicode`、`:burst <bytes>`、`:exit <0..125>`；parser 有上限且拒絕其他命令。
- burst 由固定 seed/固定 chunk size 產生，測試可精確驗 byte count。

注意 Fake CLI 是測試 fixture，不是讓 renderer 傳任意 shell 的後門。Daemon runtime registry 只認 `runtime_id=fake`，binary 路徑由 daemon build/config 固定，request payload 不得包含 executable、argv 或 environment。

## CI skeleton

建立至少三個 job：

- `frontend`: npm clean install、lint、typecheck、unit、build。
- `backend`: locked install、Ruff、mypy、pytest。
- `daemon`: fmt check、vet、unit、`go test -race ./...`、build fakecli/agentd。

workflow 建立於 `.github/workflows/`。另建 Linux integration job 安裝已固定版本的 tmux，執行 contract 與 vertical slice；Playwright job 以 Chromium、Firefox、WebKit matrix 執行。cache key 必須包含各自 lockfile；CI log 不列印環境 secrets 或 terminal content。

## 驗收清單

- [ ] 空白環境依 README 可在 15 分鐘內跑起三元件。
- [ ] `check` 在無網路、dependencies 已 bootstrap 的情況可重跑。
- [ ] Fake CLI 的 ANSI、UTF-8、Ctrl+C、resize、burst、exit 都有自動測試。
- [ ] test cleanup 後 `tmux list-sessions` 無該測試 prefix，無 fakecli/agentd 殘留 process。
- [ ] 現有 prototype 可 build；視覺參考未被不可逆刪除。
