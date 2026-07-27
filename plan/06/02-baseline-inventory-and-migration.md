# 02 — Baseline inventory 與歷史遷移

涵蓋 RT-02、RT-05、RT-06、RT-09。目的不是立刻宣告 100% covered，而是建立誠實、可逐項關閉的 baseline。

## 1. 現況量化

| 項目 | 現況 | 主要問題 |
|---|---:|---|
| PRD primary requirements | 59（FR 47 / SEC 7 / NFR 5） | 多數只在 group 層追蹤 |
| PRD requirement 內 bullet | 232 | 混合欄位、能力與 AC，不能直接全轉 |
| 無條列 AC 的 requirement | 18 | 需人工定義 pass/fail |
| PRD §19 MVP acceptance | 20 | P4 report 有手寫 status，無同 commit resolver |
| tech §23 security baseline | 15 | security review/report 有表，但不是 canonical link graph |
| research work packages | 32 | phase/ticket 與 requirement 只靠 prose |
| ADR | 18 | 決策有證據，但無 typed `specified_by` |
| test files | 91 | 只有 20 個直接出現 requirement/control ID |
| CI workflows | `ci` + `p1`…`p4` | gate 名稱與 evidence 尚無全域 stable ID |

必先修正的 consistency defect：

- `docs/p4-report.md` §6 與 `plan/05/07` 宣稱 `research/01/06-requirement-traceability.md` 有 §10/P4 逐需求狀態，實際文件只有 §1–§9。
- P0 report 仍為 No-Go、P1–P3 report 仍是 Conditional，而 P4 report 給出有條件 Go。這些是不同時間/環境的歷史 verdict，不能互相覆寫；snapshot 必須保留 phase、commit、runner 與 prerequisite。
- P1–P3 traceability 表有「本機通過/CI 尚待」混合文字；遷移時拆成 claim、executed result 與 skip，不解析成單一 boolean。

## 2. Requirement 族群初始落點

下表是 migration seed，不是驗收完成宣告。

| 族群 | 主要 design/implementation surface | 現有 verification surface | 初始風險 |
|---|---|---|---|
| FR-AUTH | `services/auth/rbac/authz`、HTTP/WS deps、auth store/views | `test_auth_api.py`、`test_security.py`、auth unit/E2E、permission matrix | token refresh/expiry 與四邊界需拆 AC |
| FR-NODE | node API/service/repository、WS registry、Nodes/Detail UI | node registration/API/WS/guard/registry tests、nodes E2E | online/stale/offline、disable/remove 要分開 |
| FR-INSTALL | `deploy/install.sh`、`internal/install`、agentd commands/update | install/update unit、CI artifact/systemd matrix、doctor | 真實六平台/systemd 不能用本機 pass 代替 |
| FR-RUNTIME | daemon `internal/runtime`、heartbeat DTO/UI | runtime tests、contract fixture、session missing-runtime tests | detect/select/allowlist/config 是不同 claims |
| FR-WORKSPACE | workspace guard、sessions/files、favorites API/UI | workspace race tests、files/session/favorites DB+E2E | roots/browse/launch/recent/favorite 跨 P2–P4 |
| FR-SESSION | session service/state/DB、tmux manager、session UI | state/service/API/integration/recovery/E2E | lifecycle、ownership、recovery criterion 多 |
| FR-TERM | protocol/relay/queue、tmux attach、xterm composable | contract、relay/overflow/recovery/unit/E2E/perf | raw bytes、resize、scrollback、reconnect、writer 分開 |
| FR-FILE | file service/policy/root、tree/Monaco/search UI | Go security/integration/bench、DB/unit/E2E | denial 類型與 stale-content clearing 是安全 AC |
| FR-CONN | daemon connection、Central node WS/registry/protocol | connection/WS/correlation/queue/contract tests | outbound/TLS/reconnect/correlation/binary/timeout 分開 |
| SEC | boundary、auth、workspace、installer/update、audit、edge | attack tests、security review、redaction、edge verification | 必須補 negative/adversarial 類型 metadata |
| NFR | perf/load/recovery/doctor/browser/platform matrix | P2/P3 bench、P4 capacity/drills、CI matrices | 結果必須帶環境、profile、時間與 commit |

## 3. PRD 原子化流程

### Pass A：結構抽取

- parser 只抽 `FR-*`/`SEC-*`/`NFR-*` heading、title、section anchor 與原始 bullet。
- 產出 review worksheet，不直接寫 `requirements.json`。
- 標示 18 個無 bullet requirement、含多個動詞的 bullet、純 enum/field list 與模糊詞。

### Pass B：人工分類

每個原始 bullet 標成：

- `criterion`：可直接驗收。
- `constraint`：與另一 criterion 合併或成 scope/security control。
- `data_shape`：由 schema/contract 驗證。
- `example`：不產生 release claim。
- `needs_rewrite`：缺 threshold/actor/failure semantics。

兩人 review：一位 product/feature owner、一位 test/security owner。

### Pass C：穩定 ID

- 在 PRD 補 AC anchors，不改原 requirement ID。
- criterion 順序一旦 merge，後續插入用下一個未使用序號，不重排舊 ID。
- 拆分舊 criterion 時保留舊 ID 為 deprecated，新增兩個 ID 並建立 `supersedes/refined_by`。
- 刪除需求只改 lifecycle；不從 registry 移除。

## 4. Links 遷移順序

每個 requirement family 分四次 PR，避免「一張巨型 mapping PR」無法 review：

1. planning/design：research work package、plan ticket、ADR、protocol/API/style section。
2. implementation：精確 path + symbol/component/migration，不用 line number。
3. verification：精確 selector + assertion scope + verification type。
4. evidence：selector → gate → artifact/result；此步完成前最多是 `verifiable`。

建議 family 順序：

1. SEC-001/002/004 + FR-FILE/WORKSPACE：現有 security tests 最完整，可驗證模型。
2. FR-SESSION/TERM/CONN + NFR-001/002/003：可驗證 integration、perf 與 recovery。
3. FR-AUTH/NODE/INSTALL/RUNTIME + SEC-003/005/007：可驗證 platform/manual/edge 差異。
4. FR-WORKSPACE-004/005、SEC-006、NFR-004/005、MVP/TECH-SEC crosswalk。

## 5. Test mapping 方法

不要求先改 91 個 test file。`links.json` 可引用既有 selector：

- pytest：`pytest://backend/tests/db/test_auth_api.py::test_name`
- Go：`gotest://daemon/internal/workspace#TestName`
- Vitest：`vitest://frontend/src/views/DashboardView.test.ts#suite > case`
- Playwright：`playwright://frontend/tests/e2e/files.spec.ts#case`
- script scenario：`scenario://scripts/p4/drills/run-all.sh#heartbeat-loss`
- contract fixture：`fixture://contracts/v1/fixtures/invalid/...json`

只有 selector 不穩定或一個 case 驗證多個不明 assertion 時才重構 test name。重構不改行為，並在同 PR 更新 link。

每個 verification link 要記：

- assertion scope（成功、拒絕、邊界、recovery、cleanup、leak、a11y 等）。
- layer（unit/contract/integration/e2e/perf/security/ops/manual）。
- environment prerequisites。
- 對 criterion 是 `primary` 或 `supporting`；parent 只靠 supporting evidence 不得 verified。

## 6. 歷史 evidence 遷移

### 可升級為 observed evidence

只有下列資訊齊全才可：

- 可辨識 commit SHA，且 working tree dirty 狀態已知。
- command/gate ID、started/finished time、exit status。
- runner/environment/profile。
- artifact 路徑或 digest。

### 只能保留 historical claim

- report 中手寫的 `pass`，但無 run/commit。
- 「測試存在」、「已實作」、「reviewed」。
- 本機結果只寫總數，無 command 或 artifact。
- 宣稱 CI 綠但沒有 run identity。

遷移輸出為 `docs/traceability/historical-gaps.md`（generated）：

- P0 blocker 後續由 P2 關閉，但 P0 snapshot 仍維持 No-Go。
- P1–P3 local pass 與 runner gap 分列。
- P4 conditional Go 的四個條件、三個未演練 alert、systemd/platform matrix 分列。
- 不存在的 traceability §10 reference 改指 generated P4 snapshot；在 snapshot 尚未產生前標 gap，不手補假表。

## 7. Baseline completion gate

RT-09 完成需滿足：

- 59 + 20 + 15 + scope guard 全部有 registry entry 與 valid source anchor。
- 18 個無 bullet requirement 已人工核准 criteria。
- 每個 active criterion 至少有 `planned_by` 與 verification profile。
- 現有 91 test files 已全部分類為 mapped、intentionally supporting、或 orphan；orphan 有 owner/disposition。
- 所有 P0–P4 report claim 都能指向 observed evidence、historical claim 或 explicit gap 三者之一。
- 工具輸出的 missing/waived/skipped/stale 數字與人工抽樣 20 條一致。
