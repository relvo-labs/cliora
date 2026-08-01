package runtime

import (
	"context"
	"errors"
	"os/exec"
	"sort"
	"time"

	"github.com/cliora/cliora/daemon/internal/config"
)

const defaultDetectTimeout = 5 * time.Second

// Registry holds only the allowlisted runtimes present in config. An unknown
// runtime id in config is ignored here (config.Validate already rejects it).
type Registry struct {
	runtimes map[string]Runtime
}

func NewRegistry(cfg map[string]config.RuntimeConfig) *Registry {
	reg := &Registry{runtimes: map[string]Runtime{}}
	for id := range config.AllowedRuntimeIDs {
		rc, ok := cfg[id]
		reg.runtimes[id] = &cliRuntime{
			id:      id,
			enabled: ok && rc.Enabled,
			binary:  rc.Binary,
			timeout: defaultDetectTimeout,
			// Absent sandbox_bypass means enabled (ADR 0023 D2). config.Load fills the
			// key in, but hand-built maps (installer detection, doctor) come through
			// here too and must get the same default.
			bypassRequested: ok && rc.BypassSandbox(),
		}
	}
	return reg
}

func (r *Registry) Get(id string) (Runtime, bool) {
	rt, ok := r.runtimes[id]
	return rt, ok
}

// LaunchSpec is the complete launch description for an allowlisted runtime: the
// absolute binary plus the daemon's own arguments. Args never contains a string a
// caller, protocol message or config file supplied (SEC-002, ADR 0023 §2.4) — the
// node's only say is a boolean that turns an entry of the daemon's table off.
type LaunchSpec struct {
	Path string
	Args []string
}

// ResolveLaunch returns the launch spec for an allowlisted runtime, or a stable
// RUNTIME_* error code. The renderer never supplies a command; this is the only
// source of a session's argv (SEC-002). It replaces the earlier ResolveBinary
// rather than sitting beside it: two entry points would be two answers to "what
// gets launched", and one of them would have no arguments.
func (r *Registry) ResolveLaunch(id string) (LaunchSpec, error) {
	rt, ok := r.runtimes[id]
	if !ok {
		return LaunchSpec{}, errors.New(ReasonNotFound)
	}
	binary := rt.Binary()
	if binary == "" {
		return LaunchSpec{}, errors.New(ReasonDisabled)
	}
	path, err := exec.LookPath(binary)
	if err != nil {
		return LaunchSpec{}, errors.New(ReasonNotFound)
	}
	return LaunchSpec{Path: path, Args: rt.LaunchArgs()}, nil
}

// DetectAll probes every allowlisted runtime and returns results ordered by id.
func (r *Registry) DetectAll(ctx context.Context, now time.Time) []DetectResult {
	results := make([]DetectResult, 0, len(r.runtimes))
	for _, rt := range r.runtimes {
		results = append(results, rt.Detect(ctx, now))
	}
	sort.Slice(results, func(i, j int) bool { return results[i].Runtime < results[j].Runtime })
	return results
}
