package systeminfo

import (
	"os"
	"path/filepath"
	"testing"
)

func TestGather(t *testing.T) {
	info := Gather()
	if info.OS == "" || info.Architecture == "" {
		t.Fatalf("os/arch must be populated: %+v", info)
	}
	if info.RunUser == "" {
		t.Errorf("run user should be populated")
	}
}

func TestReadOSReleasePrefersPrettyName(t *testing.T) {
	path := filepath.Join(t.TempDir(), "os-release")
	content := "NAME=\"Ubuntu\"\nVERSION_ID=\"24.04\"\nPRETTY_NAME=\"Ubuntu 24.04.1 LTS\"\n"
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	if got := readOSRelease(path); got != "Ubuntu 24.04.1 LTS" {
		t.Errorf("got %q", got)
	}
}

func TestReadOSReleaseFallsBackToVersionID(t *testing.T) {
	path := filepath.Join(t.TempDir(), "os-release")
	if err := os.WriteFile(path, []byte("VERSION_ID=\"12\"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if got := readOSRelease(path); got != "12" {
		t.Errorf("got %q", got)
	}
}
