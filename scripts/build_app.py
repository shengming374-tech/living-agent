"""Build relocatable native macOS app or Windows CLI / 构建内置 Python 的便携应用。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*arguments: str, cwd: Path = ROOT) -> None:
    print("+", " ".join(arguments), flush=True)
    subprocess.run(arguments, cwd=cwd, check=True)  # noqa: S603 - host-controlled build arguments.


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--python", default="3.12")
    parser.add_argument("--identity", default="-", help="macOS signing identity / 签名身份")
    args = parser.parse_args()
    uv_binary = shutil.which("uv")
    if uv_binary is None:
        raise RuntimeError("Install uv before building / 请先安装 uv")
    system = platform.system()
    if system not in {"Darwin", "Windows"}:
        parser.error("Build on macOS or Windows / 请在目标系统构建")
    output = (
        args.output or ROOT / "dist" / ("macos" if system == "Darwin" else "windows")
    ).resolve()
    output.mkdir(parents=True, exist_ok=True)
    destination = output / ("LivingAgent.app" if system == "Darwin" else "LivingAgent-CLI")
    if destination.exists():
        parser.error(f"Output already exists / 输出已存在: {destination}")
    with tempfile.TemporaryDirectory(prefix="living-agent-build-") as temporary:
        stage = Path(temporary)
        wheels = stage / "wheels"
        run(
            "uv",
            "build",
            "--wheel",
            "--out-dir",
            str(wheels),
            "--no-sources",
            "--python",
            sys.executable,
        )
        locked = stage / "requirements.txt"
        run(
            "uv",
            "export",
            "--frozen",
            "--no-dev",
            "--no-emit-project",
            "--no-editable",
            "--output-file",
            str(locked),
            "--quiet",
        )
        managed = stage / "python"
        run(
            "uv",
            "python",
            "install",
            args.python,
            "--install-dir",
            str(managed),
            "--no-bin",
            "--no-registry",
        )
        # Windows aliases can be junctions, rather than symlinks. Ask uv for the interpreter.
        # 使用 uv 定位解释器, 不依赖 Windows junction 的目录枚举结果。
        located = subprocess.check_output(  # noqa: S603 - fixed locator, isolated install root.
            [
                uv_binary,
                "python",
                "find",
                args.python,
                "--system",
                "--managed-python",
                "--no-project",
                "--no-config",
                "--no-python-downloads",
            ],
            cwd=stage,
            env={**os.environ, "UV_PYTHON_INSTALL_DIR": str(managed)},
            text=True,
            encoding="utf-8",
        )
        python = Path(located.strip()).resolve()
        runtime = python.parent.parent if system == "Darwin" else python.parent
        if not runtime.is_relative_to(managed.resolve()):
            raise RuntimeError("Runtime must be inside the isolated build directory")
        run(
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--system",
            "--break-system-packages",
            "--no-deps",
            "-r",
            str(locked),
        )
        run(
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--system",
            "--break-system-packages",
            "--no-deps",
            str(next(wheels.glob("*.whl"))),
        )
        if system == "Darwin":
            derived = stage / "xcode"
            run(
                "xcodebuild",
                "-project",
                str(ROOT / "apps/apple/LivingAgent.xcodeproj"),
                "-scheme",
                "LivingAgent",
                "-configuration",
                "Release",
                "-sdk",
                "macosx",
                "-derivedDataPath",
                str(derived),
                "CODE_SIGNING_ALLOWED=NO",
                f"ARCHS={platform.machine()}",
                "build",
            )
            app = derived / "Build/Products/Release/LivingAgent.app"
            shutil.copytree(runtime, app / "Contents/Resources/runtime", symlinks=True)
            shutil.copy2(ROOT / "LICENSE", app / "Contents/Resources/LICENSE")
            run("xattr", "-cr", str(app))
            bundled_python = (app / "Contents/Resources/runtime/bin/python3").resolve()
            # Sign libraries before the host; no sandbox is granted to the whole Python runtime.
            # 先签内置动态库, 再签宿主; 插件继续使用独立 OS 沙箱。
            binaries = [
                path
                for path in (app / "Contents/Resources/runtime").rglob("*")
                if path.is_file()
                and not path.is_symlink()
                and (path.suffix in {".so", ".dylib"} or path.resolve() == bundled_python)
            ]
            for binary in sorted(binaries):
                run("codesign", "--force", "--sign", args.identity, str(binary))
            run(
                "codesign",
                "--force",
                "--deep",
                "--sign",
                args.identity,
                *(["--options", "runtime", "--timestamp"] if args.identity != "-" else []),
                str(app),
            )
            run("codesign", "--verify", "--deep", "--strict", str(app))
            shutil.copytree(app, destination, symlinks=True)
            dmg_stage = stage / "dmg"
            dmg_stage.mkdir()
            (dmg_stage / "Applications").symlink_to("/Applications")
            # File Provider can attach Finder metadata to the output directory.
            # 从已验证的临时目录制作镜像, 避免云盘元数据污染签名。
            shutil.copytree(app, dmg_stage / destination.name, symlinks=True)
            run(
                "hdiutil",
                "create",
                "-volname",
                "LivingAgent",
                "-srcfolder",
                str(dmg_stage),
                "-format",
                "UDZO",
                str(output / f"LivingAgent-macos-{platform.machine()}.dmg"),
            )
        else:
            destination.mkdir()
            shutil.copytree(runtime, destination / "runtime", symlinks=False)
            shutil.copy2(ROOT / "apps/windows/living-agent.cmd", destination)
            shutil.copy2(ROOT / "apps/windows/living-agent-psyche.cmd", destination)
            shutil.copy2(ROOT / "LICENSE", destination)
            shutil.copy2(ROOT / "docs/APPS.md", destination / "README.md")
            shutil.make_archive(
                str(output / "LivingAgent-windows-x64"), "zip", output, destination.name
            )
        checksums = []
        for asset in sorted(output.glob("*")):
            if asset.suffix in {".zip", ".dmg"}:
                checksums.append(
                    f"{hashlib.file_digest(asset.open('rb'), 'sha256').hexdigest()}  {asset.name}"
                )
        (output / "SHA256SUMS").write_text("\n".join(checksums) + "\n")
        print(json.dumps({"application": str(destination)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
