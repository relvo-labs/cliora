//go:build race

package files

// raceEnabled reports that the race detector is instrumenting this build. The
// detector costs roughly an order of magnitude in wall-clock, so a latency
// budget measured under it says nothing about production. GATE-DAEMON-RACE runs
// `go test -race ./...`, so without this the budget check would fail there for
// a reason that has nothing to do with the code.
const raceEnabled = true
