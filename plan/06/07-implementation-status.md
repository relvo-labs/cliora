# 07 — Requirement Traceability 實作狀態

> 本文件只記錄實際完成與可定位證據。**目前狀態：traceability infrastructure 完成，imported
> baseline 已關閉，rollout 進入 changed-scope blocking，blocking gaps 為 0。** 原本 308 個只有
> supporting suite link 的 criteria 已逐條處理完畢；三個未實作行為已補上實作與測試。剩下 3 項
> 是 PRD 文字本身無法判定，列於 `traceability/baseline-debt.json`，需產品決策而非寫程式，是
> full blocking 的唯一阻擋。

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
| RT-11 | staged blocking rollout 與 baseline debt closure | 5 | ✅ 完成（stage 2） | `coverage --baseline` 雙向檢查、CI blocking；stage 3 待 debt 清零 |
| RT-12 | dogfood、failure injection、exit report | 5 | ✅ 完成 | 30 tests（含 §2 第 7、9 項注入）、`dogfood.sh` 於 `5f3133d` 實跑（0 validity error、183 verified、0 blocked-static、52 skipped、verdict blocked）、`docs/traceability-report.md` |

## Current machine baseline

| 指標 | 值 |
|---|---:|
| Registered requirements/controls | 106 |
| Atomic criteria | 369 |
| — 自帶 claim（`criterion`） | 235 |
| — 被其他 criterion 吸收 | 131 |
| — 待 PRD 改寫（`needs_rewrite`） | 3 |
| Typed links | 1,420 |
| Primary statically verifiable | 235 |
| Blocking gaps | 0 |
| Active waivers | 0 |

（2026-07-27 規劃時的人工 baseline 表已由上表取代；規模數字見 `docs/traceability-report.md` §2。）

## 已知首要缺口

3 項具名於 `traceability/baseline-debt.json`，並在 `docs/traceability-report.md` §4 說明：

1. `FR-CONN-006.AC-02`、`FR-CONN-006.AC-04`、`FR-TERM-004.AC-03`：PRD 文字與實作不一致或不可判定。
   需產品決策（改 PRD 或改實作），不能靠寫測試解決——對任一邊寫測試都等於把實作登記成需求。
2. 134 條 Pass B 分類 `review.approved` 仍為 `false`，待 product／test owner 簽核。
3. CODEOWNERS 目前只能使用 repository owner fallback，尚無 organization team handles。

這些不是 waiver：沒有人核准過，也沒有議定到期日。

原本列在此處的三個未實作行為（`FR-FILE-006.AC-04` 檔案樹自動刷新、`FR-NODE-005.AC-04`
停用 Node 時終止 Session 的選擇、`FR-SESSION-005.AC-06` 強制終止升級）已完成實作與測試。

## 更新規則

- 每完成一張 ticket，更新狀態、commit/PR、實際檔案、執行命令與 artifact。
- 部分完成標 `◐` 並列未完成 exit；不能用「工具已建立」代表 registry/coverage 已完成。
- CI 尚未實跑時標 local-only；skip/manual/waiver 分開。
- 關閉一項 baseline debt 時，同時從 `baseline-debt.json` 移除；留著會讓 changed-scope gate 失敗。
- 最終結果以 `docs/traceability-report.md` 與 dogfood snapshot 為準。
