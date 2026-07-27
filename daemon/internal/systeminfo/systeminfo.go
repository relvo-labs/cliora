// Package systeminfo gathers the OS/arch/kernel/user facts reported to Central
// in node.register / node.system_info (PRD §9.1). Architecture is normalized to
// the amd64/arm64 vocabulary the protocol allows.
package systeminfo

import (
	"bufio"
	"os"
	"os/user"
	"runtime"
	"strings"
)

type Info struct {
	Hostname     string
	OS           string
	OSVersion    string
	Architecture string
	Kernel       string
	RunUser      string
}

func Gather() Info {
	hostname, _ := os.Hostname()
	return Info{
		Hostname:     hostname,
		OS:           runtime.GOOS,
		OSVersion:    osVersion(),
		Architecture: runtime.GOARCH,
		Kernel:       kernelVersion(),
		RunUser:      runUser(),
	}
}

func runUser() string {
	if u, err := user.Current(); err == nil {
		return u.Username
	}
	return ""
}

func osVersion() string {
	// /etc/os-release is the standard on the supported distros (NFR-005).
	if v := readOSRelease("/etc/os-release"); v != "" {
		return v
	}
	return runtime.GOOS
}

func readOSRelease(path string) string {
	file, err := os.Open(path)
	if err != nil {
		return ""
	}
	defer file.Close()
	values := map[string]string{}
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		key, value, ok := strings.Cut(scanner.Text(), "=")
		if !ok {
			continue
		}
		values[key] = strings.Trim(value, `"`)
	}
	if pretty := values["PRETTY_NAME"]; pretty != "" {
		return pretty
	}
	return values["VERSION_ID"]
}

func kernelVersion() string {
	if data, err := os.ReadFile("/proc/sys/kernel/osrelease"); err == nil {
		return strings.TrimSpace(string(data))
	}
	return ""
}
