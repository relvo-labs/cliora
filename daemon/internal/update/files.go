package update

import (
	"archive/tar"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// maxBinaryBytes bounds decompression. Without it a small archive can expand into
// an arbitrarily large file — the classic decompression bomb — and the digest check
// happens on the *archive*, so it does not protect the extraction step.
const maxBinaryBytes = 256 << 20

// binaryMember is the only archive member that is ever extracted. Matching by exact
// name means a traversal path, a symlink or a second payload cannot be written,
// because nothing else is read out at all.
const binaryMember = "agentd"

func writeBounded(destination string, source io.Reader) error {
	// 0600 while it is being written: a partially-downloaded candidate must never be
	// executable, by anyone.
	file, err := os.OpenFile(destination, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600)
	if err != nil {
		return err
	}
	if _, err := io.Copy(file, source); err != nil {
		_ = file.Close()
		_ = os.Remove(destination)
		return err
	}
	return file.Close()
}

func sha256File(path string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer func() { _ = file.Close() }()
	digest := sha256.New()
	if _, err := io.Copy(digest, file); err != nil {
		return "", err
	}
	return hex.EncodeToString(digest.Sum(nil)), nil
}

// extractBinary pulls exactly one member — `agentd` — out of the tarball.
//
// Deliberately not a general extractor. There is nothing else in the archive this
// code needs, and an extractor that handled directories, symlinks and arbitrary
// paths would be a tar-traversal surface for no benefit. Anything that is not a
// regular file named `agentd` at the archive root is ignored, and an archive
// without it is an error.
func extractBinary(archivePath, destination string) error {
	file, err := os.Open(archivePath)
	if err != nil {
		return err
	}
	defer func() { _ = file.Close() }()
	gz, err := gzip.NewReader(file)
	if err != nil {
		return errors.New("release artifact is not a valid gzip archive")
	}
	defer func() { _ = gz.Close() }()

	reader := tar.NewReader(gz)
	for {
		header, err := reader.Next()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return errors.New("release artifact is not a valid tar archive")
		}
		if header.Typeflag != tar.TypeReg {
			continue
		}
		// Compared against the base name, and only accepted when the member has no
		// directory part, so `../../agentd` or `bin/agentd` never matches.
		if header.Name != binaryMember {
			continue
		}
		if err := writeBounded(destination, io.LimitReader(reader, maxBinaryBytes)); err != nil {
			return err
		}
		// Executable only now that it is complete.
		return os.Chmod(destination, 0o755)
	}
	return fmt.Errorf("release artifact does not contain %q", binaryMember)
}

// backupSuffix names a backup after the version it holds, so an operator doing a
// manual rollback can see what they are restoring.
func backupPath(binaryPath, fromVersion string) string {
	safe := sanitizeVersion(fromVersion)
	return filepath.Join(filepath.Dir(binaryPath), filepath.Base(binaryPath)+".bak-"+safe)
}

var unsafeVersionChars = regexp.MustCompile(`[^0-9A-Za-z.+_-]`)

// sanitizeVersion keeps a version string usable as a filename suffix. The version
// this is applied to is the *running binary's* own, not anything received over the
// wire, but it is still normalized: the value comes from a build-time ldflag, and a
// path built from an unvalidated string is a habit worth not having.
func sanitizeVersion(version string) string {
	cleaned := unsafeVersionChars.ReplaceAllString(strings.TrimSpace(version), "_")
	if cleaned == "" {
		return "unknown"
	}
	if len(cleaned) > 40 {
		cleaned = cleaned[:40]
	}
	return cleaned
}

// swapBinary backs up the installed binary and atomically replaces it.
//
// The candidate is first moved next to the target, because `rename(2)` is only
// atomic within a filesystem and the staging directory may be on another one. The
// backup is a *copy*, not a rename: renaming the live binary away leaves a window
// in which the path does not exist, and a `systemctl restart` landing in that
// window would fail with nothing to roll back to.
func swapBinary(binaryPath, candidate, fromVersion string) (string, error) {
	backup := backupPath(binaryPath, fromVersion)
	if err := copyFile(binaryPath, backup, 0o755); err != nil {
		return "", fmt.Errorf("cannot back up the current binary: %w", err)
	}
	staged := binaryPath + ".new"
	if err := copyFile(candidate, staged, 0o755); err != nil {
		_ = os.Remove(staged)
		return "", fmt.Errorf("cannot stage the new binary next to the target: %w", err)
	}
	if err := os.Rename(staged, binaryPath); err != nil {
		_ = os.Remove(staged)
		return "", fmt.Errorf("cannot replace the installed binary: %w", err)
	}
	return backup, nil
}

// restoreBinary puts the backup back, atomically.
func restoreBinary(binaryPath, backup string) error {
	if backup == "" {
		return errors.New("no backup was taken")
	}
	if _, err := os.Stat(backup); err != nil {
		return fmt.Errorf("backup %s is missing: %w", filepath.Base(backup), err)
	}
	staged := binaryPath + ".rollback"
	if err := copyFile(backup, staged, 0o755); err != nil {
		return err
	}
	if err := os.Rename(staged, binaryPath); err != nil {
		_ = os.Remove(staged)
		return err
	}
	return nil
}

func copyFile(source, destination string, mode os.FileMode) error {
	in, err := os.Open(source)
	if err != nil {
		return err
	}
	defer func() { _ = in.Close() }()
	out, err := os.OpenFile(destination, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, mode)
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, in); err != nil {
		_ = out.Close()
		return err
	}
	if err := out.Close(); err != nil {
		return err
	}
	// Explicit: O_CREATE honours the process umask, so the mode above is a ceiling
	// rather than a guarantee, and an executable that ended up 0644 would fail to
	// start with a confusing error.
	return os.Chmod(destination, mode)
}

// probeVersion executes a candidate binary to learn the version it reports.
//
// This is the "verify before you swap" step: the digest proves the artifact is the
// one the server published, and this proves the artifact is what its filename
// claims. Run against the staged copy, so a binary that cannot execute at all —
// wrong architecture, corrupt link — is caught while the installation is untouched.
func probeVersion(ctx context.Context, path string) (string, error) {
	cctx, cancel := contextWithTimeout(ctx, 10*time.Second)
	defer cancel()
	cmd := exec.CommandContext(cctx, path, "version")
	cmd.WaitDelay = 500 * time.Millisecond
	out, err := cmd.Output()
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(firstLine(string(out))), nil
}

func firstLine(text string) string {
	if index := strings.IndexByte(text, '\n'); index >= 0 {
		return text[:index]
	}
	return text
}

// CompareVersions orders two release versions: -1, 0 or 1.
//
// A pre-release sorts below the same final release, which is what makes the
// downgrade guard meaningful — without it, moving from `1.0.0` to `1.0.0-rc1` would
// look like a sideways move rather than the downgrade it is.
func CompareVersions(a, b string) int {
	pa, prea := parseVersion(a)
	pb, preb := parseVersion(b)
	for index := range pa {
		if pa[index] != pb[index] {
			if pa[index] < pb[index] {
				return -1
			}
			return 1
		}
	}
	switch {
	case prea == preb:
		return 0
	case prea == "":
		return 1
	case preb == "":
		return -1
	case prea < preb:
		return -1
	default:
		return 1
	}
}

var versionShape = regexp.MustCompile(`^(\d+)\.(\d+)\.(\d+)(?:-(.+))?$`)

func parseVersion(version string) ([3]int, string) {
	match := versionShape.FindStringSubmatch(strings.TrimSpace(version))
	if match == nil {
		return [3]int{}, ""
	}
	var parts [3]int
	for index := 0; index < 3; index++ {
		parts[index], _ = strconv.Atoi(match[index+1])
	}
	return parts, match[4]
}
