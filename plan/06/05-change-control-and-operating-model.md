# 05 — Change control 與日常 operating model

涵蓋 RT-10、RT-11。目標是讓 traceability 成為開發流程的一部分，而非 release 前一次性補表。

## 1. PR 類型與必要動作

| 變更類型 | 必要 traceability 動作 |
|---|---|
| 新/改 requirement | normative source + AC anchor + registry + impact + links + tests |
| Scope/非目標改變 | `SCOPE-*` + PRD/tech/style + security/architecture review |
| ADR/protocol/API/data contract | `specified_by` links + consumer/test impact；DB 另含 migration |
| Product implementation | reverse impact + implementation/test links；unknown impact 不可忽略 |
| Test rename/delete | selector links 同步；coverage 不得退步 |
| Gate/CI script | gate definition hash、evidence parser test、受影響 criteria |
| NFR threshold/profile | normative decision + benchmark policy + historical結果不可覆寫 |
| Deprecation/removal | lifecycle/supersedes + downstream target cleanup + migration/release note |
| Docs only | 若碰 normative anchor 仍視為 requirement change；純說明需 render check |

## 2. PR template

新增欄位：

```text
Requirement/control IDs:
Change type: behavior / implementation / verification / editorial / no requirement impact
Acceptance criteria changed:
Impact report:
Design/ADR/protocol:
Verification selectors and gates:
Security/privacy/NFR impact:
Waiver or release decision:
Generated traceability diff reviewed:
```

若選 `no requirement impact`：

- 必須說明理由。
- impact engine 不得命中 normative/shared high-risk target。
- component owner review；security-sensitive path 不允許只靠作者自評。

## 3. CODEOWNERS 與 review routing

建議：

- `research/prd.md`、`traceability/requirements.json`：product + architecture。
- SEC/TECH-SEC links、security waiver：security。
- `traceability/schema/**`、`scripts/traceability/**`：traceability/test infrastructure。
- `gates.json`、workflow/evidence scripts：CI/test owner + affected component。
- generated `docs/traceability/**` 不單獨設 owner；review source diff。

`owners` CLI 依 impact 產出最小必要 team。CODEOWNERS 是保底，不能取代 requirement-specific review。

## 4. Day-to-day workflow

### 開發前

```bash
trace explain FR-SESSION-006
trace impact --base origin/main --head HEAD
```

確認 criteria、design、既有 tests 與 required reviewers；若沒有 requirement，先判斷是 debt、bug 還是新需求。

### 開發中

- 更新精確 symbol/selector link。
- 行為改變同步 normative source/ADR/contract。
- 新 failure mode 補 negative criterion/test，不只加 happy path。
- NFR/安全路徑保存量測/attack scenario，不以一般 unit test 替代。

### 送 PR 前

```bash
make traceability
trace coverage --scope changed
trace render --check
```

reviewer 檢查 coverage delta 與 impact，不以「總 coverage 未下降」取代 criterion 細節。

### Merge/release

- merge 後 main 產 current snapshot，但不叫 release accepted。
- release workflow 聚合完整 gates 與 manual result，產 immutable release snapshot。
- release owner簽 snapshot identity、waiver 與 skip decision，不手寫 criterion pass。

## 5. Bug/incident 回饋

production bug 或安全 finding 必須回答：

1. 哪個 requirement/criterion 本應防止？
2. 若已有 criterion：verification link 缺失、test不夠、gate沒跑、evidence被誤判，哪一層失效？
3. 若沒有 criterion：這是 requirement gap 或 scope change？
4. 補 regression test、link、impact rule；必要時新增 criterion。
5. incident review 連回 snapshot，保留「當時為何顯示 accepted」的證據。

這讓 traceability 不只做 audit，也用來改善 test strategy。

## 6. Waiver 操作

建立：

```bash
trace waiver create --criterion NFR-005.AC-08 --release vX.Y.Z
```

工具產 skeleton，不自動核准。PR 附 impact、compensating control、expiry 與 approvers。

關閉：

- 修復後同 commit evidence pass。
- 將 waiver 標 closed 並連 evidence；不刪 entry。

監控：

- CI 在 30/14/7 天前顯示 warning。
- 到期當天 changed/full coverage fail。
- owner/team 移除時立即 fail，避免孤兒例外。

## 7. Adoption 三階段

### A. Report-only

- 全 repo validate/render 必須綠。
- baseline coverage gap 不阻擋，但新增 duplicate/broken link 阻擋。
- 每週產 gaps 排名與 owner。

### B. Changed-scope blocking

- 變更命中的 criteria 需完整 links/selectors。
- 新 product code 不可 unknown-impact。
- coverage 不得新增 must/security debt。

### C. Full blocking

- main 對所有 active must criteria 靜態 coverage 100%。
- release 對 MVP/SEC/TECH-SEC/NFR 動態 evidence 100% 或有效 decision。
- phase report 只引用 snapshot，不維護平行 pass 表。

每階段切換需記日期、baseline 數字與 rollback condition。工具誤報可暫退一階，但不得關閉 validate 或讓 broken ID 合併。

## 8. Metrics（流程品質，不是產品 telemetry）

每週/每 release 記錄：

- active criteria 數、complete/missing/stale/orphan。
- changed-scope unknown-impact 次數。
- selector resolution failure 與平均修復時間。
- active/expiring/expired waiver。
- release required gate skipped/manual 比例。
- bug 發生時原 criterion/test/gate 是否存在。

不把 coverage percentage 作個人績效；否則會誘發粗糙 links 與低價值 tests。

## 9. Runbook

新增 `docs/runbooks/traceability.md`，涵蓋：

- schema/anchor/selector/render drift 的本地重現與修復。
- CI shard merge、artifact digest/commit mismatch。
- test rename、source anchor move、requirement supersede。
- waiver 建立/續期/關閉。
- evidence tool unavailable、runner prerequisite、manual result。
- release snapshot 驗證與長期保存。
- 工具 bug 時如何進 report-only，而不修改 derived status。
