/** Renderer-only recovery for text crossing the JSONL/Desktop boundary. */

const MOJIBAKE_MARKERS = ["Ã", "Â", "â", "ä", "å", "æ", "ç", "è", "é", "ê", "ï¿½", "锟"];
// These are high-signal characters produced by the common UTF-8-as-GB18030
// failure mode. Restricting the reverse-table pass to a marked string keeps
// normal long Chinese transcripts on the ordinary O(n) normalization path.
const GB18030_MOJIBAKE_MARKERS = ["浣", "犲", "ソ", "姝", "ｅ", "鍒", "璇", "鎴", "锟"];

let gb18030PairMap: Map<number, Uint8Array> | null | undefined;

/**
 * Build the small GB18030 two-byte reverse table lazily. A real-world
 * mojibake sample such as `浣犲ソ` is UTF-8 bytes decoded as GB18030; unlike
 * Latin-1 corruption it contains no obvious ASCII marker. TextDecoder is
 * available in the renderer, so one bounded table pass lets us recover only
 * candidates that round-trip to valid UTF-8, without shipping a second
 * encoding library or changing ordinary Chinese text.
 */
function gb18030Pairs(): Map<number, Uint8Array> | null {
  if (gb18030PairMap !== undefined) return gb18030PairMap;
  try {
    const bytes: number[] = [];
    const pairs: Array<[number, number]> = [];
    for (let lead = 0x81; lead <= 0xfe; lead += 1) {
      for (let trail = 0x40; trail <= 0xfe; trail += 1) {
        if (trail === 0x7f) continue;
        bytes.push(lead, trail, 0);
        pairs.push([lead, trail]);
      }
    }
    const decoded = new TextDecoder("gb18030").decode(Uint8Array.from(bytes));
    const result = new Map<number, Uint8Array>();
    let offset = 0;
    for (const [lead, trail] of pairs) {
      const code = decoded.charCodeAt(offset);
      if (Number.isFinite(code) && decoded.charCodeAt(offset + 1) === 0) {
        result.set(code, Uint8Array.of(lead, trail));
      }
      offset += 2;
    }
    gb18030PairMap = result;
  } catch {
    // Some embedded runtimes may not expose GB18030. Latin-1 recovery and
    // the authoritative UTF-8 transport remain fully functional there.
    gb18030PairMap = null;
  }
  return gb18030PairMap;
}

function decodeGb18030MojibakeRun(run: readonly string[]): string | null {
  if (run.length < 2) return null;
  const pairs = gb18030Pairs();
  if (!pairs) return null;
  const bytes: number[] = [];
  for (const character of run) {
    const pair = pairs.get(character.codePointAt(0) ?? -1);
    if (!pair) return null;
    bytes.push(pair[0], pair[1]);
  }
  try {
    const decoded = new TextDecoder("utf-8", { fatal: true }).decode(Uint8Array.from(bytes));
    return decoded && decoded !== run.join("") ? decoded : null;
  } catch {
    return null;
  }
}

function recoverGb18030Mojibake(value: string): string {
  const characters = [...value];
  if (characters.length < 2
    || !characters.some((character) => (character.codePointAt(0) ?? 0) > 0x7f)
    || !GB18030_MOJIBAKE_MARKERS.some((marker) => value.includes(marker))) return value;
  let result = "";
  let index = 0;
  while (index < characters.length) {
    let bestLength = 0;
    let best: string | null = null;
    const run: string[] = [];
    for (let end = index; end < characters.length; end += 1) {
      run.push(characters[end]!);
      const candidate = decodeGb18030MojibakeRun(run);
      if (candidate !== null) {
        bestLength = run.length;
        best = candidate;
      }
    }
    if (best !== null && bestLength >= 2) {
      result += best;
      index += bestLength;
    } else {
      result += characters[index]!;
      index += 1;
    }
  }
  return result;
}

/** Recover only the common UTF-8-as-Latin-1 display corruption pattern. */
export function recoverMojibake(value: string): string {
  let recovered = value;
  if (MOJIBAKE_MARKERS.some((marker) => value.includes(marker))) {
    try {
      if (![...value].some((character) => character.charCodeAt(0) > 255)) {
        const bytes = Uint8Array.from([...value].map((character) => character.charCodeAt(0)));
        const decoded = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
        const sourceScore = MOJIBAKE_MARKERS.reduce((score, marker) => score + value.split(marker).length - 1, 0);
        const decodedScore = MOJIBAKE_MARKERS.reduce((score, marker) => score + decoded.split(marker).length - 1, 0);
        if (decodedScore < sourceScore) recovered = decoded;
      }
    } catch {
      // Try the GB18030 path below; malformed Latin-1 text is left intact.
    }
  }
  return recoverGb18030Mojibake(recovered);
}

export function textValue(value: unknown): string {
  return typeof value === "string" ? recoverMojibake(value) : "";
}

export function numberText(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "";
}

export function nonEmptyText(value: unknown): string | null {
  const text = textValue(value).trim();
  return text ? text : null;
}

export function positiveInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0 ? value : null;
}
