package files

import (
	"errors"
	"fmt"
	"os"
	"testing"
	"time"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/cliora/cliora/daemon/internal/protocol"
)

// TestUploadCapFitsFrameBound is the assertion that keeps one number honest.
//
// The per-file ceiling is shared by image drop and file upload, and its value is
// dictated by the frame budget rather than by taste: base64 expands by 4/3, and
// the result plus a JSON envelope has to fit MaxFilePayload. Raising the config
// key without raising the frame bound would not fail loudly — the node would
// silently drop the oversize frame and the request would time out — so the
// tripwire belongs here.
func TestUploadCapFitsFrameBound(t *testing.T) {
	cap := config.DefaultUploadMaxBytes
	base64Len := (cap + 2) / 3 * 4
	const envelopeHeadroom = 4096 // request_id, node_id, timestamp, paths, braces
	if base64Len+envelopeHeadroom > protocol.MaxFilePayload {
		t.Fatalf("per-file cap %d bytes becomes %d bytes of base64, which does not fit "+
			"MaxFilePayload %d with %d bytes of envelope headroom; raise the frame bound "+
			"in all three consumers or lower the cap",
			cap, base64Len, protocol.MaxFilePayload, envelopeHeadroom)
	}
	if config.DefaultUploadMaxBytes > config.DefaultMaxPreviewSize*2 {
		// Not a hard requirement, just a nudge: a node that can accept files far
		// larger than it can preview will produce uploads nobody can inspect from
		// the browser.
		t.Logf("note: per-file upload cap (%d) is more than twice the preview cap (%d)",
			config.DefaultUploadMaxBytes, config.DefaultMaxPreviewSize)
	}
}

func TestStoreQuotaPerDayCount(t *testing.T) {
	svc := storeService(t, func(c *config.Config) {
		c.Filesystem.Upload.Files.MaxFilesPerDay = 2
	})
	root, _ := storeRoot(t)
	for i := 0; i < 2; i++ {
		res, err := svc.Store(root, ".", fmt.Sprintf("f%d.txt", i), []byte("x"), storeNow)
		if err != nil || res.Denied {
			t.Fatalf("upload %d: err=%v code=%s", i, err, res.Code)
		}
	}
	res, err := svc.Store(root, ".", "f2.txt", []byte("x"), storeNow)
	if err != nil {
		t.Fatal(err)
	}
	if !res.Denied || res.Code != "FILE_UPLOAD_QUOTA_EXCEEDED" {
		t.Fatalf("third upload: denied=%v code=%s", res.Denied, res.Code)
	}

	// The next UTC day starts over. Nothing reads yesterday, so the entry is
	// replaced rather than accumulated.
	tomorrow := storeNow.Add(24 * time.Hour)
	res, err = svc.Store(root, ".", "f3.txt", []byte("x"), tomorrow)
	if err != nil || res.Denied {
		t.Fatalf("next day: err=%v code=%s", err, res.Code)
	}
}

func TestStoreQuotaPerSessionBytes(t *testing.T) {
	svc := storeService(t, func(c *config.Config) {
		c.Filesystem.Upload.Files.MaxSessionBytes = 10
	})
	root, _ := storeRoot(t)
	res, err := svc.Store(root, ".", "a.bin", make([]byte, 8), storeNow)
	if err != nil || res.Denied {
		t.Fatalf("first: err=%v code=%s", err, res.Code)
	}
	res, err = svc.Store(root, ".", "b.bin", make([]byte, 8), storeNow)
	if err != nil {
		t.Fatal(err)
	}
	if !res.Denied || res.Code != "FILE_UPLOAD_QUOTA_EXCEEDED" {
		t.Fatalf("second: denied=%v code=%s", res.Denied, res.Code)
	}
	// A refused upload must not have consumed quota either: 2 more bytes still fit.
	res, err = svc.Store(root, ".", "c.bin", make([]byte, 2), storeNow)
	if err != nil || res.Denied {
		t.Fatalf("third: err=%v code=%s — a refusal consumed quota", err, res.Code)
	}
}

// A write that fails after the reservation must give the quota back, or a node
// with a full disk would also run out of allowance.
func TestStoreQuotaReleasedOnWriteFailure(t *testing.T) {
	svc := storeService(t, func(c *config.Config) {
		c.Filesystem.Upload.Files.MaxFilesPerDay = 1
	})
	root, dir := storeRoot(t)
	// Make the destination unwritable so CreateExclusive fails with EACCES.
	if err := os.Mkdir(dir+"/locked", 0o500); err != nil {
		t.Fatal(err)
	}
	res, err := svc.Store(root, "locked", "a.txt", []byte("x"), storeNow)
	if err == nil && !res.Denied {
		t.Skip("running as a user that can write into a 0500 directory (root?)")
	}
	// Whether it surfaced as an error or a denial, the one allowed upload for
	// today must still be available.
	res, err = svc.Store(root, ".", "b.txt", []byte("x"), storeNow)
	if err != nil || res.Denied {
		t.Fatalf("quota was not released: err=%v code=%s", err, res.Code)
	}
}

func TestStoreFreeSpaceFloor(t *testing.T) {
	floor := int64(512 << 20)
	svc := storeService(t, func(c *config.Config) {
		c.Filesystem.Upload.Files.MinFreeBytes = &floor
	})
	root, dir := storeRoot(t)

	svc.freeBytes = func(string) (int64, error) { return floor - 1, nil }
	res, err := svc.Store(root, ".", "a.txt", []byte("x"), storeNow)
	if err != nil {
		t.Fatal(err)
	}
	if !res.Denied || res.Code != "FILE_UPLOAD_NO_SPACE" {
		t.Fatalf("below floor: denied=%v code=%s", res.Denied, res.Code)
	}
	if entries, _ := os.ReadDir(dir); len(entries) != 0 {
		t.Fatalf("something was written: %v", entries)
	}

	// Above the floor but not twice the payload. The free figure is a snapshot
	// taken before the write and the disk has other writers, so a file that
	// exactly fits is refused too — hence the two-sided check. A small floor is
	// used here because that is the only configuration in which the second clause
	// is the one that bites.
	small := int64(4)
	svc = storeService(t, func(c *config.Config) {
		c.Filesystem.Upload.Files.MinFreeBytes = &small
	})
	root2, dir2 := storeRoot(t)
	svc.freeBytes = func(string) (int64, error) { return 10, nil }
	res, err = svc.Store(root2, ".", "b.bin", make([]byte, 8), storeNow)
	if err != nil {
		t.Fatal(err)
	}
	if !res.Denied || res.Code != "FILE_UPLOAD_NO_SPACE" {
		t.Fatalf("below 2x payload: denied=%v code=%s", res.Denied, res.Code)
	}
	if entries, _ := os.ReadDir(dir2); len(entries) != 0 {
		t.Fatalf("something was written: %v", entries)
	}
}

// The one fail-open check in Store, and it is deliberate: a statfs failure is not
// a security boundary, and letting it refuse every upload would treat it as one.
func TestStoreFreeSpaceUnknownIsFailOpen(t *testing.T) {
	floor := int64(512 << 20)
	svc := storeService(t, func(c *config.Config) {
		c.Filesystem.Upload.Files.MinFreeBytes = &floor
	})
	root, _ := storeRoot(t)
	svc.freeBytes = func(string) (int64, error) { return 0, errors.New("statfs: no such device") }

	res, err := svc.Store(root, ".", "a.txt", []byte("x"), storeNow)
	if err != nil {
		t.Fatal(err)
	}
	if res.Denied {
		t.Fatalf("a statfs failure refused the upload: %s", res.Code)
	}
}

// An explicit 0 turns the check off; that has to stay distinguishable from an
// absent key, which is why the config field is a pointer.
func TestStoreFreeSpaceCheckCanBeDisabled(t *testing.T) {
	zero := int64(0)
	svc := storeService(t, func(c *config.Config) {
		c.Filesystem.Upload.Files.MinFreeBytes = &zero
	})
	root, _ := storeRoot(t)
	called := false
	svc.freeBytes = func(string) (int64, error) { called = true; return 0, nil }

	res, err := svc.Store(root, ".", "a.txt", []byte("x"), storeNow)
	if err != nil || res.Denied {
		t.Fatalf("err=%v code=%s", err, res.Code)
	}
	if called {
		t.Fatal("free space was consulted although the check is disabled")
	}
}

// statfsFreeBytes uses Bavail rather than Bfree: the difference is the reserve
// ext4 keeps for root, and agentd runs non-root (ADR 0023), so those blocks are
// not available to it. Measured at 7.9 GiB on the machine plan/15 was written on.
func TestStatfsFreeBytesIsPlausible(t *testing.T) {
	dir := t.TempDir()
	free, err := statfsFreeBytes(dir)
	if err != nil {
		t.Skipf("statfs unavailable here: %v", err)
	}
	if free <= 0 {
		t.Fatalf("free = %d, want a positive figure for %s", free, dir)
	}
}
