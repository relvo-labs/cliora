package terminal

import (
	"context"
	"errors"
	"io"
	"os"
	"os/exec"
	"sync"

	"github.com/creack/pty"
)

type Process struct {
	mu        sync.Mutex
	file      *os.File
	cmd       *exec.Cmd
	cancel    context.CancelFunc
	done      chan struct{}
	once      sync.Once
	waitOnce  sync.Once
	detaching bool
	onExit    func(int)
}

// Attach starts command on a PTY and streams its output. output receives owned
// copies of each read. onExit (optional) fires exactly once with the process
// exit code when the child exits on its own (not on Detach/Close).
func Attach(parent context.Context, command *exec.Cmd, rows, columns uint16, output func([]byte) error, onExit func(int)) (*Process, error) {
	ctx, cancel := context.WithCancel(parent)
	command = exec.CommandContext(ctx, command.Path, command.Args[1:]...)
	f, err := pty.StartWithSize(command, &pty.Winsize{Rows: rows, Cols: columns})
	if err != nil {
		cancel()
		return nil, errors.New("pty attach failed")
	}
	p := &Process{file: f, cmd: command, cancel: cancel, done: make(chan struct{}), onExit: onExit}
	go func() {
		defer close(p.done)
		buf := make([]byte, 32*1024)
		for {
			n, readErr := f.Read(buf)
			if n > 0 {
				copied := append([]byte(nil), buf[:n]...)
				if output(copied) != nil {
					return
				}
			}
			if readErr != nil {
				p.mu.Lock()
				detaching := p.detaching
				p.mu.Unlock()
				if !detaching {
					code := p.wait()
					if p.onExit != nil {
						p.onExit(code)
					}
				}
				return
			}
		}
	}()
	return p, nil
}

// wait reaps the child exactly once and returns its exit code (-1 if unknown).
func (p *Process) wait() int {
	p.waitOnce.Do(func() { _ = p.cmd.Wait() })
	if p.cmd.ProcessState != nil {
		return p.cmd.ProcessState.ExitCode()
	}
	return -1
}

func (p *Process) Write(data []byte) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.file == nil {
		return io.ErrClosedPipe
	}
	_, err := p.file.Write(data)
	return err
}
func (p *Process) Resize(rows, columns uint16) error {
	if rows < 2 || rows > 300 || columns < 2 || columns > 500 {
		return errors.New("invalid terminal size")
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.file == nil {
		return io.ErrClosedPipe
	}
	return pty.Setsize(p.file, &pty.Winsize{Rows: rows, Cols: columns})
}

// Detach tears down the transport-side PTY for reattach without treating it as
// a process exit (no onExit fires).
func (p *Process) Detach() {
	p.mu.Lock()
	p.detaching = true
	if p.file != nil {
		_ = p.file.Close()
		p.file = nil
	}
	p.cancel()
	p.mu.Unlock()
}
func (p *Process) Close() {
	p.once.Do(func() {
		p.mu.Lock()
		p.detaching = true
		if p.file != nil {
			_ = p.file.Close()
			p.file = nil
		}
		p.cancel()
		p.mu.Unlock()
		<-p.done
		p.wait()
	})
}
