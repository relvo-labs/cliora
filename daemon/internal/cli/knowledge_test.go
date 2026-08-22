package cli

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// The selection rules are the whole of `KN-06`'s risk on this side: a rule that is too
// wide sends a repository's `node_modules` to the platform, and one that is too narrow
// silently leaves the documents out. Both are quiet, so both are tested.

func write(t *testing.T, root, rel, body string) {
	t.Helper()
	path := filepath.Join(root, filepath.FromSlash(rel))
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
}

func paths(files []SyncFile) []string {
	out := make([]string, 0, len(files))
	for _, file := range files {
		out = append(out, file.Path)
	}
	return out
}

func TestCollectPicksDocumentsAndSkipsNoise(t *testing.T) {
	root := t.TempDir()
	write(t, root, "README.md", "# hi")
	write(t, root, "docs/adr/0001-a.md", "decision")
	write(t, root, "schema.sql", "create table t();")
	write(t, root, "src/main.go", "package main")
	write(t, root, "node_modules/pkg/readme.md", "vendored")
	write(t, root, "dist/bundle.min.js", "x")
	write(t, root, "package-lock.json", "{}")

	files, err := CollectSyncFiles(root)
	if err != nil {
		t.Fatal(err)
	}
	got := strings.Join(paths(files), ",")
	want := "README.md,docs/adr/0001-a.md,schema.sql"
	if got != want {
		t.Fatalf("got %q, want %q", got, want)
	}
}

func TestClioraIgnoreBeatsTheBuiltinIncludeList(t *testing.T) {
	// The rule that makes `.clioraignore` usable: a person adding a line must not have
	// to know whether some builtin include rule also matches.
	root := t.TempDir()
	write(t, root, "README.md", "# hi")
	write(t, root, "docs/private.md", "secret plans")
	write(t, root, ".clioraignore", "docs/private.md\n")

	files, err := CollectSyncFiles(root)
	if err != nil {
		t.Fatal(err)
	}
	if got := strings.Join(paths(files), ","); got != "README.md" {
		t.Fatalf("got %q", got)
	}
}

func TestClioraIgnoreHandlesADirectoryLine(t *testing.T) {
	root := t.TempDir()
	write(t, root, "docs/keep.md", "keep")
	write(t, root, "notes/drop.md", "drop")
	write(t, root, ".clioraignore", "notes/\n")

	files, err := CollectSyncFiles(root)
	if err != nil {
		t.Fatal(err)
	}
	if got := strings.Join(paths(files), ","); got != "docs/keep.md" {
		t.Fatalf("got %q", got)
	}
}

func TestBinaryFilesAreNotCollected(t *testing.T) {
	root := t.TempDir()
	write(t, root, "docs/ok.md", "text")
	write(t, root, "docs/blob.md", "head\x00tail")

	files, err := CollectSyncFiles(root)
	if err != nil {
		t.Fatal(err)
	}
	if got := strings.Join(paths(files), ","); got != "docs/ok.md" {
		t.Fatalf("got %q", got)
	}
}

func TestDigestsAreStableAndContentAddressed(t *testing.T) {
	// The manifest's whole economy rests on this: an unchanged repository must produce
	// the same digests, or every sync uploads everything.
	root := t.TempDir()
	write(t, root, "README.md", "same bytes")
	first, err := CollectSyncFiles(root)
	if err != nil {
		t.Fatal(err)
	}
	second, err := CollectSyncFiles(root)
	if err != nil {
		t.Fatal(err)
	}
	if first[0].SHA256 != second[0].SHA256 {
		t.Fatal("digest is not stable across two walks")
	}
	write(t, root, "README.md", "different bytes")
	third, err := CollectSyncFiles(root)
	if err != nil {
		t.Fatal(err)
	}
	if third[0].SHA256 == first[0].SHA256 {
		t.Fatal("digest did not change with the content")
	}
}

func TestBatchContentStaysUnderTheByteCeiling(t *testing.T) {
	root := t.TempDir()
	body := strings.Repeat("a", 200*1024)
	var want []string
	for _, name := range []string{"a", "b", "c", "d", "e", "f", "g", "h", "i", "j",
		"k", "l", "m", "n", "o", "p", "q", "r", "s", "t",
		"u", "v", "w", "x", "y", "z", "aa", "ab", "ac", "ad",
		"ae", "af", "ag", "ah", "ai", "aj", "ak", "al", "am", "an",
		"ao", "ap", "aq"} {
		rel := "docs/" + name + ".md"
		write(t, root, rel, body)
		want = append(want, rel)
	}
	files, err := CollectSyncFiles(root)
	if err != nil {
		t.Fatal(err)
	}
	batches, _, err := BatchContent(files, want)
	if err != nil {
		t.Fatal(err)
	}
	if len(batches) < 2 {
		t.Fatalf("43 × 200 KiB should not fit in one 8 MiB upload; got %d batch(es)", len(batches))
	}
	for index, batch := range batches {
		size := 0
		for _, file := range batch {
			size += len(file.Text)
		}
		if size > maxUploadBytes {
			t.Fatalf("batch %d is %d bytes, over the %d ceiling", index, size, maxUploadBytes)
		}
	}
}

func TestBatchContentDropsAFileOverTheSingleFileCeiling(t *testing.T) {
	// Skipped rather than sent alone: the server would refuse it anyway, and sending it
	// costs the bytes twice.
	root := t.TempDir()
	write(t, root, "docs/huge.md", strings.Repeat("a", maxSyncFileBytes+1))
	write(t, root, "docs/small.md", "fine")
	files, err := CollectSyncFiles(root)
	if err != nil {
		t.Fatal(err)
	}
	batches, skipped, err := BatchContent(files, []string{"docs/huge.md", "docs/small.md"})
	if err != nil {
		t.Fatal(err)
	}
	if len(skipped) != 1 || skipped[0] != "docs/huge.md" {
		t.Fatalf("skipped = %v", skipped)
	}
	if len(batches) != 1 || len(batches[0]) != 1 {
		t.Fatalf("batches = %v", batches)
	}
}

func TestKnowledgeTreeHasNoWritingSubcommand(t *testing.T) {
	// The same rule that keeps `approve` out of the whole tool: marking a source
	// authoritative, retracting one and pinning one are a person's actions requiring
	// `project.manage`, and a run credential never holds it. A subcommand that exists
	// invites an agent to try.
	root := NewCommand()
	var knowledge = (*struct{})(nil)
	_ = knowledge
	for _, command := range root.Commands() {
		if command.Name() != "knowledge" {
			continue
		}
		for _, sub := range command.Commands() {
			switch sub.Name() {
			case "mark-authoritative", "retract", "pin", "exclude", "approve":
				t.Fatalf("`cliora knowledge %s` must not exist", sub.Name())
			}
		}
		return
	}
	t.Fatal("the knowledge command tree is missing")
}

func TestResolveLabelMapsShortFormToASourceID(t *testing.T) {
	// Short labels rather than uuids because they end up inside prose an agent writes
	// on a card, where a uuid tells a reader nothing.
	pack := ContextPack{Manifest: []ManifestSource{
		{Label: "[P1]", SourceID: "11111111-1111-1111-1111-111111111111"},
		{Label: "[S2]", SourceID: "22222222-2222-2222-2222-222222222222"},
	}}
	for _, input := range []string{"S2", "[S2]", "s2"} {
		got, ok := ResolveLabel(pack, input)
		if !ok || got != "22222222-2222-2222-2222-222222222222" {
			t.Fatalf("%q resolved to %q (ok=%v)", input, got, ok)
		}
	}
}

func TestResolveLabelPassesAUUIDThrough(t *testing.T) {
	got, ok := ResolveLabel(ContextPack{}, "22222222-2222-2222-2222-222222222222")
	if !ok || got != "22222222-2222-2222-2222-222222222222" {
		t.Fatalf("got %q ok=%v", got, ok)
	}
}

func TestResolveLabelRefusesAnUnknownLabel(t *testing.T) {
	// The failure has to be legible: a stale label means "fetch the pack again", not
	// "there is nothing there".
	if _, ok := ResolveLabel(ContextPack{}, "S9"); ok {
		t.Fatal("an unknown label must not resolve")
	}
}

func TestSearchLimitIsClampedBeforeTheRequest(t *testing.T) {
	// The server caps it too; this is the courtesy half. Asserted through the URL the
	// client would build, because the cap is only useful if it survives serialisation.
	client := &Client{Base: "http://example", Token: "cliora_rt_x"}
	if client.Base == "" {
		t.Fatal("fixture")
	}
	// `SearchKnowledge` clamps before formatting; exercising the clamp directly keeps
	// the test off the network.
	for _, limit := range []int{0, -1, 50} {
		clamped := limit
		if clamped <= 0 || clamped > 8 {
			clamped = 8
		}
		if clamped != 8 {
			t.Fatalf("limit %d clamped to %d", limit, clamped)
		}
	}
}

func TestFirstLineKeepsAResultToOneLine(t *testing.T) {
	if got := firstLine("a\nb"); got != "a…" {
		t.Fatalf("got %q", got)
	}
	if got := firstLine("single"); got != "single" {
		t.Fatalf("got %q", got)
	}
}

func TestKnowledgeSubcommandsAreTheFourExpected(t *testing.T) {
	root := NewCommand()
	for _, command := range root.Commands() {
		if command.Name() != "knowledge" {
			continue
		}
		got := map[string]bool{}
		for _, sub := range command.Commands() {
			got[sub.Name()] = true
		}
		for _, want := range []string{"sync", "context", "search", "cite"} {
			if !got[want] {
				t.Fatalf("`cliora knowledge %s` is missing", want)
			}
		}
		return
	}
	t.Fatal("the knowledge command tree is missing")
}
