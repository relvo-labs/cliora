package files

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestStorePolicy is the body of GATE-FU-WRITE-POLICY. It is a table rather than
// a set of functions because the property being defended is the *completeness* of
// one list, and a table makes an omission visible.

func TestStorePolicyClassification(t *testing.T) {
	svc := storeService(t, nil)
	cases := []struct {
		name string
		dir  string
		file string
		want string
	}{
		// --- allowed ---
		{"plain file at root", ".", "data.csv", ""},
		{"plain file in subdir", "datasets/raw", "data.csv", ""},
		{"empty dir means root", "", "data.csv", ""},
		{"dotfile that is not sensitive", ".", ".editorconfig", ""},
		{"non-ascii name", "docs", "測試資料.csv", ""},
		{"name with spaces and plus", ".", "a+b c.txt", ""},

		// --- the filename must be one segment ---
		{"separator in name", ".", "a/b.txt", "invalid_name"},
		{"traversal in name", ".", "../escape.txt", "invalid_name"},
		{"dot", ".", ".", "invalid_name"},
		{"dotdot", ".", "..", "invalid_name"},
		{"empty name", ".", "", "invalid_name"},
		{"control character", ".", "a\nb.txt", "invalid_name"},
		{"nul", ".", "a\x00b.txt", "invalid_name"},
		{"256 bytes of ascii", ".", strings.Repeat("a", 256), "invalid_name"},
		// 84 CJK runes plus ".csv" is 88 code points but 256 BYTES. The wire
		// schema's maxLength counts code points and would let this through, which
		// is why the unit here is bytes (plan/15/07-open-measurements.md §2).
		{"256 bytes of cjk", ".", strings.Repeat("測", 84) + ".csv", "invalid_name"},
		{"255 bytes is fine", ".", strings.Repeat("a", 255), ""},

		// --- the destination must not escape ---
		{"absolute dir", "/etc", "a.txt", "invalid"},
		{"tilde dir", "~/x", "a.txt", "invalid"},
		{"parent dir", "..", "a.txt", "invalid"},
		{"parent inside dir", "../x", "a.txt", "invalid"},
		{"nul in dir", "a\x00b", "a.txt", "invalid"},

		// --- git, in both of its shapes ---
		{"inside .git", ".git", "config", "git_metadata"},
		{"deep inside .git", ".git/hooks", "pre-commit", "git_metadata"},
		{"nested repo .git dir", "vendor/lib/.git", "config", "git_metadata"},
		// The shape a segment-only rule misses: in a worktree or submodule, .git is
		// a FILE holding "gitdir: …", and rewriting it repoints the whole worktree.
		{"worktree .git file at root", ".", ".git", "git_metadata"},
		{"submodule .git file", "vendor/lib", ".git", "git_metadata"},

		// --- the platform's own directory ---
		{"cliora root", ".", ".cliora", "platform_owned"},
		{"inside cliora", ".cliora/uploads/2026-08-03", "x.png", "platform_owned"},

		// --- the sensitive-file policy, in the write direction ---
		{"dotenv", ".", ".env", "dotenv"},
		{"dotenv variant", "config", ".env.production", "dotenv"},
		{"private key by extension", ".", "server.pem", "private_key"},
		{"private key by name", ".", "id_rsa", "private_key"},
		{"credentials glob", ".", "aws-credentials.json", "sensitive"},
		{"sensitive destination", ".ssh", "authorized_keys", "sensitive_dir"},

		// --- tool-owned trees ---
		{"node_modules", "node_modules/left-pad", "index.js", "excluded_dir"},
		{"dist", "dist", "bundle.js", "excluded_dir"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := svc.StorableClassification(tc.dir, tc.file, VerbStore)
			if got != tc.want {
				t.Fatalf("dir=%q name=%q: classification = %q, want %q",
					tc.dir, tc.file, got, tc.want)
			}
		})
	}
}

// Every refusal above must also mean nothing happened on disk. Checking the
// classification alone would not catch a Store that consulted the policy and then
// wrote anyway.
func TestStorePolicyRefusalsWriteNothing(t *testing.T) {
	refused := []struct{ dir, file string }{
		{".", "a/b.txt"},
		{".", ".env"},
		{".", ".git"},
		{".", ".cliora"},
		{".git", "config"},
		{".ssh", "authorized_keys"},
		{"node_modules", "x.js"},
		{"/etc", "passwd"},
		{"..", "escape.txt"},
	}
	for _, tc := range refused {
		t.Run(tc.dir+"/"+tc.file, func(t *testing.T) {
			svc := storeService(t, nil)
			root, dir := storeRoot(t)
			// Give the refusals a real directory to aim at where one is named, so
			// the refusal comes from the policy rather than from a missing parent.
			for _, d := range []string{".git", ".git/hooks", ".ssh", "node_modules", ".cliora"} {
				_ = os.MkdirAll(filepath.Join(dir, d), 0o755)
			}
			before := treeSnapshot(t, dir)

			res, err := svc.Store(root, tc.dir, tc.file, []byte("payload"), storeNow)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if !res.Denied {
				t.Fatalf("accepted %q/%q", tc.dir, tc.file)
			}
			if after := treeSnapshot(t, dir); after != before {
				t.Fatalf("tree changed after a refusal:\nbefore %s\nafter  %s", before, after)
			}
		})
	}
}

// treeSnapshot is a cheap fingerprint of a tree: every path plus its size. Enough
// to catch a created, changed or removed file without depending on mtime
// granularity.
func treeSnapshot(t *testing.T, dir string) string {
	t.Helper()
	var b strings.Builder
	err := filepath.Walk(dir, func(p string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(dir, p)
		b.WriteString(rel)
		if !info.IsDir() {
			b.WriteString(":")
			b.WriteString(string(rune('0' + info.Size()%10)))
			b.WriteString(info.Mode().Perm().String())
		}
		b.WriteString("\n")
		return nil
	})
	if err != nil {
		t.Fatalf("walk: %v", err)
	}
	return b.String()
}
