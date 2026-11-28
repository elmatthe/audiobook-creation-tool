#!/bin/bash
# =====================================================================================================================
# bootstrap_host_macos.sh - stage 0 of the macOS setup: provide the app's OWN uv and Python, inside the app's folder.
#
# The macOS mirror of bootstrap_host.ps1. Called by Setup_and_Run-audiobook-creation-tool.command on a first run or an
# environment repair, never on an ordinary launch. Everything after this (the .venv, the packages, FFmpeg, the launch)
# belongs to scripts/shared/bootstrap.py. It runs on the bash 3.2 that macOS ships, and on nothing else: no Homebrew,
# no Python from PATH, no administrator password, no developer tools.
#
# v0.8.2 Phase 4 (owner decisions recorded in Phase 3B): the app's Python is CPython 3.12.15 from python-build-standalone
# 20261009, installed by the pinned uv 0.13.10 (Developer ID signed and notarized) from ACT's own verified copy of the
# archive, through ACT's own download metadata (scripts/shared/python-downloads.json), so uv can never pick another
# build. (The Python earlier versions kept in files/runtime-data/python is left exactly as it is.)
#
#  1. uv: files/runtime-data/uv/uv must be exactly the pinned program (its SHA-256).
#  2. Python: files/runtime-data/uv/python/cpython-3.12.15-macos-aarch64-none/bin/python3.12 must be a native Apple
#     Silicon program; it is RUN under a watchdog to prove it is the pinned build (sys.version, uv's BUILD stamp) with
#     ssl, venv, ensurepip and a Tk that really initialises. A moved or copied app folder (uv's minor-version link still
#     points at the old place, and uv's two install-time patches name the old prefix) is refreshed by reinstalling it.
#  3. Anything missing: explain and ask ONCE. Nothing is downloaded without a Yes. Downloads use the built-in curl into
#     files/temp/bootstrap and are checked against their exact size and SHA-256. The uv archive's members are all listed
#     BEFORE anything is extracted (only regular files and folders inside its one top folder; no absolute, "..", link or
#     set-ID member), then the built-in tar extracts it into staging and uv's own SHA-256 is checked. The Python archive
#     is kept in files/runtime-data/uv/mirror, and uv installs it from there (a file:// mirror: no network), with a
#     contained environment and a scratch folder of its own, removed afterwards. The interpreter is proved again.
#  4. Write the proven interpreter's path to --out-file (when given) and exit 0.
#
# Exit codes: 0 = a proven Python is in place; 2 = the person declined (nothing downloaded); 3 = it could not be done.
#
# Interruption: every intermediate file carries this process's id (".part-<pid>" downloads, ".act-stage-uv-<pid>"
# staging, ".probe-<pid>" output, the uv scratch "t/m<pid>") and the final files appear only through one rename (uv
# installs its own folder atomically), so the state is always absent, staging-only or complete. A trap on
# EXIT/HUP/INT/TERM stops the child it started (the probe, curl, tar or uv) and removes only its own partial files;
# closing the Terminal window delivers SIGHUP to this script and to that child. The next run removes such leftovers of a
# process that is gone, and only inside files/temp/bootstrap and files/runtime-data/uv.
#
# Qualification switches (testing only; the launcher passes none of them):
#   --assume-yes | --assume-no      answer the download question without asking
#   --download-only                 download and verify, install nothing
#   --archive-path FILE             verify and use FILE as the Python archive instead of downloading
#   --uv-archive-path FILE          verify and use FILE as the uv archive instead of downloading
#   --qualify-url URL               download the Python archive from URL (http://127.0.0.1:<port>/... only)
#   --qualify-size N --qualify-sha256 HEX   expect a fixture Python archive instead of the pinned one
#   --qualify-uv-size N --qualify-uv-sha256 HEX --qualify-uv-exe-sha256 HEX   expect a fixture uv archive
#   --probe-timeout SECONDS         the watchdog bound for the proof (default 30)
# =====================================================================================================================
set -u
umask 022

SELF_DIR="$(cd "$(dirname "$0")" && pwd -P)" || exit 3
REPO="$(cd "$SELF_DIR/../.." && pwd -P)" || exit 3
DOWNLOADS="$REPO/files/temp/bootstrap"
RUNTIME="$REPO/files/runtime-data"
UV_HOME="$RUNTIME/uv"
UV_EXE="$UV_HOME/uv"
PY_INSTALL="$UV_HOME/python"
MIRROR="$UV_HOME/mirror"
DOWNLOADS_JSON="$REPO/scripts/shared/python-downloads.json"

# Pins (keep in step with scripts/shared/uv_runner.py; a test holds them together).
UV_VERSION="0.13.10"
UV_ARCHIVE_NAME="uv-aarch64-apple-darwin.tar.gz"
UV_URL="https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$UV_ARCHIVE_NAME"
UV_SIZE=14700626
UV_SHA256="e419bf07533bdbf48795fc793601c834dd79db57a8c49ce8e25cfe3a8639958d"
UV_EXE_SHA256="4ff271e49765b1d8ed72cfbf720401941efccac6b2997ce87bb05ee790312ab3"
UV_TOP="uv-aarch64-apple-darwin"
PY_VERSION="3.12.15"
BUILD_TAG="20261009"
PY_KEY="cpython-3.12.15-macos-aarch64-none"
PY_MINOR_KEY="cpython-3.12-macos-aarch64-none"
ARCHIVE_NAME="cpython-$PY_VERSION+$BUILD_TAG-aarch64-apple-darwin-install_only.tar.gz"
ARCHIVE_URL="https://github.com/astral-sh/python-build-standalone/releases/download/$BUILD_TAG/cpython-$PY_VERSION%2B$BUILD_TAG-aarch64-apple-darwin-install_only.tar.gz"
ARCHIVE_SIZE=25165569
ARCHIVE_SHA256="83dcb04777c798bd95f3687acf9ae84b09860272ee6bdfb05be8bcf9447f75b8"
PY_SYS_VERSION="3.12.15 (main, Oct  9 2026, 15:10:57) [Clang 22.1.3 ]"

PY_HOME="$PY_INSTALL/$PY_KEY"
PYTHON_BIN="$PY_HOME/bin/python3.12"
MIRROR_ARCHIVE="$MIRROR/$BUILD_TAG/$ARCHIVE_NAME"
# Tk is proved by initialising it (a withdrawn, destroyed root: no window is shown); Tcl() alone never loads Tk
# (audit ACT67-AUD-006). The machine check refuses an interpreter running under translation. The last line is
# sys.version, compared with the pinned build's.
PROBE='import sys, ssl, venv, ensurepip, tkinter, platform; r = tkinter.Tk(); r.withdraw(); r.destroy(); assert platform.machine() == "arm64", platform.machine(); print(sys.version)'
PROBE_TIMEOUT=30
TAR_TIMEOUT=600
CURL_TIMEOUT=1200
UV_TIMEOUT=600

OUT_FILE=""
ASSUME_YES=""
ASSUME_NO=""
DOWNLOAD_ONLY=""
ARCHIVE_PATH=""
UV_ARCHIVE_PATH=""
QUALIFY_URL=""

CHILD=""          # the one child running now (probe, curl, tar or uv), stopped by the trap
PART=""           # this run's partial download
STAGE=""          # this run's uv staging folder
PROBE_OUT=""      # this run's probe output
LISTING=""        # this run's archive listing
SCRATCH=""        # this run's uv scratch folder
LAST_PROBLEM=""
RESULT_FILE=""

say() { printf '%s\n' "$*"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --out-file) OUT_FILE="${2:-}"; shift 2 ;;
        --assume-yes) ASSUME_YES=1; shift ;;
        --assume-no) ASSUME_NO=1; shift ;;
        --download-only) DOWNLOAD_ONLY=1; shift ;;
        --archive-path) ARCHIVE_PATH="${2:-}"; shift 2 ;;
        --uv-archive-path) UV_ARCHIVE_PATH="${2:-}"; shift 2 ;;
        --qualify-url) QUALIFY_URL="${2:-}"; shift 2 ;;
        --qualify-size) ARCHIVE_SIZE="${2:-}"; shift 2 ;;
        --qualify-sha256) ARCHIVE_SHA256="${2:-}"; shift 2 ;;
        --qualify-uv-size) UV_SIZE="${2:-}"; shift 2 ;;
        --qualify-uv-sha256) UV_SHA256="${2:-}"; shift 2 ;;
        --qualify-uv-exe-sha256) UV_EXE_SHA256="${2:-}"; shift 2 ;;
        --probe-timeout) PROBE_TIMEOUT="${2:-}"; shift 2 ;;
        *) say "Unknown option: $1"; exit 3 ;;
    esac
done
case "$QUALIFY_URL" in
    ""|http://127.0.0.1:*) ;;
    *) say "--qualify-url accepts only http://127.0.0.1:<port>/ (testing)."; exit 3 ;;
esac
case "$PROBE_TIMEOUT$ARCHIVE_SIZE$UV_SIZE" in *[!0-9]*) say "Invalid number."; exit 3 ;; esac

# ---------------------------------------------------------------------------------------------------------------------
#  Cleanup: only what this run made, and the child it started
# ---------------------------------------------------------------------------------------------------------------------
stop_child() {
    if [ -n "$CHILD" ]; then
        kill -TERM "$CHILD" 2>/dev/null
        local tenths=0
        while kill -0 "$CHILD" 2>/dev/null && [ "$tenths" -lt 20 ]; do
            sleep 0.1
            tenths=$((tenths + 1))
        done
        kill -KILL "$CHILD" 2>/dev/null
        wait "$CHILD" 2>/dev/null
        CHILD=""
    fi
}

cleanup() {
    stop_child
    [ -n "$PART" ] && rm -f "$PART"
    [ -n "$PROBE_OUT" ] && rm -f "$PROBE_OUT" "$PROBE_OUT.err"
    [ -n "$LISTING" ] && rm -f "$LISTING" "$LISTING.names"
    if [ -n "$STAGE" ] && [ -d "$STAGE" ] && [ ! -L "$STAGE" ]; then
        rm -rf "$STAGE"
    fi
    if [ -n "$SCRATCH" ] && [ -d "$SCRATCH" ] && [ ! -L "$SCRATCH" ]; then
        rm -rf "$SCRATCH"
    fi
}

on_signal() {
    trap - EXIT HUP INT TERM
    cleanup
    say "Setting up Python was interrupted; nothing unfinished was kept."
    exit 3
}

trap cleanup EXIT
trap on_signal HUP INT TERM

# ---------------------------------------------------------------------------------------------------------------------
#  The watchdog: macOS has no `timeout`. Runs "$@" in the background, polls it, and past LIMIT seconds sends SIGTERM,
#  waits 2 s, sends SIGKILL and always reaps it. Returns the command's status, or 124 when the watchdog ended it.
# ---------------------------------------------------------------------------------------------------------------------
run_bounded() {
    local limit="$1"
    shift
    "$@" &
    CHILD=$!
    local tenths=0
    local max=$((limit * 10))
    while kill -0 "$CHILD" 2>/dev/null; do
        if [ "$tenths" -ge "$max" ]; then
            stop_child
            return 124
        fi
        sleep 0.1
        tenths=$((tenths + 1))
    done
    wait "$CHILD"
    local status=$?
    CHILD=""
    return "$status"
}

sha256_of() {
    local out
    if [ -x /usr/bin/shasum ]; then
        out="$(/usr/bin/shasum -a 256 "$1" 2>/dev/null)" || return 1
    elif [ -x /sbin/sha256 ]; then
        out="$(/sbin/sha256 -q "$1" 2>/dev/null)" || return 1
    else
        return 1
    fi
    printf '%s' "${out%% *}"
}

# ---------------------------------------------------------------------------------------------------------------------
#  Proofs
# ---------------------------------------------------------------------------------------------------------------------
uv_is_pinned() {
    [ -f "$UV_EXE" ] && [ ! -L "$UV_EXE" ] || return 1
    [ "$(sha256_of "$UV_EXE")" = "$UV_EXE_SHA256" ]
}

probe_python() {
    LAST_PROBLEM=""
    if [ -L "$PY_HOME" ] || [ ! -d "$PY_HOME" ]; then
        LAST_PROBLEM="its folder is missing or is a link"
        return 1
    fi
    if [ -L "$PYTHON_BIN" ] || [ ! -f "$PYTHON_BIN" ]; then
        LAST_PROBLEM="bin/python3.12 is missing"
        return 1
    fi
    if [ "$(tr -d '\r\n' <"$PY_HOME/BUILD" 2>/dev/null)" != "$BUILD_TAG" ]; then
        LAST_PROBLEM="it is not the pinned build $BUILD_TAG"
        return 1
    fi
    # Read the program's header before running it: a non-native program is refused unexecuted. `file` is part of
    # macOS itself (lipo is a developer-tool shim that would ask to install the Command Line Tools).
    case "$(/usr/bin/file -b "$PYTHON_BIN" 2>/dev/null)" in
        *Mach-O*arm64*) ;;
        *) LAST_PROBLEM="bin/python3.12 is not an Apple Silicon program"; return 1 ;;
    esac
    mkdir -p "$DOWNLOADS" 2>/dev/null
    PROBE_OUT="$DOWNLOADS/.probe-$$"
    run_bounded "$PROBE_TIMEOUT" "$PYTHON_BIN" -I -c "$PROBE" >"$PROBE_OUT" 2>"$PROBE_OUT.err"
    local status=$?
    local version=""
    [ -f "$PROBE_OUT" ] && version="$(tr -d '\r\n' <"$PROBE_OUT")"
    rm -f "$PROBE_OUT" "$PROBE_OUT.err"
    PROBE_OUT=""
    if [ "$status" -eq 124 ]; then
        LAST_PROBLEM="its check did not finish within $PROBE_TIMEOUT seconds and was stopped (Tk may be unable to reach the screen, for example in a remote session)"
        return 1
    fi
    if [ "$status" -ne 0 ]; then
        LAST_PROBLEM="it did not pass its check (exit $status: ssl, venv, ensurepip or Tk is not working)"
        return 1
    fi
    if [ "$version" != "$PY_SYS_VERSION" ]; then
        LAST_PROBLEM="it is Python $version, not the pinned $PY_SYS_VERSION"
        return 1
    fi
    return 0
}

minor_link_stale() {
    # uv's absolute "cpython-3.12-..." link beside the versioned folder still pointing at another folder means this
    # copy was moved or copied; uv's two install-time patches (the dylib's install name, _sysconfigdata) then also name
    # the old place (Phase 3B), so the interpreter is installed again from the kept archive.
    local link="$PY_INSTALL/$PY_MINOR_KEY"
    [ -L "$link" ] || return 1
    [ "$(readlink "$link")" != "$PY_HOME" ]
}

# ---------------------------------------------------------------------------------------------------------------------
#  Leftovers of an earlier run that is gone
# ---------------------------------------------------------------------------------------------------------------------
pid_of() {
    local name="$1"
    local pid="${name##*-}"
    pid="${pid%%.*}"
    pid="${pid#m}"
    case "$pid" in
        ""|*[!0-9]*) return 1 ;;
    esac
    printf '%s' "$pid"
}

recover_stale() {
    local entry pid
    for entry in "$UV_HOME"/.act-stage-uv-* "$UV_HOME"/t/m* "$DOWNLOADS"/*.part-* "$DOWNLOADS"/.probe-* \
                 "$DOWNLOADS"/.listing-*; do
        [ -e "$entry" ] || [ -L "$entry" ] || continue
        case "$entry" in
            "$UV_HOME"/t/m*) pid="$(pid_of "${entry##*/t/}")" || continue ;;
            *) pid="$(pid_of "$entry")" || continue ;;
        esac
        [ "$pid" = "$$" ] && continue
        kill -0 "$pid" 2>/dev/null && continue
        if [ -L "$entry" ] || [ ! -d "$entry" ]; then
            rm -f "$entry"
        else
            rm -rf "$entry"
        fi
        say "Removed what an interrupted earlier setup left behind: ${entry#$REPO/}"
    done
}

# ---------------------------------------------------------------------------------------------------------------------
#  Consent
# ---------------------------------------------------------------------------------------------------------------------
ask_consent() {
    [ -n "$ASSUME_YES" ] && return 0
    [ -n "$ASSUME_NO" ] && return 1
    say ""
    say "The Audiobook Creation Tool runs on its own copy of Python and its own package tool, kept inside this folder."
    say ""
    say "Download them now?"
    [ -n "$NEED_UV" ] && say "  - uv $UV_VERSION, the package tool from Astral (about 15 MB, from GitHub)"
    [ -n "$NEED_ARCHIVE" ] && say "  - Python $PY_VERSION, the standalone CPython build from python-build-standalone (about 25 MB, from GitHub)"
    say "  - kept only inside this folder (files/runtime-data/uv); nothing is installed on this Mac"
    say "  - no administrator password; nothing outside this folder is changed"
    say ""
    if [ ! -t 0 ]; then
        say "No answer can be typed here, so nothing was downloaded."
        return 1
    fi
    printf '%s' "Type y and press Return to download, or just press Return to stop: "
    local reply=""
    read -r reply || return 1
    case "$reply" in
        [Yy]*) return 0 ;;
    esac
    return 1
}

# ---------------------------------------------------------------------------------------------------------------------
#  Download and verify
# ---------------------------------------------------------------------------------------------------------------------
file_problem() {
    # $1 file, $2 size, $3 sha256. Succeeds (0) when there IS a problem, described in LAST_PROBLEM.
    local file="$1" want_size="$2" want_sha="$3"
    local size digest
    size="$(/usr/bin/stat -f %z "$file" 2>/dev/null)" || { LAST_PROBLEM="it cannot be read"; return 0; }
    if [ "$size" != "$want_size" ]; then
        LAST_PROBLEM="it is $size bytes, not $want_size"
        return 0
    fi
    digest="$(sha256_of "$file")" || { LAST_PROBLEM="its SHA-256 cannot be computed"; return 0; }
    if [ "$digest" != "$want_sha" ]; then
        LAST_PROBLEM="its SHA-256 is $digest, not the pinned $want_sha"
        return 0
    fi
    return 1
}

get_verified() {
    # $1 given path, $2 url, $3 name, $4 size, $5 sha256, $6 what. RESULT_FILE = a verified local file.
    local given="$1" url="$2" name="$3" size="$4" sha="$5" what="$6"
    RESULT_FILE=""
    if [ -n "$given" ]; then
        if file_problem "$given" "$size" "$sha"; then
            say "The $what at $given was rejected: $LAST_PROBLEM."
            return 1
        fi
        RESULT_FILE="$given"
        return 0
    fi
    mkdir -p "$DOWNLOADS" || return 1
    local target="$DOWNLOADS/$name"
    if [ -f "$target" ] && [ ! -L "$target" ]; then
        if ! file_problem "$target" "$size" "$sha"; then
            say "Reusing the $what downloaded earlier (it is still the verified file)."
            RESULT_FILE="$target"
            return 0
        fi
        rm -f "$target"
    fi
    PART="$target.part-$$"
    local proto="=https"
    case "$url" in http://127.0.0.1:*) proto="=http" ;; esac
    say "Downloading the $what..."
    run_bounded "$CURL_TIMEOUT" /usr/bin/curl --fail --location --proto "$proto" --proto-redir "$proto" \
        --connect-timeout 30 --speed-limit 1024 --speed-time 60 --max-time "$CURL_TIMEOUT" \
        --silent --show-error --output "$PART" "$url"
    local status=$?
    if [ "$status" -ne 0 ]; then
        rm -f "$PART"
        PART=""
        say "The download did not finish (curl status $status). Check the internet connection and run setup again."
        return 1
    fi
    if file_problem "$PART" "$size" "$sha"; then
        rm -f "$PART"
        PART=""
        say "The downloaded $what was rejected and deleted: $LAST_PROBLEM."
        return 1
    fi
    mv -f "$PART" "$target" || return 1
    PART=""
    RESULT_FILE="$target"
    return 0
}

# ---------------------------------------------------------------------------------------------------------------------
#  Safe extraction of the uv archive
# ---------------------------------------------------------------------------------------------------------------------
check_members() {
    # Every member must be a regular file or folder inside $UV_TOP: no absolute, "..", link, device or set-ID member.
    local archive="$1"
    mkdir -p "$DOWNLOADS" || { LAST_PROBLEM="files/temp/bootstrap cannot be created"; return 1; }
    LISTING="$DOWNLOADS/.listing-$$"
    if ! /usr/bin/tar -tvzf "$archive" >"$LISTING" 2>/dev/null || ! /usr/bin/tar -tzf "$archive" >"$LISTING.names" 2>/dev/null; then
        LAST_PROBLEM="it cannot be read as a tar.gz archive"
        return 1
    fi
    local name
    while IFS= read -r name; do
        case "$name" in
            *[[:space:]]*|*\\*) LAST_PROBLEM="a member name contains a space or backslash: $name"; return 1 ;;
            /*) LAST_PROBLEM="an absolute path: $name"; return 1 ;;
            "$UV_TOP"|"$UV_TOP/"|"$UV_TOP"/*) ;;
            *) LAST_PROBLEM="a member outside the $UV_TOP/ folder: $name"; return 1 ;;
        esac
        case "/$name/" in
            */../*) LAST_PROBLEM="a parent-directory (..) path: $name"; return 1 ;;
        esac
    done <"$LISTING.names"
    local line mode
    while IFS= read -r line; do
        mode="${line%% *}"
        # A hard link first, whatever type letter the listing gives it (names with spaces were refused above).
        case "$line" in
            *" link to "*) LAST_PROBLEM="a hard link"; return 1 ;;
        esac
        case "$mode" in
            -*|d*) ;;
            *) LAST_PROBLEM="a member that is not a file or folder (type ${mode:0:1})"; return 1 ;;
        esac
        case "${mode:3:1}${mode:6:1}" in
            *[sS]*) LAST_PROBLEM="a set-user-ID or set-group-ID member"; return 1 ;;
        esac
    done <"$LISTING"
    rm -f "$LISTING" "$LISTING.names"
    LISTING=""
    return 0
}

install_uv() {
    local archive="$1"
    say "Checking the uv archive's contents..."
    if ! check_members "$archive"; then
        say "The uv archive was refused and nothing was unpacked: $LAST_PROBLEM."
        return 1
    fi
    mkdir -p "$UV_HOME" || return 1
    STAGE="$UV_HOME/.act-stage-uv-$$"
    rm -rf "$STAGE"
    mkdir "$STAGE" || return 1
    say "Unpacking uv $UV_VERSION into this folder..."
    # bsdtar refuses absolute and ".." paths unless -P is given (never given here); the listing above is the authority.
    if ! run_bounded "$TAR_TIMEOUT" /usr/bin/tar -xzf "$archive" --no-same-owner -C "$STAGE"; then
        say "The uv archive could not be unpacked."
        return 1
    fi
    local unpacked="$STAGE/$UV_TOP/uv"
    if [ -L "$unpacked" ] || [ ! -f "$unpacked" ] || [ "$(sha256_of "$unpacked")" != "$UV_EXE_SHA256" ]; then
        say "The unpacked uv is not the pinned program; it was not used."
        return 1
    fi
    chmod 755 "$unpacked" || return 1
    mv -f "$unpacked" "$UV_EXE" || { say "uv could not be moved into place."; return 1; }
    rm -rf "$STAGE"
    STAGE=""
    return 0
}

keep_archive() {
    # ACT's own offline copy of the interpreter archive, laid out as uv's --mirror reads it: <mirror>/<build>/<name>.
    local archive="$1"
    mkdir -p "$MIRROR/$BUILD_TAG" || return 1
    if [ -n "$ARCHIVE_PATH" ]; then
        cp -f "$archive" "$MIRROR_ARCHIVE" || return 1
    else
        mv -f "$archive" "$MIRROR_ARCHIVE" || return 1
    fi
    if file_problem "$MIRROR_ARCHIVE" "$ARCHIVE_SIZE" "$ARCHIVE_SHA256"; then
        say "The kept Python archive is not the verified file: $LAST_PROBLEM."
        return 1
    fi
    return 0
}

install_python() {
    # uv installs exactly the pinned build from the kept archive (a file:// mirror: no network), with every setting uv
    # could read from this Mac removed and a scratch folder of its own (shared/uv_runner.py does the same).
    local reinstall="$1"
    SCRATCH="$UV_HOME/t/m$$"
    rm -rf "$SCRATCH"
    mkdir -p "$SCRATCH/tmp" "$SCRATCH/pyc" || return 1
    local mirror_uri="file://$(printf '%s' "$MIRROR" | /usr/bin/sed 's/ /%20/g')"
    local -a extra
    extra=()
    [ -n "$reinstall" ] && extra=(--reinstall)
    say "Installing Python $PY_VERSION into this folder (from the verified copy kept here; nothing is downloaded)..."
    (
        for name in $(compgen -e); do
            case "$name" in
                UV_*|PIP_*|XDG_*|CONDA_*|PYTHON*|SSL_CERT_*|VIRTUAL_ENV|VIRTUAL_ENV_PROMPT|__PYVENV_LAUNCHER__) unset "$name" ;;
            esac
        done
        export UV_NO_CONFIG=1 UV_NO_ENV_FILE=1 UV_CACHE_DIR="$RUNTIME/uvc" UV_PYTHON_INSTALL_DIR="$PY_INSTALL" \
               UV_PYTHON_CACHE_DIR="$SCRATCH/pyc" UV_PYTHON_BIN_DIR="$UV_HOME/home/pybin" UV_PYTHON_INSTALL_BIN=0 \
               UV_PYTHON_INSTALL_REGISTRY=0 UV_PYTHON_NO_REGISTRY=1 UV_PYTHON_PREFERENCE=only-managed \
               UV_PYTHON_DOWNLOADS=manual UV_PYTHON_DOWNLOADS_JSON_URL="$DOWNLOADS_JSON" \
               UV_TOOL_DIR="$UV_HOME/home/tools" UV_TOOL_BIN_DIR="$UV_HOME/home/tool-bin" \
               UV_CREDENTIALS_DIR="$UV_HOME/home/credentials" UV_NO_PROGRESS=1 NO_COLOR=1 TMPDIR="$SCRATCH/tmp/"
        exec "$UV_EXE" python install "$PY_VERSION" --mirror "$mirror_uri" \
            --python-downloads-json-url "$DOWNLOADS_JSON" --no-bin --no-registry --no-config --color never \
            --no-progress ${extra[@]+"${extra[@]}"}
    ) &
    CHILD=$!
    local tenths=0
    local max=$((UV_TIMEOUT * 10))
    while kill -0 "$CHILD" 2>/dev/null; do
        if [ "$tenths" -ge "$max" ]; then
            stop_child
            rm -rf "$SCRATCH"
            SCRATCH=""
            say "uv did not finish installing Python within $UV_TIMEOUT seconds and was stopped."
            return 1
        fi
        sleep 0.1
        tenths=$((tenths + 1))
    done
    wait "$CHILD"
    local status=$?
    CHILD=""
    rm -rf "$SCRATCH"
    SCRATCH=""
    if [ "$status" -ne 0 ]; then
        say "uv could not install the app's Python (exit $status)."
        return 1
    fi
    return 0
}

write_result() {
    if [ -n "$OUT_FILE" ]; then
        mkdir -p "$(dirname "$OUT_FILE")" 2>/dev/null
        printf '%s' "$PYTHON_BIN" >"$OUT_FILE" || return 1
    fi
    say "Using Python: $PYTHON_BIN"
    return 0
}

# ---------------------------------------------------------------------------------------------------------------------
#  Main
# ---------------------------------------------------------------------------------------------------------------------
recover_stale

NEED_UV=""
uv_is_pinned || NEED_UV=1
PY_OK=""
STALE=""
if probe_python; then
    PY_OK=1
    minor_link_stale && STALE=1
fi
if [ -z "$NEED_UV" ] && [ -n "$PY_OK" ] && [ -z "$STALE" ]; then
    write_result || exit 3
    exit 0
fi

if [ -n "$NEED_UV" ]; then
    if [ -e "$UV_EXE" ]; then say "The app's uv in files/runtime-data/uv is not the pinned program; it will be replaced."
    else say "The app's package tool (uv $UV_VERSION) has not been downloaded yet."; fi
fi
if [ -z "$PY_OK" ]; then
    if [ -e "$PY_HOME" ]; then say "The app's own Python in files/runtime-data/uv/python does not work: $LAST_PROBLEM."
    else say "The app's own Python has not been installed yet."; fi
elif [ -n "$STALE" ]; then
    say "This copy of the app was moved or copied; its Python is refreshed for the new folder."
fi

NEED_ARCHIVE=""
if [ -z "$PY_OK" ] || [ -n "$STALE" ]; then
    if [ ! -f "$MIRROR_ARCHIVE" ] || file_problem "$MIRROR_ARCHIVE" "$ARCHIVE_SIZE" "$ARCHIVE_SHA256"; then
        NEED_ARCHIVE=1
    fi
fi
ASK=""
[ -n "$NEED_UV" ] && [ -z "$UV_ARCHIVE_PATH" ] && ASK=1
[ -n "$NEED_ARCHIVE" ] && [ -z "$ARCHIVE_PATH" ] && ASK=1
if [ -n "$ASK" ] && ! ask_consent; then
    say "Nothing was downloaded. Run the setup again whenever you are ready."
    exit 2
fi

if [ -n "$NEED_UV" ]; then
    get_verified "$UV_ARCHIVE_PATH" "$UV_URL" "$UV_ARCHIVE_NAME" "$UV_SIZE" "$UV_SHA256" "uv package tool" || exit 3
    UV_ARCHIVE="$RESULT_FILE"
    if [ -z "$DOWNLOAD_ONLY" ]; then
        install_uv "$UV_ARCHIVE" || exit 3
        [ -z "$UV_ARCHIVE_PATH" ] && rm -f "$UV_ARCHIVE"
    fi
fi
if [ -n "$NEED_ARCHIVE" ]; then
    PY_URL="$ARCHIVE_URL"
    [ -n "$QUALIFY_URL" ] && PY_URL="$QUALIFY_URL"
    get_verified "$ARCHIVE_PATH" "$PY_URL" "$ARCHIVE_NAME" "$ARCHIVE_SIZE" "$ARCHIVE_SHA256" "Python archive" || exit 3
    if [ -z "$DOWNLOAD_ONLY" ]; then
        keep_archive "$RESULT_FILE" || exit 3
    fi
fi
if [ -n "$DOWNLOAD_ONLY" ]; then
    say "Verified the downloads (not installed: --download-only)."
    exit 0
fi
if [ -z "$PY_OK" ] || [ -n "$STALE" ]; then
    REINSTALL=""
    [ -e "$PY_HOME" ] && REINSTALL=1
    install_python "$REINSTALL" || exit 3
    if ! probe_python; then
        say "The app's own Python was installed but could not be started: $LAST_PROBLEM. Nothing outside this folder was changed."
        exit 3
    fi
fi
write_result || exit 3
exit 0
