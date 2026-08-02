// Command classifyscan reports how files.Classify judges every text-looking
// file under a directory (plan/13 WF-03 §4).
//
// Two jobs:
//
//   - Acceptance: the number of *valid UTF-8* files judged binary must be 0.
//     Before this change it was 20 on this repository, all of them Markdown.
//   - Runbook: when a user reports "I cannot preview this file", run it on the
//     node against that path and the verdict comes back with the reason.
//
// Exit codes: 0 clean, 1 at least one valid-UTF-8 file judged binary, 2 usage.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"unicode/utf8"

	"github.com/cliora/cliora/daemon/internal/files"
)

// textExtensions is the set scanned by default. It is deliberately a list of
// things that *should* be previewable: the acceptance criterion is about false
// negatives on text, so scanning .png would only add noise.
var textExtensions = map[string]bool{
	".go": true, ".py": true, ".ts": true, ".tsx": true, ".js": true, ".jsx": true,
	".mjs": true, ".cjs": true, ".vue": true, ".json": true, ".jsonc": true,
	".yaml": true, ".yml": true, ".toml": true, ".ini": true, ".cfg": true,
	".conf": true, ".md": true, ".markdown": true, ".txt": true, ".rst": true,
	".sh": true, ".bash": true, ".zsh": true, ".sql": true, ".html": true,
	".htm": true, ".css": true, ".scss": true, ".rs": true, ".java": true,
	".rb": true, ".php": true, ".c": true, ".h": true, ".cpp": true, ".hpp": true,
	".mod": true, ".sum": true, ".lock": true, ".xml": true, ".xsd": true,
	".svg": true, ".csv": true, ".tsv": true, ".log": true, ".env-example": true,
}

var skipDirs = map[string]bool{
	".git": true, "node_modules": true, ".venv": true, "venv": true,
	"dist": true, "build": true, "__pycache__": true, ".mypy_cache": true,
	".pytest_cache": true, ".ruff_cache": true, "target": true, "vendor": true,
}

type finding struct {
	Path    string `json:"path"`
	Size    int    `json:"size"`
	Verdict string `json:"verdict"`
	Mime    string `json:"mime"`
	// ValidUTF8 separates "we judged text wrongly" from "this really is not
	// UTF-8". Only the former is a failure.
	ValidUTF8 bool `json:"valid_utf8"`
}

func main() {
	asJSON := flag.Bool("json", false, "emit JSON instead of a table")
	all := flag.Bool("all", false, "scan every file, not just known text extensions")
	flag.Parse()
	if flag.NArg() != 1 {
		fmt.Fprintln(os.Stderr, "usage: classifyscan [-json] [-all] <dir-or-file>")
		os.Exit(2)
	}
	root := flag.Arg(0)

	var scanned, text, binary, unsupported int
	var falseBinary []finding
	var other []finding

	walk := func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		if d.IsDir() {
			if skipDirs[d.Name()] {
				return filepath.SkipDir
			}
			return nil
		}
		if !*all && !textExtensions[strings.ToLower(filepath.Ext(path))] {
			return nil
		}
		data, readErr := os.ReadFile(path)
		if readErr != nil {
			return nil
		}
		scanned++
		verdict, mime := files.Classify(data)
		f := finding{Path: path, Size: len(data), Mime: mime, ValidUTF8: utf8.Valid(data)}
		switch verdict {
		case files.VerdictText:
			text++
			return nil
		case files.VerdictBinary:
			binary++
			f.Verdict = "binary"
			// A valid-UTF-8 file called binary is the regression this scan exists for.
			if f.ValidUTF8 {
				falseBinary = append(falseBinary, f)
				return nil
			}
		case files.VerdictUnsupportedEncoding:
			unsupported++
			f.Verdict = "unsupported_encoding"
		}
		other = append(other, f)
		return nil
	}

	if info, err := os.Stat(root); err == nil && !info.IsDir() {
		_ = walk(root, fileEntry{info}, nil)
	} else if err := filepath.WalkDir(root, walk); err != nil {
		fmt.Fprintf(os.Stderr, "walk %s: %v\n", root, err)
		os.Exit(2)
	}

	sort.Slice(falseBinary, func(i, j int) bool { return falseBinary[i].Path < falseBinary[j].Path })
	sort.Slice(other, func(i, j int) bool { return other[i].Path < other[j].Path })

	if *asJSON {
		out, _ := json.MarshalIndent(map[string]any{
			"root": root, "scanned": scanned, "text": text,
			"binary": binary, "unsupported_encoding": unsupported,
			"false_binary": falseBinary, "other_non_text": other,
		}, "", "  ")
		fmt.Println(string(out))
	} else {
		fmt.Printf("%s: scanned=%d text=%d binary=%d unsupported_encoding=%d\n",
			root, scanned, text, binary, unsupported)
		for _, f := range other {
			fmt.Printf("  [%-20s] %s (%d bytes)\n", f.Verdict, f.Path, f.Size)
		}
		for _, f := range falseBinary {
			fmt.Printf("  [FALSE BINARY       ] %s (%d bytes) — valid UTF-8 judged binary\n", f.Path, f.Size)
		}
	}

	if len(falseBinary) > 0 {
		fmt.Fprintf(os.Stderr, "\n%d valid-UTF-8 file(s) judged binary; the acceptance criterion is 0\n",
			len(falseBinary))
		os.Exit(1)
	}
}

// fileEntry adapts a FileInfo so a single-file argument reuses the walk body.
type fileEntry struct{ os.FileInfo }

func (f fileEntry) Type() fs.FileMode          { return f.Mode().Type() }
func (f fileEntry) Info() (fs.FileInfo, error) { return f.FileInfo, nil }
