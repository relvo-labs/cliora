//go:build linux

package runner

import "syscall"

// freeBytes reports the space available to an unprivileged writer on the filesystem
// holding path.
//
// `Bavail`, not `Bfree`: the difference is the reserve only root may use, and the
// daemon runs as a non-root service (SEC-007). Counting blocks it cannot actually
// write into would make the floor read as satisfied right up to the moment a write
// fails.
func freeBytes(path string) (int64, error) {
	var stat syscall.Statfs_t
	if err := syscall.Statfs(path, &stat); err != nil {
		return 0, err
	}
	return int64(stat.Bavail) * int64(stat.Bsize), nil
}
