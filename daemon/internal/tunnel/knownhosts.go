package tunnel

import (
	_ "embed"
	"os"
	"sync"
)

// The provider's pinned host keys travel inside the binary.
//
// They used to live only at /etc/agentd/pinggy_known_hosts, placed there by the
// installer — except no installer step was ever written, so the file was absent on
// every node. That is not a tunnel bug you find when you open a tunnel: `agentd
// doctor` hard-failed on the missing file, `agentd update` health checks with
// doctor, and so *every* update from a pre-tunnel release rolled straight back
// (P11 → P4-10 interaction; see docs/runbooks/update-failure.md).
//
// Embedding fixes the class, not just the instance. The keys are release content:
// they are decided when the release is built, they are covered by the artifact
// digest the updater already verifies, and a node that installs a binary therefore
// has them by definition. There is no separate file to deploy, to forget, or to
// leave behind when a node upgrades rather than reinstalls.
//
// Rotation still works out of band: an on-disk file at the configured path
// overrides these, so an operator can pin a new key the moment the provider
// rotates one, without waiting for a release. See docs/runbooks/tunnel-pinggy.md.
//
//go:embed pinggy_known_hosts
var embeddedKnownHosts []byte

// KnownHosts is a resolved pinned-key file: a path ssh can be pointed at, plus
// where its contents came from, which is the part an operator needs when the
// answer surprises them.
type KnownHosts struct {
	Path string
	// Source is SourceFile when the node's own file was used and SourceBuild when
	// the keys shipped in this binary were materialized.
	Source string
}

const (
	SourceFile  = "file"
	SourceBuild = "build"
)

// FromBuild reports whether the resolved keys came from the binary.
func (k KnownHosts) FromBuild() bool { return k.Source == SourceBuild }

var (
	materializedMu   sync.Mutex
	materializedPath string
)

// ResolveKnownHosts turns the configured path into a usable pinned-key file.
//
// The node's own file wins whenever it is usable: that is the rotation escape
// hatch, and an operator who wrote a key there means it. Otherwise the embedded
// keys are written to a private file — ssh takes a path, not a blob, so something
// has to land on disk.
//
// What this never does is widen trust. Both branches produce a file with real keys
// in it and a caller that passes StrictHostKeyChecking=yes; the failure mode of a
// stale pin is a refused tunnel (TUNNEL_PROVIDER_UNTRUSTED), never an accepted
// unknown key.
func ResolveKnownHosts(configuredPath string) (KnownHosts, error) {
	if knownHostsUsable(configuredPath) {
		return KnownHosts{Path: configuredPath, Source: SourceFile}, nil
	}
	path, err := materializeKnownHosts()
	if err != nil {
		return KnownHosts{}, err
	}
	return KnownHosts{Path: path, Source: SourceBuild}, nil
}

// materializeKnownHosts writes the embedded keys to a private file, once per
// process. The path is re-checked on every call rather than cached blindly: these
// files live in the temp directory for the lifetime of a daemon that may run for
// weeks, and a tmpfiles cleaner removing one must cost a rewrite, not every tunnel
// from then on.
func materializeKnownHosts() (string, error) {
	materializedMu.Lock()
	defer materializedMu.Unlock()

	if knownHostsUsable(materializedPath) {
		return materializedPath, nil
	}
	if len(embeddedKnownHosts) == 0 {
		// Unreachable with a correctly built binary — the embed directive fails the
		// build if the file is absent — but an empty pin must refuse rather than
		// hand ssh a file that trusts nothing and reports it as a network error.
		return "", ErrKnownHostsMissing
	}

	// 0600 and a random name. The contents are public keys, so secrecy is not the
	// point; not letting another local user replace the file between this write and
	// ssh reading it is.
	file, err := os.CreateTemp("", "agentd-known-hosts-*")
	if err != nil {
		return "", err
	}
	defer file.Close()
	if _, err := file.Write(embeddedKnownHosts); err != nil {
		_ = os.Remove(file.Name())
		return "", err
	}
	if err := file.Sync(); err != nil {
		_ = os.Remove(file.Name())
		return "", err
	}
	materializedPath = file.Name()
	return materializedPath, nil
}

// knownHostsUsable reports whether a pinned file exists and has content. An empty
// file would make every connection fail with "no host key is known", which is the
// safe direction but a confusing message; checking here lets the daemon say what is
// actually wrong — and lets an emptied file fall through to the embedded keys
// instead of taking tunnels down.
func knownHostsUsable(path string) bool {
	if path == "" {
		return false
	}
	info, err := os.Stat(path)
	return err == nil && !info.IsDir() && info.Size() > 0
}
