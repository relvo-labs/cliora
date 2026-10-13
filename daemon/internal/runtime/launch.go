package runtime

import "github.com/cliora/cliora/daemon/internal/config"

// AutoPermissionFlag keeps workspace-write and requests auto-reviewed approvals.
// SandboxBypassFlag disables approvals and the OS sandbox. It is reachable only
// through the node's explicit full_access choice (ADR 0030 amends ADR 0023 §1).
const AutoPermissionFlag = "--approve-for-me"
const SandboxBypassFlag = "--dangerously-bypass-approvals-and-sandbox"

// permissionArgs is the complete, closed table of arguments the daemon adds.
// Config selects an enum, never an argv string; session.start carries no command,
// args, flags, env or entrypoint (SEC-002, ADR 0021 §1, ADR 0023 §2.4).
var permissionArgs = map[string]map[config.PermissionMode][]string{
	"codex": {
		config.PermissionAuto:       {AutoPermissionFlag},
		config.PermissionFullAccess: {SandboxBypassFlag},
	},
}

// PermissionArgs returns a copy so a caller cannot mutate the daemon's table.
// cli_default and unknown choices add nothing; config.Validate rejects unknowns.
func PermissionArgs(id string, mode config.PermissionMode) []string {
	args := permissionArgs[id][mode]
	if len(args) == 0 {
		return nil
	}
	return append([]string(nil), args...)
}

func SupportsPermissionMode(id string) bool { return len(permissionArgs[id]) > 0 }
