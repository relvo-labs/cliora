package tmux

import (
	"context"
	"errors"
	"os/exec"
	"regexp"
	"strconv"
	"strings"

	"github.com/google/uuid"
)

const Prefix = "cliora-"

var namePattern = regexp.MustCompile(`^cliora-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

type Size struct {
	Rows    uint16
	Columns uint16
}
type StartSpec struct {
	SessionID   uuid.UUID
	RuntimeID   string
	WorkspaceID uuid.UUID
	Workspace   string
	Binary      string
	Size        Size
}
type Snapshot struct {
	Bytes     []byte
	Truncated bool
}

func Name(id uuid.UUID) (string, error) {
	if id == uuid.Nil {
		return "", errors.New("invalid session")
	}
	return Prefix + strings.ToLower(id.String()), nil
}
func ValidName(name string) bool { return namePattern.MatchString(name) }
func validSize(s Size) bool {
	return s.Rows >= 2 && s.Rows <= 300 && s.Columns >= 2 && s.Columns <= 500
}

type Client struct{ Socket string }

func (c Client) args(args ...string) []string {
	if c.Socket == "" {
		return args
	}
	return append([]string{"-L", c.Socket}, args...)
}

func allowedRuntimeID(id string) bool {
	return id == "claude" || id == "codex" || id == "fake"
}

func (c Client) Start(ctx context.Context, s StartSpec) error {
	if !allowedRuntimeID(s.RuntimeID) || !validSize(s.Size) || s.Binary == "" || s.Workspace == "" {
		return errors.New("invalid start spec")
	}
	name, err := Name(s.SessionID)
	if err != nil {
		return err
	}
	cmd := exec.CommandContext(ctx, "tmux", c.args("new-session", "-d", "-x", strconv.Itoa(int(s.Size.Columns)), "-y", strconv.Itoa(int(s.Size.Rows)), "-s", name, "-c", s.Workspace, s.Binary)...)
	if cmd.Run() != nil {
		return errors.New("tmux start failed")
	}
	return nil
}
func (c Client) Exists(ctx context.Context, id uuid.UUID) (bool, error) {
	name, err := Name(id)
	if err != nil {
		return false, err
	}
	err = exec.CommandContext(ctx, "tmux", c.args("has-session", "-t", name)...).Run()
	if err == nil {
		return true, nil
	}
	var exit *exec.ExitError
	if errors.As(err, &exit) {
		return false, nil
	}
	return false, errors.New("tmux unavailable")
}
func (c Client) Stop(ctx context.Context, id uuid.UUID) error {
	name, err := Name(id)
	if err != nil {
		return err
	}
	exists, err := c.Exists(ctx, id)
	if err != nil || !exists {
		return err
	}
	if exec.CommandContext(ctx, "tmux", c.args("kill-session", "-t", name)...).Run() != nil {
		return errors.New("tmux stop failed")
	}
	return nil
}
func (c Client) Capture(ctx context.Context, id uuid.UUID, max int) (Snapshot, error) {
	name, err := Name(id)
	if err != nil {
		return Snapshot{}, err
	}
	out, err := exec.CommandContext(ctx, "tmux", c.args("capture-pane", "-p", "-e", "-S", "-", "-t", name)...).Output()
	if err != nil {
		return Snapshot{}, errors.New("tmux capture failed")
	}
	result := Snapshot{Bytes: out}
	if len(out) > max {
		result.Bytes = append([]byte(nil), out[len(out)-max:]...)
		result.Truncated = true
	}
	return result, nil
}
