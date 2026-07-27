# 03 — Registry、CLI 與 generated views

涵蓋 RT-03、RT-04、RT-05。工具使用 repository 既有 Python/`uv` toolchain，初版只依賴標準庫與 committed JSON Schema；若採 validator library，必須鎖版於 `backend/uv.lock` 並說明理由。

## 1. Registry 契約

### `requirements.json`

頂層：

```json
{
  "schema_version": 1,
  "requirements": []
}
```

每個 entry 的必要欄位：

```json
{
  "id": "FR-AUTH-001",
  "kind": "functional",
  "title": "使用者登入",
  "source": {
    "path": "research/prd.md",
    "anchor": "fr-auth-001"
  },
  "lifecycle": "active",
  "applicability": ["mvp"],
  "criticality": "must",
  "owner": "team-central",
  "criteria": [
    {
      "id": "FR-AUTH-001.AC-01",
      "source_anchor": "fr-auth-001-ac-01",
      "verification_profile": "automated",
      "risk": "high"
    }
  ]
}
```

registry 不複製 criterion 正文；renderer 從 source anchor 讀取 display text。這可讓 source 漂移立即失敗，而不是兩份文字各自保持「有效」。

### `links.json`

```json
{
  "schema_version": 1,
  "links": [
    {
      "id": "LNK-FR-AUTH-001-AC01-VERIFY-001",
      "from": "FR-AUTH-001.AC-01",
      "type": "verified_by",
      "target": {
        "kind": "pytest",
        "locator": "backend/tests/db/test_auth_api.py::test_valid_login"
      },
      "role": "primary",
      "assertion": "有效帳密取得有效 access/refresh session",
      "owner": "team-central",
      "applicability": ["mvp"]
    }
  ]
}
```

link ID stable；只改 target 時保留 ID，語意完全不同則新增 link 並 retire 舊 link。`assertion` 不可重述整條 requirement，只描述此 target 實際證明的範圍。

### `gates.json`

每個 gate 必須有：

- stable `GATE-*` ID、owner、layer、command template。
- selector resolver、working directory、timeout。
- required environment/profile、secret-safe env allowlist。
- artifact patterns 與 parser type（JUnit、JSON、plain exit、manual manifest）。
- 觸發 policy（PR/main/release/manual）與 applicability。

例：

```json
{
  "id": "GATE-CONTRACT-CROSS-LANGUAGE",
  "layer": "contract",
  "command": ["make", "contract"],
  "trigger": ["pull_request", "release"],
  "artifacts": ["contract-junit.xml"],
  "required_for": ["mvp"]
}
```

command 使用 argv array，不接受 shell interpolation；需要複合流程時引用 committed script。

### `waivers.json`

依 01 的欄位，另加 `status`（active/expired/closed）與 `evidence_of_control`。validator 仍自行依日期/target 判斷有效，不信任手寫 status。

## 2. Schema 驗證

JSON Schema 至少限制：

- `additionalProperties: false`。
- ID regex、enum、UTC timestamp、repository-relative path。
- link type 與 target kind 的合法組合。
- criterion ID 必須以 parent ID 為 prefix。
- waiver expiry 必須晚於 creation，且不能超過 policy 最大期限。

Schema 之上的 semantic validator 再檢查：

- 全域 ID/anchor/link 唯一。
- source path/anchor 存在，case 完全一致。
- from/depends/supersedes target 存在且無非法 cycle。
- active object 不指向 retired target，除非是 `supersedes`。
- repository path 不可為 absolute、`..`、symlink 逃逸。
- selector/gate 可解析，generated file 與 registry 排序 deterministic。
- requirements、criteria、links、gates owner 不可為空或未知 team。

## 3. CLI

入口由 repository wrapper 固定 locked `uv`/Python 環境：

```bash
scripts/trace <command>
```

wrapper 內部呼叫 `uv run --project backend python -m scripts.traceability.cli`；CI 與文件不各自複製一份不同的啟動命令。

必要 subcommands：

| Command | 行為 | Exit |
|---|---|---:|
| `validate --level schema` | JSON/schema/ID/type | invalid = 2 |
| `validate --level static` | source/anchor/path/owner/link graph | invalid = 2 |
| `validate --level selectors` | collect/resolve pytest/Go/Vitest/Playwright/scenario | unresolved = 3 |
| `coverage [--scope changed|mvp|all]` | 套 verification profile 計算 missing/orphan | blocking gap = 4 |
| `render --check` | 產生至 temp 並比對 committed docs | drift = 5 |
| `render --write` | 更新 generated views | failure = 2 |
| `impact --base SHA --head SHA` | 由 source/target/path ownership 產生影響集 | unknown impact = 4 |
| `snapshot --results PATH --commit SHA` | 合併 links 與 gate results，輸出 verdict | blocking = 4 |
| `explain ID` | 顯示完整正向鏈與 status reason | read-only |
| `owners ID` | 顯示必要 reviewers | read-only |

所有 command 支援 `--format human|json`。CI 使用 JSON，開發者預設 human。錯誤輸出要包含 object ID、JSON pointer、檔案與修復提示；不可只回 stack trace。

## 4. Selector resolver

### Fast path（每個 PR）

- source/test path 存在。
- Python/Go/TS 檔內可找到 selector token。
- script scenario 與 gate ID 存在。
- contract fixture 位於 manifest 且 accept/reject expectation 一致。

### Full path（main/release 或 selector 變更）

- pytest `--collect-only` 比對完整 node ID。
- Go 依 package 執行 `go test -list`。
- Vitest/Playwright 使用其 list/JSON reporter；若版本無穩定 list API，執行 target file 並解析 machine reporter，不解析彩色 console。
- scenario script 提供 `--list-scenarios --format json`；不靠 grep shell function name。

resolver timeout/工具缺失回 `unresolved` 或 `skipped_prerequisite`，不能回 pass。

## 5. Coverage 演算法

對每個 active criterion：

1. 依 release/scope/applicability 判斷是否 required。
2. 套 verification profile 取得必要 link roles/layers。
3. 驗證 links 與 target。
4. 聚合 primary verification；supporting evidence 不單獨滿足。
5. 套 waiver，但保留原 gap 與 modifier。
6. parent requirement 取 required children 最差狀態。
7. MVP/TECH-SEC 先檢查 crosswalk，再檢查自己的 validation gate。

輸出至少分：

- complete、missing-design、missing-implementation、missing-verification。
- unresolved-selector、orphan-target、stale-link。
- no-current-evidence、failed、skipped、manual-pending。
- waived-active、waiver-expiring、waiver-expired。

coverage percentage 只作摘要，release gate 使用缺口集合；不能以 99% 掩蓋一條 blocking SEC。

## 6. Impact 演算法

影響來源：

- normative source anchor 變更：直接 requirement/criterion + 所有 downstream links。
- registry/link/gate 變更：對應 criteria。
- implementation/test path 變更：由 reverse index 找 criteria。
- shared protocol/schema/migration/authz/workspace guard 等高扇出 target：所有 linked criteria。
- 未被任何 link 命中的 product code：列 `unknown-impact`，changed-scope mode 阻擋並要求 map 或 explicit no-impact rationale。

rename 由 git diff rename metadata處理；工具不把 delete+add 靜默視為兩個無關檔。

輸出包括 required reviewers、最小 test gates、受影響 generated views、是否需 ADR/protocol/migration/security review。

## 7. Generated views

`docs/traceability/`：

- `matrix.md`：requirement → criteria → plan/design/code/test/gate，另有 reverse index。
- `coverage.md`：依 FR family、SEC、NFR、release 分組的狀態與 gap reason。
- `gaps.md`：所有 missing/unresolved/orphan/stale/waiver/skip，依 criticality 排序。
- `mvp.md`：MVP 20、tech 15、scope guards 的 release view。
- `owners.md`：requirement family 與 team ownership。
- `historical-gaps.md`：P0–P4 report/evidence reconciliation。

生成規則：

- 固定 ID 排序、LF、UTC、repository-relative links。
- 不嵌入「現在時間」於 committed docs；避免每次 render 無意義 diff。
- 不寫動態 pass 到 committed Markdown；latest evidence 只指向 artifact/snapshot identity。
- renderer 結果先寫 temp 再原子替換；`--check` 不修改工作樹。

## 8. 工具測試

`scripts/traceability/tests/` 至少包含：

- schema valid/invalid golden fixtures。
- duplicate ID/anchor、broken link、cycle、retired target。
- path traversal/symlink、absolute path、case mismatch。
- selector found/missing/ambiguous/tool unavailable/timeout。
- verification profile 聚合與 parent worst-state。
- skip/manual/waiver expiry/critical non-waivable。
- deterministic render golden test。
- impact：source change、shared target、rename、unknown code。
- snapshot：same SHA pass、stale SHA、dirty tree、artifact digest mismatch。

測試不得讀使用者 home 或連外；時間、commit、runner metadata 皆可注入。
