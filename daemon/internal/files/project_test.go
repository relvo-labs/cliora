package files

import (
	"encoding/base64"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/cliora/cliora/daemon/internal/workspace"
)

// The projection verb (ADR 0028). What is asserted here is the property the whole
// design rests on: **the two write verbs' reachable sets are disjoint, in both
// directions**, and neither replaces a byte.

func projectService(t *testing.T) (*Service, *workspace.Root, string) {
	t.Helper()
	svc := storeService(t, nil)
	root, dir := storeRoot(t)
	return svc, root, dir
}

func b64(s string) string { return base64.StdEncoding.EncodeToString([]byte(s)) }

func TestProjectWritesTheThreeSubtrees(t *testing.T) {
	svc, root, dir := projectService(t)
	res, err := svc.Project(root, []ProjectFile{
		{Path: ".cliora/context/abc.md", Mode: "0600", Data: b64("# TASK-1\n")},
		{Path: ".cliora/context/abc.token", Mode: "0600", Data: b64("cliora_st_x")},
		{Path: ".cliora/process/2026.08-1/kanban.md", Mode: "0600", Data: b64("lanes\n")},
		{Path: ".cliora/reference/design.md", Mode: "0600", Data: b64("tokens\n")},
	}, time.Now())
	if err != nil {
		t.Fatalf("project: %v", err)
	}
	if res.Denied || len(res.Written) != 4 {
		t.Fatalf("want 4 written, got denied=%v written=%v", res.Denied, res.Written)
	}
	// Mode is fixed at 0600: the credential is one of these files.
	info, statErr := os.Stat(filepath.Join(dir, ".cliora/context/abc.token"))
	if statErr != nil {
		t.Fatalf("stat: %v", statErr)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("mode = %v, want 0600", info.Mode().Perm())
	}
	// And the platform's gitignore is written on first use, so `git status` stays
	// clean without the user having to do anything.
	if _, err := os.Stat(filepath.Join(dir, ".cliora/.gitignore")); err != nil {
		t.Fatalf("gitignore missing: %v", err)
	}
}

func TestProjectRefusesEverythingOutsideTheThreeSubtrees(t *testing.T) {
	svc, root, _ := projectService(t)
	for _, rel := range []string{
		"src/main.go",             // the user's code
		".cliora",                 // the directory itself
		".cliora/uploads/x.png",   // image drop's area
		".cliora/.gitignore",      // may be the user's own file
		".cliora/context/../../x", // traversal
		".git/config",             // git's internal state
		".cliora/context/../a.md", // traversal that cleans inside the subtree
	} {
		res, err := svc.Project(root, []ProjectFile{
			{Path: rel, Mode: "0600", Data: b64("x")},
		}, time.Now())
		if err != nil {
			t.Fatalf("%s: unexpected error %v", rel, err)
		}
		if !res.Denied {
			t.Fatalf("%s: expected a refusal, got written=%v", rel, res.Written)
		}
	}
}

func TestTheUserFacingVerbStillCannotWriteTheProjectionArea(t *testing.T) {
	// The regression that matters most: adding a second verb must not have loosened
	// the first one. If this ever passes, any holder of `file.upload` can overwrite a
	// context pack — or a session credential.
	svc, _, _ := projectService(t)
	for _, dir := range []string{".cliora", ".cliora/context", ".cliora/process/2026.08-1"} {
		if reason := svc.StorableClassification(dir, "notes.md", VerbStore); reason != "platform_owned" {
			t.Fatalf("%s: VerbStore reason = %q, want platform_owned", dir, reason)
		}
	}
}

func TestProjectTreatsAnExistingFileAsSuccess(t *testing.T) {
	// A second session in the same workspace finds the same process notes already
	// there. That is what `skipped` is for, and it is why this path needs no overwrite
	// flag anywhere in the protocol.
	svc, root, _ := projectService(t)
	files := []ProjectFile{
		{Path: ".cliora/process/2026.08-1/kanban.md", Mode: "0600", Data: b64("lanes\n")},
	}
	if _, err := svc.Project(root, files, time.Now()); err != nil {
		t.Fatalf("first: %v", err)
	}
	res, err := svc.Project(root, files, time.Now())
	if err != nil {
		t.Fatalf("second: %v", err)
	}
	if res.Denied || len(res.Skipped) != 1 || len(res.Written) != 0 {
		t.Fatalf("want 1 skipped, got %+v", res)
	}
	// And the original bytes are untouched — "skipped" must never mean "replaced".
	body, _ := os.ReadFile(filepath.Join(root.Canonical(), ".cliora/process/2026.08-1/kanban.md"))
	if string(body) != "lanes\n" {
		t.Fatalf("content changed: %q", body)
	}
}

func TestProjectRefusesAModeItMayNotWrite(t *testing.T) {
	svc, root, _ := projectService(t)
	res, err := svc.Project(root, []ProjectFile{
		{Path: ".cliora/context/a.md", Mode: "0644", Data: b64("x")},
	}, time.Now())
	if err != nil || !res.Denied || res.Reason != "invalid_mode" {
		t.Fatalf("want invalid_mode refusal, got %+v err=%v", res, err)
	}
}

func TestProjectRefusesAnOversizeFile(t *testing.T) {
	svc, root, _ := projectService(t)
	big := make([]byte, maxProjectFileBytes+1)
	res, err := svc.Project(root, []ProjectFile{
		{Path: ".cliora/context/a.md", Mode: "0600", Data: base64.StdEncoding.EncodeToString(big)},
	}, time.Now())
	if err != nil || !res.Denied || res.Code != "FILE_UPLOAD_TOO_LARGE" {
		t.Fatalf("want oversize refusal, got %+v err=%v", res, err)
	}
}

func TestProjectRefusesWhenClioraIsNotADirectory(t *testing.T) {
	// os.Root follows in-root symlinks, so a `.cliora` that is a file — or a link —
	// would otherwise redirect every write. Bound to what is actually on disk.
	svc, root, dir := projectService(t)
	if err := os.WriteFile(filepath.Join(dir, ".cliora"), []byte("not a dir"), 0o600); err != nil {
		t.Fatalf("setup: %v", err)
	}
	res, err := svc.Project(root, []ProjectFile{
		{Path: ".cliora/context/a.md", Mode: "0600", Data: b64("x")},
	}, time.Now())
	if err != nil || !res.Denied {
		t.Fatalf("want a refusal, got %+v err=%v", res, err)
	}
}

func TestRetentionLeavesTheUserSFilesAlone(t *testing.T) {
	// ADR 0024's W2 answer for this store — and the one mistake that would be
	// expensive: `uploads/` is image drop's area, and a user's screenshots must not
	// disappear on the projection's timer.
	svc, root, dir := projectService(t)
	if _, err := svc.Project(root, []ProjectFile{
		{Path: ".cliora/context/old.md", Mode: "0600", Data: b64("stale")},
		{Path: ".cliora/process/2026.07-1/kanban.md", Mode: "0600", Data: b64("old process")},
		{Path: ".cliora/process/2026.08-1/kanban.md", Mode: "0600", Data: b64("live process")},
	}, time.Now()); err != nil {
		t.Fatalf("project: %v", err)
	}
	if err := os.MkdirAll(filepath.Join(dir, ".cliora/uploads/2026-08-01"), 0o700); err != nil {
		t.Fatalf("setup: %v", err)
	}
	shot := filepath.Join(dir, ".cliora/uploads/2026-08-01/shot.png")
	if err := os.WriteFile(shot, []byte("png"), 0o600); err != nil {
		t.Fatalf("setup: %v", err)
	}

	// Everything is "old" as far as the sweep is concerned.
	future := time.Now().Add(90 * 24 * time.Hour)
	removed, err := svc.ProjectRetention(root, "2026.08-1", 30*24*time.Hour, future)
	if err != nil {
		t.Fatalf("retention: %v", err)
	}
	if removed == 0 {
		t.Fatal("expected the stale context pack to be removed")
	}
	if _, err := os.Stat(shot); err != nil {
		t.Fatalf("image drop's file was removed: %v", err)
	}
	if _, err := os.Stat(filepath.Join(dir, ".cliora/.gitignore")); err != nil {
		t.Fatalf("the gitignore was removed: %v", err)
	}
	// The version in force survives: a live session is pointing at it.
	if _, err := os.Stat(filepath.Join(dir, ".cliora/process/2026.08-1/kanban.md")); err != nil {
		t.Fatalf("the live process notes were removed: %v", err)
	}
	if _, err := os.Stat(filepath.Join(dir, ".cliora/context/old.md")); err == nil {
		t.Fatal("the stale context pack survived")
	}
}
