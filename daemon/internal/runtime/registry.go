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
		}
	}
	return reg
}

func (r *Registry) Get(id string) (Runtime, bool) {
	rt, ok := r.runtimes[id]
	return rt, ok
}

// ResolveBinary returns the absolute launch binary for an allowlisted runtime,
// or a stable RUNTIME_* error code. The renderer never supplies a command; this
// is the only source of the launch argv[0] (SEC-002).
func (r *Registry) ResolveBinary(id string) (string, error) {
	rt, ok := r.runtimes[id]
	if !ok {
		return "", errors.New(ReasonNotFound)
	}
	binary := rt.Binary()
	if binary == "" {
		return "", errors.New(ReasonDisabled)
	}
	path, err := exec.LookPath(binary)
	if err != nil {
		return "", errors.New(ReasonNotFound)
	}
	return path, nil
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
