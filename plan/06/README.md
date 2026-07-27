# Cliora Requirement Traceability 可實作規劃

本目錄把 `research/01/06-requirement-traceability.md` 的靜態對照表，轉成可由 CI 驗證、可隨 release 產生證據、可支援需求變更影響分析的完整追蹤系統。它不是新增產品 Phase 5，也不重做 P0–P4 功能；ticket 統一使用 `RT-` 前綴。

## 為何需要這一期

目前 repository 已有大量實作、測試、ADR、phase report 與 evidence script，但關聯主要靠人工維護的 prose：

- PRD 有 **59** 個一級 requirement（47 FR、7 SEC、5 NFR）、**20** 個 MVP 驗收條件；tech 另有 **15** 個 release-blocking 安全基準。
- 59 個 requirement 下共有 232 個條列項，但其中混合欄位清單、能力清單與真正驗收條件；另有 **18 個 requirement 沒有條列式驗收條件**，不能直接機械編號。
- `research/01` 有 **32** 個 work package，`docs/adr` 有 18 份 ADR，程式已橫跨 Central、Daemon、Frontend、protocol、deployment 與 ops。
- repository 目前有 91 個 Python/Go/Vitest/Playwright 測試檔，只有 20 個測試檔直接寫出 FR/SEC/NFR 或 PRD §19 ID；「測試存在」尚不能回答它驗證哪一條 acceptance criterion。
- `docs/p4-report.md` 宣稱 traceability §10 已記錄 P4 逐需求狀態，但 `research/01/06-requirement-traceability.md` 實際只到 §9。這是必須由自動檢查阻止的文件漂移。
- 現有 evidence pack 已誠實記錄 executed/skipped gate，但沒有 machine-readable 的 requirement → test/gate → 同 commit 結果，因此不能可靠推導 release coverage。

## 文件導覽

| 文件 | 用途 |
|---|---|
| [00-execution-plan.md](./00-execution-plan.md) | 成功定義、範圍、固定原則、架構、ticket 波次與共同 DoD |
| [01-requirement-model-and-governance.md](./01-requirement-model-and-governance.md) | requirement/criterion ID、生命週期、關聯型別、owner、變更與 waiver 規則 |
| [02-baseline-inventory-and-migration.md](./02-baseline-inventory-and-migration.md) | 現況缺口、逐需求族群盤點、PRD 原子化與歷史證據遷移 |
| [03-registry-cli-and-generated-views.md](./03-registry-cli-and-generated-views.md) | `traceability/` 資料格式、CLI 子命令、驗證演算法與產生文件 |
| [04-verification-evidence-and-ci.md](./04-verification-evidence-and-ci.md) | test selector、gate result、同 commit 證據、CI/release 整合與手動驗證 |
| [05-change-control-and-operating-model.md](./05-change-control-and-operating-model.md) | PR impact、review ownership、release decision、日常操作與 adoption 規則 |
| [06-verification-and-exit.md](./06-verification-and-exit.md) | 工具測試、dogfood、coverage gate、rollout、退出條件與失敗回復 |
| [07-implementation-status.md](./07-implementation-status.md) | RT ticket 的實作進度與實際證據；初始均未開工 |

## 使用規則

1. 先完成 RT-01/02 的 ID 與語意盤點；未經產品 review，不可把現有 bullet 自動宣告為 acceptance criterion。
2. normative requirement 文字仍以 `research/prd.md`、核准 ADR 與明確列出的 tech baseline 為準；machine registry 保存 metadata 與 source anchor，不複製另一份規格正文。
3. `docs/traceability/*.md` 全部由工具產生，不手改；PR review 看 source registry/links 與生成 diff。
4. 靜態 link 只能證明「有對應 target」，不能證明「已通過」。`verified` 必須來自同一 commit 的 machine-readable gate result。
5. skip、manual、waiver、accepted risk 是四種不同狀態，不得折成 pass。
6. 導入期間採 report-only → changed-scope blocking → full blocking，不用一次大改 91 個測試檔。

## 完成結果

完成後，任何人都能從 requirement 或 acceptance criterion 查到規劃、ADR/設計、實作 symbol、精確測試 selector、執行 gate、最新同 commit 證據與 waiver；反向也能從改動檔案或失敗測試找出受影響需求。Release 只能由可重現證據推導狀態，不再靠 phase report 中手寫的 `pass`。
