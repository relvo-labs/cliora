# 04 — Verification、evidence 與 CI

涵蓋 RT-06、RT-07、RT-08。此文件把現有「commands.txt + prose report」提升為 machine-readable，但保留人類可讀摘要。

## 1. 三層資料

| 層 | 檔案 | 能證明什麼 |
|---|---|---|
| Trace claim | `requirements/links/gates.json` | 應由哪個 target/gate 驗證 |
| Run result | `gate-results.json` | 某 gate 在某 commit/environment 實際執行結果 |
| Resolved snapshot | `trace-snapshot.json` | 此 release claim 是否有符合 policy 的 evidence |

任何一層缺失都不能得到 `verified`。Markdown report 只能 render snapshot，不是 evidence source。

## 2. `gate-results.json`

必要 metadata：

```json
{
  "schema_version": 1,
  "run_id": "github-123456",
  "commit": "<40-char-sha>",
  "tree_state": "clean",
  "generated_at": "2026-07-27T00:00:00Z",
  "runner": {
    "provider": "github-actions",
    "os": "ubuntu-24.04",
    "arch": "amd64",
    "profile": "release"
  },
  "gates": []
}
```

每個 gate result：

- gate ID、started/finished、duration、status（passed/failed/skipped/cancelled）。
- exact command argv、exit code、tool versions。
- selectors executed；JUnit/JSON summary 中 passed/failed/skipped count。
- environment labels（browser、distribution、architecture、load profile）。
- artifact relative path、size、SHA-256。
- skip prerequisite 或 failure code；不得只寫自由文字。

secret env value、token、terminal bytes、file content、private absolute path 不得寫入。環境只存 allowlisted名稱與非敏感值。

## 3. Evidence validity

snapshot resolver 依序檢查：

1. commit 與 requested release SHA 完全相同。
2. tree clean；local dirty run 永遠不能作 release evidence。
3. gate definition hash 與 registry version一致，避免改了 gate 後沿用舊 pass。
4. artifact digest/size 可驗，result schema valid。
5. selector 確實在 executed set；只跑同檔其他 test 不算。
6. environment/applicability 符合，例如 WebKit 不能由 Chromium pass 代替。
7. result 未超過 evidence freshness policy；security/contract/functional 預設每 commit，容量/外部 live smoke 依 ADR 0019 定期但須 code-impact 檢查。
8. 無 blocking skip、expired waiver、manual pending。

snapshot 輸出每條 criterion 的 verdict reason 與 evidence refs，不能只輸出總百分比。

## 4. 現有 evidence script 遷移

### P3/P4

- 保留 `commands.txt`、`skipped.txt`、`summary.md` 供人閱讀。
- `scripts/p3/evidence.sh`、`scripts/p4/evidence.sh` 的 `run/skip` 同時 append structured result。
- 每個現有 label 配 stable gate ID；例如 backend format、contract、permission matrix、capacity、backup、drill、edge、browser。
- CI 各 job 先上傳自己的 shard；final evidence job merge shards，拒絕 duplicate gate 或 commit mismatch。
- final job 不重跑所有測試以假裝收集；它驗證並合併上游真實 artifacts。需要重跑的 gate 必須有獨立 result，不能覆蓋上游。

### P0–P2

- 不回寫未知歷史 run。
- 新 workflow run 可使用同一 reporter 產生 current evidence。
- 舊 prose 只保留 historical claim，直到新 run 取代。

## 5. Manual/external evidence

真實 Claude/Codex 原生審批、實體 systemd/platform matrix、替代 TLS edge 等可能需要手動或外部 runner。

`manual-result.json` 必須包含：

- procedure ID/version、requirement criteria、release commit。
- actor/team、reviewer、UTC time、environment/CLI/browser/platform versions。
- 每一步 expected/observed/result。
- screenshot/log artifact digest；敏感內容先 redact。
- deviations、failure/skip、有效期限。

只有 registry 明確允許 `manual_external` 的 criterion 能使用。能自動化的測試失敗不得以手動 pass 覆蓋。

## 6. CI 結構

新增 `.github/workflows/traceability.yml`：

### `static`

- schema + semantic validate。
- source anchor/path/owner/link graph。
- render `--check`。
- changed-scope impact，產出 `impact.json`/`impact.md`。

### `selectors`

- 只在 test/link/gate/requirements 或被 link 的 target 改動時跑 full resolver。
- 安裝 Python/Go/Node locked toolchain。
- 上傳 selector resolution artifact。

### `coverage`

- PR：`coverage --scope changed`。
- main：`coverage --scope all`，baseline debt 尚在 rollout 時只 report。
- release：`coverage --scope mvp --strict`。

### `snapshot`

- 只在 release/evidence aggregation，`needs` 所有 required gate jobs。
- 下載 shards、驗 commit/digest/environment、產 `trace-snapshot.json` 與 human report。
- blocking gap 時失敗，但仍以 `if: always()` 上傳診斷 artifact。

不得使用 `continue-on-error` 把 required trace gate變綠。Report-only 用明確 mode 與 non-blocking job summary，不用忽略 exit code。

## 7. Makefile 與本地命令

新增：

```make
traceability-validate
traceability-selectors
traceability-render
traceability-coverage
traceability-test
traceability
```

`traceability` 執行 schema/static、render check、changed/full local coverage 與工具 tests；不假裝執行缺 browser/systemd 的 release snapshot。

`make check` 在 rollout 第二階段加入 `traceability-validate` + render check；full selector/coverage 由專用 target/CI 執行，避免每次 backend unit 重跑三語言 collect。

## 8. PR 影響與最小 gate

impact engine 產生 required gate set，供 CI matrix 與 reviewer：

- `contracts/**`：cross-language contract + all consumers。
- auth/RBAC/WS boundary：authz/security/permission matrix + relevant E2E。
- workspace/files guard/policy：Go race/fuzz/security + DB relay + files E2E。
- session/terminal/protocol：contract + daemon integration/race + relay/security + session E2E + perf if queue/limits changed。
- installer/update/deploy：artifact/install/update/security/edge/platform。
- requirement/criterion change：所有 downstream primary verification；不能只跑 docs。
- trace tooling change：全 registry golden + dogfood snapshot。

impact 是最小集合，不取代既有 broader workflow。Release 仍執行完整 policy。

## 9. Coverage policy

### Changed-scope gate

- 新 active criterion 缺 required links：fail。
- 刪/rename target 導致 unresolved selector：fail。
- product code change 無任何 trace map：fail 或提供 reviewed `no_requirement_impact` record。
- 只修改 test 但不更新 link：若 selector仍解析可 pass；coverage delta 必須無退步。

### Full release gate

- MVP/SEC/TECH-SEC criteria coverage 100%。
- FR/NFR active must criteria 100%；`should` gap 必須有 decision。
- no expired waiver、no blocking skip/manual pending。
- same-commit required gates 全 pass。
- compatibility matrix 按每個宣稱平台/瀏覽器展開，不用單一聚合 pass。
- NFR 每個 threshold 有 result、environment、sample/profile 與 verdict。

## 10. Retention

- committed：requirements/links/gates/waivers、generated static views、release snapshot index。
- CI artifact：raw results、JUnit/log/screenshots，依 release policy retention。
- release 長期保存：`trace-snapshot.json`、`gate-results` summary、artifact digests、manual sign-off、waiver/decision。
- 不長期保存 terminal/file raw content；leak scanner 本身也是 required gate。
