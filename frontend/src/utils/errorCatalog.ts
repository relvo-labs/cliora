// Cause and next step for each stable error code, for the browser (P4-07).
//
// Mirrors `backend/app/api/error_catalog.py` and `docs/error-catalog.md`. The server
// already sends a safe `message`; what it cannot send is wording in the viewer's
// language, so the pairing here is: **the server's message says what happened, this
// says what to do about it.**
//
// The code set and the retryable flags are kept in lockstep by
// `test_the_frontend_knows_every_code_it_can_receive` and
// `test_the_frontend_retry_affordance_matches_the_catalog` in
// `backend/tests/test_error_catalog.py` — a code the UI does not know renders with no
// guidance, which is the difference between an error a user can act on and one they
// can only screenshot.

export interface ErrorGuidance {
  cause: string;
  nextStep: string;
  // Whether to offer a retry control. Copied from the server's catalog rather than
  // guessed per call site: offering retry on a permanent failure teaches users to
  // ignore the button.
  retryable: boolean;
}

const GUIDANCE: Record<string, ErrorGuidance> = {
  // --- Authentication and authorization ---
  UNAUTHENTICATED: {
    cause: "登入狀態已失效或不存在。",
    nextStep: "請重新登入。",
    retryable: true,
  },
  INVALID_CREDENTIALS: {
    cause: "帳號或密碼不正確。",
    nextStep: "請確認後重試；連續失敗會被記錄。",
    retryable: true,
  },
  ACCOUNT_DISABLED: {
    cause: "此帳號已被 Admin 停用。",
    nextStep: "請聯繫 Admin 重新啟用。",
    retryable: false,
  },
  TOKEN_EXPIRED: {
    cause: "存取憑證已過期。",
    nextStep: "系統會自動更新；若失敗請重新登入。",
    retryable: true,
  },
  TOKEN_INVALID: {
    cause: "憑證無效，或已因登出／權限變更而被撤銷。",
    nextStep: "請重新登入。",
    retryable: false,
  },
  FORBIDDEN: {
    // Deliberately does not distinguish "your role lacks it" from "you do not own
    // it": the server returns one message for both so a caller cannot learn that a
    // resource exists or who owns it (ADR 0016), and the UI must not undo that.
    cause: "你的角色不允許此操作，或該資源屬於其他人。",
    nextStep: "如需此權限請聯繫 Admin。",
    retryable: false,
  },

  // --- Request shape ---
  INVALID_ARGUMENT: {
    cause: "請求中有一個值不被接受。",
    nextStep: "修正後重新送出。",
    retryable: false,
  },
  INVALID_QUERY: {
    cause: "查詢條件超出允許範圍（未知欄位、時間範圍過寬，或單頁筆數過大）。",
    nextStep: "縮小範圍或減少單頁筆數；伺服器訊息會指出上限。",
    retryable: false,
  },
  NOT_FOUND: {
    cause: "資源不存在或已被移除。",
    nextStep: "重新載入清單。",
    retryable: false,
  },
  INTERNAL_ERROR: {
    cause: "伺服器發生未預期的錯誤；細節僅記錄在伺服器日誌。",
    nextStep: "請重試；若持續發生，回報畫面上的 request_id。",
    retryable: true,
  },
  CANCELLED: {
    cause: "請求已被取消（切換頁面或變更條件）。",
    nextStep: "無需處理，這不是錯誤。",
    retryable: false,
  },

  // --- Enrollment ---
  ENROLLMENT_TOKEN_INVALID: {
    cause: "安裝 Token 無效、已過期、已撤銷，或已用盡次數。",
    nextStep: "重新建立安裝 Token 後再執行安裝程式。",
    retryable: false,
  },

  // --- Node and relay ---
  NODE_NOT_FOUND: {
    cause: "此 Node 不存在或已被移除。",
    nextStep: "重新載入 Node 清單。",
    retryable: false,
  },
  NODE_OFFLINE: {
    cause: "Daemon 目前沒有連線，因此無法轉送任何請求。",
    nextStep: "在該機器上檢查 systemctl status agentd 與 agentd doctor。",
    retryable: true,
  },
  NODE_DISABLED: {
    cause: "此 Node 已被停用：連線仍在，但拒絕新的操作。",
    nextStep: "在 Node 詳情頁重新啟用。",
    retryable: false,
  },
  NODE_BUSY: {
    cause: "此 Node 待回覆的請求已達上限。",
    nextStep: "稍後重試；若持續發生，Daemon 可能已卡住。",
    retryable: true,
  },
  NODE_AUTH_FAILED: {
    cause: "Daemon 無法證明它持有此 Node 的私鑰。",
    nextStep: "輪替憑證，或重新註冊該 Node。",
    retryable: false,
  },
  REQUEST_TIMEOUT: {
    cause: "Daemon 未在時限內回覆。",
    nextStep: "請重試。若這是更新操作，逾時屬預期行為：Daemon 會在重啟後回報。",
    retryable: true,
  },
  QUEUE_OVERFLOW: {
    cause: "終端機輸出的速度超過此瀏覽器的處理能力，佇列已滿並主動關閉連線。",
    nextStep: "重新連線；中斷處會明確標示，不會假裝內容連續。",
    retryable: true,
  },

  // --- Protocol ---
  INVALID_MESSAGE: {
    cause: "有一個訊框不符合 v1 契約。",
    nextStep: "請回報：正常的用戶端不會產生此錯誤。",
    retryable: false,
  },
  PROTOCOL_VERSION_UNSUPPORTED: {
    cause: "對端使用的協定版本不被支援。",
    nextStep: "更新 Daemon（或伺服器）使雙方同為 v1。",
    retryable: false,
  },
  MESSAGE_TYPE_UNSUPPORTED: {
    cause: "此訊息型別不在此方向的允許清單中。",
    nextStep: "更新 Daemon。",
    retryable: false,
  },
  FRAME_TOO_LARGE: {
    cause: "訊框超過大小上限（控制訊框 64 KiB，檔案回應 8 MiB）。",
    nextStep: "縮小請求範圍：較少的項目，或較小的檔案。",
    retryable: false,
  },
  INVALID_SESSION: {
    cause: "訊框指向的 Session 與其連線不符。",
    nextStep: "重新載入頁面。",
    retryable: false,
  },

  // --- Runtime ---
  RUNTIME_NOT_ALLOWED: {
    cause: "此 runtime 不在允許清單中（僅 claude、codex）。",
    nextStep: "改選允許的 runtime。",
    retryable: false,
  },
  RUNTIME_NOT_FOUND: {
    cause: "此 Node 上未偵測到該 CLI。",
    nextStep: "在該機器上安裝後，以 agentd runtime list 確認。",
    retryable: false,
  },
  RUNTIME_DISABLED: {
    cause: "此 Node 的設定停用了該 runtime。",
    nextStep: "在 config.yaml 啟用後重啟 Daemon。",
    retryable: false,
  },
  RUNTIME_NOT_EXECUTABLE: {
    cause: "設定的 binary 存在，但 Daemon 的執行使用者無法執行它。",
    nextStep: "修正權限後執行 agentd doctor。",
    retryable: false,
  },

  // --- Session and terminal ---
  SESSION_NOT_FOUND: {
    cause: "此 Session 在 Central 或該 Node 上皆不存在。",
    nextStep: "重新載入 Session 清單。",
    retryable: false,
  },
  SESSION_ALREADY_EXISTS: {
    cause: "此 Node 上已有相同 id 的 Session 在執行。",
    nextStep: "重新載入；既有的 Session 仍可使用。",
    retryable: false,
  },
  SESSION_NOT_RUNNING: {
    cause: "此 Session 已結束。",
    nextStep: "建立新的 Session。",
    retryable: false,
  },
  SESSION_INVALID_STATE: {
    cause: "此操作不適用於 Session 目前的狀態。",
    nextStep: "重新載入以取得目前狀態。",
    retryable: false,
  },
  SESSION_LIMIT_REACHED: {
    cause: "此 Node 已達同時執行 Session 的上限。",
    nextStep: "結束一個 Session，或改用其他 Node。",
    retryable: false,
  },
  SESSION_START_FAILED: {
    cause: "Node 接受了請求，但 CLI 沒有啟動。",
    nextStep:
      "以此 request_id 查該 Node 的日誌；並用 agentd runtime list 確認 runtime。",
    retryable: true,
  },
  SHELL_ALREADY_OPEN: {
    cause:
      "每個 Session 同時只能有一個系統終端機，而目前有另一個分頁或視窗正連著它。",
    nextStep:
      "回到持有它的分頁，或在那裡關閉它；沒有人連著的終端機不會被拒絕，下次開啟就會取代它。",
    retryable: false,
  },
  INVALID_TERMINAL_SIZE: {
    cause: "要求的終端機尺寸超出允許範圍。",
    nextStep: "調整視窗大小後重試。",
    retryable: false,
  },
  TERMINAL_ALREADY_CONTROLLED: {
    cause: "已有其他人持有此終端機的輸入權。",
    nextStep: "以唯讀方式連接，或在有權限時接管。",
    retryable: false,
  },

  // --- Workspace ---
  // --- 專案層（ADR 0027）---
  //
  // 旗標關閉時的 /api/projects* 刻意回一個沒有錯誤碼的 404，所以這裡沒有
  // PROJECTS_DISABLED —— 一個具名的碼會洩漏「這個功能存在，只是關著」，
  // 而那正是裸 404 要藏住的事。
  PROJECT_NOT_FOUND: {
    cause: "該專案不存在，或已被移除。",
    nextStep: "回到專案列表重新整理。",
    retryable: false,
  },
  PROJECT_SLUG_TAKEN: {
    cause: "已有專案使用這個識別碼；識別碼在整個平台上唯一，且建立後不可變更。",
    nextStep: "換一個識別碼。顯示名稱不受限制，可以維持原本想要的名字。",
    retryable: false,
  },
  PROJECT_SLUG_INVALID: {
    cause:
      "識別碼只能用小寫英數字與連字號；若名稱全為非拉丁字元，系統無法自動推導。",
    nextStep: "自行指定一個識別碼，例如 traqora-api。",
    retryable: false,
  },
  PROJECT_STATUS_INVALID: {
    cause: "專案狀態只有進行中、暫停、已封存三種。",
    nextStep: "改用其中一種。",
    retryable: false,
  },
  PROJECT_ARCHIVED: {
    cause:
      "已封存的專案不接受新的 Session 與新的 Workspace 綁定；既有的一律不受影響。",
    nextStep: "先解除封存，或改用其他專案。",
    retryable: false,
  },
  PROJECT_WORKSPACE_NOT_FOUND: {
    cause: "該綁定已被解除，或屬於另一個專案。",
    nextStep: "重新整理專案頁面。",
    retryable: false,
  },
  // --- 任務層（ADR 0028）---
  //
  // 兩組看起來像、其實不同：相依未滿足是「等一下就好」，循環相依是「這個圖永遠
  // 滿足不了」；關卡不存在是打錯字，關卡被停用是這個部署的狀態。合併任何一組，
  // 使用者就分不出該等待還是該去改東西。
  TASK_NOT_FOUND: {
    cause: "該卡片、Epic、User Story 或相依關係不存在於這個專案。",
    nextStep: "重新整理看板。",
    retryable: false,
  },
  TASK_VERSION_CONFLICT: {
    cause:
      "這張卡剛被別人改過。每次寫入都帶著讀取當下的版本，所以兩個人同時拖同一張卡不會互相覆蓋。",
    // 不是 retryable：同一個請求原樣重送會再撞一次版本。要重來的是「讀新版 → 再拖」，
    // 那是使用者的動作，不是一個重試按鈕。
    nextStep: "看板已重新載入這張卡，請再拖一次。",
    retryable: false,
  },
  VIEW_NAME_CONFLICT: {
    cause:
      "同一個擁有者底下已經有同名的檢視——共用檢視以專案為範圍，個人檢視以人為範圍。" +
      "已刪除的檢視名稱會釋出，因為背後的索引是部分索引。",
    nextStep: "換一個名稱，或直接使用既有的那一個。",
    retryable: false,
  },
  VIEW_NOT_OWNED: {
    cause:
      "這是別人的個人檢視。**回 403 而不是 404 是刻意的**：別人的個人檢視本來就不會出現在" +
      "清單裡，所以說「這不是你的」沒有洩漏任何推不出來的事，而且讓客戶端能把它與" +
      "「已被刪除」分開處理。",
    nextStep: "改用「複製」建立一份屬於自己的個人檢視。",
    retryable: false,
  },
  BULK_LIMIT_EXCEEDED: {
    cause:
      "一次批次修改的卡片太多。每一張都走與單張完全相同的寫入路徑——完成判準、相依檢查、" +
      "稽核與活動紀錄、知識佇列——所以一批是一百次那樣的寫入，不是一句 SQL。" +
      "`details.limit` 與 `details.received` 給出兩個數字。",
    nextStep: "把選取範圍拆成不超過上限的幾批。",
    retryable: false,
  },
  FILTER_FIELD_NOT_ALLOWED: {
    cause:
      "篩選用的欄位不在允許清單裡。篩選是一份白名單而不是查詢語言：十五個欄位、八個運算子，" +
      "每一組配對只有一條編譯路徑。`details.allowed_fields` 列出可用的欄位。",
    nextStep: "改用清單內的欄位。",
    retryable: false,
  },
  FILTER_OP_NOT_ALLOWED: {
    cause:
      "這個運算子不適用於這個欄位——`contains` 只屬於標籤陣列，`gt`／`lt` 只屬於時間。" +
      "`details.allowed_ops` 列出這個欄位接受哪些。",
    nextStep: "改用 `details.allowed_ops` 裡的運算子。",
    retryable: false,
  },
  FILTER_TOO_COMPLEX: {
    cause:
      "篩選超出上限：巢狀深度 3、葉條件 20 個、單一清單 50 個值。" +
      "`details.limit` 說明是哪一項，並附上實際值與上限。",
    nextStep: "簡化篩選條件；`details.limit` 指名越界的那一項。",
    retryable: false,
  },
  RANK_NEIGHBOR_STALE: {
    cause:
      "你放下的那兩張卡已經不相鄰了——其中一張被刪除、被移到別的專案，或是有人先重排了。" +
      "移動送出的是「放在這兩張之間」而不是一個位置編號，因為在有篩選的看板上，" +
      "編號指的不是同一件事。",
    // 與 TASK_VERSION_CONFLICT 同一個理由：原樣重送會再撞一次。要重來的是
    // 「看新的順序 → 再拖」，那是使用者的動作。
    nextStep: "看板已重新載入順序，卡片留在原位，請再拖一次。",
    retryable: false,
  },
  TASK_DEPENDENCY_UNSATISFIED: {
    cause:
      "前置卡片尚未完成。進入「就緒」之後的車道等於宣告這張卡可以動工，而未完成的前置卡與這個宣告矛盾。",
    nextStep: "先完成訊息中指名的卡片，或解除已經不成立的相依關係。",
    retryable: false,
  },
  TASK_DEPENDENCY_CYCLE: {
    cause:
      "前置卡片已經（直接或間接）相依於這張卡，加上這條會形成一個永遠無法滿足的循環。",
    nextStep: "先移除循環中的其中一條相依關係。",
    retryable: false,
  },
  TASK_STAGE_INVALID: {
    cause: "車道、風險、優先權、來源或交付模式不在流程定義的詞彙裡。",
    nextStep: "查看該專案的流程定義所允許的值。",
    retryable: false,
  },
  TASK_ACCEPTANCE_CRITERIA_INVALID: {
    cause:
      "驗收標準必須是物件陣列，才能在卡片與 Agent 情境中逐項呈現；自 V2.4 起它的結果也必須是四個值之一。",
    nextStep:
      "把每一項改成至少含有 text 欄位的物件，結果填 passed／failed／partial／not_verified。",
    retryable: false,
  },
  TASK_DONE_GATE_UNMET: {
    cause:
      "進入「完成」是在主張這件事做完了，而平台握有支持那個主張的事實。缺的每一項都列在 details.missing 裡——不是只列第一項，因為缺摘要與缺驗證報告要做的事不一樣。",
    nextStep:
      "補齊被指名的項目。管理者可以帶著理由強制推進，而那個理由會永久顯示在卡片上。",
    retryable: false,
  },
  TASK_FORCE_REASON_REQUIRED: {
    cause:
      "強制推進必須填寫理由。理由同時記在卡片與時間軸上，那正是這個出口「可見」而不是「靜悄悄」的原因。",
    nextStep: "在請求中帶上 force_reason。",
    retryable: false,
  },
  TASK_DELIVERY_NEEDS_SOURCE: {
    cause:
      "這張卡要以合併請求交付，卻同時宣告不取得程式碼。兩個欄位刻意分開，而這個組合沒有東西可以開 PR。",
    nextStep: "把來源改成 repo，或把交付方式改成不交付／產物。",
    retryable: false,
  },
  TASK_PR_TARGET_MISSING: {
    cause:
      "以合併請求交付必須指定目標分支。在派工當下拒絕，而不是等到執行完才發現。",
    nextStep: "在卡片上填寫目標分支。",
    retryable: false,
  },
  TASK_EXISTING_PR_OUT_OF_NAMESPACE: {
    cause:
      "平台只推得到 cliora/ 命名空間之內，所以「接續既有 PR」只對平台自己開的 PR 成立。**這看起來像缺陷，實際上是邊界**：那條約束編譯在節點程式裡，也正是「平台會推到哪裡」不必查資料就答得出來的原因。",
    nextStep: "改用分支交付並自行合併，或接續一個平台開的 PR。",
    retryable: false,
  },
  TASK_PROVIDER_UNSUPPORTED: {
    cause:
      "這個部署沒有該主機的合併請求整合。在派工當下拒絕，而不是等工作做完才失敗。",
    nextStep: "改用分支交付，或改用支援的主機上的儲存庫。",
    retryable: false,
  },
  VERIFICATION_COMMANDS_INVALID: {
    cause:
      "驗證命令是引數陣列而不是命令字串，所以管線與 && 不會生效——請拆成多條。編碼後的長度在**存檔時**就量，而不是等到派工才量：一條存得下來卻從來送不出去的命令，會讓「這個專案的驗證從來沒跑過」變成沒有人會去查的事實。",
    nextStep: "縮短名稱或引數，或把這條命令拆成兩條。",
    retryable: false,
  },
  PLAN_STEPS_INVALID: {
    cause:
      "執行計畫的步驟必須是物件，且狀態必須是五個值之一。details.allowed 列出可用的值。",
    nextStep: "把每一個步驟改成含標題與合法狀態的物件。",
    retryable: false,
  },
  PLAN_NOTE_REQUIRED: {
    cause:
      "改寫執行計畫必須說明為什麼。「為什麼改」正是這張表用版本列而不是可改欄位的理由。",
    nextStep: "附上一句說明這次改了什麼、為什麼。",
    retryable: false,
  },
  PLAN_SEQ_CONFLICT: {
    cause:
      "兩個寫入者同時取到同一個版本序。伺服器已自動重試一次；第二次再撞代表寫入速度超出這張表的用途。",
    nextStep: "重新送出一次。",
    retryable: true,
  },
  VERIFICATION_REPORT_INVALID: {
    cause:
      "驗證報告的欄位不合法，details.field 指名是哪一個。帶了 source 欄位**不是**錯誤——它會被接受、丟棄，並記下曾被丟棄，因為可信度由寫入路徑決定。",
    nextStep: "修正被指名的欄位；result 是五個值之一。",
    retryable: false,
  },
  EVIDENCE_KIND_INVALID: {
    cause:
      "證據類型決定它的可信度等級，所以它是封閉集合。details.allowed 列出可用的值。",
    nextStep: "改用清單中的類型。",
    retryable: false,
  },
  EVIDENCE_KIND_NOT_WRITABLE: {
    cause:
      "類型決定來源，所以 Agent 寫入機器事實類型是**被拒絕而不是被降級**——降級後的那一列仍然在主張一件沒有人觀察過的事。",
    nextStep: "改記為發現、限制或風險。",
    retryable: false,
  },
  EVIDENCE_PAYLOAD_TOO_LARGE: {
    cause:
      "證據是給人掃一眼的結構化事實，不是檔案儲存體。產物已經有配額、保留期與下載路徑。",
    nextStep: "改附成卡片產物。",
    retryable: false,
  },
  EVIDENCE_RUN_LIMIT: {
    cause: "單次執行的證據筆數有上限，避免一次執行塞滿整張卡的證據清單。",
    nextStep: "改用摘要，或把細節附成產物。",
    retryable: false,
  },
  PROCESS_OVERRIDE_UNKNOWN_KEY: {
    cause:
      "專案只能停用流程定義裡既有的項目，不能新增。不認得的項目被拒絕而不是被存起來——存起來會靜默無效，而打字的人以為自己關掉了它。",
    nextStep: "對照該專案的流程定義檢查名稱。details.unknown 列出是哪幾個。",
    retryable: false,
  },
  TASK_CONTEXT_TOO_LARGE: {
    cause: "驗收標準必須完整保留在 4 KB 任務情境包中，目前內容超過保留預算。",
    nextStep: "縮短或合併驗收標準；描述類區塊會由系統自動省略。",
    retryable: false,
  },
  FORBIDDEN_FIELD: {
    cause:
      "這個欄位不能用這種方式設定。被拒絕而不是被忽略，是因為靜默丟掉的欄位是使用者以為改成功的變更。審查關卡尤其如此：它有自己的端點與自己的權限。",
    nextStep: "改用擁有該欄位的端點。",
    retryable: false,
  },
  GATE_UNKNOWN: {
    cause: "流程定義裡沒有這個關卡。",
    nextStep: "查看該專案的流程定義所列的關卡。",
    retryable: false,
  },
  GATE_DISABLED: {
    cause:
      "這個關卡依賴一項未啟用的整合（介面審查需要 tunnel 整合）。它在讀取時就被停用，而不是留著一個永遠無法通過的關卡——那是死鎖不是嚴謹。",
    nextStep: "啟用該整合，或不經過這個關卡繼續。",
    retryable: false,
  },
  GATE_REQUIRES_HUMAN_ACTOR: {
    cause: "審查關卡必須由人核准；Agent 的輸出不等於核准。",
    nextStep: "由具備核准權限的人在平台上勾選。",
    retryable: false,
  },
  // --- 需求與拆解（D28）---
  REQUIREMENT_NOT_FOUND: {
    cause: "該需求不存在於這個專案。",
    nextStep: "重新整理需求列表。",
    retryable: false,
  },
  REQUIREMENT_NOT_SPECIFIED: {
    cause: "核准是「核准某個東西」；還沒有任何規格版本時沒有東西可以核准。",
    nextStep: "先新增一版規格。",
    retryable: false,
  },
  SPEC_HAS_OPEN_QUESTIONS: {
    cause:
      "還有問題既沒有答案、也沒有被明確標為「已知未知」。規格在這種狀態下不得核准。",
    nextStep: "逐一回答，或把它標記為已知未知，再核准。",
    retryable: false,
  },
  REQUIREMENT_ALREADY_APPROVED: {
    cause:
      "規格版本在核准前只新增不修改；核准之後改變主意是一個新的需求，而不是把舊的改寫。",
    nextStep: "另提一個需求。",
    retryable: false,
  },
  REQUIREMENT_NOT_APPROVED: {
    cause:
      "拆解一個還沒有人同意的東西，產出的是會被丟掉的工作。這條由 API 強制，不是畫面隱藏——V2.5 的 Agent 走的是同一條路。",
    nextStep: "先核准規格。",
    retryable: false,
  },
  PROPOSAL_NOT_FOUND: {
    cause: "該拆解提案不存在。",
    nextStep: "重新整理需求頁面。",
    retryable: false,
  },
  PROPOSAL_ALREADY_DECIDED: {
    cause: "接受提案會建立真的卡片，所以只做一次；再決定一次會建出重複的卡。",
    nextStep: "計畫有變的話，另建一個提案。",
    retryable: false,
  },
  // --- V2.5 釐清、拆解與文件修訂提案（ADR 0034）---
  TASK_KIND_FORBIDS_SECRETS: {
    cause:
      "釐清與拆解不需要憑證就能讀程式碼與提問，所以宣告了機密的卡片在派工當下被拒。刻意排在允許清單檢查之前——要修的是清空欄位，不是放寬專案設定。",
    nextStep: "清空卡片的機密欄位。",
    retryable: false,
  },
  TASK_KIND_DELIVERY_NOT_ALLOWED: {
    cause:
      "釐清、拆解與 mockup 卡片不產生程式碼變更；宣告分支或合併請求會在交付那一步失敗，而那時整個 run 已經跑完了。",
    nextStep: "把交付方式改成「無交付」或「卡片產物」。",
    retryable: false,
  },
  TASK_KIND_NEEDS_REQUIREMENT: {
    cause:
      "釐清或拆解是對著一個需求做的；沒有需求就沒有東西可讀，也沒有地方可以寫回去。",
    nextStep: "從需求頁面派工，或先把卡片連到需求。",
    retryable: false,
  },
  TASK_MOCKUP_INTEGRATION_DISABLED: {
    cause:
      "沒有啟用 tunnel 整合就沒有辦法展示可互動的預覽，所以這個關卡整個不存在。一般的 UI 實作卡不受影響，Agent 附截圖為產物也不受影響。",
    nextStep: "啟用 tunnel 整合，或把這張卡改成一般的實作卡。",
    retryable: false,
  },
  TASK_KIND_LOCKED: {
    cause:
      "這張卡的規格版本、提問串與執行紀錄都由它當時的種類解釋；事後改種類會留下一張莫名產出規格的實作卡。",
    nextStep: "建立一張新的卡片。",
    retryable: false,
  },
  TASK_KIND_MISMATCH: {
    cause:
      "卡片的種類決定它可以做哪些寫入：`/spec` 服務釐清卡，`/proposal` 服務拆解卡。",
    nextStep: "用對應這張卡種類的路徑。",
    retryable: false,
  },
  QUESTION_ALREADY_PENDING: {
    cause:
      "一次一個問題。一口氣問五個，實務上會得到三個答案，而提問者分辨不出哪兩個被忽略了。兩個相關的子問題寫成同一則訊息是可以的。",
    nextStep: "把問題合併成一則，或等上一題有回覆。",
    retryable: false,
  },
  // --- V2-C1 conversation (ADR 0035/0036/0037) ------------------------------
  QUESTION_NOT_FOUND: {
    cause:
      "這個問題不在這張卡上。屬於別張卡的問題會回報成「不存在」，因為那句話是真的，而且不會透露別處有什麼。",
    nextStep: "重新載入卡片，回覆卡片上列出的問題。",
    retryable: false,
  },
  QUESTION_ALREADY_ANSWERED: {
    cause:
      "已經有人回答過這一題了。團隊裡兩個人同時回答同一題是常態，不是錯誤狀態。",
    nextStep: "看一下既有的回覆；還有想補充的就留言。",
    retryable: false,
  },
  QUESTION_NOT_OPEN: {
    cause:
      "這個問題已經逾時或被取消。逾時的問題會保留下來供閱讀，但回答它不會再喚起 Agent。",
    nextStep: "重新派工，或提出新的問題。",
    retryable: false,
  },
  RUN_NOT_WAITING_FOR_INPUT: {
    cause: "這個執行不在等待回覆的狀態，沒有東西可以續跑。",
    nextStep: "重新載入卡片；若持續發生，附上 request id 回報。",
    retryable: false,
  },
  CONVERSATION_CURSOR_AHEAD: {
    cause:
      "你這一端記住的對話位置超前了這張卡。回傳空白頁會讓它永遠停在那裡而沒有任何提示，所以直接拒絕。",
    nextStep: "重新載入對話。",
    retryable: true,
  },
  MESSAGE_IDEMPOTENCY_CONFLICT: {
    cause:
      "同一個冪等鍵先前用在內容不同的訊息上。一個鍵對應一則訊息，重複使用會讓重送和新訊息分不出來。",
    nextStep: "重新輸入後再送出一次。",
    retryable: false,
  },
  TURN_ALREADY_QUEUED: {
    cause:
      "這個回答已經建立過一輪 Agent 執行。一個回答最多喚起一輪，由資料庫保證。",
    nextStep: "等既有的那一輪；不需要第二輪。",
    retryable: false,
  },
  MESSAGE_TOO_LARGE: {
    cause: "訊息超過單則長度上限。你打的字沒有遺失。",
    nextStep: "縮短訊息，或把長篇內容以產物附上。",
    retryable: false,
  },
  AGENT_CANNOT_DECIDE: {
    cause:
      "接受或退回提案是人的動作，需要核准權限，而 Agent 的執行憑證永遠不具備它。",
    nextStep: "把內容以提案送出，交由人決定。",
    retryable: false,
  },
  KNOWLEDGE_DISABLED: {
    cause:
      "這個專案沒有啟用專案記憶。開關是逐專案的，不是整個部署的——" +
      "一個 500 檔的專案與一個 50000 檔的 monorepo 需要不同的答案。",
    nextStep: "在專案設定裡啟用專案記憶（需要專案管理權限）。",
    retryable: false,
  },
  SOURCE_NOT_FOUND: {
    cause:
      "這份來源已不可用：可能被新版本取代、原始檔案已刪除，" +
      "或這個引用標記來自更早的一次情境組裝。",
    nextStep: "重新取得目前的引用清單（`cliora knowledge context`）。",
    retryable: false,
  },
  SOURCE_EXCLUDED: {
    cause:
      "有人把這份來源從這張卡排除了。排除是逐卡片、可還原的，" +
      "與刪除不同——它讓一張卡忽略某份文件，而不影響其他引用它的卡。",
    nextStep: "問問排除它的人，或引用別的來源。",
    retryable: false,
  },
  CONTEXT_BUDGET_EXCEEDED: {
    cause:
      "這張卡的情境包在預算內組不出來。裁切順序是固定的——先砍檢索到的參考資料，" +
      "再壓縮較舊的對話——而專案規則與未決問題永不被裁切。",
    nextStep: "縮短專案規則的文字，或把卡片拆小。",
    retryable: false,
  },
  KNOWLEDGE_SYNC_TOO_LARGE: {
    cause:
      "這次程式庫同步超過上限。回應會指名是哪一項——檔數、位元組或頻率。" +
      "單一過大的檔案只會被跳過，不會讓整次同步失敗。",
    nextStep: "用 `.clioraignore` 縮小範圍，或調整專案的同步上限。",
    retryable: true,
  },
  SPEC_SECTION_UNKNOWN: {
    cause: "規格書的九個章節是封閉的，否則兩個撰寫者會用兩種拼法寫同一件事。",
    nextStep: "改用清單上的章節名稱。",
    retryable: false,
  },
  SPEC_VERSION_LIMIT: {
    cause:
      "版本數上限是防止迴圈的後盾，不是設計限制——一次真正的釐清幾輪就會收斂。",
    nextStep: "核准目前這一版，或另提一個需求。",
    retryable: false,
  },
  SPEC_QUESTION_AMBIGUOUS: {
    cause:
      "答案與「已知未知」任一個都算解決，兩個都填會讓核准按鈕亮起來卻看不出是哪一種狀態——而「這是答案」與「我們決定不解決」正是審閱者要分辨的。",
    nextStep: "留下答案，或留下「已知未知」的標記，擇一。",
    retryable: false,
  },
  PROPOSAL_EMPTY: {
    cause: "沒有任何 Task 的拆解不是拆解。",
    nextStep: "至少提出一張 Task。",
    retryable: false,
  },
  PROPOSAL_TOO_LARGE: {
    cause:
      "上限不是顆粒度的判斷（伺服器判斷不了），是防止失控的後盾。撞到它通常表示這個需求該先拆成幾個 Epic。",
    nextStep: "先拆分需求，或一次只拆一個 Epic。",
    retryable: false,
  },
  PROPOSAL_TREE_INVALID: {
    cause:
      "有重複的 id，或父節點／相依指向樹裡不存在的節點。在提交時檢查而不是接受時——否則沒被勾選的節點之間的錯誤會很晚才浮現。",
    nextStep: "修正被指名的節點後重新提交。",
    retryable: false,
  },
  PROPOSAL_TREE_CYCLE: {
    cause:
      "相依形成循環。錯誤訊息會列出循環路徑——在一棵四十個節點的樹裡，只說「有循環」是無法行動的。",
    nextStep: "打斷循環後重新提交。",
    retryable: false,
  },
  PROPOSAL_FIELD_FORBIDDEN: {
    cause:
      "機密是人在卡片上的決定，不是提案的。這裡拒絕而不是靜默移除，因為移除會讓提交者以為自己宣告成功了。",
    nextStep: "移除該欄位；卡片建立後由人補上機密。",
    retryable: false,
  },
  PROPOSAL_RISK_UNDERSTATED: {
    cause:
      "密鑰、認證、金流、遷移與基礎設施是停止條件第四條。這個比對刻意寬鬆、也刻意寧可誤報：多一個徽章的代價是取消勾選一次，漏掉的代價是一張碰金流的卡以低風險進入就緒。",
    nextStep: "把風險改成高，或在比對誤判時調整措辭。",
    retryable: false,
  },
  PROPOSAL_REJECT_NEEDS_NOTE: {
    cause:
      "理由是這條路徑上唯一會累積的訊號：下一次拆解同一個需求時，它會作為負面情境提供。",
    nextStep: "寫下為什麼不採用。",
    retryable: false,
  },
  PROPOSAL_OVERRIDE_NOT_ACCEPTED: {
    cause:
      "不是這次勾選的節點——那樣的修改會在日後某次部分接受時被靜默套用；或者修改的是就緒條件，那會讓「缺就緒條件的卡落在待辦」變成一條可以繞過的規則。",
    nextStep: "先勾選該節點，或在卡片建立之後再修改。",
    retryable: false,
  },
  PATCH_PROPOSAL_NOT_FOUND: {
    cause: "該文件修訂提案不存在。",
    nextStep: "重新整理專案的提案清單。",
    retryable: false,
  },
  PATCH_PROPOSAL_TARGET_INVALID: {
    cause:
      "路徑必須是 repo 內的相對路徑。平台從不開啟這個檔案——這個檢查是為了不讓審閱畫面上出現一個看起來像攻擊的字串。",
    nextStep: "改用 repo 相對路徑，章節名稱用那四個之一。",
    retryable: false,
  },
  PATCH_PROPOSAL_TOO_LARGE: {
    cause:
      "在提交時拒絕而不是在渲染時截斷：一份被截斷的 diff 看起來是完整的，而人會據此做決定。",
    nextStep: "依文件拆成數份提案。",
    retryable: false,
  },
  PATCH_PROPOSAL_ALREADY_DECIDED: {
    cause: "接受與拒絕都只做一次；該列保留了決定者與時間。",
    nextStep: "文件又變了的話，提交一份新的提案。",
    retryable: false,
  },
  PATCH_PROPOSAL_REJECT_NEEDS_NOTE: {
    cause:
      "與拆解提案同一條規則：沒有理由的拒絕，三個月後與沒有這一列無法分辨。",
    nextStep: "寫下為什麼不採用。",
    retryable: false,
  },
  SESSION_PROJECT_MISMATCH: {
    cause:
      "Session 指定專案時，其 Workspace 必須是該專案的綁定之一。比對是完全相等的，所以已綁定路徑的子目錄本身並未綁定。",
    nextStep:
      "從該專案的綁定清單中選一個路徑、先綁定這個路徑，或不要指定專案。",
    retryable: false,
  },
  WORKSPACE_OUTSIDE_ALLOWED_ROOT: {
    cause: "此路徑解析後落在該 Node 允許的所有根目錄之外。",
    nextStep: "改選允許根目錄內的路徑（agentd workspace list）。",
    retryable: false,
  },
  WORKSPACE_NOT_FOUND: {
    cause: "該目錄在 Node 上不存在。",
    nextStep: "建立該目錄，或改選其他目錄。",
    retryable: false,
  },
  WORKSPACE_NOT_DIRECTORY: {
    cause: "路徑存在，但不是目錄。",
    nextStep: "請選擇一個目錄。",
    retryable: false,
  },
  WORKSPACE_PERMISSION_DENIED: {
    cause: "Daemon 的執行使用者無法讀取該目錄。",
    nextStep: "授予該使用者權限，或改選其他目錄。",
    retryable: false,
  },
  WORKSPACE_INVALID: {
    cause: "路徑格式不被接受（非絕對路徑或格式錯誤）。",
    nextStep: "提供允許根目錄內的絕對路徑。",
    retryable: false,
  },

  // --- Files ---
  FILE_NOT_FOUND: {
    // One message for missing / denied / outside-root, so the response cannot be used
    // to probe what exists (ADR 0014). The UI keeps that conflation.
    cause: "此檔案不存在，或無法透過此 workspace 存取。",
    nextStep: "重新整理檔案樹。",
    retryable: false,
  },
  FILE_INVALID_PATH: {
    cause: "路徑格式錯誤，或試圖離開 workspace 範圍。",
    nextStep: "請從檔案樹選取，而不要手動輸入路徑。",
    retryable: false,
  },
  FILE_PERMISSION_DENIED: {
    cause: "Daemon 的執行使用者無法讀取此檔案。",
    nextStep: "授予該使用者讀取權限。",
    retryable: false,
  },
  FILE_DENIED: {
    cause: "此檔案符合該 Node 的敏感檔政策，內容完全未被讀取。",
    nextStep: "無法透過瀏覽器取得內容，此為刻意設計。",
    retryable: false,
  },
  FILE_TOO_LARGE: {
    cause: "檔案超過預覽上限（預設 2 MiB）。",
    nextStep: "請在該機器上開啟。",
    retryable: false,
  },
  FILE_BINARY: {
    cause: "內容為二進位，沒有可呈現的文字。",
    nextStep: "無需處理。",
    retryable: false,
  },

  // --- 圖片投放（ADR 0024）---
  FILE_UPLOAD_TOO_LARGE: {
    cause: "圖片超過 4 MiB 上限。",
    nextStep: "請壓縮或縮小尺寸後再試。",
    retryable: false,
  },
  FILE_UPLOAD_UNSUPPORTED_TYPE: {
    cause:
      "內容不是 PNG、JPEG、GIF 或 WebP；判定依據是檔案內容，不是宣告的型別。",
    nextStep: "請轉存為支援的圖片格式（SVG 與 PDF 不算圖片）。",
    retryable: false,
  },
  FILE_UPLOAD_QUOTA_EXCEEDED: {
    cause: "此 Session 的上傳用量或當日檔數已達上限。",
    // This used to say "delete them in the file tree", which has never been
    // possible — there is no delete affordance, and ADR 0026 deliberately did not
    // add one. Pointing at the terminal is the only honest advice.
    nextStep:
      "請在該 Node 上以終端機清理 .cliora/uploads/ 內不需要的圖片；逾期 7 天者會自動清除。",
    retryable: false,
  },
  FILE_UPLOAD_FAILED: {
    cause: "Node 無法寫入工作區（磁碟、權限，或 .cliora 不是目錄）。",
    nextStep: "請通知管理者在該機器上執行 agentd doctor，它會指出要修的檔案。",
    retryable: true,
  },
  FILE_UPLOAD_DISABLED: {
    cause: "此 Node 的設定關閉了上傳。工作區是否可被寫入由該機器決定。",
    nextStep:
      "請與該 Node 的擁有者確認 filesystem.upload.enabled 或 filesystem.upload.files.enabled 設定。",
    retryable: false,
  },

  // --- General file upload (ADR 0026) ---
  FILE_EXISTS: {
    cause:
      "該目錄裡已經有同名的檔案或資料夾。上傳永不覆寫既有項目，所以這是拒絕而不是失敗。",
    nextStep:
      "請改一個名字再上傳；若本來就要取代它，請在該 Node 上以終端機處理。",
    retryable: false,
  },
  FILE_UPLOAD_NO_SPACE: {
    cause:
      "該 Node 的工作區磁碟可用空間低於下限。上傳的檔案屬於使用者，平台不會自動清除它們，所以沒有任何機制會自行釋放空間。",
    nextStep: "請通知管理者釋放空間；agentd doctor 會顯示它比對的數字。",
    retryable: true,
  },
  FILE_INVALID_NAME: {
    cause: "檔名必須是單一路徑片段：不含 /、不含控制字元、不超過 255 位元組。",
    nextStep: "請改名後再上傳。",
    retryable: false,
  },

  // --- Daemon update ---
  UPDATE_NOT_ALLOWED: {
    cause:
      "此版本未針對該架構發佈、為降級，或該 Daemon 沒有安裝所需的權限（它刻意以非 root 執行）。",
    nextStep:
      "在該機器上執行 sudo agentd update；詳見 update-failure runbook。",
    retryable: false,
  },
  UPDATE_DOWNLOAD_FAILED: {
    cause: "該 Node 無法取得 manifest 或安裝檔。",
    nextStep: "檢查該機器的網路連線後重試。",
    retryable: true,
  },
  UPDATE_CHECKSUM_MISMATCH: {
    cause: "下載到的位元組與已發佈的 checksum 不符；沒有安裝任何東西。",
    nextStep: "不要直接重試——視為安全事件並檢查 artifacts 目錄（見 runbook）。",
    retryable: false,
  },
  UPDATE_HEALTHCHECK_FAILED: {
    cause: "新版本啟動了但未通過自身檢查，因此已被回復。",
    nextStep: "該 Node 正執行舊版本。請附上 agentd doctor 輸出回報。",
    retryable: false,
  },
  UPDATE_ROLLED_BACK: {
    cause: "替換後的某個階段失敗，舊版 binary 已被還原。",
    nextStep: "沒有中斷服務。依 audit 中的 stage 判斷原因。",
    retryable: false,
  },
  UPDATE_IN_PROGRESS: {
    cause: "此 Node 已有一個更新在執行；同時只允許一個。",
    nextStep: "等待進行中的更新回報結果。",
    retryable: true,
  },
  // 埠轉發（ADR 0022）。流量不經過平台，因此這些狀態都是「連不上服務商」或
  // 「設定不允許」，而不是傳輸中的錯誤。
  SECRET_KEY_MISSING: {
    cause:
      "服務商憑證只能加密保存，而此部署未設定加密金鑰。" +
      "平台選擇拒絕而不是先存明文——已經寫下的明文無法收回。",
    nextStep: "請部署管理員設定 CLIORA_SECRET_ENCRYPTION_KEY，然後再啟用整合。",
    retryable: false,
  },
  TUNNEL_INTEGRATION_DISABLED: {
    cause:
      "此部署的埠轉發整合尚未啟用；啟用的同時也要指定它要用哪一個服務商帳號。",
    nextStep: "請管理員在「系統整合設定」啟用埠轉發，並填入服務商憑證。",
    retryable: false,
  },
  TUNNEL_NODE_DISABLED: {
    cause:
      "此 Node 未參與埠轉發：可能是平台側的 per-node 設定關閉，也可能是 Node 本機設定否決。" +
      "兩者的處置不同，因此錯誤訊息會指出是哪一層。",
    nextStep:
      "若是平台設定，可在此 Node 的埠轉發頁開啟；" +
      "若是本機否決，需由該 Node 的擁有者在該機器的 agentd 設定檔把 tunnel.enabled 改回來——平台無法覆寫。",
    retryable: false,
  },
  TUNNEL_PROVIDER_NOT_CONFIGURED: {
    cause:
      "此 Node 尚不具備埠轉發的先決條件：ssh 用戶端、對外連線或已釘選的主機金鑰。",
    nextStep: "在該 Node 執行 `agentd doctor`，它會指出缺少哪一項。",
    retryable: false,
  },
  TUNNEL_PROVIDER_UNAVAILABLE: {
    cause:
      "Node 無法建立到隧道服務商的對外連線；這通常是網路路徑問題，而不是平台故障。",
    nextStep: "稍後重試；若持續發生，確認該 Node 可連線到服務商的 443 埠。",
    retryable: true,
  },
  TUNNEL_PROVIDER_UNAUTHORIZED: {
    cause:
      "服務商不接受已儲存的憑證。它的回應方式是靜默降級為匿名、有時限的隧道，" +
      "因此平台選擇中止而不是把它當成你要的那一條交出去。",
    nextStep: "請管理員在「整合設定」更新服務商憑證。",
    retryable: false,
  },
  TUNNEL_PROVIDER_UNTRUSTED: {
    cause:
      "服務商出示的主機金鑰與 Node 上釘選的不符，連線已中止。" +
      "這既是對外連線被攔截的樣子，也是服務商正常輪替金鑰的樣子。",
    nextStep: "請聯繫管理員。不要以停用金鑰驗證的方式繞過。",
    retryable: false,
  },
  TUNNEL_PORT_NOT_ALLOWED: {
    cause:
      "1024 以下的 port 一律不轉發，而此 Node 的允許範圍可能更窄；" +
      "平台、Node 與本機設定取最窄的那一個。",
    nextStep: "改用 1024 以上、且在此 Node 埠轉發頁所顯示範圍內的 port。",
    retryable: false,
  },
  TUNNEL_LIMIT_REACHED: {
    cause:
      "三個上限之一已滿：平台的整體併發預算、此 Node 的上限，或你自己的上限。",
    nextStep: "關閉不再需要的隧道，或請管理員把預算調整為與服務商方案一致。",
    retryable: false,
  },
  // 卡片產物（ADR 0030 Part B）。三個配額碼各自要說清楚是哪一層滿了——
  // 出口條件明寫「不是靜默失敗」：一個附不上產物的 Agent 必須能在卡片上說出來。
  ARTIFACT_TOO_LARGE: {
    cause: "單一產物不得超過此部署的單件上限。",
    nextStep: "拆開、壓縮，或附一份摘要並把完整輸出放在別處。",
    retryable: false,
  },
  ARTIFACT_RUN_LIMIT: {
    cause:
      "單次執行可附加的件數有上限，這樣一個迴圈就不會把整個專案的配額吃光。",
    nextStep: "把多個檔案合併成一件再附加。",
    retryable: false,
  },
  ARTIFACT_PROJECT_QUOTA: {
    cause:
      "產物跟著卡片走、不會被定時刪除，所以一個專案會一直累積到有人決定刪哪些。",
    nextStep:
      "刪掉不再需要的產物——刪除會真的釋放空間，而「誰以什麼理由刪的」仍然留著。",
    retryable: false,
  },
  ARTIFACT_DIGEST_MISMATCH: {
    cause:
      "這不是防竄改（連線本來就是 TLS），而是防截斷：一個被中途砍斷的上傳應該失敗，而不是變成一件打不開的產物。",
    nextStep: "重新上傳一次。",
    retryable: true,
  },
  ARTIFACT_DELETED: {
    cause: "它的內容已經被刪除；而「誰以什麼理由刪的」是刻意留著的。",
    nextStep: "卡片上那一列旁邊寫著理由。",
    retryable: false,
  },
  RUN_TOKEN_TTL_EXCEEDED: {
    cause:
      "一枚 run 憑證的效期不得超過此部署對「Agent 憑證最長活多久」的既有承諾。" +
      "牆鐘從 1 小時放大到 6 小時之後這個上限開始會咬到，所以在這裡拒絕，而不是發一枚會在 run 中途過期的 token。",
    nextStep: "調低 run 的逾時，或調高 CLIORA_RUN_TOKEN_TTL_HOURS。",
    retryable: false,
  },
  // Agent Runner（ADR 0029）。這一組全部發生在「派工」那一刻，而它們的順序是設計的一
  // 部分：先擋卡片本身的問題，再擋本期做不到的宣告，最後才是設定與 Agent。
  TASK_NOT_READY: {
    cause:
      "只有在「就緒」車道的卡片可以派給 Agent。派工是一個執行動作，而還沒進就緒的卡片代表還沒有人同意要動工。",
    nextStep: "先把卡片移到「就緒」。",
    retryable: false,
  },
  RUN_ALREADY_ACTIVE: {
    cause:
      "一張卡同時只會有一次執行。兩個 Agent 同時改同一份工作，沒有辦法合併結果。",
    nextStep: "等這次執行結束，或先取消它。",
    retryable: false,
  },
  RUN_NOT_ACTIVE: {
    cause: "取消只對排隊中或執行中的 run 有意義。",
    nextStep: "看一下這次執行的結果；若要重做，重新派工一次。",
    retryable: false,
  },
  // V2.3 取代了 TASK_REQUIRES_SECRETS：機密存在了，所以拒絕的理由變成關於**這張卡**，
  // 而不是關於版本。兩個碼，因為它們在不同的頁面上修（ADR 0032 §0）。
  TASK_SECRETS_NOT_ALLOWED: {
    cause:
      "卡片只能宣告專案允許清單裡的名稱。允許清單是**意圖**（這個專案的卡片可以要求哪些名稱），" +
      "刻意不從實際存在的機密推導——否則刪掉一枚機密會悄悄讓一批卡片不能派工。",
    nextStep: "把名稱加進專案的允許清單，或修正卡片；回應會指名是哪幾個。",
    retryable: false,
  },
  TASK_SECRETS_MISSING: {
    cause:
      "名稱是允許的，但底下還沒有機密——最常見的原因是它被刪掉了。照樣執行等於讓卡片在" +
      "**沒有它宣告的值**的情況下跑，而那看起來會像 Agent 壞掉。",
    nextStep: "到專案設定建立那枚機密，或移除卡片上的宣告。",
    retryable: false,
  },
  TASK_BRANCH_NOT_DELIVERABLE: {
    cause:
      "平台只會推 `cliora/<卡號>-<次數>` 命名空間內的分支，所以一張接續其他分支的卡片" +
      "永遠交付不了。在派工當下拒絕，而不是等 run 做完工作才在推送時失敗。",
    nextStep: "把交付方式改成「附成產物」，或接續一條平台自己建立的分支。",
    retryable: false,
  },
  AGENT_TAG_MISMATCH: {
    cause:
      "**指定不會創造資格。** 會指定某台機器，通常正是因為只有它有卡片需要的東西；" +
      "讓指定覆蓋 tag，等於在一台沒有 docker 的機器上跑一張要 docker 的卡，然後在第三分鐘失敗。",
    nextStep:
      "回應會指名缺哪幾個 tag：換一台 Agent，或在那個 node 的設定檔裡加上它們。",
    retryable: false,
  },
  AGENT_REFUSES_UNTAGGED: {
    cause:
      "那台機器被保留給有宣告 tag 的工作（`run_untagged: false`）。沒有這個設定，" +
      "一台專機仍會被一堆普通卡片佔滿。",
    nextStep: "給卡片加上那台機器具備的 tag，或派給另一台 Agent。",
    retryable: false,
  },
  AGENT_REFUSES_SECRETS: {
    cause:
      "那個 node 的擁有者宣告了不收機密（`accept_secrets: false`），那是營運者對" +
      "「哪些機器可以持有憑證」的否決權（ADR 0032 §0）。",
    nextStep: "派給一台收機密的 Agent，或移除卡片上的機密宣告。",
    retryable: false,
  },
  SECRET_NAME_INVALID: {
    cause: "機密的名稱會變成一個環境變數，所以必須是大寫字母、數字與底線。",
    nextStep: "改成像 GITHUB_TOKEN 這樣的名稱。",
    retryable: false,
  },
  SECRET_NAME_RESERVED: {
    cause:
      "PATH、HOME 這類名稱與 GIT_／SSH_／CLIORA_ 前綴是保留的。一枚叫 GIT_ASKPASS 的機密" +
      "會直接接管平台自己那條 git 憑證路徑所依賴的機制。",
    nextStep: "換一個不在保留集合裡的名稱。",
    retryable: false,
  },
  SECRET_KIND_INVALID: {
    cause:
      "機密的類型決定它的值在 node 上會去哪裡，所以它是一個封閉集合（ADR 0032 §4）。",
    nextStep: "使用 env、git_pat、git_ssh_key 或 provider_token。",
    retryable: false,
  },
  SECRET_EXISTS: {
    cause: "同一個專案裡，尚未刪除的機密名稱是唯一的。",
    nextStep: "改用「輪替」覆寫既有的那一枚，而不是建立第二枚。",
    retryable: false,
  },
  SECRET_IN_USE: {
    cause:
      "有一個已登記的 repository 用這枚機密認證。刪掉它會讓那個 repository 指向一枚" +
      "不存在的憑證，而失敗會在 run 跑到一半才出現。",
    nextStep: "先把那個 repository 指向別的憑證；回應會指名是哪一個。",
    retryable: false,
  },
  SECRET_TOO_LARGE: {
    cause:
      "上限是 8 KiB，也就是實測過最大的合法輸入（RSA-4096 私鑰 3 369 bytes）的 2.4 倍。" +
      "八枚機密還要一起塞進一個 64 KiB 的派工訊框，旁邊還有情境包。",
    nextStep: "ed25519 私鑰只要 399 bytes，做的是同一件事。",
    retryable: false,
  },
  GIT_SECRET_DELIVERY_DISABLED: {
    cause:
      "**預設關閉**（2026-08-13 裁決）：現階段 git 認證由 node 的擁有者自行配置，平台不管理。" +
      "存下一枚永遠不會被下放的憑證，是一個看起來設定完成而其實沒有的狀態。",
    nextStep:
      "在 node 上配置 git 認證，或在 Central 設定 CLIORA_GIT_SECRET_DELIVERY_ENABLED。",
    retryable: false,
  },
  TASK_DELIVERY_UNSUPPORTED: {
    cause:
      "本階段的交付方式是把產物附加到卡片上；分支與 PR 要等平台自己的 git 寫入路徑。",
    nextStep:
      "先把交付方式設成「不交付」或「附成產物」；回應會指名宣告的模式從哪一版開始生效。",
    retryable: false,
  },
  PROJECT_NO_REPOSITORY: {
    cause:
      "Agent 會自己把程式碼拉下來，所以平台必須知道程式碼在哪裡。這不是卡片上的欄位能回答的——它是專案設定。",
    nextStep:
      "到專案設定登記 repository 之後再派工一次；回應帶著那一頁的連結。",
    retryable: false,
  },
  REPOSITORY_HOST_NOT_ALLOWED: {
    cause:
      "有兩份允許清單：這個部署的，以及每一台 Node 的。這是部署的那一份，而它在管理員設定之前是空的。",
    nextStep: "請管理員把該 host 加進 CLIORA_GIT_ALLOWED_HOSTS。",
    retryable: false,
  },
  REPOSITORY_EXISTS: {
    cause: "一個專案可以登記多個 repository，但同一個不能登記兩次。",
    nextStep: "直接用既有的那一筆；若要改分支，先移除再重新登記。",
    retryable: false,
  },
  AGENT_DISABLED: {
    cause:
      "卡片指定了一個被停用的 Agent。這在派工當下就擋下而不是排進佇列，因為「被停用」是有人做的決定，" +
      "不是一台等一下會回來的機器。",
    nextStep: "啟用那個 Agent，或不指定 Agent 直接派工。",
    retryable: false,
  },
  // 從 node 送回來的那一組。它們會經由 relay 到達畫面，所以每一個都要有指引。
  AGENT_RUNS_DISABLED: {
    cause:
      "有一台 daemon 想註冊成 Runner，但這個部署把 Agent 執行關掉了。該 node 的互動式 Session 不受影響。",
    nextStep: "若這個部署要提供無人值守執行，請在 Central 打開該旗標。",
    retryable: false,
  },
  RUNNER_NOT_REGISTERED: {
    cause:
      "poll 在 register 之前抵達——通常是 daemon 剛重連、還沒重新宣告自己。",
    nextStep: "不需要處理；daemon 在下一次連線時會註冊並繼續 poll。",
    retryable: true,
  },
  RUNNER_DISABLED: {
    cause: "管理員把它停用了，所以即使它的 node 在線上，它仍然不會被派工。",
    nextStep: "在 Agents 頁把它啟用。",
    retryable: false,
  },
  RUN_NOT_FOUND: {
    cause:
      "這個 run id 在平台上不存在——通常是一個延遲或重複的訊框，而那個 run 已經被回收了。",
    nextStep: "不需要處理；租約逾時之後這是正常現象。",
    retryable: false,
  },
  RUN_INVALID_STATE: {
    cause: "對一個已經進入終態的 run 送了續租或進度回報。",
    nextStep: "不需要處理；node 發現那個 run 不在之後就會停止回報。",
    retryable: false,
  },
  RUN_SOURCE_UNAVAILABLE: {
    cause:
      "三件事之一：那台機器沒有該 repository 的憑證、host 不在該 node 的允許清單內，或 ref 不存在。" +
      "details 會指名是哪一種——而且**永遠不會回顯 URL**，因為有人可能把憑證貼進去了。",
    nextStep:
      "看 details：在那台機器上補憑證、把 host 加進該 node 的允許清單，或修正卡片上的分支。",
    retryable: false,
  },
  RUN_DISK_QUOTA: {
    cause:
      "單次執行的目錄或該 node 的總量超過配額。配額存在的理由很具體：一個失控的建置會把磁碟塞滿，" +
      "而那會連互動式 Session 一起拖下去。",
    nextStep:
      "等清理迴圈，或在那台 node 上調高 runner.run_quota_bytes——如果那份工作真的需要更多。",
    retryable: false,
  },
  RUN_IDLE_TIMEOUT: {
    cause:
      "存活判定看的是執行環境的事件流而不是牆鐘。在閒置上限內沒有任何事件抵達，所以這次執行被中止了。",
    nextStep:
      "看 run log 的最後幾筆；若那份工作合理地會安靜更久，調高 runner.idle_timeout_seconds。",
    retryable: false,
  },
  RUN_TIMEOUT: {
    cause:
      "這是兜底而不是存活判定：這次執行一直有在吐事件，只是沒能在時限內做完。",
    nextStep: "把卡片拆小，或調高這個部署的 run 牆鐘上限。",
    retryable: false,
  },
  RUN_RUNTIME_UNAVAILABLE: {
    cause: "那支 CLI 沒裝、不可執行，或版本太舊而沒有帶事件流的非互動介面。",
    nextStep: "在那台機器上安裝或更新 CLI，並讓 daemon 重新註冊。",
    retryable: false,
  },
  RUN_CANCELLED: {
    cause: "有人按了取消，或那台 node 正在關機。",
    nextStep: "準備好之後重新派工一次。",
    retryable: false,
  },
  RUN_INTERNAL_ERROR: {
    cause:
      "daemon 的執行路徑裡出了問題。細節只在那台 node 的 log 裡，連同 request id。",
    nextStep: "重試；若持續發生，收集那個 run id 前後的 daemon log。",
    retryable: true,
  },
  AGENT_RUNTIME_MISMATCH: {
    cause:
      "被指定的 Node 沒有回報這張卡需要的執行環境——常見原因是那支 CLI 有裝但版本太舊，偵測不到非互動介面。",
    nextStep: "改指定別的 Agent，或更新那台機器上的 CLI 並讓它重新註冊。",
    retryable: false,
  },
};

// A code with no entry still gets guidance rather than a blank panel: an unknown code
// most likely comes from a newer server, and "report it" is the honest next step.
const UNKNOWN_GUIDANCE: ErrorGuidance = {
  cause: "伺服器回報了此用戶端尚不認識的錯誤代碼。",
  nextStep: "請回報這個代碼與 request_id。",
  retryable: true,
};

export function errorGuidance(code: string | undefined): ErrorGuidance {
  return (code && GUIDANCE[code]) || UNKNOWN_GUIDANCE;
}

export function knownErrorCodes(): string[] {
  return Object.keys(GUIDANCE).sort();
}
