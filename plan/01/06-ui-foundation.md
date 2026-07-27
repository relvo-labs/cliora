# 06 — P0-W6 UI Foundation

## 目標

把展示原型可沿用的視覺語言轉為 semantic tokens 與可測元件，支撐 P0 Terminal 狀態；不在此階段重做 Dashboard、Nodes、Sessions 或 Workspace 完整頁面。

## P0-12：token 與 primitives

建立：

```text
frontend/src/theme/tokens.css
frontend/src/theme/naive.ts
frontend/src/components/common/AppShell.vue
frontend/src/components/common/StatusBadge.vue
frontend/src/components/common/AsyncState.vue
frontend/src/components/common/FocusRing.css
frontend/src/views/TokenShowcaseView.vue
```

Semantic token 至少包含 surface/canvas/elevated、text primary/secondary/muted/inverse、border/default/focus/danger、action primary/hover/disabled、status online/offline/busy/error、terminal background/foreground/selection/cursor。值映射自 `research/style.md`；component 不再重複硬編碼 palette。

Naive UI theme override 使用同一 token source，避免 CSS 與 JS 兩份人工色碼；若技術上必須輸出 TS 常數，建立單一 source/generation 或以 contract test 驗兩者一致。移除 `package.json` 的 floating `latest` 後鎖定 Naive UI、xterm、router、test dependencies。

## App Shell 與狀態

- MVP desktop baseline 1440×900；小於此尺寸可 horizontal overflow/收合，不能以 `min-width:1180px` 讓重要狀態不可達。
- P0 Shell 使用 56px header、可收合 280px sidebar、28px status bar；Terminal 是主工作區，不再包裝成裝飾 card。
- StatusBadge 以 icon + text + optional color 表達，涵蓋 connected/reconnecting/disconnected/exited/gap。
- AsyncState 涵蓋 idle/loading/success/empty/stale/offline/forbidden/partial/error；P0 showcase 展示全狀態，產品頁只使用適用子集。
- 全部互動可鍵盤操作，focus ring 明顯；dialog/toast（若 P0 stop/error 使用）需可恢復焦點並有 aria live 策略。
- motion 150–250ms，遵守 `prefers-reduced-motion`；不使用 bounce/glow/glass。

## 驗收方式

- Token showcase 展示 default/hover/focus/disabled/loading/error 與所有 terminal status。
- unit/component test 驗 semantic class/ARIA、keyboard activation、focus return、reduced motion。
- 以 1440×900 與 1920×1080 做 screenshot baseline；另在較窄 viewport 確認狀態與 retry/stop 仍可觸達。
- 文字與互動元件達 WCAG AA contrast；狀態移除顏色後仍可理解。
- Terminal mount/unmount 不因 Shell resize 重複建立 instance，面板收合只觸發 fit/resize。

## P0 不處理

Dashboard aggregates、Nodes cards、正式 Sessions list/New Session dialog、Enrollment、Monaco/FileTree、mobile layout 與 tablet read-only mode留在 P1–P3。產品正式名稱固定為 `Cliora`；可保留 `VITE_PRODUCT_NAME` 作部署顯示設定，但預設值、測試與正式品牌皆為 `Cliora`，並移除 component 中既有的 `Cask` 字樣。
