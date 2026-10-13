function readGitDiffPath(source: string, start: number): { value: string; end: number } | null {
  let index = start;
  while (index < source.length && /\s/u.test(source[index] ?? "")) index += 1;
  const quoted = source[index] === '"';
  if (quoted) index += 1;
  const bytes: number[] = [];
  const encoder = new TextEncoder();
  let closed = !quoted;
  while (index < source.length) {
    const character = source[index] ?? "";
    if (quoted && character === '"') {
      index += 1;
      closed = true;
      break;
    }
    if (!quoted && /\s/u.test(character)) break;
    if (character === "\\") {
      index += 1;
      const escaped = source[index] ?? "";
      if (/[0-7]/u.test(escaped)) {
        const octal = source.slice(index, index + 3);
        if (!/^[0-7]{3}$/u.test(octal)) return null;
        bytes.push(Number.parseInt(octal, 8));
        index += 3;
      } else {
        const decoded: Record<string, number> = { t: 9, n: 10, r: 13, b: 8, f: 12, v: 11, "\\": 92, '"': 34 };
        const code = decoded[escaped];
        if (code === undefined) return null;
        bytes.push(code);
        index += 1;
      }
      continue;
    }
    const codePoint = source.codePointAt(index);
    if (codePoint === undefined) return null;
    const value = String.fromCodePoint(codePoint);
    bytes.push(...encoder.encode(value));
    index += value.length;
  }
  if (!closed) return null;
  return { value: new TextDecoder().decode(Uint8Array.from(bytes)), end: index };
}

/** Return the old/new paths encoded by a real `diff --git` header. */
export function diffSectionPaths(line: string): string[] {
  const prefix = "diff --git ";
  if (!line.startsWith(prefix)) return [];
  const first = readGitDiffPath(line, prefix.length);
  if (first) {
    const second = readGitDiffPath(line, first.end);
    if (second && line.slice(second.end).trim() === "" && first.value.startsWith("a/") && second.value.startsWith("b/")) {
      return Array.from(new Set([first.value.slice(2), second.value.slice(2)].filter(Boolean)));
    }
    if (line[prefix.length] === '"' && first.value.startsWith("a/")) {
      const remainder = line.slice(first.end).trimStart();
      if (!remainder.startsWith('"') && remainder.startsWith("b/")) {
        const newPath = remainder.slice(2);
        if (newPath) return Array.from(new Set([first.value.slice(2), newPath]));
      }
    }
  }

  // Git may leave ordinary spaces unquoted. Accept only an unambiguous ` b/`
  // boundary instead of splitting a single path into fake tokens. Mixed
  // quoted output can also have an unquoted old path containing spaces.
  const header = line.slice(prefix.length);
  const mixedBoundaries: Array<{ oldPath: string; newPath: string }> = [];
  let mixedIndex = header.indexOf(' "b/');
  while (mixedIndex >= 0) {
    const oldToken = header.slice(0, mixedIndex);
    const second = readGitDiffPath(header, mixedIndex + 1);
    if (oldToken.startsWith("a/") && second && header.slice(second.end).trim() === "" && second.value.startsWith("b/")) {
      const oldPath = oldToken.slice(2);
      const newPath = second.value.slice(2);
      if (oldPath && newPath) mixedBoundaries.push({ oldPath, newPath });
    }
    mixedIndex = header.indexOf(' "b/', mixedIndex + 1);
  }
  if (mixedBoundaries.length === 1) {
    const paths = mixedBoundaries[0];
    return paths ? Array.from(new Set([paths.oldPath, paths.newPath])) : [];
  }

  const boundaries: Array<{ oldPath: string; newPath: string }> = [];
  let index = header.indexOf(" b/");
  while (index >= 0) {
    const oldToken = header.slice(0, index);
    const newToken = header.slice(index + 1);
    if (oldToken.startsWith("a/") && newToken.startsWith("b/")) {
      const oldPath = oldToken.slice(2);
      const newPath = newToken.slice(2);
      if (oldPath && newPath) boundaries.push({ oldPath, newPath });
    }
    index = header.indexOf(" b/", index + 1);
  }
  if (boundaries.length !== 1) return [];
  const [paths] = boundaries;
  if (!paths) return [];
  return Array.from(new Set([paths.oldPath, paths.newPath]));
}
