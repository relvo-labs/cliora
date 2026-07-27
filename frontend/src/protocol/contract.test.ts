import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { ProtocolError, decodeBinary, decodeControl } from "./decode";

const FIXTURES = resolve(process.cwd(), "..", "contracts", "v1", "fixtures");
const manifest = JSON.parse(
  readFileSync(resolve(FIXTURES, "manifest.json"), "utf8"),
) as {
  json: Array<{ path: string; accept: boolean; type?: string }>;
  binary: Array<{
    name: string;
    accept: boolean;
    version?: number;
    kind?: number;
    session_id?: string;
    payload_hex?: string;
    hex?: string;
  }>;
};

function hexToBytes(hex: string): Uint8Array {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < bytes.length; i += 1)
    bytes[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  return bytes;
}

describe("contract v1 (TypeScript consumer)", () => {
  for (const item of manifest.json) {
    it(`json: ${item.path}`, () => {
      const raw = new Uint8Array(readFileSync(resolve(FIXTURES, item.path)));
      if (item.accept) {
        expect(decodeControl(raw).type).toBe(item.type);
      } else {
        expect(() => decodeControl(raw)).toThrow(ProtocolError);
      }
    });
  }

  for (const item of manifest.binary) {
    it(`binary: ${item.name}`, () => {
      if (item.accept) {
        const session = hexToBytes(item.session_id!.replace(/-/g, ""));
        const payload = hexToBytes(item.payload_hex!);
        const frame = new Uint8Array([1, item.kind!, ...session, ...payload]);
        const decoded = decodeBinary(frame);
        expect(decoded.kind).toBe(item.kind);
        expect(Array.from(decoded.payload)).toEqual(Array.from(payload));
      } else {
        expect(() => decodeBinary(hexToBytes(item.hex!))).toThrow(
          ProtocolError,
        );
      }
    });
  }
});
