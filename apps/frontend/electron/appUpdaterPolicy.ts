export const OFFICIAL_UPDATE_REPOSITORY = 'kuguya-AI-app-develop/Hermes-Yachiyo';
export const OFFICIAL_APP_BUNDLE_ID = 'io.github.arisataki.oha-yachiyo';

const PRODUCT_NAME = 'Oha-Yachiyo';
const CHANNEL_BY_BRANCH = {
  main: 'stable',
  alpha: 'alpha',
  'oha-develop': 'experimental',
} as const;

type UpdateBranch = keyof typeof CHANNEL_BY_BRANCH;

export type UpdateBuildIdentity = {
  name?: unknown;
  channel?: unknown;
  branch?: unknown;
  repository?: unknown;
  latest_json_url?: unknown;
};

export type TrustedUpdateTarget = {
  branch: UpdateBranch;
  channel: (typeof CHANNEL_BY_BRANCH)[UpdateBranch];
  latestTag: string;
  metadataFileName: string;
  dmgFileName: string;
  metadataUrl: string;
  downloadUrl: string;
};

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function updateBranch(value: unknown): UpdateBranch | null {
  const candidate = stringValue(value);
  return Object.hasOwn(CHANNEL_BY_BRANCH, candidate) ? candidate as UpdateBranch : null;
}

export function normalizeSha256(value: unknown): string | null {
  const candidate = stringValue(value).toLowerCase();
  return /^[0-9a-f]{64}$/.test(candidate) ? candidate : null;
}

export function trustedUpdateTarget(current: UpdateBuildIdentity): TrustedUpdateTarget {
  if (stringValue(current.name) !== PRODUCT_NAME) {
    throw new Error('当前应用构建缺少可信产品标识');
  }
  const branch = updateBranch(current.branch);
  if (!branch) throw new Error('当前应用构建使用了未知更新分支');
  const channel = CHANNEL_BY_BRANCH[branch];
  if (stringValue(current.channel) !== channel) {
    throw new Error('当前应用构建的更新渠道与分支不匹配');
  }
  if (stringValue(current.repository) !== OFFICIAL_UPDATE_REPOSITORY) {
    throw new Error('当前应用构建未指向官方更新仓库');
  }
  const latestTag = `${branch}-latest`;
  const metadataFileName = `${PRODUCT_NAME}-${branch}-latest.json`;
  const dmgFileName = `${PRODUCT_NAME}-${branch}-latest.dmg`;
  const prefix = `https://github.com/${OFFICIAL_UPDATE_REPOSITORY}/releases/download/${latestTag}`;
  const metadataUrl = `${prefix}/${metadataFileName}`;
  const downloadUrl = `${prefix}/${dmgFileName}`;
  if (stringValue(current.latest_json_url) !== metadataUrl) {
    throw new Error('当前应用构建的更新元数据链接不可信');
  }
  return {
    branch,
    channel,
    latestTag,
    metadataFileName,
    dmgFileName,
    metadataUrl,
    downloadUrl,
  };
}

export function validateTrustedLatestMetadata<T>(
  current: UpdateBuildIdentity,
  value: unknown,
): T & { sha256: string; dirty: false; release_publishable: true } {
  const metadata = recordValue(value);
  if (!metadata) throw new Error('更新元数据必须是 JSON 对象');
  const target = trustedUpdateTarget(current);
  if (stringValue(metadata.name) !== PRODUCT_NAME) throw new Error('更新元数据产品标识不可信');
  if (stringValue(metadata.branch) !== target.branch) throw new Error('更新元数据分支与当前渠道不匹配');
  if (stringValue(metadata.channel) !== target.channel) throw new Error('更新元数据渠道与当前构建不匹配');
  if (stringValue(metadata.dmg_name) !== target.dmgFileName) throw new Error('更新安装包文件名不可信');
  if (stringValue(metadata.latest_json_url) !== target.metadataUrl) throw new Error('更新元数据自引用链接不可信');
  if (stringValue(metadata.download_url) !== target.downloadUrl) throw new Error('更新安装包下载链接不可信');
  const sha256 = normalizeSha256(metadata.sha256);
  if (!sha256) throw new Error('更新元数据缺少合法的 SHA256');
  if (metadata.release_publishable !== true) throw new Error('该更新构建未通过正式发布门禁');
  if (metadata.dirty !== false) throw new Error('该更新构建不是干净的可复现源码构建');
  return {
    ...metadata,
    sha256,
    dirty: false,
    release_publishable: true,
  } as T & { sha256: string; dirty: false; release_publishable: true };
}

export function isVerifiedDownloadedUpdate(record: unknown, latest?: unknown): boolean {
  const download = recordValue(record);
  if (!download || download.ok !== true || download.verified !== true) return false;
  if (!stringValue(download.path) || !stringValue(download.file_name)) return false;
  const actualSha256 = normalizeSha256(download.sha256);
  if (!actualSha256) return false;
  const embeddedLatest = recordValue(download.latest);
  const embeddedSha256 = normalizeSha256(embeddedLatest?.sha256);
  if (!embeddedSha256 || embeddedSha256 !== actualSha256) return false;
  if (latest !== undefined) {
    const expectedSha256 = normalizeSha256(recordValue(latest)?.sha256);
    if (!expectedSha256 || expectedSha256 !== actualSha256) return false;
  }
  return true;
}

/**
 * Positional parameters supplied by Electron main:
 * app path, DMG path, app name, old PID, expected SHA, bundle id,
 * expected short version, and persisted download-record path.
 */
export function buildMacAppUpdateInstallerScript(): string {
  return [
    'set -euo pipefail',
    'app_path="$1"',
    'dmg_path="$2"',
    'app_name="$3"',
    'app_pid="$4"',
    'expected_sha256="$5"',
    'expected_bundle_id="$6"',
    'expected_version="$7"',
    'record_path="$8"',
    'mount_dir=""',
    'work_dir=""',
    'backup_app=""',
    'staged_app=""',
    'cleanup() {',
    '  status=$?',
    '  trap - EXIT',
    '  restored=0',
    '  if [[ "$status" -ne 0 ]]; then',
    '    if [[ -n "$backup_app" && -e "$backup_app" ]]; then',
    '      if [[ -e "$app_path" ]]; then',
    '        failed_app="$work_dir/failed.app"',
    '        /bin/mv "$app_path" "$failed_app" >/dev/null 2>&1 || true',
    '      fi',
    '      if [[ ! -e "$app_path" ]]; then',
    '        if /bin/mv "$backup_app" "$app_path" >/dev/null 2>&1; then restored=1; fi',
    '      fi',
    '    elif [[ -e "$app_path" ]]; then',
    '      restored=1',
    '    fi',
    '    if [[ "$restored" -eq 1 ]]; then /usr/bin/open -- "$app_path" >/dev/null 2>&1 || true; fi',
    '  fi',
    '  if [[ -n "$mount_dir" && -d "$mount_dir" ]]; then',
    '    /usr/bin/hdiutil detach "$mount_dir" -quiet >/dev/null 2>&1 || true',
    '    /bin/rmdir "$mount_dir" >/dev/null 2>&1 || true',
    '  fi',
    '  if [[ -n "$work_dir" && -d "$work_dir" ]]; then',
    '    if [[ ! -e "$backup_app" ]]; then /bin/rm -rf "$work_dir" >/dev/null 2>&1 || true; fi',
    '  fi',
    '  exit "$status"',
    '}',
    'trap cleanup EXIT',
    'wait_attempts=0',
    'while /bin/kill -0 "$app_pid" >/dev/null 2>&1; do',
    '  wait_attempts=$((wait_attempts + 1))',
    '  if [[ "$wait_attempts" -ge 480 ]]; then echo "Timed out waiting for current app to quit" >&2; exit 1; fi',
    '  /bin/sleep 0.25',
    'done',
    'actual_sha256="$(/usr/bin/shasum -a 256 "$dmg_path" | /usr/bin/awk \"{print \\\$1}\")"',
    'if [[ "$actual_sha256" != "$expected_sha256" ]]; then echo "Downloaded DMG SHA256 changed before install" >&2; exit 1; fi',
    'mount_dir="$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/oha-yachiyo-update-mount.XXXXXX")"',
    '/usr/bin/hdiutil attach "$dmg_path" -nobrowse -readonly -mountpoint "$mount_dir" -quiet',
    'source_app="$mount_dir/$app_name"',
    'if [[ ! -d "$source_app" ]]; then echo "Cannot find exact app bundle in update DMG" >&2; exit 1; fi',
    'parent_dir="$(/usr/bin/dirname "$app_path")"',
    'work_dir="$(/usr/bin/mktemp -d "$parent_dir/.oha-yachiyo-update.XXXXXX")"',
    'staged_app="$work_dir/staged.app"',
    'backup_app="$work_dir/backup.app"',
    '/usr/bin/ditto "$source_app" "$staged_app"',
    'info_plist="$staged_app/Contents/Info.plist"',
    'if [[ ! -f "$info_plist" ]]; then echo "Staged app is missing Info.plist" >&2; exit 1; fi',
    'bundle_id="$(/usr/libexec/PlistBuddy -c \"Print :CFBundleIdentifier\" "$info_plist")"',
    'if [[ "$bundle_id" != "$expected_bundle_id" ]]; then echo "Staged app bundle id mismatch" >&2; exit 1; fi',
    'staged_version="$(/usr/libexec/PlistBuddy -c \"Print :CFBundleShortVersionString\" "$info_plist")"',
    'if [[ -n "$expected_version" && "$staged_version" != "$expected_version" ]]; then echo "Staged app version mismatch" >&2; exit 1; fi',
    '/usr/bin/codesign --verify --deep --strict "$staged_app"',
    '/bin/mv "$app_path" "$backup_app"',
    '/bin/mv "$staged_app" "$app_path"',
    '/usr/bin/open "$app_path"',
    '/bin/rm -rf "$backup_app" >/dev/null 2>&1 || true',
    '/bin/rm -f "$record_path" >/dev/null 2>&1 || true',
  ].join('\n');
}
