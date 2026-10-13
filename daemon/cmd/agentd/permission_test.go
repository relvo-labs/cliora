package main

import (
	"bytes"
	"strings"
	"testing"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/cliora/cliora/daemon/internal/runtime"
)

func TestDoctorCodexPermissionPosture(t *testing.T) {
	for _, tc := range []struct {
		mode    config.PermissionMode
		applied bool
		note    string
		want    []string
	}{
		{config.PermissionAuto, true, "", []string{"[info]", "permission=auto", "sandbox=enforced", "flag_applied=true"}},
		{config.PermissionCLIDefault, false, "", []string{"[info]", "permission=cli_default", "flag_applied=false", "sandbox=enforced"}},
		{config.PermissionFullAccess, true, "", []string{"permission=full_access", "sandbox=bypassed"}},
		{config.PermissionAuto, false, runtime.ReasonSandboxFlagUnsupported, []string{"[warn]", runtime.AutoPermissionFlag, "launching without a flag", "effective_permission=cli_default"}},
		{config.PermissionFullAccess, false, runtime.ReasonSandboxFlagUnsupported, []string{"[warn]", runtime.SandboxBypassFlag, "sandbox=enforced", "launching without a flag"}},
	} {
		var out bytes.Buffer
		effective := config.PermissionCLIDefault
		if tc.applied {
			effective = tc.mode
		}
		reportSandboxPosture(&out, runtime.DetectResult{
			Runtime: "codex", PermissionMode: tc.mode, EffectivePermissionMode: effective,
			PermissionSource: "config", FlagApplied: tc.applied, SandboxNote: tc.note,
			SandboxBypass: tc.applied && tc.mode == config.PermissionFullAccess,
		})
		for _, want := range tc.want {
			if !strings.Contains(out.String(), want) {
				t.Errorf("%s output missing %q: %s", tc.mode, want, &out)
			}
		}
	}
}
