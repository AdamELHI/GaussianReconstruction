#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
workspace_dir="$(dirname -- "$(dirname -- "$script_dir")")"
bundle_dir="${1:-$workspace_dir/Colmap}"
colmap_executable="${COLMAP_BIN:-$(command -v colmap || true)}"

if [[ -z "$colmap_executable" || ! -x "$colmap_executable" ]]; then
    echo "COLMAP was not found. Install it or set COLMAP_BIN." >&2
    exit 1
fi

colmap_executable="$(readlink -f -- "$colmap_executable")"
mkdir -p -- "$bundle_dir/bin" "$bundle_dir/lib"
install -m 0755 -- "$colmap_executable" "$bundle_dir/bin/colmap"

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
    ldd "$colmap_executable" |
        awk '/=> \// { print $3 } /^\// { print $1 }' |
        sort -u
)

if ldd "$colmap_executable" | grep -q "not found"; then
    echo "COLMAP has unresolved shared-library dependencies:" >&2
    ldd "$colmap_executable" | grep "not found" >&2
    exit 1
fi

LD_LIBRARY_PATH="$bundle_dir/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
    "$bundle_dir/bin/colmap" -h >/dev/null

echo "COLMAP Linux bundle created: $bundle_dir"
echo "Executable: $bundle_dir/bin/colmap"
echo "Libraries: $bundle_dir/lib"
