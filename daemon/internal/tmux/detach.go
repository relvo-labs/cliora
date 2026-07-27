package tmux

import (
	"context"
	"os/exec"

	"github.com/google/uuid"
)

// DetachClients removes transport clients without stopping the owned tmux session.
func (c Client) DetachClients(ctx context.Context, id uuid.UUID) error {
	name, err := Name(id)
	if err != nil {
		return err
	}
	command := exec.CommandContext(ctx, "tmux", c.args("detach-client", "-s", name)...)
	if err := command.Run(); err != nil {
		return nil
	}
	return nil
}
