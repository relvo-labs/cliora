// Command storescan reports which paths under a directory the upload policy
// would refuse as a destination, and why (plan/15 FU-07, ADR 0026 §4).
//
// Two jobs, the same split as classifyscan:
//
//   - Evidence: the "writable position = readable position" claim is only
//     interesting if you can see what it excludes. This prints the exclusions with
//     their classifications.
//   - Runbook: when a user reports "I cannot upload into this directory", the
//     error names one classification for one path. This names all of them, so the
//     answer does not depend on guessing which rule fired.
//
// It drives the real policy function rather than reimplementing the rules — a
// second implementation of a security rule is exactly what ADR 0026 §4 avoids by
// calling the read path's own SensitiveClassification.
//
// Exit codes: 0 always (this is a report, not an assertion), 2 usage.
package main

import (
	"flag"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"time"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/cliora/cliora/daemon/internal/files"
)

func main() {
	summary := flag.Bool("summary", false, "print only the per-classification counts")
	flag.Usage = func() {
		fmt.Fprintf(os.Stderr, "usage: storescan [-summary] <dir>\n")
	}
	flag.Parse()
	if flag.NArg() != 1 {
		flag.Usage()
		os.Exit(2)
	}
	root := flag.Arg(0)

	// Defaults, not a node's live config: the question this answers is "what does
	// the shipped policy refuse", and a report that silently used someone's local
	// overrides would be misleading on a runbook page.
	cfg := &config.Config{}
	cfg.Filesystem.MaxPreviewSize = config.DefaultMaxPreviewSize
	cfg.Filesystem.Upload.MaxBytes = config.DefaultUploadMaxBytes
	cfg.Filesystem.DeniedPatterns = config.DefaultDeniedPatterns
	cfg.Filesystem.DeniedDirectories = config.DefaultDeniedDirectories
	cfg.Workspace.ExcludedDirectories = config.DefaultExcludedDirs
	svc := files.NewService(cfg, time.Now)

	counts := map[string]int{}
	var refused []string
	total := 0

	err := filepath.WalkDir(root, func(p string, d fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			// An unreadable subtree is not this command's problem to solve.
			return nil //nolint:nilerr // report what is reachable
		}
		if d.IsDir() {
			return nil
		}
		rel, relErr := filepath.Rel(root, p)
		if relErr != nil {
			return nil
		}
		total++
		dir := filepath.Dir(rel)
		reason := svc.StorableClassification(dir, filepath.Base(rel), files.VerbStore)
		if reason == "" {
			counts["writable"]++
			return nil
		}
		counts[reason]++
		refused = append(refused, fmt.Sprintf("%-16s %s", reason, rel))
		return nil
	})
	if err != nil {
		fmt.Fprintf(os.Stderr, "walk %s: %v\n", root, err)
		os.Exit(2)
	}

	fmt.Printf("scanned %d existing files under %s\n", total, root)
	keys := make([]string, 0, len(counts))
	for k := range counts {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		fmt.Printf("  %-16s %d\n", k, counts[k])
	}
	if !*summary && len(refused) > 0 {
		sort.Strings(refused)
		fmt.Println("\nrefused as an upload destination or name:")
		for _, line := range refused {
			fmt.Println("  " + line)
		}
	}
	fmt.Println("\nThis reports which *existing* paths the policy would refuse as an upload")
	fmt.Println("target. A refusal is not a regression: those files are already unreadable")
	fmt.Println("through the preview, and keeping the two directions identical is the point")
	fmt.Println("(ADR 0026 §4). What would be a problem is the reverse — a path the preview")
	fmt.Println("will show that this says is writable but the node then refuses.")
}
