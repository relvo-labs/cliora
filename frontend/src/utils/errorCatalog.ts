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
