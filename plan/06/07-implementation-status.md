# 07 — Requirement Traceability 實作狀態

> 本文件只記錄實際完成與可定位證據。**目前狀態：traceability infrastructure 完成，imported
> baseline 已關閉，rollout 已進入 full release blocking（stage 3）。** 原本 308 個只有 supporting
> suite link 的 criteria 已逐條處理完畢；三個未實作行為已補上實作與測試；三個 PRD 與實作矛盾
> 已由產品決定改 PRD，撤回的 criterion 保留 ID 為 deprecated 並由 replacement `supersedes`。
> `traceability/baseline-debt.json` 為空，`coverage --strict` 回 0。

## Ticket 狀態

| Ticket | 內容 | Wave | 狀態 | 實際證據 |
|---|---|---:|---|---|
| RT-01 | ADR 0019：模型、owner、status、waiver、retention | 0 | ✅ 完成 | `docs/adr/0019-requirement-traceability.md`（含 classification 與 rollout stage 2） |
| RT-02 | PRD/tech/scope inventory、AC 原子化與 anchors | 0 | ✅ 完成 | 106 objects／369 criteria；PRD/tech stable anchors |
| RT-03 | schema + requirements/links/gates/waivers registry | 1 | ✅ 完成 | `traceability/schema/*`、四份 registry + `baseline-debt.json` |
| RT-04 | validate/coverage/render CLI 與 tests | 1 | ✅ 完成 | `scripts/traceability/*`；30 tests |
| RT-05 | planning/design/implementation links | 2 | ✅ 完成 | 369 criteria 的 primary planning/design/implementation 或 control link |
| RT-06 | test/scenario selectors 與 verification profile mapping | 2 | ✅ 完成 | Pass B 分類 134 條、171 條 criteria 補上 242 條 exact primary `verified_by`；4 個缺的 assertion 已補寫測試 |
| RT-07 | structured gate results + snapshot + evidence integration | 3 | ✅ 完成 | P3/P4 emitter、`run-gate --skip-reason`、`merge`、environment-leg 強制、`scripts/traceability/dogfood.sh` |
| RT-08 | Makefile/CI/impact/generated drift gates | 3 | ✅ 完成 | Make targets、`traceability.yml`（blocking）、P4 docs job |
| RT-09 | P0–P4 historical reconciliation | 4 | ✅ 完成 | generated `historical-gaps.md`、traceability §10–11 |
| RT-10 | PR/CODEOWNERS/waiver/release operating model | 4 | ◐ 完成有外部映射缺口 | PR template、runbook、`@Lei-k` fallback；organization team handles 需 repository 外部作業 |
| RT-11 | staged blocking rollout 與 baseline debt closure | 5 | ✅ 完成（stage 3） | `coverage --strict` 為 gate、`--baseline` 雙向檢查作為 ratchet；debt 已清零 |
| RT-12 | dogfood、failure injection、exit report | 5 | ✅ 完成 | 30 tests（含 §2 第 7、9 項注入）、`dogfood.sh` 於 `48f1bd4` 實跑（0 validity error、189 verified、0 blocked-static、0 needs-rewrite、52 skipped、verdict blocked）、`docs/traceability-report.md` |

## Current machine baseline

| 指標 | 值 |
|---|---:|
| Registered requirements/controls | 106 |
| Atomic criteria（active） | 372 |
| — 自帶 claim（`criterion`） | 241 |
| — 被其他 criterion 吸收 | 131 |
| — 待 PRD 改寫（`needs_rewrite`） | 0 |
| 已撤回並由 replacement supersede | 2 |
| Typed links | 1,446 |
| Primary statically verifiable | 241 |
| Blocking gaps | 0 |
| Active waivers | 0 |

（2026-07-27 規劃時的人工 baseline 表已由上表取代；規模數字見 `docs/traceability-report.md` §2。）

## 已知首要缺口

`traceability/baseline-debt.json` 已空，static coverage 無缺口。剩下的不是 coverage gap：

1. 131 條 Pass B 吸收分類 `review.approved` 仍為 `false`，待 product／test owner 簽核。
2. CODEOWNERS 目前只能使用 repository owner fallback，尚無 organization team handles（repository 外部作業）。
3. Release verdict 仍需在有 deployed edge、browser matrix、capacity rig 與兩項 manual procedure
   的環境跑一次完整 snapshot；本機能跑的 7 個 gate 已產生 189 條 verified。

原本列在此處的六項已全部關閉：三個未實作行為（`FR-FILE-006.AC-04`、`FR-NODE-005.AC-04`、
`FR-SESSION-005.AC-06`）補上實作與測試；三個 PRD 矛盾（`FR-CONN-006.AC-02`、
`FR-CONN-006.AC-04`、`FR-TERM-004.AC-03`）由產品決定改 PRD。

## 更新規則

- 每完成一張 ticket，更新狀態、commit/PR、實際檔案、執行命令與 artifact。
- 部分完成標 `◐` 並列未完成 exit；不能用「工具已建立」代表 registry/coverage 已完成。
- CI 尚未實跑時標 local-only；skip/manual/waiver 分開。
- 關閉一項 baseline debt 時，同時從 `baseline-debt.json` 移除；留著會讓 changed-scope gate 失敗。
- 最終結果以 `docs/traceability-report.md` 與 dogfood snapshot 為準。
