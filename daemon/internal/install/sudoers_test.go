package install

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// testInstaller writes into a temp directory with a stub validator, so none of these
// tests need root and none of them can touch the real /etc/sudoers.d — which, given
// what a bad file there does to a machine, is not a convenience but a requirement.
func testInstaller(t *testing.T, validate func(path string) error) *SudoersInstaller {
	t.Helper()
	return &SudoersInstaller{
		Path:   filepath.Join(t.TempDir(), "60-agentd"),
		Visudo: "visudo-stub",
		Runner: func(_ context.Context, _ string, args ...string) error {
			// The production call is `visudo -c -f <path>`; assert the shape so a
			// refactor cannot quietly stop validating.
			if len(args) != 3 || args[0] != "-c" || args[1] != "-f" {
				return errors.New("unexpected validator invocation")
			}
			return validate(args[2])
		},
		LookPathF: func(string) (string, error) { return "/usr/sbin/visudo-stub", nil },
		Verifier:  nil, // verified separately; requires a real user and sudo
	}
}

func TestSudoersContentRejectsAnythingThatIsNotAUserName(t *testing.T) {
	for _, user := range []string{
		"neil; rm -rf /",
		"root ALL=(ALL) NOPASSWD:ALL",
		"neil\nmallory ALL=(ALL) NOPASSWD:ALL",
		"",
		"Neil",
		"1neil",
		strings.Repeat("a", 33),
	} {
		if _, err := SudoersContent(user); err == nil {
			t.Errorf("accepted %q as a user name", user)
		}
	}
}

func TestSudoersContentIsOneGrantWithItsReasoning(t *testing.T) {
	content, err := SudoersContent("neil")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(content, "neil ALL=(ALL) NOPASSWD:ALL") {
		t.Errorf("missing the grant:\n%s", content)
	}
	// The file is read by whoever audits the machine, and the two questions they
	// will have are "who put this here" and "how do I take it away".
	for _, want := range []string{"Managed by agentd", "ADR 0023", "posture --privileged-terminal=false"} {
		if !strings.Contains(content, want) {
			t.Errorf("content does not explain %q:\n%s", want, content)
		}
	}
	// Exactly one non-comment line: an extra directive here is an extra grant.
	grants := 0
	for _, line := range strings.Split(strings.TrimSpace(content), "\n") {
		if line != "" && !strings.HasPrefix(line, "#") {
			grants++
		}
	}
	if grants != 1 {
		t.Errorf("content has %d directives, want 1:\n%s", grants, content)
	}
}

func TestInstallWritesAValidatedFileWithSudosRequiredMode(t *testing.T) {
	validated := ""
	s := testInstaller(t, func(path string) error { validated = path; return nil })
	if err := s.Install(context.Background(), "neil"); err != nil {
		t.Fatalf("Install: %v", err)
	}
	if validated == "" {
		t.Error("the file was installed without being validated")
	}
	if validated == s.Path {
		t.Error("validation must run on the temp file, before it is in place")
	}
	info, err := os.Stat(s.Path)
	if err != nil {
		t.Fatal(err)
	}
	// sudo silently ignores a drop-in that is more permissive than 0440, so this
	// mode is correctness, not tidiness.
	if info.Mode().Perm() != SudoersMode.Perm() {
		t.Errorf("mode = %o, want %o", info.Mode().Perm(), SudoersMode.Perm())
	}
}

// A rejected file must leave nothing behind — not the target, and not the temp file
// either. A machine cannot be left one syntax error away from having no sudo.
func TestInstallLeavesNothingBehindWhenValidationFails(t *testing.T) {
	s := testInstaller(t, func(string) error { return errors.New("syntax error near line 5") })
	err := s.Install(context.Background(), "neil")
	if err == nil {
		t.Fatal("Install succeeded with a rejected file")
	}
	if !strings.Contains(err.Error(), "rejected") {
		t.Errorf("error does not say the file was rejected: %v", err)
	}
	if _, statErr := os.Stat(s.Path); statErr == nil {
		t.Error("a rejected file was installed anyway")
	}
	entries, _ := os.ReadDir(filepath.Dir(s.Path))
	if len(entries) != 0 {
		names := []string{}
		for _, e := range entries {
			names = append(names, e.Name())
		}
		t.Errorf("temp files left behind: %v", names)
	}
}

// No validator means no safe way to install this file. Refusing is the only correct
// answer: "write it and hope" is how a machine loses sudo entirely.
func TestInstallRefusesWhenVisudoIsMissing(t *testing.T) {
	s := testInstaller(t, func(string) error { return nil })
	s.LookPathF = func(string) (string, error) { return "", errors.New("not found") }
	if err := s.Install(context.Background(), "neil"); err == nil {
		t.Fatal("Install proceeded without a validator")
	}
	if _, statErr := os.Stat(s.Path); statErr == nil {
		t.Error("a file was written without validation")
	}
}

func TestInstallRollsBackWhenSudoDoesNotActuallyWork(t *testing.T) {
	s := testInstaller(t, func(string) error { return nil })
	s.Verifier = func(context.Context, string) error { return errors.New("sudo: a password is required") }
	if err := s.Install(context.Background(), "neil"); err == nil {
		t.Fatal("Install reported success although sudo did not work")
	}
	if _, statErr := os.Stat(s.Path); statErr == nil {
		t.Error("the drop-in was left in place after a failed verification")
	}
}

func TestInstallRestoresThePreviousFileOnFailedVerification(t *testing.T) {
	s := testInstaller(t, func(string) error { return nil })
	previous := "# previous grant\nolduser ALL=(ALL) NOPASSWD:ALL\n"
	if err := os.WriteFile(s.Path, []byte(previous), SudoersMode); err != nil {
		t.Fatal(err)
	}
	s.Verifier = func(context.Context, string) error { return errors.New("nope") }
	if err := s.Install(context.Background(), "neil"); err == nil {
		t.Fatal("expected failure")
	}
	data, err := os.ReadFile(s.Path)
	if err != nil {
		t.Fatalf("the previous file was not restored: %v", err)
	}
	if string(data) != previous {
		t.Errorf("restored content = %q, want the previous grant", string(data))
	}
}

func TestRemoveIsIdempotent(t *testing.T) {
	s := testInstaller(t, func(string) error { return nil })
	if err := s.Remove(); err != nil {
		t.Errorf("removing an absent drop-in should succeed: %v", err)
	}
	if err := s.Install(context.Background(), "neil"); err != nil {
		t.Fatal(err)
	}
	if err := s.Remove(); err != nil {
		t.Fatalf("Remove: %v", err)
	}
	if s.Installed() {
		t.Error("Installed() is true after Remove")
	}
}
