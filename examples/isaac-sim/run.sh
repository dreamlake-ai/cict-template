#!/bin/bash
# Install Isaac Sim into node-local scratch and run a headless scene.
#   examples/isaac-sim/run.sh OUTPUT_DIR
# Exit codes: 0 checks passed, 1 checks failed, 2 environment/install error.
# OUTPUT_DIR gets summary.json (and metrics.json, frame.png) for every outcome;
# the workflow then saves it as the run's evidence (ci/evidence.py).
#
# Environment: ISAACSIM_VERSION (default 5.1.0), SIM_SECONDS (600), RENDER (true).
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
out="${1:?usage: run.sh OUTPUT_DIR}"
ISAACSIM_VERSION="${ISAACSIM_VERSION:-5.1.0}"
scratch="${RUNNER_TEMP:-/tmp}/isaac"
mkdir -p "$out" "$scratch"
need_gb=40

fail_env() {  # reason -> evidence + exit 2
  python3 - "$out" "$1" <<'PY'
import json, os, sys
out, reason = sys.argv[1], sys.argv[2]
r = {"passed": False, "error": reason, "checks": [{"name": "environment", "passed": False, "observed": reason, "expected": "ok"}]}
json.dump(r, open(os.path.join(out, "summary.json"), "w"), indent=2)
print(json.dumps(r, indent=1))
PY
  exit 2
}

echo "== machine"
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader || fail_env "nvidia-smi failed"
nproc; free -g | head -2
df -h "$scratch" "${DREAMLAKE_CACHE_DIR:-/tmp}" 2>/dev/null || true

# Isaac Sim needs ~25-35 GB unpacked: install it on the node's own disk, never on
# a shared volume (it would fill it, and is slow to read from many nodes).
free_gb=$(df -BG --output=avail "$scratch" | tail -1 | tr -dc 0-9)
[ "${free_gb:-0}" -ge "$need_gb" ] || fail_env "node-local scratch $scratch has ${free_gb}G free, need ${need_gb}G"

command -v uv >/dev/null || { curl -LsSf https://astral.sh/uv/0.9.5/install.sh | sh; export PATH="$HOME/.local/bin:$PATH"; }
# Caches that survive between runs on the same node (node-local, never a shared volume):
# RTX shaders compile on the first frame and take minutes cold; pip wheels are ~15 GB.
keep="/var/tmp/isaac-cache-$(id -u)"
mkdir -p "$keep" && [ -w "$keep" ] || keep="$scratch/keep"
echo "== caches in $keep ($(du -sh "$keep" 2>/dev/null | cut -f1) kept)"
export UV_CACHE_DIR="$keep/uv" UV_PYTHON_INSTALL_DIR="$keep/python"
export XDG_CACHE_HOME="$keep/xdg" OMNI_KIT_ACCEPT_EULA=YES ACCEPT_EULA=Y PRIVACY_CONSENT=Y

echo "== install isaacsim ${ISAACSIM_VERSION} (node-local)"
t0=$(date +%s)
# Isaac Sim 4.x/5.x wheels are cp311; 6.x are cp312.
case "$ISAACSIM_VERSION" in 4.*|5.*) py=3.11 ;; *) py=3.12 ;; esac
uv venv -q --python "$py" "$scratch/venv" || fail_env "uv could not create a Python $py env"
VIRTUAL_ENV="$scratch/venv" uv pip install -q "isaacsim[all,extscache]==${ISAACSIM_VERSION}" \
  --extra-index-url https://pypi.nvidia.com --index-strategy unsafe-best-match || fail_env "pip install isaacsim==${ISAACSIM_VERSION} failed"
# The camera video for DreamLake's viewer is encoded with imageio's bundled ffmpeg.
VIRTUAL_ENV="$scratch/venv" uv pip install -q "imageio>=2.30" "imageio-ffmpeg>=0.5" || echo "imageio unavailable: no video"
echo "install took $(( $(date +%s) - t0 ))s"

# Isaac Sim's MDL/iray stack dlopens libGLU (Ubuntu: libglu1-mesa) and
# libOpenGL; without them RTX crashes right after "app ready". Jobs have no root,
# so when the node lacks them, unpack the Ubuntu packages into scratch instead.
syslibs="$scratch/syslibs"
missing=()
ldconfig -p | grep -q 'libGLU.so.1 ' || missing+=(libglu1-mesa)
ldconfig -p | grep -q 'libOpenGL.so.0 ' || missing+=(libopengl0)
if [ ${#missing[@]} -gt 0 ]; then
  echo "== user-space system libraries: ${missing[*]}"
  mkdir -p "$syslibs/debs" && cd "$syslibs/debs"
  apt-get download "${missing[@]}" >/dev/null 2>&1 || {
    . /etc/os-release
    for pkg in "${missing[@]}"; do
      url=$(curl -fsSL "https://packages.ubuntu.com/${VERSION_CODENAME}/amd64/${pkg}/download" | grep -oE 'http://(archive|us\.archive)\.ubuntu\.com/ubuntu/pool/[^"]+\.deb' | head -1)
      [ -n "$url" ] && curl -fsSLO "$url"
    done
  }
  for deb in ./*.deb; do [ -f "$deb" ] && dpkg-deb -x "$deb" "$syslibs/root"; done
  cd - >/dev/null
  libdir="$syslibs/root/usr/lib/x86_64-linux-gnu"
  [ -e "$libdir/libGLU.so.1" ] || [[ ! " ${missing[*]} " =~ " libglu1-mesa " ]] || fail_env "could not obtain libGLU.so.1 (libglu1-mesa)"
  export LD_LIBRARY_PATH="$libdir${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  ls "$libdir"
fi

echo "== run"
code=0
"$scratch/venv/bin/python" "$here/scene.py" --out "$out" \
  --sim-seconds "${SIM_SECONDS:-600}" --render "${RENDER:-true}" || code=$?
[ -f "$out/summary.json" ] || fail_env "Isaac Sim exited $code without writing summary.json"
exit "$code"
