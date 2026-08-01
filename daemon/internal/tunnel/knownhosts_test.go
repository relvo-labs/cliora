package tunnel

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// The keys have to actually be in the binary. Without this the embed directive can be
// deleted, or the file emptied, and every symptom shows up somewhere else: tunnels that
// refuse, a doctor that fails, an update that rolls back.
func TestTheBuildCarriesUsableHostKeys(t *testing.T) {
	if len(embeddedKnownHosts) == 0 {
		t.Fatal("no host keys are embedded in this build")
	}
	hosts := 0
	for _, line := range strings.Split(string(embeddedKnownHosts), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		if !strings.Contains(line, " ssh-") {
			t.Fatalf("not a known_hosts entry: %q", line)
		}
		hosts++
	}
	if hosts == 0 {
		t.Fatal("the embedded file has comments but no host key")
	}
}

func TestResolveUsesTheNodesFileWhenItIsUsable(t *testing.T) {
	path := writeKnownHosts(t)
	resolved, err := ResolveKnownHosts(path)
	if err != nil {
		t.Fatal(err)
	}
	if resolved.Path != path || resolved.Source != SourceFile || resolved.FromBuild() {
		t.Fatalf("expected the node's file, got %+v", resolved)
	}
}

func TestResolveFallsBackToTheBuildAndSaysSo(t *testing.T) {
	resolved, err := ResolveKnownHosts(filepath.Join(t.TempDir(), "absent"))
	if err != nil {
		t.Fatal(err)
	}
	if !resolved.FromBuild() {
		t.Fatalf("expected the embedded keys, got %+v", resolved)
	}
	content, err := os.ReadFile(resolved.Path)
	if err != nil {
		t.Fatal(err)
	}
	if string(content) != string(embeddedKnownHosts) {
		t.Fatal("the materialized file does not match the embedded keys")
	}
	// Public keys, but not a file another local user may swap between this write and
	// ssh reading it.
	info, err := os.Stat(resolved.Path)
	if err != nil {
		t.Fatal(err)
	}
	if perm := info.Mode().Perm(); perm&0o077 != 0 {
		t.Fatalf("materialized key file is %o, want no group/world access", perm)
	}
}

// A long-lived daemon outlives temp-file cleaners. Losing the materialized file must cost
// one rewrite, not every tunnel from then on.
func TestResolveRewritesAMaterializedFileThatWasSweptAway(t *testing.T) {
	first, err := ResolveKnownHosts("")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(first.Path); err != nil {
		t.Fatal(err)
	}
	second, err := ResolveKnownHosts("")
	if err != nil {
		t.Fatalf("a swept file must be rewritten, got %v", err)
	}
	if !knownHostsUsable(second.Path) {
		t.Fatalf("%s is not usable after the rewrite", second.Path)
	}
}
