#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(dirname -- "$script_dir")"
bundle_dir="${1:-$project_dir/Colmap}"
colmap_executable="${COLMAP_BIN:-$(command -v colmap || true)}"
extra_library_path="${COLMAP_EXTRA_LIBRARY_PATH:-}"

if [[ -z "$colmap_executable" || ! -x "$colmap_executable" ]]; then
    echo "COLMAP was not found. Install it or set COLMAP_BIN." >&2
    exit 1
fi

colmap_executable="$(readlink -f -- "$colmap_executable")"
mkdir -p -- "$bundle_dir/bin" "$bundle_dir/lib"
install -m 0755 -- "$colmap_executable" "$bundle_dir/bin/colmap"

runtime_library_path="$extra_library_path"
if [[ -n "${LD_LIBRARY_PATH:-}" ]]; then
    runtime_library_path="${runtime_library_path:+$runtime_library_path:}$LD_LIBRARY_PATH"
fi

ldd_output="$(
    LD_LIBRARY_PATH="$runtime_library_path" ldd "$colmap_executable"
)"

if grep -qi "libmkl" <<<"$ldd_output"; then
    echo "COLMAP is linked to Intel MKL, which is not safe to bundle partially." >&2
    echo "Recompile COLMAP with OpenBLAS before creating the bundle." >&2
    exit 1
fi

is_host_runtime_library() {
    case "$1" in
        ld-linux-*|libc.so.*|libdl.so.*|libm.so.*|libpthread.so.*|librt.so.*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

while IFS= read -r dependency; do
    [[ -n "$dependency" && -f "$dependency" ]] || continue
    dependency_name="$(basename -- "$dependency")"
    if is_host_runtime_library "$dependency_name"; then
        continue
    fi
    install -m 0644 -- "$dependency" "$bundle_dir/lib/$dependency_name"
done < <(
    printf '%s\n' "$ldd_output" |
        awk '/=> \// { print $3 } /^\// { print $1 }' |
        sort -u
)

if grep -q "not found" <<<"$ldd_output"; then
    echo "COLMAP has unresolved shared-library dependencies:" >&2
    grep "not found" <<<"$ldd_output" >&2
    exit 1
fi

LD_LIBRARY_PATH="$bundle_dir/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
    "$bundle_dir/bin/colmap" -h >/dev/null

echo "COLMAP Linux bundle created: $bundle_dir"
echo "Executable: $bundle_dir/bin/colmap"
echo "Libraries: $bundle_dir/lib"
