#!/usr/bin/env python3
import os
import sys
import re
import shutil
import subprocess
import plistlib

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

    print("\n🎉 BUILD COMPLETE SUCCESSFUL!")
    print(f"📍 Application Location: {bundle_dir}")
    print("══════════════════════════════════════════════════")

if __name__ == "__main__":
    main()
