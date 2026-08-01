// faketunnelapp is the web application a port-forwarding end-to-end test forwards
// (plan/11 §3.2). It listens on loopback and answers every request with a marker, so a test
// can tell "the app answered" apart from "something answered".
//
// A Go binary rather than `python -m http.server` for two reasons: CI always has the Go
// toolchain (it builds the daemon), and this can be imported by a Go test as well as run by
// the stack script. It is the same role `cmd/fakecli` plays for the terminal path.
package main

import (
	"flag"
	"fmt"
	"log"
	"net/http"
)

// The marker a test greps for. Deliberately not a word that appears anywhere else in the
// repository, so a matching page cannot be some other fixture.
const marker = "CLIORA_TUNNEL_APP_MARKER"

func main() {
	addr := flag.String("addr", "127.0.0.1:5199", "loopback address to listen on")
	flag.Parse()

	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		// The Host header is echoed because it is the one thing PG-01 measured that surprises
		// people: the app receives the tunnel's hostname, not loopback, unless the Host
		// rewrite is asked for. A test can assert which one arrived.
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		fmt.Fprintf(w, "<!doctype html><title>%s</title><p>%s</p><p>host: %s</p><p>path: %s</p>",
			marker, marker, r.Host, r.URL.Path)
	})

	server := &http.Server{Addr: *addr, Handler: mux}
	log.Printf("faketunnelapp listening on %s", *addr)
	if err := server.ListenAndServe(); err != nil {
		log.Fatal(err)
	}
}
