package protocol

import (
	"crypto/rand"
	"encoding/json"
	"errors"
	"sync"
	"time"

	"github.com/google/uuid"
)

// crockford is the ULID alphabet (excludes I, L, O, U) matching the envelope's
// request_id pattern ^[0-9A-HJKMNP-TV-Z]{26}$.
const crockford = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

// ULID generator state. Every emitted event/message gets its own unique,
// time-ordered id (P1-02): a 48-bit millisecond timestamp plus 80 bits of
// crypto randomness. Within a single millisecond the randomness is incremented
// so ids remain unique AND monotonically increasing (mirrors the canonical ULID
// spec) without pulling in a third-party dependency.
var (
	ulidMu       sync.Mutex
	ulidLastMS   uint64
	ulidLastRand [10]byte
)

// NewID returns a 26-character Crockford base32 ULID valid for request_id/event
// fields. Callers answering a request echo that request's id; pure daemon events
// call NewID() for a fresh, unique id (never borrowing a correlation id).
func NewID() string {
	ms := uint64(time.Now().UnixMilli()) & ((1 << 48) - 1)

	ulidMu.Lock()
	if ms <= ulidLastMS {
		// Same millisecond (or a backwards clock step): hold the timestamp and
		// bump the random component so ids stay unique and monotonic.
		ms = ulidLastMS
		incrementRand(&ulidLastRand)
	} else {
		ulidLastMS = ms
		// crypto/rand does not fail in practice; on the theoretical error path
		// the previous randomness is reused and the monotonic increment on the
		// next same-ms call still keeps ids distinct.
		_, _ = rand.Read(ulidLastRand[:])
	}
	rnd := ulidLastRand
	ulidMu.Unlock()

	return encodeULID(ms, rnd)
}

// incrementRand adds 1 to the 80-bit big-endian random component.
func incrementRand(r *[10]byte) {
	for i := len(r) - 1; i >= 0; i-- {
		r[i]++
		if r[i] != 0 {
			return
		}
	}
}

// encodeULID packs the 48-bit timestamp and 80-bit randomness into 16 bytes and
// renders the canonical 26-char Crockford string (2 zero pad bits + 128 bits =
// 130 bits = 26×5, so the leading char carries only the top 3 timestamp bits and
// always falls in 0-7).
func encodeULID(ms uint64, rnd [10]byte) string {
	var id [16]byte
	id[0] = byte(ms >> 40)
	id[1] = byte(ms >> 32)
	id[2] = byte(ms >> 24)
	id[3] = byte(ms >> 16)
	id[4] = byte(ms >> 8)
	id[5] = byte(ms)
	copy(id[6:], rnd[:])

	dst := make([]byte, 26)
	var acc uint32
	bits := 2 // two zero pad bits lead the 130-bit space
	di := 0
	for _, b := range id {
		acc = acc<<8 | uint32(b)
		bits += 8
		for bits >= 5 {
			bits -= 5
			dst[di] = crockford[(acc>>uint(bits))&31]
			di++
		}
	}
	return string(dst)
}

const timestampLayout = "2006-01-02T15:04:05.000000Z07:00"

type outEnvelope struct {
	Version   int    `json:"version"`
	Type      string `json:"type"`
	RequestID string `json:"request_id"`
	NodeID    string `json:"node_id"`
	Timestamp string `json:"timestamp"`
	Payload   any    `json:"payload"`
}

// BuildControl marshals a v1 control envelope with a UTC timestamp. A caller
// that is answering a request passes that request's id; a pure event passes
// NewID().
func BuildControl(msgType string, nodeID uuid.UUID, requestID string, payload any, now time.Time) ([]byte, error) {
	return json.Marshal(outEnvelope{
		Version:   1,
		Type:      msgType,
		RequestID: requestID,
		NodeID:    nodeID.String(),
		Timestamp: now.UTC().Format(timestampLayout),
		Payload:   payload,
	})
}

type wireError struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

type outResponse struct {
	Version   int        `json:"version"`
	Type      string     `json:"type"`
	RequestID string     `json:"request_id"`
	NodeID    string     `json:"node_id"`
	Timestamp string     `json:"timestamp"`
	Success   bool       `json:"success"`
	Error     *wireError `json:"error,omitempty"`
	Payload   any        `json:"payload"`
}

// BuildResponse marshals a success/failure response envelope with the required
// `success` field (the schema mandates success:true for session.started/
// attached/stopped, which BuildControl cannot express).
func BuildResponse(
	msgType string, nodeID uuid.UUID, requestID string, success bool, payload any, now time.Time,
) ([]byte, error) {
	if payload == nil {
		payload = map[string]any{}
	}
	frame, err := json.Marshal(outResponse{
		Version:   1,
		Type:      msgType,
		RequestID: requestID,
		NodeID:    nodeID.String(),
		Timestamp: now.UTC().Format(timestampLayout),
		Success:   success,
		Payload:   payload,
	})
	if err != nil {
		return nil, err
	}
	// Never emit a frame Central would drop on decode: an over-limit frame would
	// vanish and the caller would see a request timeout instead of an answer.
	// The caller turns this into a safe error reply.
	limit := MaxPayload
	if LargeFrameTypes[msgType] {
		limit = MaxFilePayload
	}
	if len(frame) > limit {
		return nil, ErrFrameTooLarge
	}
	return frame, nil
}

// ErrFrameTooLarge is returned when a built response would exceed the frame
// bound for its type.
var ErrFrameTooLarge = errors.New("FRAME_TOO_LARGE")

// BuildError marshals a type:"error" envelope (success:false + stable code)
// correlated to the request it answers.
func BuildError(
	nodeID uuid.UUID, requestID, code, message string, now time.Time,
) ([]byte, error) {
	return json.Marshal(outResponse{
		Version:   1,
		Type:      "error",
		RequestID: requestID,
		NodeID:    nodeID.String(),
		Timestamp: now.UTC().Format(timestampLayout),
		Success:   false,
		Error:     &wireError{Code: code, Message: message},
		Payload:   map[string]any{},
	})
}
