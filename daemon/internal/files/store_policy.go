package files

import (
	"path"
	"strings"
	"unicode/utf8"
)

// General file upload: the second path by which anything is written into a
// workspace (ADR 0026, FR-FILE-010), and the first where the *caller* chooses
// where it lands and what it is called.
//
// Image drop could delete a whole class of problems by refusing to let the
// request name anything (ADR 0024 §3). This path cannot — `requirements.txt`'s
// name is its entire meaning — so it pays for that with the checks below. ADR
// 0024 §4 wrote down which ones would be needed before this path existed:
// normalisation, binding to the opened inode, the sensitive-file policy in the
// write direction, no symlink creation, and `.git` protection.
//
// The rule they add up to is one sentence, and it is why none of this is a
// second copy of the read path's policy:
//
//	the platform does not write to a location, or under a name, that it
//	would refuse to show you.

// maxFilenameBytes bounds a single path segment. The unit is BYTES, not runes:
// the wire schema's maxLength counts code points, so an 88-character CJK name is
// 256 bytes and passes the schema while exceeding what most filesystems accept
// (measured: plan/15/07-open-measurements.md §2). The schema bounds the shape;
// this bounds the unit.
const maxFilenameBytes = 255

// gitDirName is refused in every position of a stored path. See classifyGitPath.
const gitDirName = ".git"

// Verb identifies which operation is being judged. It exists so that a second
// write verb cannot quietly inherit the answers below — the .cliora/ rules in
// particular are per-verb, and a table that lives in several places is a table
// that will one day be updated in all but one.
type Verb int

// VerbStore is a general file upload (ADR 0026), the only verb today.
const VerbStore Verb = iota

// StorableClassification returns "" if a file may be stored at dir/name, or a
// coarse refusal reason. It is the write-direction counterpart of
// SensitiveClassification and deliberately calls it rather than reimplementing
// it: two copies would be two copies to keep in step, and they would not stay in
// step.
//
// A classification string rather than a bool, for the same reason the read path
// returns one: the audit needs a coarse category and the user needs to know
// which kind of refusal this is — "that is git's internal state" and "that name
// is protected" have different next steps.
//
// Order is default-deny and cheapest-first, the same discipline as Read: nothing
// here touches the filesystem, so a refusal costs one string walk.
func (s *Service) StorableClassification(dir, name string, verb Verb) string {
	if reason := classifyFilename(name); reason != "" {
		return reason
	}
	cleanDir, ok := cleanStoreDir(dir)
	if !ok {
		return "invalid"
	}
	rel := name
	if cleanDir != "." {
		rel = path.Join(cleanDir, name)
	}
	// The workspace root is a legitimate destination *directory* — dropping a
	// file at the top of the tree is an ordinary thing to want. What is refused
	// is the root as a target path, which is only reachable with a name
	// classifyFilename already rejects; this is its second layer.
	if rel == "." || rel == "" {
		return "workspace_root"
	}
	if reason := classifyGitPath(rel); reason != "" {
		return reason
	}
	// .cliora/ belongs to the platform, and this verb has no exception: the only
	// thing under it a user has business changing is a dropped image, and
	// removing one is not an upload.
	if verb == VerbStore && (rel == clioraDir || strings.HasPrefix(rel, clioraDir+"/")) {
		return "platform_owned"
	}
	// The same sensitive-file policy the preview uses, in the other direction. It
	// covers both halves at once: a destination under .ssh/ and a filename of
	// .env are the same refusal.
	if class := s.policy.SensitiveClassification(rel); class != "" {
		return class
	}
	// Excluded directories are an ignore rule when reading (their config comment
	// says so explicitly) but a security control when writing: nobody should be
	// uploading into node_modules from a browser, and the contents of those trees
	// are produced by tools rather than by people. Same list, two strengths —
	// worth knowing before anyone relaxes it.
	for _, seg := range strings.Split(rel, "/") {
		if s.excludedDirs[seg] {
			return "excluded_dir"
		}
	}
	return ""
}

// cleanStoreDir normalises a destination directory and reports whether it is
// usable. "" and "." both mean the workspace root. Anything absolute, ~-rooted,
// escaping, or containing a NUL is refused here as well as by workspace.relClean
// at the syscall layer (defence in depth, SEC-001).
func cleanStoreDir(dir string) (string, bool) {
	if strings.ContainsRune(dir, 0) {
		return "", false
	}
	if dir == "" || dir == "." {
		return ".", true
	}
	if strings.HasPrefix(dir, "/") || strings.HasPrefix(dir, "~") {
		return "", false
	}
	clean := path.Clean(dir)
	if clean == ".." || strings.HasPrefix(clean, "../") {
		return "", false
	}
	return clean, true
}

// classifyFilename enforces that name is a single, storable path segment.
func classifyFilename(name string) string {
	if name == "" || len(name) > maxFilenameBytes {
		return "invalid_name"
	}
	if name == "." || name == ".." {
		return "invalid_name"
	}
	if strings.ContainsRune(name, '/') || strings.ContainsRune(name, 0) {
		return "invalid_name"
	}
	// A control character in a name is never intentional, and it makes the name
	// unquotable in every log, shell and audit view downstream.
	for _, r := range name {
		if r < 0x20 || r == 0x7f {
			return "invalid_name"
		}
	}
	if !utf8.ValidString(name) {
		return "invalid_name"
	}
	return ""
}

// classifyGitPath refuses git's internal state.
//
// This is a new rule, not a relocated one. `.git` appears only in
// workspace.excluded_directories — whose own comment says it is an ignore rule
// and not a security control — and the default denied_directories are .ssh, .aws
// and .gnupg. So `.git/config` is readable today by naming it directly.
//
// Matching EVERY segment, including the last, is what covers the second shape:
// in a git worktree or submodule `.git` is a FILE containing "gitdir: …", not a
// directory, so a rule that only looked at leading segments would let it be
// overwritten — and rewriting that file repoints the entire worktree.
func classifyGitPath(rel string) string {
	for _, seg := range strings.Split(rel, "/") {
		if seg == gitDirName {
			return "git_metadata"
		}
	}
	return ""
}
