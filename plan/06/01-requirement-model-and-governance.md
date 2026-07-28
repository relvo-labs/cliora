# 01 — Requirement model、ID 與治理

涵蓋 RT-01、RT-02 的規則基線。實作者先以 ADR 0019 固定本文件的決策，再建立 registry。

## 1. 追蹤物件

| 類型 | ID 範例 | Normative source | 用途 |
|---|---|---|---|
| Functional requirement | `FR-SESSION-006` | PRD §8 | 使用者/系統能力 |
| Security requirement | `SEC-001` | PRD §15 | release-blocking security invariant |
| Non-functional requirement | `NFR-003` | PRD §16 | 可量測品質門檻 |
| Atomic criterion | `FR-SESSION-006.AC-01` | requirement 下明確 criterion anchor | 最小 verification/status 單位 |
| MVP acceptance | `MVP-AC-14` | PRD §19 #14 | release journey claim |
| Tech security control | `TECH-SEC-15` | tech §23 #15 | 技術 release baseline |
| Scope guard | `SCOPE-011` | PRD §4 對應條目 | 防止任意 shell 等範圍回歸 |
| Work package | `P2-W3` | `research/01` | planning target，不推導 pass |
| Implementation ticket | `P4-10`、`RT-07` | `plan/*` | delivery target |
| Gate | `GATE-P4-BROWSER-WEBKIT` | `gates.json` | 穩定執行/證據 ID |
| Waiver | `WVR-2026-001` | `waivers.json` | 有期限且有 owner 的例外 |

ADR、source path、test selector、artifact 不另發 requirement ID；它們是 typed target。

## 2. Atomic criterion 規則

每個 criterion 必須：

- 只描述一個可判定結果；避免「A 且 B 且 C」共用一個 pass。
- 有 stable anchor，不依賴 line number。
- 指定 verification profile：`automated`、`measurement`、`inspection`、`manual_external`。
- 指定 applicability：`all`、`mvp`、`release`、特定平台/瀏覽器或僅 development。
- 指定 criticality：`must`、`should`、`informational`；SEC/TECH-SEC 預設 `must`。
- 能說明 pass/fail，不以「合理」、「快速」、「適當」等未量化文字收尾。

對現有 PRD 的處理：

1. 欄位清單、enum、支援平台清單只有在每項皆為可驗收 claim 時才拆成 AC。
2. 沒有 bullet 的 18 個 requirement 由 product/engineering 共同補 criteria；不可由 parser 猜測。
3. 原意不變的拆分屬 editorial change；新增門檻或改行為必須走正式 requirement change。
4. PRD 以 `<a id="fr-session-006-ac-01"></a>` 或同等穩定 anchor 標記，不在正文塞工具專用 JSON。

## 3. Lifecycle 與 derived status

### Author-controlled lifecycle

`proposed → active → deprecated → retired`

- `proposed` 不進 release coverage，但必須有 owner 與 decision date。
- `active` 依 applicability 進 coverage。
- `deprecated` 必須有 replacement 或 removal release。
- `retired` 保留 ID，不重用、不刪歷史 links。

另有 `deferred` disposition，但它不是 lifecycle：必須指定 target release、理由與重新評估日期。MVP `must` 不可無限 deferred。

### Tool-derived delivery status

| 狀態 | 判定 |
|---|---|
| `specified` | source/anchor、owner、criteria 完整 |
| `planned` | required planning/design links 完整 |
| `implemented` | required implementation targets 可解析 |
| `verifiable` | verification profile 與 selector/gate 完整 |
| `verified` | 所有 required verification 在符合 policy 的 commit/environment pass |
| `accepted` | release validation 完整，無 blocking skip/waiver/finding |
| `blocked` | required link/evidence 失敗或缺失 |

`waived`、`skipped`、`stale`、`manual_pending` 是 verdict modifier，不是較高的完成階段。工具不得讓人工在 registry 直接填 `verified: true`。

Parent requirement 狀態取所有 required child criteria 的最差狀態；MVP/tech control 則依其 linked criteria 與自身 validation gate 聚合。

## 4. Link types 與方向

| Type | From → target | 意義 |
|---|---|---|
| `refined_by` | requirement → criterion/control | 分解或補強 |
| `planned_by` | criterion → work package/ticket | 排程責任 |
| `specified_by` | criterion → ADR/protocol/API/style section | 設計/契約 |
| `implemented_by` | criterion → code/config/migration symbol | 實作位置 |
| `verified_by` | criterion → exact test/scenario selector | verification claim |
| `measured_by` | NFR criterion → benchmark/load gate | threshold measurement |
| `validated_by` | MVP/control → E2E/manual/ops gate | release validation |
| `guards_scope` | scope guard → test/grep/policy | 非目標防線 |
| `depends_on` | criterion → criterion | 真正的前置依賴；不可用來替代 coverage |
| `supersedes` | requirement/ADR → older object | 取代關係 |

每條 link 必須有唯一 ID、owner、rationale、target locator 與 applicability；首次引入的 commit/PR 可由 Git history 或 merge 後 snapshot 記錄，不要求作者預知 merge SHA。禁止以 `notes` 中的自然語言路徑代替 typed target。

## 5. Verification profiles

| Requirement 類型 | 最低要求 |
|---|---|
| FR | implementation + automated test；跨邊界能力另需 integration/E2E |
| SEC | implementation + positive/negative/adversarial test + security gate |
| NFR latency/capacity | metric/threshold + measurement command + environment/profile + result |
| NFR availability | failure/recovery scenario + clock/timeout policy + integration/drill |
| Compatibility | platform/browser matrix；每個宣稱平台有獨立 result |
| MVP acceptance | linked FR/SEC coverage + release journey validation |
| Scope guard | 可執行 boundary/contract/grep；若只能 review，需 inspection checklist |
| External CLI live smoke | versioned manual procedure + actor/time/commit/environment/artifact |

同一 test 可以驗多個 criteria，但 link 必須說明 assertion scope。單一 broad E2E 不可取代低層安全 boundary test。

## 6. Owner 與核准

| 變更 | 必要核准 |
|---|---|
| FR/AC 語意、priority、applicability | Product owner + feature owner |
| SEC/TECH-SEC 或 trust boundary | Security owner + architecture owner |
| NFR threshold/environment | Product/ops + performance owner |
| Protocol/API/DB contract link | 對應 component owner |
| Verification selector/gate | Test owner + feature owner |
| Manual-only 分類 | Test owner + release owner |
| Waiver（非 Critical/High） | Requirement owner + release owner；security 類另需 security owner |
| Retire/supersede ID | 原 owner + product/architecture owner |

owner 使用 repository 可解析的 team key；個人可作 assignee，不作唯一長期 owner。

## 7. Waiver 與 release decision

Waiver 至少包含：

- `id`、受影響 criteria、scope/release、原因與使用者/安全影響。
- 缺少的是 implementation、verification、environment 還是 threshold。
- compensating control、偵測方式、owner、approvers。
- `created_at`、`expires_at`、最晚修復 release、revisit trigger。
- 對應 issue/ADR/report。

規則：

- 到期、owner 不存在、target requirement retired、commit/release scope 不符即失效。
- Critical/High security finding、未授權任意 command/path escape/secret leakage 不可 waiver。
- `skipped` 只能描述 runner prerequisite；若 release 接受它，另建 waiver/release decision。
- 同一 waiver 不得跨 release 自動續期；renewal 是新 review。

## 8. Requirement change 流程

每次 semantic change 依序：

1. 更新 normative source 與 criterion anchor，保留舊 ID 或明確 supersede。
2. 執行 `impact --base <sha> --head <sha>`，列出 design/code/test/gate/report。
3. 更新 registry 與 links；若 contract/data/security 受影響，同步 ADR/schema/migration。
4. 更新/新增 tests，跑 changed-scope verification。
5. render generated views，review coverage delta。
6. merge 後由 CI 產生新 snapshot；舊 snapshot 永不覆寫。

只改 implementation 而沒有改需求時，不修改 requirement 正文，但仍由 path ownership/links 產生 impact，確認對應 verification 有跑。
