package main

import (
	"bufio"
	"fmt"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"

	"golang.org/x/term"
)

func main() {
	// `--version` lets the daemon's runtime detector treat fakecli as an
	// allowlisted CLI (claude/codex) in dev/e2e without a real binary: it prints
	// a version line and exits instead of reading stdin.
	if len(os.Args) > 1 && os.Args[1] == "--version" {
		fmt.Println("fakecli 1.0.0")
		return
	}
	rows, cols := size()
	fmt.Printf("FAKECLI_READY v1 rows=%d cols=%d\r\n", rows, cols)
	signals := make(chan os.Signal, 2)
	signal.Notify(signals, syscall.SIGINT, syscall.SIGWINCH)
	go func() {
		for sig := range signals {
			if sig == syscall.SIGINT {
				fmt.Print("INTERRUPTED\r\n")
			} else {
				r, c := size()
				fmt.Printf("RESIZE rows=%d cols=%d\r\n", r, c)
			}
		}
	}()
	scanner := bufio.NewScanner(os.Stdin)
	scanner.Buffer(make([]byte, 4096), 4096)
	for scanner.Scan() {
		line := scanner.Text()
		fmt.Print(line, "\r\n")
		run(line)
	}
}
func size() (int, int) {
	cols, rows, err := term.GetSize(int(os.Stdin.Fd()))
	if err != nil {
		return 24, 80
	}
	return rows, cols
}
func run(line string) {
	parts := strings.Fields(line)
	if len(parts) == 0 {
		return
	}
	switch parts[0] {
	case ":ansi":
		fmt.Print("\x1b[31mANSI_RED\x1b[0m\r\n")
	case ":unicode":
		fmt.Print("中文 café 🚀\r\n")
	case ":burst":
		if len(parts) != 2 {
			return
		}
		n, err := strconv.Atoi(parts[1])
		if err != nil || n < 0 || n > 16*1024*1024 {
			return
		}
		chunk := []byte("0123456789abcdef")
		for n > 0 {
			count := len(chunk)
			if n < count {
				count = n
			}
			_, _ = os.Stdout.Write(chunk[:count])
			n -= count
		}
	case ":exit":
		if len(parts) == 2 {
			code, err := strconv.Atoi(parts[1])
			if err == nil && code >= 0 && code <= 125 {
				os.Exit(code)
			}
		}
	}
}
