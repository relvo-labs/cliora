package tmux

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/google/uuid"
)

func TestRenderConfCarriesTheScrollFix(t *testing.T) {
	conf := RenderConf(7000)
	for _, want := range []string{
		"set -g mouse on",
		"set -g history-limit 7000",
		"set -sg escape-time 10",
		"set -g status off",
	} {
		if !strings.Contains(conf, want) {
			t.Errorf("rendered conf missing %q:\n%s", want, conf)
		}
	}
	// The file is read on a machine by someone who did not write it, so it has to
	// explain why mouse mode is on — that option is the reason drag-select changed
	// behaviour, and "why did selection break" is the question it will be asked.
	if !strings.Contains(conf, "alternate screen") {
		t.Errorf("conf does not explain why mouse mode is on:\n%s", conf)
	}
}

func TestWriteConfIsAtomicAndPrivate(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "agentd")
	path, err := WriteConf(dir, 5000)
	if err != nil {
		t.Fatalf("WriteConf: %v", err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Errorf("mode = %o, want 600", info.Mode().Perm())
	}
	// Rewriting must leave exactly one file: a leftover temp file would eventually
	// be picked up by nothing, but it would also be a directory full of them.
	if _, err := WriteConf(dir, 9000); err != nil {
		t.Fatalf("rewrite: %v", err)
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 1 || entries[0].Name() != ConfigFileName {
		names := []string{}
		for _, e := range entries {
			names = append(names, e.Name())
		}
		t.Errorf("directory contains %v, want just %s", names, ConfigFileName)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(data), "history-limit 9000") {
		t.Error("rewrite did not replace the previous content")
	}
}

func TestResolveConfigDirPrefersTheSystemdRuntimeDirectory(t *testing.T) {
	t.Setenv("RUNTIME_DIRECTORY", "/run/agentd")
	t.Setenv("XDG_RUNTIME_DIR", "/run/user/1000")
	if got := ResolveConfigDir(); got != "/run/agentd" {
		t.Errorf("dir = %q, want /run/agentd", got)
	}
	// systemd may hand over a colon-separated list; the first entry is ours.
	t.Setenv("RUNTIME_DIRECTORY", "/run/agentd:/run/other")
	if got := ResolveConfigDir(); got != "/run/agentd" {
		t.Errorf("dir = %q, want the first entry of the list", got)
	}
	t.Setenv("RUNTIME_DIRECTORY", "")
	if got := ResolveConfigDir(); got != "/run/user/1000/agentd" {
		t.Errorf("dir = %q, want the XDG fallback", got)
	}
	t.Setenv("XDG_RUNTIME_DIR", "")
	if got := ResolveConfigDir(); !strings.Contains(got, "agentd-") {
		t.Errorf("dir = %q, want a per-uid temp fallback", got)
	}
}

func TestClientArgsCarrySocketAndConfigEverywhere(t *testing.T) {
	c := Client{Socket: DefaultSocket, ConfigPath: "/run/agentd/tmux.conf"}
	got := strings.Join(c.args("has-session", "-t", "x"), " ")
	want := "-L cliora -f /run/agentd/tmux.conf has-session -t x"
	if got != want {
		t.Errorf("args = %q, want %q", got, want)
	}
	// The attach path used to build its own argv, which is how a session could be
	// created on one server and attached on another.
	attach := strings.Join(c.AttachArgs("cliora-x"), " ")
	if !strings.HasPrefix(attach, "-L cliora -f /run/agentd/tmux.conf attach-session") {
		t.Errorf("AttachArgs = %q", attach)
	}
	// An unconfigured client (tests, dev) must stay exactly as it was.
	if got := strings.Join(Client{}.args("kill-server"), " "); got != "kill-server" {
		t.Errorf("bare client args = %q", got)
	}
}

func TestStartRejectsAnythingThatIsNotAFlag(t *testing.T) {
	c := Client{}
	base := StartSpec{
		SessionID: uuid.New(),
		RuntimeID: "codex",
		Workspace: "/tmp",
		Binary:    "/bin/true",
		Size:      Size{Rows: 24, Columns: 80},
	}
	for _, args := range [][]string{
		{"; rm -rf /"},
		{"--flag=value with space"},
		{"$(id)"},
		{"/etc/passwd"},
		{""},
		{"--ok", "&& curl evil"},
	} {
		spec := base
		spec.Args = args
		if err := c.Start(context.Background(), spec); err == nil {
			t.Errorf("Start accepted args %v", args)
		}
	}
}

func TestValidArgsAcceptsTheSandboxFlag(t *testing.T) {
	if !validArgs([]string{"--dangerously-bypass-approvals-and-sandbox"}) {
		t.Error("the one argument this feature exists to pass was rejected")
	}
}

func TestLegacySessionNamesOnlyMatchesOurSessions(t *testing.T) {
	// Nothing to assert about a machine we do not control except that the call is
	// safe and filters by the cliora- name pattern; a bare tmux with no server
	// returns nothing rather than erroring out.
	for _, name := range LegacySessionNames(context.Background()) {
		if !ValidName(name) {
			t.Errorf("returned %q, which is not a cliora session name", name)
		}
	}
}
