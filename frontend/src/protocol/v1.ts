export const NODE_ID = "00000000-0000-4000-8000-000000000001";
export const WORKSPACE_ID = "00000000-0000-4000-8000-000000000003";
export const MAX_PAYLOAD = 64 * 1024;

export type ControlType = "session.attach" | "session.stop" | "terminal.resize";
export interface ControlMessage {
  version: 1;
  type: ControlType;
  request_id: string;
  node_id: string;
  timestamp: string;
  payload: { session_id: string; rows?: number; columns?: number };
}

// Crockford base32 (ULID alphabet): excludes I, L, O, U.
const CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
let sequence = 0;
export function createRequestId(): string {
  sequence += 1;
  let value = sequence;
  const chars: string[] = [];
  for (let i = 0; i < 26; i += 1) {
    chars.push(CROCKFORD[value % 32]);
    value = Math.floor(value / 32);
  }
  return chars.reverse().join("");
}

export function control(
  type: ControlType,
  sessionId: string,
  rows?: number,
  columns?: number,
): ControlMessage {
  const payload: ControlMessage["payload"] = { session_id: sessionId };
  if (rows !== undefined && columns !== undefined)
    Object.assign(payload, { rows, columns });
  return {
    version: 1,
    type,
    request_id: createRequestId(),
    node_id: NODE_ID,
    timestamp: new Date().toISOString(),
    payload,
  };
}

export function encodeTextInput(value: string): Uint8Array {
  return new TextEncoder().encode(value);
}
export function encodeBinaryInput(value: string): Uint8Array {
  return Uint8Array.from(value, (character) => character.charCodeAt(0) & 0xff);
}
