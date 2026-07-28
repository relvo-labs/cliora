# 06 — Traceability 系統驗證與退出條件

涵蓋 RT-11、RT-12。Traceability 自己也必須可追蹤、可測試；不能用未驗證工具替 release 宣告完整。

## 1. 測試分層

| 層級 | 必測內容 |
|---|---|
| Schema | valid/invalid registry、unknown field、ID/timestamp/path enum |
| Semantic | duplicate/cycle/retired target、anchor/path/owner、profile completeness |
| Selector | pytest/Go/Vitest/Playwright/scenario/fixture 的 found/missing/ambiguous/timeout |
| Graph | 正反向 link、parent aggregation、MVP/TECH-SEC crosswalk、orphan |
| Evidence | same/stale SHA、dirty tree、definition hash、digest、environment matrix、skip |
| Waiver | approval、scope、expiry、non-waivable security、renewal |
| Render | deterministic/golden、human links、generated drift |
| Impact | source/implementation/test/gate、rename、shared target、unknown code |
| Integration | CLI → CI shard → merge → snapshot → generated release view |
| Security/privacy | path escape、symlink、command argv、artifact leakage、untrusted JUnit/JSON bounds |

## 2. 失敗注入

在 fixture repository 或測試分支逐項注入：

1. 刪除 `FR-FILE-005` source anchor。
2. 重複 criterion ID。
3. test rename 但不更新 selector。
4. 刪除 implementation target。
5. 讓 generated matrix 過期。
6. 使用前一個 commit 的全綠 gate result。
7. 把 Chromium result 標成 WebKit requirement。
8. required gate 設 skipped。
9. 使用 expired waiver。
10. 嘗試 waiver Critical path escape。
11. 修改 gate command 後沿用舊 definition hash。
12. artifact digest 不符或 result JSON 超大/含 traversal path。

預期全部在正確層級 fail，並輸出可行修復訊息。若任何一項仍得到 accepted，本期 No-Go。

## 3. Dogfood 範圍

用目前最成熟且風險高的三條鏈先驗：

### Path/file

`SEC-001`、`SEC-004`、`FR-WORKSPACE-003`、`FR-FILE-001…007`：

- ADR 0014/0015。
- daemon workspace/files symbols。
- contract、Go race/fuzz/integration、Central boundary、frontend unit/E2E。
- P3 latency/denial/security evidence。

### Session/terminal

`FR-SESSION-*`、`FR-TERM-*`、`FR-CONN-*`、`NFR-001/002/003`：

- ADR 0012/0013、protocol。
- Central relay/state、daemon tmux/session、xterm。
- contract/integration/security/E2E/perf/capacity。
- recovery、slow client、overflow/gap。

### Auth/ops/release

`FR-AUTH-*`、`FR-INSTALL-*`、`SEC-003/005/006/007`、`NFR-004/005`：

- ADR 0016–0018。
- permission/audit/update/deploy/edge。
- platform/browser/manual/ops drill 的 skip/waiver 差異。

三條都能產正向鏈、反向 impact 與 same-commit snapshot 後，再全量 rollout。

## 4. CI 驗收

- PR 故意破壞 registry/link/render 時 `static` fail。
- selector 改名時 `selectors` fail。
- shared security target 變更時 impact 要求完整 security gate。
- report-only baseline gap 顯示為非阻擋 summary，新增同類 gap 仍 fail。
- release snapshot job `needs` required gates；紅色上游不能產 accepted snapshot。
- 診斷 artifact 即使 fail 仍上傳，但其 verdict 必須是 blocked。
- 同一 run 的 shards commit/profile 不同時 merge fail。
- workflow/job display name 可變，但 stable gate ID 不變。

## 5. Coverage exit matrix

| Scope | 靜態 coverage | 動態 evidence |
|---|---:|---:|
| 59 PRD requirements 的 active must criteria | 100% profile/link complete | release-applicable 全部 current |
| MVP 20 | 100% crosswalk | 20/20 validated 或 blocking decision |
| TECH-SEC 15 | 100% primary + adversarial | 15/15 current；Critical/High 不可例外 |
| NFR 5 | threshold/profile/gate 100% | 每項有環境化量測/矩陣 |
| Scope guards | 100% disposition | required automated/inspection evidence |
| Existing test files | 100% mapped/supporting/orphan disposition | orphan 不影響 requirement pass |

「100%」只代表沒有缺欄/缺 link；test 品質仍由 assertion review、failure injection 與 incident feedback驗證。

## 6. 文件一致性 exit

- `research/01/06-requirement-traceability.md` 改為高層入口與 generated view link；移除會過期的逐 phase pass prose，或明確標 historical。
- `docs/p0`…`p4-report.md` 保留各自時間點 verdict，但引用具 identity 的 snapshot/gap，不互相覆寫。
- 修正 P4 report/plan 對不存在 §10 的引用。
- `docs/release-checklist.md` 改由 release snapshot 產 checklist 或至少驗證 ID 完整；不能再另維護 20 項手表。
- `docs/security-review-p4.md`、permission matrix、error catalog、runbooks 對應 links 可反向查詢。
- `research/01` 共通 DoD 的「traceability 已同步」改成實際 CLI gate。

## 7. Performance 與可靠性

- 59 requirements、數百 criteria、數千 links 下，schema/static/render 本地目標 < 5 秒。
- selector full resolution 可較慢，但依 package batch，不為每條 link重啟工具。
- impact 在正常 PR < 10 秒（不含 tests）。
- 10,000 links fixture 不得 recursion overflow 或非線性爆炸。
- JSON/result size、artifact count、selector output 有上限；malformed input fail closed。
- renderer/coverage 同輸入 byte-for-byte deterministic。

未達本地目標不得把 static gate塞入每次 `make check`；先優化或保留專用 target並記 decision。

## 8. Rollout 與 rollback

### Rollout

1. merge schema/CLI 與空 registry golden tests。
2. 加 baseline inventory，report-only。
3. family-by-family 補 links、selectors、generated views。
4. 開 changed-scope blocking。
5. evidence scripts/CI shards 產 structured result。
6. dogfood release snapshot。
7. 清 baseline debt後開 full release blocking。

### Rollback

- 工具 defect：CI 降為 report-only，保留 artifacts與 gap；不可手動改 accepted。
- schema migration defect：reader 支援目前與前一 schema version，提供 deterministic migration command。
- generated docs defect：回退 renderer，不回退 normative registry change。
- evidence parser defect：該 run 標 invalid，重新執行；不得人工把 invalid JSON 修成 pass。

## 9. 最終操作驗收

對一個乾淨 commit 執行：

```bash
make traceability
trace impact --base <previous-release> --head HEAD
trace coverage --scope mvp --format json
trace snapshot --results artifacts/.../gate-results.json --commit HEAD
trace explain MVP-AC-20
trace explain SEC-001
trace explain NFR-003
```

驗收者應能：

- 從 `MVP-AC-20` 走到 audit criteria、實作、exact tests、P4 gate result。
- 從 workspace guard symbol 反查 SEC/FR 與 required tests。
- 看出 WebKit/systemd/drill 是 passed、skipped、manual 或 waived，而非模糊 `pass`。
- 更換一個 test name 後看到 selector/coverage fail。
- 注入 stale evidence 後看到 snapshot blocked。

## 10. Exit report

RT-12 產 `docs/traceability-report.md`：

- registry 數量與 atomization review 結果。
- 各族群 static/dynamic coverage。
- orphan/stale/waiver/manual/skip 清單。
- failure injection 與 privacy scan。
- CLI/CI 效能。
- P0–P4 historical reconciliation。
- rollout mode、已知限制與 Go/No-Go。

只有 §2、§4、§5、§6、§9 全部通過，且無未處理的 Critical/High trace integrity/security finding，才可切 full blocking。
