package files

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/cliora/cliora/daemon/internal/workspace"
)

// defaultCfg mirrors the P3 config defaults (ADR 0015) for unit tests without
// going through file loading.
func defaultCfg() *config.Config {
	cfg := &config.Config{}
	cfg.Filesystem.MaxPreviewSize = config.DefaultMaxPreviewSize
	cfg.Filesystem.DeniedPatterns = config.DefaultDeniedPatterns
	cfg.Filesystem.DeniedDirectories = config.DefaultDeniedDirectories
	cfg.Workspace.ExcludedDirectories = config.DefaultExcludedDirs
	cfg.Filesystem.Search = config.SearchConfig{
		MaxDepth:       config.DefaultSearchMaxDepth,
		MaxResults:     config.DefaultSearchMaxResults,
		MaxScanned:     config.DefaultSearchMaxScanned,
		TimeoutSeconds: config.DefaultSearchTimeoutSec,
	}
	return cfg
}

func testService() *Service {
	return NewService(defaultCfg(), func() time.Time { return time.Unix(0, 0).UTC() })
}

// buildTree lays out a workspace with a mix of files, dirs, excluded dirs, and
// sensitive/binary/oversize fixtures, returning the allowed root and workspace.
func buildTree(t *testing.T) (root, ws string) {
	t.Helper()
	base := t.TempDir()
	root = filepath.Join(base, "projects")
	ws = filepath.Join(root, "app")
	dirs := []string{
		filepath.Join(ws, "src"),
		filepath.Join(ws, "node_modules", "pkg"),
		filepath.Join(ws, ".ssh"),
	}
	for _, d := range dirs {
		if err := os.MkdirAll(d, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	files := map[string]string{
		filepath.Join(ws, "main.go"):        "package main\n",
		filepath.Join(ws, "src", "app.ts"):  "export const x = 1\n",
		filepath.Join(ws, ".env"):           "SECRET=1\n",
		filepath.Join(ws, "server.pem"):     "-----BEGIN KEY-----\n",
		filepath.Join(ws, ".ssh", "config"): "Host *\n",
		filepath.Join(ws, "app_secret.txt"): "not actually denied by balanced policy\n",
		filepath.Join(ws, "bin.dat"):        "\x00\x01\x02binary\x00",
		filepath.Join(ws, "readme.md"):      "# hi\n",
	}
	for p, c := range files {
		if err := os.WriteFile(p, []byte(c), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return root, ws
}

func openWS(t *testing.T, root, ws string) *workspace.Root {
	t.Helper()
	r, err := workspace.New([]string{root}).OpenWorkspace(ws)
	if err != nil {
		t.Fatalf("open workspace: %v", err)
	}
	t.Cleanup(func() { r.Close() })
	return r
}

func TestListOrderingAndExclusion(t *testing.T) {
	root, ws := buildTree(t)
	s := testService()
	r := openWS(t, root, ws)
	res, err := s.List(r, ".", "", 0)
	if err != nil {
		t.Fatal(err)
	}
	// Directories sort before files.
	var order []string
	var excludedSeen bool
	for _, e := range res.Entries {
		order = append(order, e.Name)
		if e.Name == "node_modules" {
			if !e.Excluded || e.Expandable {
				t.Errorf("node_modules should be excluded and non-expandable: %+v", e)
			}
			excludedSeen = true
		}
		if strings.Contains(e.RelPath, ws) {
			t.Errorf("entry leaked absolute path: %q", e.RelPath)
		}
	}
	if !excludedSeen {
		t.Fatal("excluded dir not present in listing (should be shown, not loaded)")
	}
	// First three names must be the directories in sorted order.
	wantDirs := []string{".ssh", "node_modules", "src"}
	for i, d := range wantDirs {
		if order[i] != d {
			t.Errorf("position %d = %q, want dir %q (order=%v)", i, order[i], d, order)
		}
	}
}

func TestListPagination(t *testing.T) {
	root, ws := buildTree(t)
	s := testService()
	r := openWS(t, root, ws)
	first, err := s.List(r, ".", "", 2)
	if err != nil {
		t.Fatal(err)
	}
	if len(first.Entries) != 2 || !first.Truncated || first.NextCursor == "" {
		t.Fatalf("expected 2 truncated entries with cursor, got %+v", first)
	}
	second, err := s.List(r, ".", first.NextCursor, 2)
	if err != nil {
		t.Fatal(err)
	}
	if second.Entries[0].Name == first.Entries[0].Name {
		t.Fatal("cursor did not advance")
	}
}

func TestReadPolicyMatrix(t *testing.T) {
	root, ws := buildTree(t)
	s := testService()
	r := openWS(t, root, ws)

	cases := []struct {
		path       string
		wantDenied bool
		wantCode   string
		wantReason string
	}{
		{"main.go", false, "", ""},
		{"src/app.ts", false, "", ""},
		{"readme.md", false, "", ""},
		{".env", true, "FILE_DENIED", "dotenv"},
		{"server.pem", true, "FILE_DENIED", "private_key"},
		{".ssh/config", true, "FILE_DENIED", "sensitive_dir"},
		{"bin.dat", true, "FILE_BINARY", ""},
		// Balanced policy: app_secret.txt is NOT denied (no broad *secret* glob).
		{"app_secret.txt", false, "", ""},
	}
	for _, tc := range cases {
		t.Run(tc.path, func(t *testing.T) {
			res, err := s.Read(r, tc.path)
			if err != nil {
				t.Fatalf("read %s: %v", tc.path, err)
			}
			if res.Denied != tc.wantDenied {
				t.Fatalf("denied=%v want %v (%+v)", res.Denied, tc.wantDenied, res)
			}
			if tc.wantDenied && res.Code != tc.wantCode {
				t.Fatalf("code=%s want %s", res.Code, tc.wantCode)
			}
			if tc.wantReason != "" && res.Reason != tc.wantReason {
				t.Fatalf("reason=%s want %s", res.Reason, tc.wantReason)
			}
			// A denial must never carry content.
			if res.Denied && res.Content != "" {
				t.Fatal("denial leaked content")
			}
			if !tc.wantDenied && res.Content == "" {
				t.Fatal("expected content for previewable file")
			}
		})
	}
}

func TestReadOversize(t *testing.T) {
	root, ws := buildTree(t)
	cfg := defaultCfg()
	cfg.Filesystem.MaxPreviewSize = 8
	s := NewService(cfg, nil)
	if err := os.WriteFile(filepath.Join(ws, "big.txt"), make([]byte, 100), 0o644); err != nil {
		t.Fatal(err)
	}
	r := openWS(t, root, ws)
	res, err := s.Read(r, "big.txt")
	if err != nil {
		t.Fatal(err)
	}
	if !res.Denied || res.Code != "FILE_TOO_LARGE" || res.Size != 100 {
		t.Fatalf("expected FILE_TOO_LARGE size 100, got %+v", res)
	}
	if res.Content != "" {
		t.Fatal("oversize denial leaked content")
	}
}

func TestReadSymlinkDenied(t *testing.T) {
	root, ws := buildTree(t)
	s := testService()
	// A benign-named in-workspace symlink to the sensitive .env must not preview
	// .env content: O_NOFOLLOW refuses the final symlink component.
	if err := os.Symlink(".env", filepath.Join(ws, "notes.txt")); err != nil {
		t.Fatal(err)
	}
	r := openWS(t, root, ws)
	res, err := s.Read(r, "notes.txt")
	if err != nil {
		t.Fatal(err)
	}
	if !res.Denied || res.Code != "FILE_DENIED" || res.Reason != "dotenv" {
		t.Fatalf("expected sensitive (resolved dotenv) denial, got %+v", res)
	}
	if strings.Contains(res.Content, "SECRET") {
		t.Fatal("symlink preview leaked sensitive content")
	}
}

func TestSearchFilenameOnlyWithBounds(t *testing.T) {
	root, ws := buildTree(t)
	s := testService()
	r := openWS(t, root, ws)
	res, err := s.Search(context.Background(), r, "app", "", 0)
	if err != nil {
		t.Fatal(err)
	}
	// Matches app.ts and app_secret.txt by filename; must not descend node_modules.
	var names []string
	for _, e := range res.Results {
		names = append(names, e.Name)
		if strings.Contains(e.RelPath, "node_modules") {
			t.Errorf("search descended excluded dir: %q", e.RelPath)
		}
	}
	if len(names) == 0 {
		t.Fatal("expected filename matches for 'app'")
	}
}

func TestSearchResultsBound(t *testing.T) {
	root, ws := buildTree(t)
	cfg := defaultCfg()
	s := NewService(cfg, nil)
	// Create many matching files.
	for i := 0; i < 20; i++ {
		name := filepath.Join(ws, "hit"+string(rune('a'+i))+".txt")
		if err := os.WriteFile(name, []byte("x"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	r := openWS(t, root, ws)
	res, err := s.Search(context.Background(), r, "hit", "", 5)
	if err != nil {
		t.Fatal(err)
	}
	if len(res.Results) != 5 || !res.Partial || res.StoppedReason != "results" {
		t.Fatalf("expected 5 results partial=results, got %d partial=%v reason=%s", len(res.Results), res.Partial, res.StoppedReason)
	}
}

func TestSearchCancelled(t *testing.T) {
	root, ws := buildTree(t)
	s := testService()
	r := openWS(t, root, ws)
	ctx, cancel := context.WithCancel(context.Background())
	cancel() // cancelled before walking
	res, err := s.Search(ctx, r, "app", "", 0)
	if err != nil {
		t.Fatal(err)
	}
	if !res.Partial || res.StoppedReason != "timeout" {
		t.Fatalf("expected cancelled search to be partial/timeout, got %+v", res)
	}
}
