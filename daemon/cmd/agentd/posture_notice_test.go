package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// SEC-007.AC-02: installation must state that this node's terminal can reach root and
// that codex runs without a sandbox. It is asserted here rather than left to a reviewer
// because it is the one part of the posture an operator cannot discover afterwards by
// reading the console — by then the machine is already installed.
func TestInstallerStatesThePrivilegedPosture(t *testing.T) {
	var out bytes.Buffer
	printPostureNotice(&out, true)
	text := out.String()
	for _, want := range []string{"sudo", "root", "codex", "sandbox", "--privileged-terminal=false"} {
		if !strings.Contains(text, want) {
			t.Errorf("the privileged notice does not mention %q:\n%s", want, text)
		}
	}
	// It must also say what to do instead, or it is a warning with no exit.
	if !strings.Contains(text, "sandbox_bypass: false") {
		t.Errorf("the notice does not say how to keep the sandbox:\n%s", text)
	}
}

func TestInstallerStatesTheUnprivilegedPostureToo(t *testing.T) {
	// Silence would be worse here than in the privileged case: an operator who passed
	// --no-privileged-terminal needs to learn that it did not also turn off the codex
	// bypass, which is a separate switch (ADR 0023 §4).
	var out bytes.Buffer
	printPostureNotice(&out, false)
	text := out.String()
	if !strings.Contains(text, "cannot escalate") {
		t.Errorf("the unprivileged notice does not state the posture:\n%s", text)
	}
	if !strings.Contains(text, "sandbox_bypass: false") {
		t.Errorf("the unprivileged notice does not mention the separate codex switch:\n%s", text)
	}
}

// The shell installer is thin by design, so the flag has to reach the binary. A default
// that only exists in one of the two places is how a fleet ends up half in each posture.
func TestInstallScriptPassesThePostureFlagExplicitly(t *testing.T) {
	data, err := os.ReadFile(filepath.Join("..", "..", "..", "deploy", "install.sh"))
	if err != nil {
		t.Fatal(err)
	}
	script := string(data)
	for _, want := range []string{
		"--no-privileged-terminal",
		"--privileged-terminal=true",
		"--privileged-terminal=false",
	} {
		if !strings.Contains(script, want) {
			t.Errorf("install.sh never uses %q", want)
		}
	}
}
