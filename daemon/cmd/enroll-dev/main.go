// Command enroll-dev is a rootless enrollment helper for local/CI end-to-end
// runs. It reuses the same internal/install code path as `agentd install`
// (keypair → POST /api/nodes/register → config + credentials), but writes the
// 0600 files to caller-chosen paths without chown/systemd, and forces an
// allowlisted runtime (claude) to point at an arbitrary binary — the Fake CLI —
// so the e2e stack has an online node with a launchable runtime and no real
// Claude/Codex install. It is a dev/test tool (like cmd/fakecli) and is never
// shipped in the agentd binary.
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/user"
	"path/filepath"
	"time"

	"gopkg.in/yaml.v3"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/cliora/cliora/daemon/internal/install"
	"github.com/cliora/cliora/daemon/internal/runtime"
	"github.com/cliora/cliora/daemon/internal/systeminfo"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "enroll-dev:", err)
		os.Exit(1)
	}
}

func run() error {
	var (
		server        string
		token         string
		name          string
		workspaceRoot string
		runtimeBinary string
		configPath    string
		credsPath     string
		allowInsecure bool
	)
	flag.StringVar(&server, "server", "", "Central base URL (http://127.0.0.1:8000)")
	flag.StringVar(&token, "token", "", "one-time enrollment token")
	flag.StringVar(&name, "name", "e2e-node", "node name")
	flag.StringVar(&workspaceRoot, "workspace-root", "", "allowed workspace root (absolute)")
	flag.StringVar(&runtimeBinary, "runtime-binary", "", "binary to launch for the 'claude' runtime (e.g. the fakecli path)")
	flag.StringVar(&configPath, "config", "", "output path for config.yaml")
	flag.StringVar(&credsPath, "credentials", "", "output path for credentials.yaml")
	flag.BoolVar(&allowInsecure, "allow-insecure", true, "permit http/ws server URL (dev default)")
	flag.Parse()

	if server == "" || token == "" || workspaceRoot == "" || runtimeBinary == "" ||
		configPath == "" || credsPath == "" {
		return fmt.Errorf("--server, --token, --workspace-root, --runtime-binary, --config and --credentials are required")
	}
	abs, err := filepath.Abs(runtimeBinary)
	if err != nil {
		return err
	}
	if _, err := os.Stat(abs); err != nil {
		return fmt.Errorf("runtime binary %q not found: %w", abs, err)
	}

	runUser := "e2e"
	if u, err := user.Current(); err == nil {
		runUser = u.Username
	}

	publicKey, privateKey, err := config.GenerateKeypair()
	if err != nil {
		return err
	}

	now := time.Now()
	// Present the Fake CLI as the allowlisted "claude" runtime: available, with
	// its resolved binary path, so both the register report and generated config
	// enable it (BuildConfig only enables Available runtimes).
	detected := []runtime.DetectResult{{
		Runtime:    "claude",
		Available:  true,
		Version:    "fakecli 1.0.0",
		BinaryPath: abs,
		CheckedAt:  now,
	}}

	params := install.Params{
		Server:         server,
		Token:          token,
		NodeName:       name,
		RunUser:        runUser,
		WorkspaceRoots: []string{workspaceRoot},
		AllowInsecure:  allowInsecure,
		DaemonVersion:  "e2e",
		PublicKey:      publicKey,
		HeartbeatSecs:  2,
	}

	info := systeminfo.Gather()
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	resp, err := install.Register(ctx, install.DefaultClient(), server,
		install.BuildRegisterRequest(params, info, detected))
	if err != nil {
		return fmt.Errorf("register: %w", err)
	}

	cfg, err := install.BuildConfig(params, detected)
	if err != nil {
		return err
	}
	cfgData, err := install.MarshalConfig(cfg)
	if err != nil {
		return err
	}
	credsData, err := yaml.Marshal(config.Credentials{NodeID: resp.NodeID, PrivateKey: privateKey})
	if err != nil {
		return err
	}
	if err := writeFile(configPath, cfgData); err != nil {
		return err
	}
	if err := writeFile(credsPath, credsData); err != nil {
		return err
	}

	fmt.Printf("enrolled node %s (runtime claude -> %s)\n", resp.NodeID, abs)
	fmt.Printf("config: %s\ncredentials: %s\n", configPath, credsPath)
	return nil
}

// writeFile writes at 0600 (config.Load/LoadCredentials reject broader modes)
// under the current user, no chown — the daemon runs as that same user here.
func writeFile(path string, data []byte) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	if err := os.WriteFile(path, data, 0o600); err != nil {
		return err
	}
	return os.Chmod(path, 0o600)
}
