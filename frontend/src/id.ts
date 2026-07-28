type RandomSource = {
  randomUUID?: () => string;
  getRandomValues?: (values: Uint8Array) => Uint8Array;
};

/** Return an RFC 4122 version-4 UUID, including on non-HTTPS LAN pages.
 *
 * Browsers restrict `crypto.randomUUID()` to secure contexts. The dashboard
 * may intentionally be served over plain HTTP on a trusted LAN or tailnet, so
 * client and draft-rule IDs need a compatible fallback.
 */
export function randomUuid(source: RandomSource | undefined = globalThis.crypto): string {
  if (source?.randomUUID) return source.randomUUID();

  const bytes = new Uint8Array(16);
  if (source?.getRandomValues) {
    source.getRandomValues(bytes);
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256);
    }
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((value) => value.toString(16).padStart(2, "0"));
  return [
    hex.slice(0, 4).join(""),
    hex.slice(4, 6).join(""),
    hex.slice(6, 8).join(""),
    hex.slice(8, 10).join(""),
    hex.slice(10).join(""),
  ].join("-");
}
