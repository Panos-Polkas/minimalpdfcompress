from pathlib import Path
import shutil
import sys

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd().resolve()
GUI = ROOT / "src" / "gui.py"
BACKEND = ROOT / "src" / "backend.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{label}: expected exactly 1 matching source block, found {count}. "
            "Your checkout may differ from the current main branch. No files were changed."
        )
    return text.replace(old, new, 1)


def main():
    if not GUI.is_file() or not BACKEND.is_file():
        raise RuntimeError(
            f"Could not find src/gui.py and src/backend.py under:\n  {ROOT}\n"
            "Run this script from the minimalpdfcompress repository root, or pass the repository path as the first argument."
        )

    gui_text = GUI.read_text(encoding="utf-8")
    backend_text = BACKEND.read_text(encoding="utf-8")

    # 1) Recursive folder scanning.
    gui_text = replace_once(
        gui_text,
        '            pdf_files = sorted(list(folder_path.glob("*.pdf")))',
        '            # Include PDFs from the selected folder and every subfolder.\n'
        '            # Path objects preserve Unicode/Greek names.\n'
        '            pdf_files = sorted(folder_path.rglob("*.pdf"))',
        "Recursive PDF discovery",
    )

    gui_text = replace_once(
        gui_text,
        '                messagebox.showinfo("No Files", "No PDF files were found in that folder.", parent=self.root)',
        '                messagebox.showinfo("No Files", "No PDF files were found in that folder or its subfolders.", parent=self.root)',
        "Recursive-scan status message",
    )

    # 2) Add a helper that selects a writable ASCII-only temp directory.
    marker = "        processed_filenames = []\n\n        def process_a_file(input_file, output_file):"
    helper = '''        processed_filenames = []

        def get_ascii_temp_base():
            """Find a writable ASCII-only temp folder for legacy Windows CLI tools.

            Python/pathlib support Unicode paths, but some external PDF tools may
            still fail when paths contain Greek or other non-ASCII characters.
            Files passed to those tools are staged through this directory.
            """
            candidates = [tempfile.gettempdir()]

            if os.name == "nt":
                system_root = os.environ.get("SystemRoot")
                if system_root:
                    candidates.append(str(Path(system_root) / "Temp"))

            seen = set()
            for candidate in candidates:
                if not candidate or candidate in seen:
                    continue
                seen.add(candidate)

                try:
                    candidate.encode("ascii")
                except UnicodeEncodeError:
                    continue

                base = Path(candidate)
                try:
                    base.mkdir(parents=True, exist_ok=True)
                    with tempfile.NamedTemporaryFile(dir=base, delete=True):
                        pass
                    return base
                except OSError:
                    continue

            raise ProcessingError(
                "Could not find a writable ASCII-only temporary directory. "
                "Set TEMP/TMP to an ASCII-only path such as C:\\\\Temp and try again."
            )

        def process_a_file(input_file, output_file):'''
    backend_text = replace_once(backend_text, marker, helper, "ASCII-safe temporary directory helper")

    # 3) Stage both input and output through ASCII-only paths before invoking CLI tools.
    temp_old = '''            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_out:
                temp_output_path = Path(temp_out.name)

            try:
                if compression_mode == 'Lossless':'''
    temp_new = '''            ascii_temp_base = get_ascii_temp_base()
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, dir=ascii_temp_base) as temp_in:
                safe_input_path = Path(temp_in.name)
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, dir=ascii_temp_base) as temp_out:
                temp_output_path = Path(temp_out.name)

            try:
                # Python handles the original Unicode/Greek path; external tools
                # only see the ASCII-safe staged path.
                shutil.copy2(input_file, safe_input_path)

                if compression_mode == 'Lossless':'''
    backend_text = replace_once(backend_text, temp_old, temp_new, "Unicode-safe staging setup")

    replacements = [
        (
            "optimizer.optimize_true_lossless(input_file, temp_output_path, strip_metadata=params['strip_metadata'])",
            "optimizer.optimize_true_lossless(safe_input_path, temp_output_path, strip_metadata=params['strip_metadata'])",
            "True-lossless input path",
        ),
        (
            "optimizer.optimize_lossless(input_file, temp_output_path, strip_metadata=params['strip_metadata'])",
            "optimizer.optimize_lossless(safe_input_path, temp_output_path, strip_metadata=params['strip_metadata'])",
            "Lossless input path",
        ),
        (
            "optimizer.optimize_pdfa(input_file, temp_output_path)",
            "optimizer.optimize_pdfa(safe_input_path, temp_output_path)",
            "PDF/A input path",
        ),
        (
            "optimizer.optimize_text_only(input_file, temp_output_path, strip_metadata=params['strip_metadata'])",
            "optimizer.optimize_text_only(safe_input_path, temp_output_path, strip_metadata=params['strip_metadata'])",
            "Text-only input path",
        ),
        (
            "                        input_file, temp_output_path, params['dpi'],",
            "                        safe_input_path, temp_output_path, params['dpi'],",
            "Lossy input path",
        ),
    ]
    for old, new, label in replacements:
        backend_text = replace_once(backend_text, old, new, label)

    cleanup_old = '''            finally:
                if temp_output_path.exists():
                    os.remove(temp_output_path)
            return 0 # Return 0 size contribution if error wasn't handled by copying original'''
    cleanup_new = '''            finally:
                if temp_output_path.exists():
                    os.remove(temp_output_path)
                if safe_input_path.exists():
                    os.remove(safe_input_path)
            return 0 # Return 0 size contribution if error wasn't handled by copying original'''
    backend_text = replace_once(backend_text, cleanup_old, cleanup_new, "Temporary-file cleanup")

    # All checks/replacements succeeded. Only now make backups and write changes.
    gui_backup = GUI.with_suffix(GUI.suffix + ".bak")
    backend_backup = BACKEND.with_suffix(BACKEND.suffix + ".bak")
    shutil.copy2(GUI, gui_backup)
    shutil.copy2(BACKEND, backend_backup)

    GUI.write_text(gui_text, encoding="utf-8")
    BACKEND.write_text(backend_text, encoding="utf-8")

    print("Fixes applied successfully.")
    print(f"Modified: {GUI}")
    print(f"Modified: {BACKEND}")
    print(f"Backup:   {gui_backup}")
    print(f"Backup:   {backend_backup}")
    print()
    print("Changes:")
    print("  1. Add Folder now searches recursively with Path.rglob('*.pdf').")
    print("  2. Compression stages external-tool input/output through ASCII-only temp paths.")
    print("  3. Original Greek filenames and destination paths are preserved by Python.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
