"""Executable and source-level guards for the fail-closed Electron updater."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "apps" / "frontend"
POLICY = FRONTEND / "electron" / "appUpdaterPolicy.ts"
TSC = FRONTEND / "node_modules" / ".bin" / "tsc"


@pytest.fixture(scope="module")
def compiled_policy(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output_dir = tmp_path_factory.mktemp("electron-updater-policy")
    subprocess.run(
        [
            str(TSC),
            str(POLICY),
            "--target",
            "ES2022",
            "--module",
            "NodeNext",
            "--moduleResolution",
            "NodeNext",
            "--strict",
            "--skipLibCheck",
            "--outDir",
            str(output_dir),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    matches = list(output_dir.rglob("appUpdaterPolicy.js"))
    assert len(matches) == 1
    return matches[0]


def _run_policy(module_path: Path, body: str) -> object:
    script = f"""
      const policy = await import({json.dumps(module_path.as_uri())});
      const result = await (async () => {{ {body} }})();
      process.stdout.write(JSON.stringify(result));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_trust_policy_accepts_only_exact_official_release_urls(compiled_policy: Path) -> None:
    result = _run_policy(
        compiled_policy,
        """
        const current = {
          name: 'Oha-Yachiyo',
          channel: 'experimental',
          branch: 'oha-develop',
          repository: policy.OFFICIAL_UPDATE_REPOSITORY,
          latest_json_url: 'https://github.com/kuguya-AI-app-develop/Hermes-Yachiyo/releases/download/oha-develop-latest/Oha-Yachiyo-oha-develop-latest.json',
        };
        const accepted = policy.trustedUpdateTarget(current);
        const rejected = [
          { ...current, latest_json_url: current.latest_json_url.replace('https:', 'http:') },
          { ...current, latest_json_url: current.latest_json_url.replace('github.com', 'github.example') },
          { ...current, latest_json_url: current.latest_json_url.replace('kuguya-AI-app-develop', 'attacker') },
          { ...current, latest_json_url: current.latest_json_url.replace('oha-develop-latest', 'main-latest') },
          { ...current, latest_json_url: `${current.latest_json_url}?mirror=1` },
          { ...current, latest_json_url: ` ${current.latest_json_url}` },
          { ...current, repository: 'local/oha-yachiyo' },
        ].map((candidate) => {
          try { policy.trustedUpdateTarget(candidate); return false; } catch { return true; }
        });
        return { officialRepository: policy.OFFICIAL_UPDATE_REPOSITORY, accepted, rejected };
        """,
    )

    assert result["officialRepository"] == "kuguya-AI-app-develop/Hermes-Yachiyo"
    assert result["accepted"]["downloadUrl"] == (
        "https://github.com/kuguya-AI-app-develop/Hermes-Yachiyo/releases/download/"
        "oha-develop-latest/Oha-Yachiyo-oha-develop-latest.dmg"
    )
    assert result["rejected"] == [True] * 7


def test_latest_metadata_requires_sha_publishable_clean_and_exact_assets(compiled_policy: Path) -> None:
    result = _run_policy(
        compiled_policy,
        """
        const current = {
          name: 'Oha-Yachiyo', channel: 'stable', branch: 'main',
          repository: policy.OFFICIAL_UPDATE_REPOSITORY,
          latest_json_url: 'https://github.com/kuguya-AI-app-develop/Hermes-Yachiyo/releases/download/main-latest/Oha-Yachiyo-main-latest.json',
        };
        const target = policy.trustedUpdateTarget(current);
        const metadata = {
          name: 'Oha-Yachiyo', channel: 'stable', branch: 'main',
          dmg_name: target.dmgFileName,
          download_url: target.downloadUrl,
          latest_json_url: target.metadataUrl,
          sha256: 'A'.repeat(64),
          dirty: false,
          release_publishable: true,
        };
        const accepted = policy.validateTrustedLatestMetadata(current, metadata);
        const rejected = [
          { ...metadata, sha256: '' },
          { ...metadata, sha256: 'a'.repeat(63) },
          { ...metadata, release_publishable: false },
          { ...metadata, release_publishable: undefined },
          { ...metadata, dirty: true },
          { ...metadata, dirty: undefined },
          { ...metadata, download_url: target.downloadUrl.replace('https:', 'http:') },
          { ...metadata, latest_json_url: `${target.metadataUrl}#latest` },
        ].map((candidate) => {
          try { policy.validateTrustedLatestMetadata(current, candidate); return false; } catch { return true; }
        });
        return { sha256: accepted.sha256, rejected };
        """,
    )

    assert result["sha256"] == "a" * 64
    assert result["rejected"] == [True] * 8


def test_download_record_requires_verified_sha_identity(compiled_policy: Path) -> None:
    result = _run_policy(
        compiled_policy,
        """
        const sha = 'b'.repeat(64);
        const latest = { sha256: sha };
        const good = {
          ok: true, verified: true, path: '/tmp/update.dmg', file_name: 'update.dmg',
          sha256: sha, latest: { sha256: sha },
        };
        return {
          good: policy.isVerifiedDownloadedUpdate(good, latest),
          unverified: policy.isVerifiedDownloadedUpdate({ ...good, verified: false }, latest),
          missing: policy.isVerifiedDownloadedUpdate({ ...good, sha256: undefined }, latest),
          embeddedMismatch: policy.isVerifiedDownloadedUpdate({ ...good, latest: { sha256: 'c'.repeat(64) } }, latest),
          latestMismatch: policy.isVerifiedDownloadedUpdate(good, { sha256: 'd'.repeat(64) }),
        };
        """,
    )

    assert result == {
        "good": True,
        "unverified": False,
        "missing": False,
        "embeddedMismatch": False,
        "latestMismatch": False,
    }


def test_installer_script_stages_validates_swaps_and_rolls_back(compiled_policy: Path) -> None:
    result = _run_policy(
        compiled_policy,
        """
        const script = policy.buildMacAppUpdateInstallerScript();
        const positions = {
          hash: script.indexOf('actual_sha256="$(/usr/bin/shasum'),
          stage: script.indexOf('/usr/bin/ditto "$source_app" "$staged_app"'),
          bundle: script.indexOf('CFBundleIdentifier'),
          codesign: script.indexOf('/usr/bin/codesign --verify --deep --strict "$staged_app"'),
          backup: script.indexOf('/bin/mv "$app_path" "$backup_app"'),
          install: script.indexOf('/bin/mv "$staged_app" "$app_path"'),
          open: script.indexOf('/usr/bin/open "$app_path"'),
        };
        return {
          script,
          positions,
          deletesCurrent: script.includes('rm -rf "$app_path"'),
          restoresBackup: script.includes('/bin/mv "$backup_app" "$app_path"'),
          preservesBackupOnRollbackFailure: script.includes('if [[ ! -e "$backup_app" ]]'),
        };
        """,
    )

    positions = result["positions"]
    subprocess.run(
        ["/bin/zsh", "-n"],
        input=result["script"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert 0 <= positions["hash"] < positions["stage"] < positions["bundle"]
    assert positions["bundle"] < positions["codesign"] < positions["backup"]
    assert positions["backup"] < positions["install"] < positions["open"]
    assert result["deletesCurrent"] is False
    assert result["restoresBackup"] is True
    assert result["preservesBackupOnRollbackFailure"] is True


def test_main_and_update_view_keep_installation_fail_closed() -> None:
    main = (FRONTEND / "electron" / "main.ts").read_text(encoding="utf-8")
    view = (FRONTEND / "src" / "views" / "AppUpdateView.tsx").read_text(encoding="utf-8")

    assert "validateTrustedLatestMetadata" in main
    assert "isVerifiedDownloadedUpdate" in main
    assert "verified: true" in main
    assert "verified: Boolean(expectedSha256)" not in main
    assert "const check = await checkAppUpdate();" in main
    assert "await sha256File(dmgPath)" in main
    assert "rm -rf \"$app_path\"" not in main
    assert "const installReady = Boolean(" in view
    assert "check?.ok === true" in view
    assert "download.verified !== true" in view
    assert "更新已下载，可安装并重启；当前元数据未提供 SHA256 校验值" not in view
    assert "{installReady ? (" in view
