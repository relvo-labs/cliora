package connection

import (
	"testing"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/cliora/cliora/daemon/internal/runtime"
)

func TestRuntimeItemsReportMeasuredCodexSandbox(t *testing.T) {
	for _, mode := range []config.PermissionMode{config.PermissionAuto, config.PermissionCLIDefault, config.PermissionFullAccess} {
		for _, applied := range []bool{false, true} {
			bypass := mode == config.PermissionFullAccess && applied
			items := runtimeItems([]runtime.DetectResult{{Runtime: "codex", PermissionMode: mode, FlagApplied: applied, SandboxBypass: bypass}})
			if got, ok := items[0]["sandbox_bypass"]; !ok || got != bypass {
				t.Fatalf("wire posture: %v", items)
			}
			for _, key := range []string{"permission_mode", "permission_source", "flag_applied"} {
				if _, ok := items[0][key]; ok {
					t.Fatalf("local diagnostic %s leaked onto wire", key)
				}
			}
		}
	}
	for _, id := range []string{"claude", "shell"} {
		items := runtimeItems([]runtime.DetectResult{{Runtime: id}})
		if _, ok := items[0]["sandbox_bypass"]; ok {
			t.Fatalf("%s unexpectedly reports sandbox", id)
		}
	}
}
