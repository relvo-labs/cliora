// FU-01 #3: what Statfs reports for a workspace, and how far Bfree overstates
// it. agentd runs non-root (ADR 0023), so the reserved blocks in Bfree-Bavail
// are not available to it — measured at 7.9 GiB on ext4, which is why
// files.Store uses Bavail (plan/15/07-open-measurements.md §3).
//
// Usage: go run scripts/fu/statfs-probe.go <path>...
package main

import (
	"fmt"
	"os"
	"syscall"
)

func report(path string) {
	var st syscall.Statfs_t
	if err := syscall.Statfs(path, &st); err != nil {
		fmt.Printf("%-40s ERROR %v\n", path, err)
		return
	}
	bavail := int64(st.Bavail) * st.Bsize
	bfree := int64(st.Bfree) * st.Bsize
	total := int64(st.Blocks) * st.Bsize
	fmt.Printf("%-40s Bsize=%-6d Bavail=%-12s Bfree=%-12s Blocks=%-12s reserved(Bfree-Bavail)=%s\n",
		path, st.Bsize, human(bavail), human(bfree), human(total), human(bfree-bavail))
}

func human(b int64) string {
	const u = 1024
	if b < u {
		return fmt.Sprintf("%dB", b)
	}
	f := float64(b)
	units := []string{"KiB", "MiB", "GiB", "TiB"}
	i := -1
	for f >= u && i < len(units)-1 {
		f /= u
		i++
	}
	return fmt.Sprintf("%.1f%s", f, units[i])
}

func main() {
	for _, p := range os.Args[1:] {
		report(p)
	}
}
