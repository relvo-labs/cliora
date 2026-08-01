package runtime

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/cliora/cliora/daemon/internal/config"
)

// TestOnlyCodexHasLaunchFlags is the guard on the table growing. Every argument the
// daemon can add to a session's argv comes from launch.go, so "who else got flags?"
// has to be answerable by a test rather than by reading a diff (ADR 0023 §2.4).
func TestOnlyCodexHasLaunchFlags(t *testing.T) {
	for id := range config.AllowedRuntimeIDs {
		args := SandboxBypassArgs(id)
		if id == "codex" {
			if len(args) != 1 || args[0] != SandboxBypassFlag {
				t.Errorf("codex flags = %v, want exactly [%s]", args, SandboxBypassFlag)
			}
			continue
		}
		if len(args) != 0 {
			t.Errorf("runtime %q has launch flags %v; only codex may have any", id, args)
		}
	}
}

// The config package refuses sandbox_bypass on a runtime the daemon cannot bypass.
// If the two lists drift, a node could set a key that silently does nothing (or be
// refused a key that would have worked).
func TestSandboxBypassRuntimeListsAgree(t *testing.T) {
	for id := range config.SandboxBypassRuntimeIDs {
		if !SupportsSandboxBypass(id) {
			t.Errorf("config accepts sandbox_bypass for %q but there are no flags for it", id)
		}
	}
	for id := range config.AllowedRuntimeIDs {
		if SupportsSandboxBypass(id) && !config.SandboxBypassRuntimeIDs[id] {
			t.Errorf("runtime %q has bypass flags but config would reject the key", id)
		}
	}
}

func TestSandboxBypassArgsCannotBeMutatedThroughTheReturnedSlice(t *testing.T) {
	got := SandboxBypassArgs("codex")
	got[0] = "--something-else"
	if SandboxBypassArgs("codex")[0] != SandboxBypassFlag {
		t.Fatal("the flag table was mutated through a returned slice")
	}
}

// fakeCLI writes a script that answers --version and, optionally, lists the bypass
// flag in --help. That is the only observable the daemon has for "does this build
// accept the flag" (ADR 0023 D3).
func fakeCLI(t *testing.T, name string, listsFlag bool) (dir, path string) {
	t.Helper()
	dir = t.TempDir()
	path = filepath.Join(dir, name)
	help := "usage: " + name + "\n  --help\n"
	if listsFlag {
		help = "usage: " + name + "\n  " + SandboxBypassFlag + "  skip everything\n"
	}
	script := "#!/bin/sh\ncase \"$1\" in\n--version) echo '" + name + " 9.9.9';;\n--help) cat <<'EOF'\n" +
		help + "EOF\n;;\nesac\n"
	if err := os.WriteFile(path, []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	return dir, path
}

func withPath(t *testing.T, dir string) {
	t.Helper()
	old := os.Getenv("PATH")
	t.Setenv("PATH", dir+string(os.PathListSeparator)+old)
}

func TestResolveLaunchAddsTheFlagByDefault(t *testing.T) {
	dir, _ := fakeCLI(t, "codex", true)
	withPath(t, dir)
	// No sandbox_bypass key at all: absent means enabled (ADR 0023 D2).
	reg := NewRegistry(map[string]config.RuntimeConfig{"codex": {Enabled: true, Binary: "codex"}})
	spec, err := reg.ResolveLaunch("codex")
	if err != nil {
		t.Fatalf("ResolveLaunch: %v", err)
	}
	if len(spec.Args) != 1 || spec.Args[0] != SandboxBypassFlag {
		t.Errorf("args = %v, want [%s]", spec.Args, SandboxBypassFlag)
	}
	if !strings.HasSuffix(spec.Path, "codex") {
		t.Errorf("path = %q", spec.Path)
	}
}

func TestResolveLaunchOmitsTheFlagWhenTheNodeSaysNo(t *testing.T) {
	dir, _ := fakeCLI(t, "codex", true)
	withPath(t, dir)
	disabled := false
	reg := NewRegistry(map[string]config.RuntimeConfig{
		"codex": {Enabled: true, Binary: "codex", SandboxBypass: &disabled},
	})
	spec, err := reg.ResolveLaunch("codex")
	if err != nil {
		t.Fatalf("ResolveLaunch: %v", err)
	}
	if len(spec.Args) != 0 {
		t.Errorf("args = %v, want none: the node vetoed the bypass", spec.Args)
	}
}

// The console must not claim a posture the machine is not in: a CLI that does not
// know the flag is launched without it and reported as enforced (ADR 0023 D3).
func TestUnsupportedFlagIsReportedNotAssumed(t *testing.T) {
	dir, _ := fakeCLI(t, "codex", false)
	withPath(t, dir)
	reg := NewRegistry(map[string]config.RuntimeConfig{"codex": {Enabled: true, Binary: "codex"}})
	spec, err := reg.ResolveLaunch("codex")
	if err != nil {
		t.Fatalf("ResolveLaunch: %v", err)
	}
	if len(spec.Args) != 0 {
		t.Errorf("args = %v, want none: this build does not accept the flag", spec.Args)
	}
	result := reg.DetectAll(context.Background(), time.Now())
	var codex DetectResult
	for _, r := range result {
		if r.Runtime == "codex" {
			codex = r
		}
	}
	if !codex.Available {
		t.Error("an unsupported flag must not make the runtime unavailable")
	}
	if !codex.SandboxBypassRequested {
		t.Error("SandboxBypassRequested should record what the config asked for")
	}
	if codex.SandboxBypass {
		t.Error("SandboxBypass must report the measured outcome, not the request")
	}
	if codex.SandboxNote != ReasonSandboxFlagUnsupported {
		t.Errorf("SandboxNote = %q, want %q", codex.SandboxNote, ReasonSandboxFlagUnsupported)
	}
	if codex.Reason != "" {
		t.Errorf("Reason = %q; it explains an unusable runtime and this one launches fine",
			codex.Reason)
	}
}

func TestDetectReportsBypassForAWorkingBuild(t *testing.T) {
	dir, _ := fakeCLI(t, "codex", true)
	withPath(t, dir)
	reg := NewRegistry(map[string]config.RuntimeConfig{"codex": {Enabled: true, Binary: "codex"}})
	for _, r := range reg.DetectAll(context.Background(), time.Now()) {
		if r.Runtime != "codex" {
			if r.SandboxBypass || r.SandboxBypassRequested {
				t.Errorf("%s reports a sandbox posture it cannot have", r.Runtime)
			}
			continue
		}
		if !r.SandboxBypass || r.SandboxNote != "" {
			t.Errorf("codex = %+v, want bypassed with no note", r)
		}
	}
}

// A --help that never returns must not be able to stall a session launch. Same
// bound and the same WaitDelay reasoning as version detection.
func TestFlagProbeDoesNotHang(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "codex")
	if err := os.WriteFile(path, []byte("#!/bin/sh\nsleep 30\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	withPath(t, dir)
	reg := NewRegistry(map[string]config.RuntimeConfig{"codex": {Enabled: true, Binary: "codex"}})
	rt, _ := reg.Get("codex")
	cli := rt.(*cliRuntime)
	cli.timeout = 200 * time.Millisecond
	done := make(chan []string, 1)
	go func() { done <- cli.LaunchArgs() }()
	select {
	case args := <-done:
		if len(args) != 0 {
			t.Errorf("args = %v, want none when the probe times out", args)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("LaunchArgs blocked on a hung --help")
	}
}

func TestBuildCommandCarriesTheSameArgsAsResolveLaunch(t *testing.T) {
	dir, _ := fakeCLI(t, "codex", true)
	withPath(t, dir)
	reg := NewRegistry(map[string]config.RuntimeConfig{"codex": {Enabled: true, Binary: "codex"}})
	rt, _ := reg.Get("codex")
	cmd := rt.BuildCommand(StartOptions{Workspace: dir})
	if len(cmd.Args) != 2 || cmd.Args[1] != SandboxBypassFlag {
		t.Errorf("BuildCommand argv = %v; it must agree with the launch path", cmd.Args)
	}
}
