import { homedir, tmpdir } from "node:os";
import { relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

// This is a test-process guard, not a product configuration rule.  The
// current Windows workstation's real profile/config are forbidden targets for
// offline CDP fixtures even when a caller forgets to override one env var.
export const REAL_USER_PROFILE = resolve("C:\\Users\\93445");
export const REAL_USER_CONFIG = resolve(REAL_USER_PROFILE, ".uthcode", "config.toml");

function samePath(left, right) {
  return resolve(left).toLowerCase() === resolve(right).toLowerCase();
}

function within(candidate, root) {
  const relativePath = relative(resolve(root), resolve(candidate));
  return relativePath === "" || (!relativePath.startsWith(`..${sep}`) && relativePath !== "..");
}

function allowedTestRoot(candidate) {
  return within(candidate, tmpdir()) || within(candidate, fileURLToPath(new URL("../../", import.meta.url)));
}

function assertSafePath(label, candidate) {
  const resolved = resolve(candidate);
  if (samePath(resolved, REAL_USER_PROFILE) || samePath(resolved, REAL_USER_CONFIG)) {
    throw new Error(`${label} resolves to the real user profile/config and is forbidden: ${resolved}`);
  }
  if (within(resolved, REAL_USER_PROFILE) && !within(resolved, tmpdir())) {
    throw new Error(`${label} resolves inside the real user profile and is forbidden: ${resolved}`);
  }
  if (!allowedTestRoot(resolved)) {
    throw new Error(`${label} must be under the workspace or system temp: ${resolved}`);
  }
}

export function assertIsolatedCdpPaths({ label = "CDP test", homePaths = [], configPaths = [], outputPaths = [] } = {}) {
  const homes = homePaths.filter((value) => typeof value === "string" && value.trim());
  if (homes.length === 0) throw new Error(`${label} requires an explicit isolated test HOME`);
  for (const home of homes) assertSafePath(`${label} HOME`, home);
  for (const configPath of configPaths.filter((value) => typeof value === "string" && value.trim())) {
    assertSafePath(`${label} config`, configPath);
  }
  for (const outputPath of outputPaths.filter((value) => typeof value === "string" && value.trim())) {
    assertSafePath(`${label} output`, outputPath);
  }
}

export function assertCdpEnvironmentIsolated({ label = "CDP test", env = process.env, outputPaths = [] } = {}) {
  const homePaths = [env.HOME, env.USERPROFILE, env.APPDATA, env.LOCALAPPDATA].filter(
    (value) => typeof value === "string" && value.trim(),
  );
  const fallbackHome = homePaths[0] ?? homedir();
  const configPaths = [
    env.UTHCODE_CONFIG_PATH,
    ...homePaths.map((home) => resolve(home, ".uthcode", "config.toml")),
    resolve(fallbackHome, ".uthcode", "config.toml"),
  ];
  assertIsolatedCdpPaths({ label, homePaths: [fallbackHome, ...homePaths], configPaths, outputPaths });
}
