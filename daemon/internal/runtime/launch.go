package runtime

// SandboxBypassFlag disables codex's approval prompt and its OS sandbox in one
// switch. It is spelled out here, once, so that a security review can read the
// complete set of arguments the daemon may add to a launch in a single file.
//
// Cliora nodes are disposable isolated VMs (ADR 0023): the posture this flag
// creates is the requested default, not an accident. A machine that is not
// disposable installs with --no-privileged-terminal and sets
// runtime.codex.sandbox_bypass: false.
const SandboxBypassFlag = "--dangerously-bypass-approvals-and-sandbox"

// sandboxBypassArgs is the complete, closed table of arguments the daemon adds to
// a runtime's argv. It is a compile-time constant on purpose:
//
//   - config.RuntimeConfig has no argv field, and the node's control over this is
//     a single boolean (config.RuntimeConfig.SandboxBypass);
//   - session.start carries no command, args, flags, env or entrypoint field, and
//     `additionalProperties: false` keeps it that way (ADR 0021 §1, ADR 0023 §2.4).
//
// So there is exactly one place a launch argument can come from, and it is this
// map. Adding a caller-supplied string to it — from a config field, a wire field
// or an environment variable — is the change SEC-002 exists to prevent.
var sandboxBypassArgs = map[string][]string{
	"codex": {SandboxBypassFlag},
}

// SandboxBypassArgs returns the flags that disable the sandbox for a runtime, or
// nil when the runtime has no such flags. The slice is copied so a caller cannot
// mutate the table.
func SandboxBypassArgs(id string) []string {
	args := sandboxBypassArgs[id]
	if len(args) == 0 {
		return nil
	}
	return append([]string(nil), args...)
}

// SupportsSandboxBypass reports whether the daemon knows how to disable a
// runtime's sandbox at all. It answers a different question from
// cliRuntime.bypassAvailable, which is about the installed binary accepting the
// flag (ADR 0023 D3).
func SupportsSandboxBypass(id string) bool {
	return len(sandboxBypassArgs[id]) > 0
}
