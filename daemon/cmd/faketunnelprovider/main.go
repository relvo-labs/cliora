// faketunnelprovider stands in for the provider's ssh client in end-to-end tests
// (plan/11 §3.2). It is invoked exactly where `ssh` would be, prints a URL the way the real
// service does, and then stays alive until it is signalled.
//
// Why a binary rather than the real thing: the browser suite has to exercise Central, the
// protocol, the supervisor and the pages together, and doing that against the real provider
// would make the suite depend on a third party's availability, an account, and outbound
// network. A CI that goes red when somebody else has an outage is a CI whose red means
// nothing.
//
// Why the URL is on `.example.invalid`: RFC 2606 guarantees it never resolves. The suite
// asserts that the URL is *shown*, with `target="_blank"` and `rel="noopener noreferrer"` —
// it must not open it. A fake hostname that could resolve would eventually be opened by
// somebody's browser, or by a well-meaning retry in a test.
//
// The banner text mirrors what PG-01 measured, including the two lines before the URL and the
// "You are not authenticated." line the free tier prints, because the daemon's parser is
// written against that shape and a fake that is tidier than reality tests a parser nobody
// runs.
package main

import (
	"fmt"
	"math/rand/v2"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"
)

// Modes, chosen with FAKE_PROVIDER_MODE. `ok` is the free tier: anonymous, hourly expiry.
const (
	modeOK            = "ok"
	modeAuthenticated = "authenticated"
	modeHostKey       = "hostkey"
	modeNoURL         = "nourl"
	modeShortLived    = "shortlived"
)

func main() {
	mode := strings.TrimSpace(os.Getenv("FAKE_PROVIDER_MODE"))
	if mode == "" {
		mode = modeOK
	}
	// Recorded so a test can assert what the daemon actually passed — the host key options
	// especially, which are the one thing that must never be missing.
	if path := os.Getenv("FAKE_PROVIDER_ARGS_FILE"); path != "" {
		_ = os.WriteFile(path, []byte(strings.Join(os.Args[1:], " ")+"\n"), 0o600)
	}

	switch mode {
	case modeHostKey:
		// Byte-for-byte what OpenSSH says, because the daemon classifies failures by matching
		// this string (the fragile part of integrating a third party, ADR 0022).
		fmt.Fprintln(os.Stderr, "No RSA host key is known for free.pinggy.io and you have requested strict checking.")
		fmt.Fprintln(os.Stderr, "Host key verification failed.")
		os.Exit(255)
	case modeNoURL:
		fmt.Println("some unrelated chatter")
	case modeAuthenticated:
		fmt.Printf("https://%s.pinggy.link\n", slug())
	default:
		fmt.Println("You are not authenticated.")
		fmt.Println("Your tunnel will expire in 60 minutes. Upgrade to Pinggy Pro to get unrestricted tunnels. https://dashboard.pinggy.io")
		// Two URLs, one per measured suffix — except that a fake must not print a real
		// provider domain, so both carry the reserved TLD and the daemon's suffix allowlist
		// is widened for tests only through the same environment variable that selects this
		// binary. The shape (slug plus what looks like an IP) is the free tier's.
		fmt.Printf("https://%s-203-0-113-7.tunnel.example.invalid\n", slug())
	}
	if mode == modeShortLived {
		// Exits immediately after announcing: the reconnect path's trigger.
		return
	}

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGTERM, syscall.SIGINT)
	select {
	case <-stop:
	case <-time.After(lifetime()):
	}
}

func slug() string {
	const alphabet = "abcdefghijklmnopqrstuvwxyz"
	out := make([]byte, 5)
	for i := range out {
		out[i] = alphabet[rand.IntN(len(alphabet))]
	}
	return string(out)
}

func lifetime() time.Duration {
	if raw := os.Getenv("FAKE_PROVIDER_LIFETIME_SECONDS"); raw != "" {
		if seconds, err := time.ParseDuration(raw + "s"); err == nil {
			return seconds
		}
	}
	return time.Hour
}
