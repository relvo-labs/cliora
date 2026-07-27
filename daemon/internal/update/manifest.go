package update

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// Artifact mirrors one entry of Central's release manifest. The daemon treats
// every field as data to *verify against*, never as an instruction: `Filename` is
// re-checked against the closed name pattern before it is used, because a
// compromised or buggy server must not be able to turn a filename into a path.
type Artifact struct {
	Version      string `json:"version"`
	Architecture string `json:"architecture"`
	Filename     string `json:"filename"`
	SHA256       string `json:"sha256"`
	Size         int64  `json:"size"`
}

type Manifest struct {
	Latest    string     `json:"latest"`
	Artifacts []Artifact `json:"artifacts"`
}

// artifactName is the same closed shape Central's allowlist uses. Re-validated on
// this side so a manifest entry can never introduce a path separator, a traversal
// segment, or a name the download endpoint would refuse anyway.
var artifactName = regexp.MustCompile(`^agentd_[0-9A-Za-z.+_-]+_linux_(?:amd64|arm64)\.tar\.gz$`)

var sha256Hex = regexp.MustCompile(`^[0-9a-f]{64}$`)

// Find returns the artifact for one version and architecture.
//
// Every reason for "no" collapses to the same answer, on purpose: an unknown
// version, an architecture that was not built, a malformed digest and an
// unacceptable filename are all "not an allowlisted release", and treating any of
// them as a special case would mean acting on a manifest entry that failed
// validation.
func (m Manifest) Find(version, architecture string) (Artifact, bool) {
	for _, artifact := range m.Artifacts {
		if artifact.Version != version || artifact.Architecture != architecture {
			continue
		}
		if !artifactName.MatchString(artifact.Filename) {
			continue
		}
		if !sha256Hex.MatchString(artifact.SHA256) {
			continue
		}
		if artifact.Size <= 0 {
			continue
		}
		return artifact, true
	}
	return Artifact{}, false
}

// ManifestFetcher reads the release manifest. An interface so tests can supply one
// without a server, and so the only implementation that touches the network is the
// one below, which derives its URL from local config.
type ManifestFetcher interface {
	Fetch(ctx context.Context) (Manifest, error)
}

// Downloader retrieves one artifact to a local path.
type Downloader interface {
	Download(ctx context.Context, artifact Artifact, destination string) error
}

// maxManifestBytes bounds the manifest read so a hostile or broken server cannot
// stream unbounded JSON into memory.
const maxManifestBytes = 1 << 20

// downloadSlack allows the served file to differ slightly from the manifest's
// recorded size without failing the read; the digest is the real check, this only
// bounds how much is read at all.
const downloadSlack = 4096

// HTTPSource fetches the manifest and artifacts from one Central base URL.
//
// The base URL comes from this node's config file and nothing else. That is the
// whole point: the update protocol carries no URL, so there is no path by which a
// remote caller can redirect where a binary comes from (SEC-002).
type HTTPSource struct {
	BaseURL string
	Client  *http.Client
}

// NewHTTPSource derives the artifact origin from the configured Central WebSocket
// URL, since that is the one server address a node is already trusting.
//
// `ws://` maps to `http://` and `wss://` to `https://`. A non-ws scheme is
// rejected rather than passed through: it would mean the config is not what this
// function's caller believes, and guessing is how a downgrade to plaintext
// happens silently.
func NewHTTPSource(serverWSURL string, client *http.Client) (*HTTPSource, error) {
	base, err := HTTPBase(serverWSURL)
	if err != nil {
		return nil, err
	}
	if client == nil {
		client = &http.Client{Timeout: 5 * time.Minute}
	}
	return &HTTPSource{BaseURL: base, Client: client}, nil
}

// HTTPBase converts the configured ws(s) endpoint into its http(s) origin.
func HTTPBase(serverWSURL string) (string, error) {
	parsed, err := url.Parse(strings.TrimSpace(serverWSURL))
	if err != nil || parsed.Host == "" {
		return "", errors.New("server.url in config.yaml is not a valid URL")
	}
	switch parsed.Scheme {
	case "wss":
		parsed.Scheme = "https"
	case "ws":
		parsed.Scheme = "http"
	default:
		return "", fmt.Errorf("server.url must be ws:// or wss:// (got %q)", parsed.Scheme)
	}
	// The configured URL points at /ws/nodes; the artifact endpoints live at the
	// origin, so only scheme and host are kept.
	return parsed.Scheme + "://" + parsed.Host, nil
}

func (s *HTTPSource) Fetch(ctx context.Context) (Manifest, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, s.BaseURL+"/api/releases/manifest", nil)
	if err != nil {
		return Manifest{}, err
	}
	resp, err := s.Client.Do(req)
	if err != nil {
		return Manifest{}, errors.New("cannot reach the release manifest")
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		return Manifest{}, fmt.Errorf("release manifest returned HTTP %d", resp.StatusCode)
	}
	var manifest Manifest
	if err := json.NewDecoder(io.LimitReader(resp.Body, maxManifestBytes)).Decode(&manifest); err != nil {
		return Manifest{}, errors.New("release manifest is not valid JSON")
	}
	return manifest, nil
}

func (s *HTTPSource) Download(ctx context.Context, artifact Artifact, destination string) error {
	// The filename is validated here as well as in Find: this method is the one that
	// puts a server-supplied string into a URL path, so it re-checks rather than
	// trusting an earlier caller to have done it.
	if !artifactName.MatchString(artifact.Filename) {
		return errors.New("artifact filename is not an allowlisted release name")
	}
	target := s.BaseURL + "/api/downloads/" + url.PathEscape(artifact.Filename)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, target, nil)
	if err != nil {
		return err
	}
	resp, err := s.Client.Do(req)
	if err != nil {
		return errors.New("cannot download the release artifact")
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		return errors.New("release artifact download returned HTTP " + strconv.Itoa(resp.StatusCode))
	}
	// Bounded by the manifest's recorded size: a server that streams forever must
	// not be able to fill the disk. The digest check that follows is what decides
	// whether the bytes are the right ones.
	return writeBounded(destination, io.LimitReader(resp.Body, artifact.Size+downloadSlack))
}
