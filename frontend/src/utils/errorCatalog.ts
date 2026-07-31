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
    cause: "此 Session 已經開著一個系統終端機（每個 Session 同時只能有一個）。",
    nextStep:
      "回到持有它的分頁，或關閉後再重新開啟；閒置一段時間後也會自動回收。",
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
