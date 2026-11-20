#!/bin/bash
# =====================================================================================================================
# bootstrap_host_macos.sh - stage 0 of the macOS setup: provide the app's OWN Python, inside the app's folder.
#
# The macOS mirror of bootstrap_host.ps1 (v0.8.x P1A; owner decisions D1/D2). Called by
# Setup_and_Run-audiobook-creation-tool.command on a first run or an environment repair, never on an ordinary launch.
# Everything after this (the .venv, the packages, FFmpeg, the launch) belongs to scripts/shared/bootstrap.py; this
# file only provides a proven base Python, because bootstrap.py cannot run without one. It runs on the bash 3.2 that
# macOS ships, and on nothing else: no Homebrew, no Python from PATH, no administrator password, no developer tools.
#
#  1. If files/runtime-data/python/bin/python3.12 is there, check that it is a native Apple Silicon program, then RUN
#     it under a watchdog to prove it is 3.12 with ssl, venv, ensurepip and a Tk that really initialises. Use it.
#  2. Otherwise explain and ask. Nothing is downloaded without a Yes.
#  3. Download the pinned standalone CPython build (python-build-standalone, the build Windows uses too) with the
#     built-in curl into files/temp/bootstrap and check its exact size and SHA-256 (the authority: the archive is not
#     signed as a whole). A mismatch deletes the file; there is no other source.
#  4. List every archive member BEFORE extracting anything and refuse the archive if any member is not a regular
#     file, folder or link; has an absolute or ".." path; sits outside the one "python/" folder; is a link that points
#     outside it; or carries a set-user-ID or set-group-ID bit. Then extract with the built-in tar into a staging
#     folder, check the program, and move it into place with one rename. Prove it, then delete archive and staging.
#  5. Write the proven interpreter's path to --out-file (when given) and exit 0.
#
# Exit codes: 0 = a proven Python is in place; 2 = the person declined (nothing downloaded); 3 = it could not be done.
#
# Interruption: every intermediate file carries this process's id (".part-<pid>" downloads, ".act-stage-python-<pid>"
# staging, ".probe-<pid>" output) and the final folder appears only through the one rename, so the state is always
# absent, staging-only or complete. A trap on EXIT/HUP/INT/TERM stops the child it started (the probe, curl or tar)
# and removes only its own partial files; closing the Terminal window delivers SIGHUP to this script and to that child
# (the Terminal's foreground process group). The next run removes such leftovers of a process that is gone, and only
# inside files/temp/bootstrap and files/runtime-data. An interpreter that is complete but fails its proof is never
# deleted: it is set aside as python.unusable-<time> once the person agrees to replace it.
#
# Qualification switches (testing only; the launcher passes none of them):
#   --assume-yes | --assume-no      answer the download question without asking
#   --download-only                 download and verify the archive, do not unpack it
#   --archive-path FILE             verify and use FILE instead of downloading
#   --qualify-url URL               download from URL (http://127.0.0.1:<port>/... only) instead of GitHub
#   --qualify-size N --qualify-sha256 HEX   expect a fixture archive instead of the pinned one
#   --probe-timeout SECONDS         the watchdog bound for the proof (default 30)
# =====================================================================================================================
set -u
umask 022

SELF_DIR="$(cd "$(dirname "$0")" && pwd -P)" || exit 3
REPO="$(cd "$SELF_DIR/../.." && pwd -P)" || exit 3
DOWNLOADS="$REPO/files/temp/bootstrap"
RUNTIME="$REPO/files/runtime-data"
PYTHON_HOME="$RUNTIME/python"
PYTHON_BIN="$PYTHON_HOME/bin/python3.12"

PY_VERSION="3.12.15"
BUILD_TAG="20261009"
ARCHIVE_NAME="cpython-$PY_VERSION+$BUILD_TAG-aarch64-apple-darwin-install_only.tar.gz"
ARCHIVE_URL="https://github.com/astral-sh/python-build-standalone/releases/download/$BUILD_TAG/cpython-$PY_VERSION%2B$BUILD_TAG-aarch64-apple-darwin-install_only.tar.gz"
ARCHIVE_SIZE=25165569
ARCHIVE_SHA256="83dcb04777c798bd95f3687acf9ae84b09860272ee6bdfb05be8bcf9447f75b8"
TOP="python"
# Tk is proved by initialising it (a withdrawn, destroyed root: no window is shown); Tcl() alone never loads Tk
# (audit ACT67-AUD-006). The machine check refuses an interpreter running under translation.
PROBE='import sys, ssl, venv, ensurepip, tkinter, platform; r = tkinter.Tk(); r.withdraw(); r.destroy(); v = sys.version_info; assert platform.machine() == "arm64", platform.machine(); print("%d.%d" % (v[0], v[1]))'
PROBE_TIMEOUT=30
TAR_TIMEOUT=600
CURL_TIMEOUT=1200

OUT_FILE=""
ASSUME_YES=""
ASSUME_NO=""
DOWNLOAD_ONLY=""
ARCHIVE_PATH=""
QUALIFY_URL=""

CHILD=""          # the one child running now (probe, curl or tar), stopped by the trap
PART=""           # this run's partial download
STAGE=""          # this run's staging folder
PROBE_OUT=""      # this run's probe output
LISTING=""        # this run's archive listing
LAST_PROBLEM=""
RESULT_ARCHIVE=""

say() { printf '%s\n' "$*"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --out-file) OUT_FILE="${2:-}"; shift 2 ;;
        --assume-yes) ASSUME_YES=1; shift ;;
        --assume-no) ASSUME_NO=1; shift ;;
        --download-only) DOWNLOAD_ONLY=1; shift ;;
        --archive-path) ARCHIVE_PATH="${2:-}"; shift 2 ;;
        --qualify-url) QUALIFY_URL="${2:-}"; shift 2 ;;
        --qualify-size) ARCHIVE_SIZE="${2:-}"; shift 2 ;;
        --qualify-sha256) ARCHIVE_SHA256="${2:-}"; shift 2 ;;
        --probe-timeout) PROBE_TIMEOUT="${2:-}"; shift 2 ;;
        *) say "Unknown option: $1"; exit 3 ;;
    esac
done
case "$QUALIFY_URL" in
    ""|http://127.0.0.1:*) ;;
    *) say "--qualify-url accepts only http://127.0.0.1:<port>/ (testing)."; exit 3 ;;
esac
case "$PROBE_TIMEOUT$ARCHIVE_SIZE" in *[!0-9]*) say "Invalid number."; exit 3 ;; esac

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
#  Proof of an interpreter folder
# ---------------------------------------------------------------------------------------------------------------------
probe_python() {
    local home="$1"
    local py="$home/bin/python3.12"
    LAST_PROBLEM=""
    if [ -L "$home" ] || [ ! -d "$home" ]; then
        LAST_PROBLEM="its folder is missing or is a link"
        return 1
    fi
    if [ -L "$py" ] || [ ! -f "$py" ]; then
        LAST_PROBLEM="bin/python3.12 is missing"
        return 1
    fi
    # Read the program's header before running it: a non-native program is refused unexecuted. `file` is part of
    # macOS itself (lipo is a developer-tool shim that would ask to install the Command Line Tools).
    case "$(/usr/bin/file -b "$py" 2>/dev/null)" in
        *Mach-O*arm64*) ;;
        *) LAST_PROBLEM="bin/python3.12 is not an Apple Silicon program"; return 1 ;;
    esac
    mkdir -p "$DOWNLOADS" 2>/dev/null
    PROBE_OUT="$DOWNLOADS/.probe-$$"
    run_bounded "$PROBE_TIMEOUT" "$py" -I -c "$PROBE" >"$PROBE_OUT" 2>"$PROBE_OUT.err"
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
    if [ "$version" != "3.12" ]; then
        LAST_PROBLEM="it is Python $version, not 3.12"
        return 1
    fi
    return 0
}

# ---------------------------------------------------------------------------------------------------------------------
#  Leftovers of an earlier run that is gone
# ---------------------------------------------------------------------------------------------------------------------
pid_of() {
    local name="$1"
    local pid="${name##*-}"
    pid="${pid%%.*}"
    case "$pid" in
        ""|*[!0-9]*) return 1 ;;
    esac
    printf '%s' "$pid"
}

recover_stale() {
    local entry pid
    for entry in "$RUNTIME"/.act-stage-python-* "$DOWNLOADS"/*.part-* "$DOWNLOADS"/.probe-* "$DOWNLOADS"/.listing-*; do
        [ -e "$entry" ] || [ -L "$entry" ] || continue
        pid="$(pid_of "$entry")" || continue
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
    say "The Audiobook Creation Tool runs on its own copy of Python, kept inside this folder."
    say ""
    say "Download Python $PY_VERSION for it now?"
    say "  - about 25 MB, from GitHub (the standalone CPython build from python-build-standalone)"
    say "  - kept only inside this folder (files/runtime-data/python); nothing is installed on this Mac"
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
archive_problem() {
    local file="$1"
    local size digest
    size="$(/usr/bin/stat -f %z "$file" 2>/dev/null)" || { LAST_PROBLEM="it cannot be read"; return 0; }
    if [ "$size" != "$ARCHIVE_SIZE" ]; then
        LAST_PROBLEM="it is $size bytes, not $ARCHIVE_SIZE"
        return 0
    fi
    digest="$(sha256_of "$file")" || { LAST_PROBLEM="its SHA-256 cannot be computed"; return 0; }
    if [ "$digest" != "$ARCHIVE_SHA256" ]; then
        LAST_PROBLEM="its SHA-256 is $digest, not the pinned $ARCHIVE_SHA256"
        return 0
    fi
    return 1
}

get_archive() {
    RESULT_ARCHIVE=""
    if [ -n "$ARCHIVE_PATH" ]; then
        if archive_problem "$ARCHIVE_PATH"; then
            say "The Python archive at $ARCHIVE_PATH was rejected: $LAST_PROBLEM."
            return 1
        fi
        RESULT_ARCHIVE="$ARCHIVE_PATH"
        return 0
    fi
    mkdir -p "$DOWNLOADS" || return 1
    local target="$DOWNLOADS/$ARCHIVE_NAME"
    if [ -f "$target" ] && [ ! -L "$target" ]; then
        if ! archive_problem "$target"; then
            say "Reusing the Python archive downloaded earlier (it is still the verified file)."
            RESULT_ARCHIVE="$target"
            return 0
        fi
        rm -f "$target"
    fi
    PART="$target.part-$$"
    local url="$ARCHIVE_URL"
    local proto="=https"
    if [ -n "$QUALIFY_URL" ]; then
        url="$QUALIFY_URL"
        proto="=http"
    fi
    say "Downloading Python $PY_VERSION (about 25 MB)..."
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
    if archive_problem "$PART"; then
        rm -f "$PART"
        PART=""
        say "The downloaded Python archive was rejected and deleted: $LAST_PROBLEM."
        return 1
    fi
    mv -f "$PART" "$target" || return 1
    PART=""
    RESULT_ARCHIVE="$target"
    return 0
}

# ---------------------------------------------------------------------------------------------------------------------
#  Safe extraction
# ---------------------------------------------------------------------------------------------------------------------
# Lexically resolve link target $2 of member $1 and succeed only when it stays inside the top folder.
link_stays_inside() {
    local member="$1" target="$2"
    case "$target" in
        /*|"") return 1 ;;
    esac
    local dir="${member%/*}"
    [ "$dir" = "$member" ] && dir=""
    local joined="$dir/$target"
    local -a stack
    stack=()
    local count=0
    local part
    local saved_ifs="$IFS"
    IFS="/"
    set -f
    for part in $joined; do
        case "$part" in
            ""|".") ;;
            "..")
                if [ "$count" -eq 0 ]; then
                    IFS="$saved_ifs"; set +f
                    return 1
                fi
                count=$((count - 1))
                ;;
            *)
                stack[$count]="$part"
                count=$((count + 1))
                ;;
        esac
    done
    IFS="$saved_ifs"
    set +f
    [ "$count" -ge 1 ] && [ "${stack[0]}" = "$TOP" ]
}

check_members() {
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
            "$TOP"|"$TOP/"|"$TOP"/*) ;;
            *) LAST_PROBLEM="a member outside the $TOP/ folder: $name"; return 1 ;;
        esac
        case "/$name/" in
            */../*) LAST_PROBLEM="a parent-directory (..) path: $name"; return 1 ;;
        esac
    done <"$LISTING.names"
    local line mode count member target
    local -a words
    set -f
    while IFS= read -r line; do
        words=($line)
        count=${#words[@]}
        if [ "$count" -lt 2 ]; then
            set +f
            LAST_PROBLEM="an unreadable listing line"
            return 1
        fi
        mode="${words[0]}"
        if [ "$count" -ge 4 ] && [ "${words[$((count - 3))]}" = "link" ] && [ "${words[$((count - 2))]}" = "to" ]; then
            set +f
            LAST_PROBLEM="a hard link: ${words[$((count - 4))]}"
            return 1
        fi
        case "$mode" in
            -*|d*) member="${words[$((count - 1))]}"; target="" ;;
            l*)
                if [ "$count" -lt 4 ] || [ "${words[$((count - 2))]}" != "->" ]; then
                    set +f
                    LAST_PROBLEM="an unreadable link entry"
                    return 1
                fi
                member="${words[$((count - 3))]}"
                target="${words[$((count - 1))]}"
                ;;
            *)
                set +f
                LAST_PROBLEM="a member that is not a file, folder or link (type ${mode:0:1}): ${words[$((count - 1))]}"
                return 1
                ;;
        esac
        case "${mode:3:1}${mode:6:1}" in
            *[sS]*)
                set +f
                LAST_PROBLEM="a set-user-ID or set-group-ID member: $member"
                return 1
                ;;
        esac
        if [ -n "$target" ] && ! link_stays_inside "$member" "$target"; then
            set +f
            LAST_PROBLEM="a link that points outside the $TOP/ folder: $member -> $target"
            return 1
        fi
    done <"$LISTING"
    set +f
    rm -f "$LISTING" "$LISTING.names"
    LISTING=""
    return 0
}

install_local() {
    local archive="$1"
    say "Checking the archive's contents..."
    if ! check_members "$archive"; then
        say "The Python archive was refused and nothing was unpacked: $LAST_PROBLEM."
        return 1
    fi
    mkdir -p "$RUNTIME" || return 1
    STAGE="$RUNTIME/.act-stage-python-$$"
    rm -rf "$STAGE"
    mkdir "$STAGE" || return 1
    say "Unpacking Python $PY_VERSION into this folder..."
    # bsdtar refuses absolute and ".." paths unless -P is given (never given here); the listing above is the authority.
    if ! run_bounded "$TAR_TIMEOUT" /usr/bin/tar -xzf "$archive" --no-same-owner -C "$STAGE"; then
        say "The archive could not be unpacked."
        return 1
    fi
    local unpacked="$STAGE/$TOP"
    case "$(/usr/bin/file -b "$unpacked/bin/python3.12" 2>/dev/null)" in
        *Mach-O*arm64*) ;;
        *) say "The archive did not contain an Apple Silicon python/bin/python3.12."; return 1 ;;
    esac
    if [ -e "$PYTHON_HOME" ] || [ -L "$PYTHON_HOME" ]; then
        # A copy that failed its proof (or a copy from another computer): set aside under its own name, never deleted.
        local aside="$RUNTIME/python.unusable-$(date +%Y%m%d-%H%M%S)-$$"
        mv "$PYTHON_HOME" "$aside" || { say "The previous files/runtime-data/python could not be moved aside."; return 1; }
        say "The previous copy that did not work was kept at ${aside#$REPO/} (it can be deleted)."
    fi
    mv "$unpacked" "$PYTHON_HOME" || { say "The new Python could not be moved into place."; return 1; }
    rm -rf "$STAGE"
    STAGE=""
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

if [ -e "$PYTHON_HOME" ] || [ -L "$PYTHON_HOME" ]; then
    if probe_python "$PYTHON_HOME"; then
        write_result || exit 3
        exit 0
    fi
    say "The app's own Python in files/runtime-data/python does not work: $LAST_PROBLEM."
    say "It will be replaced, and kept aside rather than deleted."
else
    say "The app's own Python has not been downloaded yet."
fi

if ! ask_consent; then
    say "Python was not downloaded. Run the setup again whenever you are ready."
    exit 2
fi

get_archive || exit 3
if [ -n "$DOWNLOAD_ONLY" ]; then
    say "Verified archive: $RESULT_ARCHIVE (not unpacked: --download-only)."
    exit 0
fi

install_local "$RESULT_ARCHIVE" || exit 3
if ! probe_python "$PYTHON_HOME"; then
    say "The app's own Python was unpacked but could not be started: $LAST_PROBLEM. Nothing outside this folder was changed."
    exit 3
fi
if [ -z "$ARCHIVE_PATH" ]; then
    rm -f "$RESULT_ARCHIVE"
fi
write_result || exit 3
exit 0
