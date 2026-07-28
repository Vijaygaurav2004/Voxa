#!/usr/bin/env python3
import os
import sys
import re
import shutil
import subprocess
import plistlib
import tempfile
from pathlib import Path


# Credentials baked into the bundle so a downloaded DMG works out of the box.
# OAuth ids/secrets are optional — absent ones simply leave that integration as
# "Setup…" in the app until the developer adds them and rebuilds.
_EMBED_KEYS = [
    "OPENAI_API_KEY",
    "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
    "GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET",
]


def _mask(value: str) -> str:
    """Mask a secret for logging — never print full credential values."""
    if not value:
        return "(empty)"
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:4]}…{value[-4:]} (len {len(value)})"


def _read_env_file(path: Path) -> dict:
    """Parse a simple KEY=value .env file into a dict (ignores comments/blanks)."""
    out = {}
    try:
        for line in path.read_text().splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def collect_credentials(workspace_dir: str) -> dict:
    """
    Gather embeddable credentials, precedence: real environment > ~/.voxa/.env >
    <project>/.env. Returns only the keys in _EMBED_KEYS that have a value.
    """
    sources = [
        _read_env_file(Path.home() / ".voxa" / ".env"),
        _read_env_file(Path(workspace_dir) / ".env"),
    ]
    creds = {}
    for key in _EMBED_KEYS:
        val = os.environ.get(key)
        if not val:
            for src in sources:
                if src.get(key):
                    val = src[key]
                    break
        if val:
            creds[key] = val
    return creds


def embed_credentials(contents_dir: str, workspace_dir: str) -> None:
    """Write the collected credentials into Contents/Resources/voxa-defaults.env."""
    creds = collect_credentials(workspace_dir)
    resources_dir = os.path.join(contents_dir, "Resources")
    os.makedirs(resources_dir, exist_ok=True)
    dest = os.path.join(resources_dir, "voxa-defaults.env")

    print("🔐 Embedding bundle credentials (masked):")
    for key in _EMBED_KEYS:
        if key in creds:
            print(f"     {key}: {_mask(creds[key])}")
        else:
            note = "→ Google sign-in shows Setup…" if key.startswith("GOOGLE") else (
                "→ GitHub shows Setup…" if key.startswith("GITHUB") else "→ app will prompt on first run")
            print(f"     {key}: not set  {note}")

    lines = ["# Embedded at build time — do not edit. Overridden by ~/.voxa/.env.\n"]
    lines += [f"{k}={creds[k]}\n" for k in _EMBED_KEYS if k in creds]
    with open(dest, "w") as f:
        f.writelines(lines)
    os.chmod(dest, 0o600)
    print(f"✅ Wrote {dest} ({len([k for k in _EMBED_KEYS if k in creds])} credential(s))\n")


def make_dmg(bundle_dir: str, app_name: str, builds_dir: str) -> str:
    """Build a drag-to-Applications .dmg (compressed) from the .app bundle."""
    dmg_path = os.path.join(builds_dir, f"{app_name}.dmg")
    if os.path.exists(dmg_path):
        os.remove(dmg_path)

    print("💽 Building DMG (drag-to-Applications)...")
    staging = tempfile.mkdtemp(prefix="voxa_dmg_")
    try:
        # Copy the app in (preserve symlinks/signature), add an /Applications alias.
        shutil.copytree(bundle_dir, os.path.join(staging, f"{app_name}.app"), symlinks=True)
        os.symlink("/Applications", os.path.join(staging, "Applications"))
        subprocess.run(
            ["hdiutil", "create",
             "-volname", app_name,
             "-srcfolder", staging,
             "-ov", "-format", "UDZO",
             dmg_path],
            check=True, capture_output=True, text=True,
        )
        print(f"✅ DMG created: {dmg_path}")
        return dmg_path
    except subprocess.CalledProcessError as e:
        print(f"⚠️  DMG creation failed: {e.stderr.strip()}")
        return ""
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def build_backend(workspace_dir: str, force: bool = True) -> str:
    """
    Build the self-contained Python backend with PyInstaller so the shipped .app
    needs no Python install. Returns the path to the onedir output folder
    (…/backend_dist/voxa-backend) that gets embedded into the bundle.
    """
    dist_dir = os.path.join(workspace_dir, "backend_dist")
    work_dir = os.path.join(workspace_dir, "backend_work")
    out_folder = os.path.join(dist_dir, "voxa-backend")
    entry = os.path.join(workspace_dir, "scripts", "backend_entry.py")

    if os.path.exists(out_folder) and not force:
        print(f"♻️  Reusing existing backend build at: {out_folder}")
        return out_folder

    print("🐍 Building standalone Python backend (PyInstaller)...")
    cmd = [
        sys.executable, "-m", "PyInstaller", entry,
        "--name", "voxa-backend",
        "--noconfirm", "--clean",
        "--distpath", dist_dir,
        "--workpath", work_dir,
        "--specpath", work_dir,
        "--paths", workspace_dir,
        "--collect-all", "uvicorn",
        "--collect-submodules", "voxa",
        "--hidden-import", "webrtcvad",
        "--hidden-import", "sounddevice",
        "--hidden-import", "multipart",
        "--hidden-import", "websockets",
    ]
    try:
        subprocess.run(cmd, cwd=workspace_dir, check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Backend build failed (exit {e.returncode})")
        sys.exit(1)

    exe = os.path.join(out_folder, "voxa-backend")
    if not os.path.exists(exe):
        print(f"❌ Backend executable not found at: {exe}")
        sys.exit(1)
    print(f"✅ Backend built: {out_folder}\n")
    return out_folder


def main():
    # Setup paths relative to script location
    script_dir = os.path.dirname(os.path.abspath(__file__))
    workspace_dir = os.path.dirname(script_dir)
    voxa_app_dir = os.path.join(workspace_dir, "VoxaApp")
    builds_dir = os.path.join(workspace_dir, "builds")

    print("══════════════════════════════════════════════════")
    print("🚀  VOXA BUILD PIPELINE")
    print("══════════════════════════════════════════════════\n")

    # Ensure builds directory exists
    if not os.path.exists(builds_dir):
        os.makedirs(builds_dir)
        print(f"📁 Created builds directory at: {builds_dir}")

    # Scan builds directory to determine next version
    existing_builds = []
    pattern = re.compile(r'^voxa\s+(\d+)\.app$', re.IGNORECASE)
    for name in os.listdir(builds_dir):
        match = pattern.match(name)
        if match:
            existing_builds.append(int(match.group(1)))

    next_version = 2
    if existing_builds:
        next_version = max(existing_builds) + 1

    print(f"📦 Existing builds found: {sorted(existing_builds)}")
    print(f"⭐ Next build target name: voxa {next_version}.app\n")

    # Compile Swift target
    print("🔨 Compiling VoxaApp in release mode...")
    try:
        res = subprocess.run(["swift", "build", "-c", "release"], cwd=voxa_app_dir, check=True)
        print("✅ Swift compilation succeeded!\n")
    except subprocess.CalledProcessError as e:
        print(f"❌ Swift compilation failed with exit code: {e.returncode}")
        sys.exit(1)

    # Build the self-contained Python backend (unless told to reuse it)
    skip_backend = "--skip-backend" in sys.argv
    backend_folder = build_backend(workspace_dir, force=not skip_backend)

    # Prepare bundle directory structure
    app_name = f"voxa {next_version}"
    bundle_dir = os.path.join(builds_dir, f"{app_name}.app")
    contents_dir = os.path.join(bundle_dir, "Contents")
    macos_dir = os.path.join(contents_dir, "MacOS")

    if os.path.exists(bundle_dir):
        print(f"⚠️ Warning: Target build directory {bundle_dir} already exists. Overwriting it.")
        shutil.rmtree(bundle_dir)

    os.makedirs(macos_dir, exist_ok=True)
    print(f"📁 Created app bundle structure at: {bundle_dir}")

    # Copy and customize Info.plist
    src_plist = os.path.join(voxa_app_dir, "Sources", "Info.plist")
    dest_plist = os.path.join(contents_dir, "Info.plist")

    if not os.path.exists(src_plist):
        print(f"❌ Source Info.plist not found at: {src_plist}")
        sys.exit(1)

    print("📄 Configuring Info.plist...")
    try:
        with open(src_plist, "rb") as fp:
            plist = plistlib.load(fp)

        plist["CFBundleName"] = app_name
        plist["CFBundleExecutable"] = app_name
        plist["CFBundleIdentifier"] = f"com.voxa.voxa{next_version}"
        plist["CFBundleVersion"] = f"{next_version}.0"
        plist["CFBundleShortVersionString"] = f"{next_version}.0"

        with open(dest_plist, "wb") as fp:
            plistlib.dump(plist, fp)
        print("✅ Configured Info.plist")
    except Exception as e:
        print(f"❌ Failed to parse/write Info.plist: {e}")
        sys.exit(1)

    # Copy binary and set executable permission
    src_binary = os.path.join(voxa_app_dir, ".build", "release", "VoxaApp")
    dest_binary = os.path.join(macos_dir, app_name)

    if not os.path.exists(src_binary):
        print(f"❌ Compiled binary not found at: {src_binary}")
        sys.exit(1)

    print(f"💾 Copying executable binary...")
    try:
        shutil.copy2(src_binary, dest_binary)
        os.chmod(dest_binary, 0o755)
        print(f"✅ Copied executable and set permissions")
    except Exception as e:
        print(f"❌ Failed to copy binary: {e}")
        sys.exit(1)

    # Embed the standalone Python backend into Contents/Resources/backend/
    resources_dir = os.path.join(contents_dir, "Resources")
    backend_dest = os.path.join(resources_dir, "backend", "voxa-backend")
    print("📦 Embedding Python backend into the app bundle...")
    try:
        os.makedirs(os.path.join(resources_dir, "backend"), exist_ok=True)
        if os.path.exists(backend_dest):
            shutil.rmtree(backend_dest)
        shutil.copytree(backend_folder, backend_dest, symlinks=True)
        os.chmod(os.path.join(backend_dest, "voxa-backend"), 0o755)
        print(f"✅ Embedded backend at: {backend_dest}")
    except Exception as e:
        print(f"❌ Failed to embed backend: {e}")
        sys.exit(1)

    # Embed credentials (OpenAI key + any OAuth ids/secrets) BEFORE signing so
    # they're covered by the signature — this is what makes the DMG "just work".
    embed_credentials(contents_dir, workspace_dir)

    # Ad-hoc code-sign the whole bundle so macOS lets it launch.
    print("🔏 Ad-hoc code-signing the bundle...")
    try:
        subprocess.run(
            ["codesign", "--force", "--deep", "--sign", "-", bundle_dir],
            check=True, capture_output=True, text=True,
        )
        print("✅ Code-signed (ad-hoc)")
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Ad-hoc code-signing failed (app may still run): {e.stderr.strip()}")

    # Build the distributable DMG (drag-to-Applications). Skip with --no-dmg.
    dmg_path = ""
    if "--no-dmg" not in sys.argv:
        dmg_path = make_dmg(bundle_dir, app_name, builds_dir)

    print("\n🎉 BUILD COMPLETE SUCCESSFUL!")
    print(f"📍 Application: {bundle_dir}")
    if dmg_path:
        print(f"💽 Distributable: {dmg_path}")
        print("   To share: send the .dmg — the recipient opens it and drags Voxa to Applications.")
        print("   First launch: right-click Voxa → Open (ad-hoc signature), then grant permissions.")
    print("══════════════════════════════════════════════════")

if __name__ == "__main__":
    main()
