// This file is deliberately an **external** test package: it is the only place where
// the two halves of the run's credential handshake meet in one process. The daemon
// writes `.cliora/context/{task.md,run.token}` (`WriteContext`) and the `cliora` CLI
// reads it back by walking up from `repo/` (`cli.FindContext`). Both sides had their
// own passing unit tests while disagreeing about the token's filename, and the seam
// between them is exactly what no test covered — so a staging run spent its whole
// life printing "無法連線到 Cliora" at a platform that was answering the daemon fine,
// and finished `RUN_DELIVERY_INCOMPLETE` because nothing could be attached.
//
// **It lives under `internal/cli/` rather than `internal/runner/`, and the reason is
// a promise rather than a preference**: `GATE-CV-TOUCH-LIST` asserts that V2-C1 leaves
// the daemon's node half with a zero-byte diff, and `internal/runner/` is on its list.
// A test file would have been an honest addition and a red gate — and a gate that a
// true statement turns red gets discharged by deleting the statement. The seam is
// symmetric, so the side that may be touched is the side that hosts the test; it
// imports `runner` to write the pack exactly as the daemon does.
package cli_test

import (
	"os"
	"testing"

	"github.com/cliora/cliora/daemon/internal/cli"
	"github.com/cliora/cliora/daemon/internal/runner"
)

func TestTheCLIFindsTheCredentialTheDaemonWrote(t *testing.T) {
	root := t.TempDir()
	layout := runner.NewLayout(root, "9f3c1a20-4e7b-4c11-9a55-0123456789ab")
	if err := os.MkdirAll(layout.Repo, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := runner.WriteContext(layout,
		"# TASK-1 一張卡\n`cliora context show` 讀本機檔案。API：http://127.0.0.1:8000\n",
		"cliora_rt_example"); err != nil {
		t.Fatal(err)
	}

	// From the checkout, which is where the agent's process actually stands.
	ctx, err := cli.FindContext(layout.Repo, "")
	if err != nil {
		t.Fatalf("the run's checkout could not find its own context: %v", err)
	}
	if ctx.Token != "cliora_rt_example" {
		t.Fatalf("token = %q; with an empty one every `cliora` call reports the "+
			"platform as unreachable and the run delivers nothing", ctx.Token)
	}
	if ctx.APIBase != "http://127.0.0.1:8000" {
		t.Fatalf("api base = %q", ctx.APIBase)
	}
	if !ctx.Run {
		t.Fatal("a context whose credential came from run.token is a run's context")
	}
}

// The other half of the promise: the token is gone when the run ends, and the CLI's
// answer to that must be "no credential", not a false report of an outage.
func TestAfterTheRunEndsThereIsNoCredential(t *testing.T) {
	root := t.TempDir()
	layout := runner.NewLayout(root, "9f3c1a20-4e7b-4c11-9a55-0123456789ab")
	if err := os.MkdirAll(layout.Repo, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := runner.WriteContext(layout, "# TASK-1\nAPI：http://127.0.0.1:8000\n",
		"cliora_rt_example"); err != nil {
		t.Fatal(err)
	}
	if err := runner.DropToken(layout); err != nil {
		t.Fatal(err)
	}
	ctx, err := cli.FindContext(layout.Repo, "")
	if err != nil {
		t.Fatalf("find: %v", err)
	}
	if ctx.Token != "" {
		t.Fatalf("the dropped credential is still readable: %q", ctx.Token)
	}
	_, code, postErr := cli.NewClient(ctx).PostMessage("hi", "note", "")
	if code != cli.ExitUnreachable {
		t.Fatalf("exit code = %d", code)
	}
	if postErr == nil || postErr.Error() != cli.NoCredentialMessage {
		t.Fatalf("a missing credential was reported as something else: %v", postErr)
	}
}
