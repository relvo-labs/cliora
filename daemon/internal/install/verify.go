package install

import (
	"context"
	"fmt"
	"net"
	"net/url"
	"time"
)

// ActiveChecker reports whether the installed service is currently active. It is
// injected so the post-start verification can be unit tested without systemd.
type ActiveChecker func(context.Context) (bool, error)

// VerifyConnection runs a bounded, best-effort post-start check (P1-15): it waits
// for the service to report active and confirms the Central endpoint is
// TCP-reachable. It never logs or returns the enrollment token or node secret —
// only the generic host it could not reach. The whole check is capped by timeout
// so `agentd install` cannot hang.
func VerifyConnection(ctx context.Context, wsURL string, active ActiveChecker, timeout time.Duration) error {
	cctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	if err := waitActive(cctx, active); err != nil {
		return err
	}
	if err := reachCentral(cctx, wsURL); err != nil {
		return err
	}
	return nil
}

// waitActive polls the service state until it is active or the context expires.
func waitActive(ctx context.Context, active ActiveChecker) error {
	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()
	for {
		ok, err := active(ctx)
		if ok {
			return nil
		}
		select {
		case <-ctx.Done():
			if err != nil {
				return fmt.Errorf("service did not become active")
			}
			return fmt.Errorf("service did not become active within the timeout")
		case <-ticker.C:
		}
	}
}

// reachCentral confirms the Central host:port accepts a TCP connection. It
// derives the port from the ws/wss scheme and reports only the host on failure.
func reachCentral(ctx context.Context, wsURL string) error {
	u, err := url.Parse(wsURL)
	if err != nil || u.Host == "" {
		return fmt.Errorf("invalid central url")
	}
	hostport := u.Host
	if u.Port() == "" {
		port := "443"
		if u.Scheme == "ws" {
			port = "80"
		}
		hostport = net.JoinHostPort(u.Hostname(), port)
	}
	var d net.Dialer
	conn, err := d.DialContext(ctx, "tcp", hostport)
	if err != nil {
		return fmt.Errorf("central %s not reachable after start", u.Host)
	}
	_ = conn.Close()
	return nil
}
