# 00 — Requirement Traceability 執行總控

## 1. 成功定義

本期要建立一條可執行的鏈：

```text
normative source
  → requirement
  → atomic acceptance criterion
  → work package / ADR / design
  → implementation target
  → exact verification selector
  → CI gate result at commit
  → release evidence / decision
```

成功不是「產生一張很大的 Markdown 表」，而是同時具備：

- **正向追蹤**：每個 active criterion 都能找到規劃、實作、驗證與 release 證據。
- **反向追蹤**：test/gate/code/ADR 的改動可列出影響的 requirement；孤兒 target 可被發現。
- **狀態可信**：`verified` 由同 commit、指定環境、實際 exit status 推導，不由人工填寫。
- **變更可控**：新增、修改、刪除、延後需求會觸發 impact report、owner review、必要 migration 與 evidence 更新。
- **發布可判定**：MVP 20 項、59 個 PRD requirement、15 個 tech security baseline 的 coverage 與例外一目了然。
- **維護成本有界**：資料以少量 JSON registry + typed link 維護，Markdown view 自動產生；不要求每個 test body 塞重複 tag。

## 2. 範圍

### 納入

- PRD `FR-*`、`SEC-*`、`NFR-*` 的 requirement 與 atomic acceptance criteria。
- PRD §19 的 `MVP-AC-01`…`MVP-AC-20`。
- tech §23 的 `TECH-SEC-01`…`TECH-SEC-15`。
- PRD §4 非目標的 `SCOPE-001`…，作為 scope guard；只對已有防線的項目要求 automated guard。
- `research/01` work package、`plan/01`…`plan/05` ticket、ADR、protocol schema、API/DB/UI design 作為 planning/design target。
- Backend、Daemon、Frontend、contract、migration、deployment、runbook、performance/security/ops drill。
- 現有 P0–P4 reports、P3/P4 evidence packs 與 release checklist 的歷史遷移。

### 不納入

- 不在本期改變產品功能、RBAC 規則、protocol 或安全 policy。
- 不把 traceability registry 放進 production database，也不在 runtime request path 執行。
- 不導入外部 ALM/需求管理 SaaS；Git repository 與 CI artifact 是 MVP 系統邊界。
- 不把 source file 的存在視為「已實作」，也不把 test file 的存在視為「已驗證」。
- 不為了補 coverage 而偽造 acceptance criterion、假 gate 或回填不存在的歷史 pass。
- 不永久保存大量 test log；只保存可追溯 manifest、必要報告與 CI retention 內 artifact。

## 3. 固定原則

1. **需求正文單一來源**：PRD/核准 ADR/tech baseline 保存規範文字；registry 只保存 ID、anchor、分類、owner、狀態與 links。
2. **criterion 是最小驗證單位**：parent requirement 狀態由所有 required criteria 聚合，不接受只在 requirement group 層貼一個 test file。
3. **claim 與 evidence 分離**：`links.json` 是 claim；`gate-results.json` 是 execution evidence；`trace-snapshot.json` 才是兩者於某 commit 的解析結果。
4. **路徑不是充分 selector**：能定位時使用 pytest node ID、Go test name、Vitest/Playwright title、gate ID 或 script scenario ID。
5. **skip 不是 pass**：缺 browser/systemd/runner/real node 時記 `skipped` 與 prerequisite；release policy 再判斷是否阻擋。
6. **歷史不改寫**：舊 report 可標 `historical_claim`；只有能解析到 commit/run/artifact 的結果才可升為 `observed_evidence`。
7. **安全要求較嚴**：SEC 與 tech §23 必須有 negative/adversarial verification；Critical/High 不可用一般 waiver 放行。
8. **NFR 必須帶環境**：threshold、sample profile、硬體/runner、時間與結果缺一不可。
9. **生成物不可手改**：matrix、coverage、gap、impact view 全由 CLI render。
10. **導入不癱瘓開發**：先 baseline，再只擋新增漂移，最後才要求全 coverage。

## 4. 目標結構與 ownership

```text
traceability/
  requirements.json          # Product owner：ID、source、lifecycle、criteria metadata
  links.json                 # Feature/test owners：typed static links
  gates.json                 # Test/CI owner：stable gate catalog
  waivers.json               # Product + security/release owner：有期限的例外
  schema/*.schema.json       # Traceability owner：資料契約
scripts/traceability/
  cli.py                     # validate/coverage/render/impact/snapshot
  model.py
  validate.py
  render.py
  evidence.py
  tests/
scripts/trace                 # repository wrapper，固定呼叫 locked uv/Python 環境
docs/traceability/
  matrix.md                  # generated：正向與反向矩陣
  coverage.md                # generated：依族群/criterion 的 coverage
  gaps.md                    # generated：missing/stale/orphan/waived/skipped
  mvp.md                     # generated：MVP 20 + tech 15 release view
artifacts/<phase>/<run-id>/
  gate-results.json          # generated：執行結果與環境
  trace-snapshot.json        # generated：該 commit 的 requirement verdict
```

Ownership 邊界：

- Product owner 決定 requirement/criterion 語意、priority、lifecycle 與 release applicability。
- Architecture/security owner 核准 ADR、SEC/tech baseline link 與 waiver。
- Feature owner 維護 design/implementation/test links。
- Test/CI owner維護 gate catalog、selector resolution 與 evidence provenance。
- Release owner只對當次 snapshot 簽核，不直接改 derived status。

## 5. 執行波次與 ticket

| Wave | Ticket | 產出 | 前置 |
|---:|---|---|---|
| 0 | **RT-01** | 決策 ADR 0019：ID/criterion policy、normative source、狀態推導、waiver、evidence retention、owner | 無 |
| 0 | **RT-02** | 59 PRD requirement + 20 MVP + 15 tech security + scope guard 的 inventory；18 個無條列驗收 requirement 人工原子化；PRD stable anchors | RT-01 |
| 1 | **RT-03** | `traceability/schema/*`、`requirements.json`、`links.json`、`gates.json`、`waivers.json` 初版 | RT-02 |
| 1 | **RT-04** | CLI `validate/coverage/render`、unit/golden tests、generated views | RT-03 |
| 2 | **RT-05** | P0–P4 work package/ADR/design/implementation links；orphan/stale/path/symbol 檢查 | RT-03/04 |
| 2 | **RT-06** | 91 個現有 test file 與 contract/perf/security/ops scenario 的 selector mapping；negative/manual/NFR 分類 | RT-03/04 |
| 3 | **RT-07** | structured `gate-results.json`、`snapshot`、同 commit/hash/environment 驗證；P3/P4 evidence script 整合 | RT-04/06 |
| 3 | **RT-08** | `make traceability`、`.github/workflows/traceability.yml`、PR impact comment/artifact、generated-doc drift gate | RT-04/05/06 |
| 4 | **RT-09** | 歷史報告 reconciliation：補正不存在的 traceability §10 聲稱、標記 P0–P4 claim/evidence/skip | RT-05/07 |
| 4 | **RT-10** | PR template/CODEOWNERS/change policy、waiver/release-decision workflow、runbook | RT-08 |
| 5 | **RT-11** | report-only → changed-scope blocking → full release blocking rollout；baseline debt 清零 | RT-08/09/10 |
| 5 | **RT-12** | dogfood release snapshot、mutation/negative tests、exit report `docs/traceability-report.md` | 全部 |

關鍵路徑：

```text
RT-01 → RT-02 → RT-03 → RT-04
                    ├→ RT-05 ─┐
                    └→ RT-06 ─┴→ RT-07 → RT-08 → RT-10 → RT-11 → RT-12
                                      └→ RT-09 ────────────────┘
```

Wave 內可並行，但 RT-02 的 criterion 語意未核准前不得大量建 links；否則會把錯誤粒度固化進工具。

## 6. 每張 ticket 的完成格式

每張 RT ticket 至少附：

- 影響的 requirement/control ID 與 source anchor。
- 資料契約或 CLI 行為變更，含 backward-compatibility/migration。
- positive、invalid、duplicate、missing、stale、orphan、skip/waiver 測試。
- 實際命令、exit status 與產物路徑。
- deterministic 證明：排序、timestamp 注入、path normalization、同輸入同輸出。
- security/privacy review：artifact 不得收 secret、token、terminal bytes、file content 或使用者私人絕對路徑。
- generated docs diff；不得只手改 Markdown。
- rollout mode 與失敗時的回復方式。

## 7. 非阻擋與阻擋規則

### PR 階段

- schema 無效、duplicate ID、broken source anchor、missing changed-scope link、generated docs 漂移：阻擋。
- 既有未遷移 debt：report-only，直到 RT-11 指定日期。
- selector 無法解析：changed scope 阻擋；未觸及的 baseline debt 列 gap。

### Release 階段

- active MVP/SEC/TECH-SEC criterion 缺 required link 或無同 commit pass：阻擋。
- NFR 沒有當次或 policy 允許期間內的量測：阻擋或需明確 release decision。
- manual evidence 未簽名、過期、commit 不符：阻擋。
- skipped required environment leg：不可由工具自動判 pass；交 release policy 決定。
- 未處理 Critical/High security finding：不可 waiver。

## 8. 完成定義

本期只有在下列條件同時成立時完成：

- 所有納入的 canonical ID 唯一、stable anchor 可解析、無孤兒 criterion。
- active criteria 100% 有 planned/design link；FR/SEC 100% 有 implementation link。
- active criteria 100% 有符合其 verification profile 的 test/gate/manual procedure。
- MVP 20 與 tech security 15 對當次 dogfood commit 產出完整 snapshot。
- trace CLI 的 schema、validator、renderer、impact 與 evidence resolver 有自動測試。
- PR workflow 能故意破壞一個 ID/link/generated view 後確實失敗。
- release workflow 能證明 stale commit、skip、expired waiver 不會被誤判為 pass。
- `research/01/06`、P0–P4 reports 與 generated matrix 不再互相聲稱不存在的章節或證據。
