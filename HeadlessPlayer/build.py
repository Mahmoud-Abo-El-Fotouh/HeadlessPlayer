#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone packaging and localization build script for HeadlessPlayer NVDA Add-on.
Zero external dependencies required (features built-in pure Python GNU gettext msgfmt compiler).

Usage:
    python build.py
    python build.py --clean
    python build.py --output "C:/path/to/dist"
    python build.py --label "InitialRelease"
"""

import os
import sys
import re
import struct
import array
import zipfile
import hashlib
import shutil
import argparse
from typing import Dict, List, Tuple

# Reconfigure stdout/stderr for safe Unicode printing on Windows
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


class PurePythonMsgfmt:
    """
    Pure-Python parser for GNU .po files and generator of binary .mo files.
    Complies with GNU gettext MO file specification.
    """
    def __init__(self) -> None:
        self.messages: Dict[str, str] = {}

    def parse_po(self, po_filepath: str) -> None:
        self.messages = {}
        with open(po_filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()

        msgid = None
        msgstr = None
        in_msgid = False
        in_msgstr = False

        def unescape(s: str) -> str:
            res: List[str] = []
            i = 0
            n = len(s)
            while i < n:
                if s[i] == "\\" and i + 1 < n:
                    nxt = s[i + 1]
                    if nxt == "n":
                        res.append("\n")
                    elif nxt == "t":
                        res.append("\t")
                    elif nxt == "r":
                        res.append("\r")
                    elif nxt == '"':
                        res.append('"')
                    elif nxt == "\\":
                        res.append("\\")
                    else:
                        res.append("\\" + nxt)
                    i += 2
                else:
                    res.append(s[i])
                    i += 1
            return "".join(res)

        def extract_quoted(line: str) -> str:
            line = line.strip()
            if line.startswith('"') and line.endswith('"'):
                return line[1:-1]
            return ""

        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            if line.startswith("msgid "):
                if msgid is not None and msgstr is not None:
                    self.messages[msgid] = msgstr
                rest = line[6:].strip()
                msgid = unescape(extract_quoted(rest))
                msgstr = None
                in_msgid = True
                in_msgstr = False
            elif line.startswith("msgstr "):
                rest = line[7:].strip()
                msgstr = unescape(extract_quoted(rest))
                in_msgid = False
                in_msgstr = True
            elif line.startswith('"') and line.endswith('"'):
                content = unescape(extract_quoted(line))
                if in_msgid and msgid is not None:
                    msgid += content
                elif in_msgstr and msgstr is not None:
                    msgstr += content

        if msgid is not None and msgstr is not None:
            self.messages[msgid] = msgstr

    def generate_mo(self, mo_filepath: str) -> None:
        keys = sorted(self.messages.keys())
        offsets: List[Tuple[int, int, int, int]] = []
        ids = b""
        strs = b""

        for k in keys:
            v = self.messages[k]
            k_bytes = k.encode("utf-8")
            v_bytes = v.encode("utf-8")

            offsets.append((len(ids), len(k_bytes), len(strs), len(v_bytes)))
            ids += k_bytes + b"\x00"
            strs += v_bytes + b"\x00"

        key_start = 7 * 4 + len(keys) * 8 * 2
        value_start = key_start + len(ids)

        karray: List[int] = []
        varray: List[int] = []
        for id_offset, id_len, str_offset, str_len in offsets:
            karray.extend([id_len, id_offset + key_start])
            varray.extend([str_len, str_offset + value_start])

        header = struct.pack(
            "Iiiiiii",
            0x950412DE,             # Magic number (LE)
            0,                      # Version
            len(keys),              # Number of strings
            7 * 4,                  # Offset of original strings table
            7 * 4 + len(keys) * 8,  # Offset of translation strings table
            0,                      # Hash table size
            0                       # Hash table offset
        )

        with open(mo_filepath, "wb") as f:
            f.write(header)
            f.write(array.array("i", karray).tobytes())
            f.write(array.array("i", varray).tobytes())
            f.write(ids)
            f.write(strs)


def compile_locales(base_dir: str) -> None:
    """
    Compiles all .po files under locale/*/LC_MESSAGES/ into binary .mo files,
    generating both domain-specific .mo and NVDA's standard nvda.mo.
    """
    locale_dir = os.path.join(base_dir, "locale")
    if not os.path.exists(locale_dir):
        print("[!] No locale directory found. Skipping translation compilation.")
        return

    compiler = PurePythonMsgfmt()
    for root, _, files in os.walk(locale_dir):
        for f in files:
            if f.endswith(".po"):
                po_path = os.path.join(root, f)
                mo_name = os.path.splitext(f)[0] + ".mo"
                mo_path = os.path.join(root, mo_name)
                nvda_mo_path = os.path.join(root, "nvda.mo")

                print(f"[*] Compiling translation: {os.path.relpath(po_path, base_dir)} -> {mo_name} & nvda.mo")
                compiler.parse_po(po_path)
                compiler.generate_mo(mo_path)
                compiler.generate_mo(nvda_mo_path)
                print(f"    Compiled {len(compiler.messages)} translation strings into {mo_name} and nvda.mo.")


def parse_manifest(manifest_path: str) -> Dict[str, str]:
    """
    Parses manifest.ini key-value pairs.
    """
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"manifest.ini not found at {manifest_path}")

    manifest_data: Dict[str, str] = {}
    with open(manifest_path, "r", encoding="utf-8") as f:
        multiline_key = None
        multiline_val: List[str] = []

        for raw_line in f:
            line = raw_line.strip()
            if multiline_key is not None:
                if line.endswith('"""') or line.endswith("'''"):
                    multiline_val.append(line[:-3].strip())
                    manifest_data[multiline_key] = " ".join(multiline_val)
                    multiline_key = None
                    multiline_val = []
                else:
                    multiline_val.append(line)
                continue

            if not line or line.startswith("#") or line.startswith(";"):
                continue

            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip()
                if val.startswith('"""') or val.startswith("'''"):
                    if (val.startswith('"""') and val.endswith('"""') and len(val) >= 6) or \
                       (val.startswith("'''") and val.endswith("'''") and len(val) >= 6):
                        manifest_data[key] = val[3:-3].strip()
                    else:
                        multiline_key = key
                        multiline_val = [val[3:].strip()]
                else:
                    val = val.strip('"').strip("'")
                    manifest_data[key] = val

    return manifest_data


def sync_documentation_versions(base_dir: str, manifest: Dict[str, str]) -> None:
    """
    Automatically synchronizes version and NVDA compatibility across README.md
    and all doc/* documentation files based on manifest.ini.
    """
    version = manifest.get("version", "1.0.0")
    min_ver = manifest.get("minimumNVDAVersion", "2022.1")
    last_ver = manifest.get("lastTestedNVDAVersion", "2026.1")
    author = manifest.get("author", "Mahmoud Abo El Fotouh <mahmoudaboelfotouh.20@gmail.com>")
    
    root_dir = os.path.dirname(base_dir) if os.path.basename(base_dir) == "HeadlessPlayer" else base_dir
    
    # 1. Root README.md
    readme_path = os.path.join(root_dir, "README.md")
    if os.path.isfile(readme_path):
        with open(readme_path, "r", encoding="utf-8") as f:
            content = f.read()
        content = re.sub(r"\*\*Version:\*\*.*", f"**Version:** {version}  ", content)
        content = re.sub(r"\*\*NVDA Compatibility:\*\*.*", f"**NVDA Compatibility:** NVDA {min_ver} to {last_ver}+", content)
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(content)

    # 2. English doc/en/readme.md
    en_md = os.path.join(base_dir, "doc", "en", "readme.md")
    if os.path.isfile(en_md):
        with open(en_md, "r", encoding="utf-8") as f:
            content = f.read()
        content = re.sub(r"\*\*Version:\*\*.*", f"**Version:** {version}  ", content)
        content = re.sub(r"\*\*NVDA Compatibility:\*\*.*", f"**NVDA Compatibility:** NVDA {min_ver} to {last_ver}+", content)
        with open(en_md, "w", encoding="utf-8") as f:
            f.write(content)

    # 3. English doc/en/readme.html
    en_html = os.path.join(base_dir, "doc", "en", "readme.html")
    if os.path.isfile(en_html):
        with open(en_html, "r", encoding="utf-8") as f:
            content = f.read()
        escaped_author = author.replace('<', '&lt;').replace('>', '&gt;')
        content = re.sub(
            r"<p><strong>Version:</strong>.*?<strong>NVDA Compatibility:</strong>.*?</p>",
            f"<p><strong>Version:</strong> {version} &nbsp;|&nbsp; <strong>Author:</strong> {escaped_author} &nbsp;|&nbsp; <strong>NVDA Compatibility:</strong> NVDA {min_ver} to {last_ver}+</p>",
            content
        )
        with open(en_html, "w", encoding="utf-8") as f:
            f.write(content)

    # 4. Arabic doc/ar/readme.md
    ar_md = os.path.join(base_dir, "doc", "ar", "readme.md")
    if os.path.isfile(ar_md):
        with open(ar_md, "r", encoding="utf-8") as f:
            content = f.read()
        content = re.sub(r"\*\*الإصدار:\*\*.*", f"**الإصدار:** {version}  ", content)
        content = re.sub(r"\*\*التوافق:\*\*.*", f"**التوافق:** NVDA {min_ver} إلى {last_ver} وأحدث", content)
        with open(ar_md, "w", encoding="utf-8") as f:
            f.write(content)

    # 5. Arabic doc/ar/readme.html
    ar_html = os.path.join(base_dir, "doc", "ar", "readme.html")
    if os.path.isfile(ar_html):
        with open(ar_html, "r", encoding="utf-8") as f:
            content = f.read()
        content = re.sub(
            r"<p><strong>الإصدار:</strong>.*?<strong>التوافق:</strong>.*?</p>",
            f"<p><strong>الإصدار:</strong> {version} &nbsp;|&nbsp; <strong>المطور:</strong> محمود أبو الفتوح &lt;mahmoudaboelfotouh.20@gmail.com&gt; &nbsp;|&nbsp; <strong>التوافق:</strong> NVDA {min_ver} إلى {last_ver} وأحدث</p>",
            content
        )
        with open(ar_html, "w", encoding="utf-8") as f:
            f.write(content)


def package_addon(base_dir: str, output_dir: str, custom_label: str = None) -> str:
    """
    Packages the add-on directory into a .nvda-addon archive with proper naming convention.
    """
    manifest_path = os.path.join(base_dir, "manifest.ini")
    manifest = parse_manifest(manifest_path)

    # Automatically synchronize documentation versions with manifest.ini
    sync_documentation_versions(base_dir, manifest)

    name = manifest.get("name", "HeadlessPlayer")
    version = manifest.get("version", "1.0.0")
    if custom_label:
        summary_slug = re.sub(r"[^\w\d_-]", "_", custom_label).strip("_")
        addon_filename = f"{name}_v{version}_{summary_slug}.nvda-addon"
    else:
        addon_filename = f"{name}_v{version}.nvda-addon"

    os.makedirs(output_dir, exist_ok=True)
    addon_filepath = os.path.join(output_dir, addon_filename)

    # Excluded files and directories
    EXCLUDE_DIRS = {".git", ".github", ".vscode", "__pycache__", ".agents", "tests", "dist"}
    EXCLUDE_EXTS = {".pyc", ".pyo", ".gitattributes", ".gitignore", ".tmp"}

    # Guard: Ensure mpv.exe binary is present and not a tiny Git LFS text pointer
    mpv_binary_path = os.path.join(base_dir, "resources", "bin", "x64", "mpv.exe")
    if os.path.exists(mpv_binary_path):
        mpv_size = os.path.getsize(mpv_binary_path)
        if mpv_size < 1024 * 1024:
            raise RuntimeError(
                f"FATAL: {mpv_binary_path} is only {mpv_size} bytes (Git LFS pointer) instead of the full binary! "
                "Please run 'git lfs pull' or enable 'lfs: true' in GitHub Actions checkout."
            )

    print(f"\n[*] Packaging NVDA Add-on: {addon_filename}")
    added_count = 0
    with zipfile.ZipFile(addon_filepath, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(base_dir):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".")]

            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in EXCLUDE_EXTS or file.endswith("~") or file == "build.py":
                    continue

                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, base_dir)

                # Skip output directory if inside base_dir
                if os.path.abspath(full_path) == os.path.abspath(addon_filepath):
                    continue

                zipf.write(full_path, rel_path)
                print(f"  + Added: {rel_path}")
                added_count += 1

    # Calculate SHA-256 Checksum
    sha256 = hashlib.sha256()
    with open(addon_filepath, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    digest = sha256.hexdigest()

    file_size_bytes = os.path.getsize(addon_filepath)
    file_size_kb = file_size_bytes / 1024.0

    print("\n" + "=" * 64)
    print(" HEADLESSPLAYER ADD-ON BUILD SUCCESSFUL!")
    print(f" Package:  {addon_filename}")
    print(f" Path:     {addon_filepath}")
    print(f" Files:    {added_count} files bundled")
    print(f" Size:     {file_size_kb:.2f} KB ({file_size_bytes:,} bytes)")
    print(f" SHA-256:  {digest}")
    print("=" * 64 + "\n")
    return addon_filepath


def main() -> None:
    parser = argparse.ArgumentParser(description="HeadlessPlayer NVDA Add-on Builder")
    parser.add_argument("--clean", action="store_true", help="Clean up compiled .mo and build files")
    parser.add_argument("--output", default=None, help="Custom output directory for the .nvda-addon package")
    parser.add_argument("--label", default=None, help="Custom naming label / slug (e.g. InitialRelease)")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = args.output or os.path.join(base_dir, "dist")

    if args.clean:
        print("[*] Cleaning build artifacts...")
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
        for root, _, files in os.walk(base_dir):
            for f in files:
                if f.endswith(".mo") or f.endswith(".pyc"):
                    try:
                        os.remove(os.path.join(root, f))
                    except Exception:
                        pass
        print("[*] Clean completed.")
        return

    # 1. Compile PO files into binary MO files
    compile_locales(base_dir)

    # 2. Package Add-on into .nvda-addon bundle
    package_addon(base_dir, output_dir, custom_label=args.label)


if __name__ == "__main__":
    main()
