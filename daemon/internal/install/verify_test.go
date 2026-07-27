package install

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestVerifyConnectionSucceeds(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	defer srv.Close()
	wsURL := strings.Replace(srv.URL, "http", "ws", 1) + "/ws/nodes/x"

	active := func(context.Context) (bool, error) { return true, nil }
	if err := VerifyConnection(context.Background(), wsURL, active, 2*time.Second); err != nil {
		t.Fatalf("expected success, got %v", err)
	}
}

func TestVerifyConnectionServiceNeverActive(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	defer srv.Close()
	wsURL := strings.Replace(srv.URL, "http", "ws", 1) + "/ws/nodes/x"

	active := func(context.Context) (bool, error) { return false, nil }
	err := VerifyConnection(context.Background(), wsURL, active, 800*time.Millisecond)
	if err == nil || !strings.Contains(err.Error(), "active") {
		t.Fatalf("expected service-not-active error, got %v", err)
	}
}

func TestVerifyConnectionCentralUnreachable(t *testing.T) {
	// Port 1 refuses connections; the reachability probe must fail fast.
	active := func(context.Context) (bool, error) { return true, nil }
	err := VerifyConnection(context.Background(), "ws://127.0.0.1:1/ws/nodes/x", active, 2*time.Second)
	if err == nil || !strings.Contains(err.Error(), "not reachable") {
		t.Fatalf("expected unreachable error, got %v", err)
	}
}

// TestVerifyConnectionNoSecretLeak guards that failure diagnostics never echo a
// token or secret — they only mention host/state.
func TestVerifyConnectionNoSecretLeak(t *testing.T) {
	active := func(context.Context) (bool, error) { return true, nil }
	err := VerifyConnection(context.Background(), "ws://127.0.0.1:1/ws/nodes/super-secret-node", active, 2*time.Second)
	if err == nil {
		t.Fatal("expected error")
	}
	if strings.Contains(err.Error(), "super-secret-node") {
		t.Errorf("diagnostic leaked path/secret material: %v", err)
	}
}
