#!/usr/bin/env bash
# Single entry point for the Eden Archive admin web UI (dashboard, worlds,
# assets, upload, EdenFind, ...). Run with no arguments for an interactive
# menu, or pass a command directly: ./eden.sh start
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

RUNTIME_DIR="admin/.runtime"
PID_FILE="$RUNTIME_DIR/eden.pid"
LOG_FILE="$RUNTIME_DIR/eden.log"
PORT="${PORT:-8765}"
URL="http://127.0.0.1:$PORT"

mkdir -p "$RUNTIME_DIR"

is_running() {
  [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE" 2>/dev/null)" 2>/dev/null
}

cmd_start() {
  if is_running; then
    echo "[eden] already running (pid $(cat "$PID_FILE")) — $URL"
    return 0
  fi
  if [ ! -f admin-filelist/worlds.db ]; then
    echo "[eden] admin-filelist/worlds.db not found — EdenFind won't come up until you run:"
    echo "[eden]   ./eden.sh rebuild"
    echo "[eden] continuing to start the admin app on its own..."
  fi
  echo "[eden] starting admin app on $URL (EdenFind, if built, comes up automatically as a page in it)"
  nohup env PORT="$PORT" bash admin/run.sh >>"$LOG_FILE" 2>&1 &
  local pid=$!
  echo "$pid" > "$PID_FILE"
  sleep 2
  if is_running; then
    echo "[eden] started (pid $pid). Logs: ./eden.sh logs"
  else
    echo "[eden] failed to start — check $LOG_FILE"
    rm -f "$PID_FILE"
    return 1
  fi
}

# Collects $1 and every descendant pid (recursively) into the global
# TREE_PIDS array. run.sh execs uvicorn --reload, which forks a reloader +
# worker, and the admin app itself spawns EdenFind as a further child — all
# need to go, but nothing outside this tree (e.g. the invoking shell) should
# be touched, which rules out a process-group kill.
collect_tree() {
  local pid="$1"
  TREE_PIDS+=("$pid")
  local child
  for child in $(pgrep -P "$pid" 2>/dev/null); do
    collect_tree "$child"
  done
}

cmd_stop() {
  if ! is_running; then
    echo "[eden] not running"
    rm -f "$PID_FILE"
    return 0
  fi
  local pid
  pid="$(cat "$PID_FILE")"
  echo "[eden] stopping (pid $pid and its child processes)"
  local TREE_PIDS=()
  collect_tree "$pid"
  kill -TERM "${TREE_PIDS[@]}" 2>/dev/null
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    is_running || break
    sleep 0.5
  done
  if is_running; then
    echo "[eden] still up, sending SIGKILL"
    kill -KILL "${TREE_PIDS[@]}" 2>/dev/null
  fi
  rm -f "$PID_FILE"
  echo "[eden] stopped"
}

cmd_restart() {
  cmd_stop
  cmd_start
}

cmd_status() {
  if is_running; then
    echo "[eden] running (pid $(cat "$PID_FILE")) — $URL"
    echo "[eden]   EdenFind page:      $URL/edenfind"
    echo "[eden]   EdenFind direct:    http://127.0.0.1:${EDENFIND_PORT:-8778}"
  else
    echo "[eden] not running"
  fi
  if [ -f admin-filelist/worlds.db ]; then
    echo "[eden] EdenFind index: built ($(du -h admin-filelist/worlds.db | cut -f1))"
  else
    echo "[eden] EdenFind index: not built (run ./eden.sh rebuild)"
  fi
}

cmd_logs() {
  touch "$LOG_FILE"
  echo "[eden] tailing $LOG_FILE (ctrl-c to stop watching; the server keeps running)"
  tail -n 60 -f "$LOG_FILE"
}

cmd_rebuild() {
  echo "[eden] rebuilding EdenFind search index from admin-filelist/file_list2.txt (~85s)"
  echo "[eden] (preserves star/reject/note triage state across the rebuild)"
  (cd admin-filelist && python3 build.py)
  echo "[eden] done. Restart to pick it up if the app is already running: ./eden.sh restart"
}

cmd_selftest() {
  echo "[eden] running EdenFind selftest (checks the index against known baseline counts)"
  (cd admin-filelist && python3 -m edenfind.selftest)
  echo "[eden] running admin app test suite (front-matter round-trip + everything else)"
  admin/.venv/bin/python -m pytest admin/tests -q
}

cmd_open() {
  if ! is_running; then
    echo "[eden] not running — starting it first"
    cmd_start || return 1
  fi
  echo "[eden] opening $URL"
  if command -v open >/dev/null 2>&1; then open "$URL"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"
  else echo "[eden] don't know how to open a browser on this OS — visit $URL manually"
  fi
}

usage() {
  cat <<EOF
Eden Archive admin web UI — control script

Usage: ./eden.sh <command>

Commands:
  start      Start the admin app (background). EdenFind is embedded as its
             /edenfind page and starts automatically alongside it.
  stop       Stop the admin app (and the EdenFind subprocess it launched).
  restart    stop, then start.
  status     Show whether it's running, its URL, and whether EdenFind's
             search index has been built.
  logs       Tail the combined server log. Ctrl-C just stops watching.
  rebuild    Rebuild EdenFind's SQLite search index from file_list2.txt
             (~85s). Needed once before EdenFind will come up, and again
             any time file_list2.txt or featured/ change.
  selftest   Run EdenFind's baseline self-check and the admin app's test
             suite (front-matter round-trip safety net).
  open       Start if needed, then open the app in your default browser.
  help       Show this message.

With no command, drops into an interactive menu.
EOF
}

interactive_menu() {
  while true; do
    echo
    echo "=== Eden Archive admin web UI ==="
    cmd_status
    echo
    echo "  1) start     4) logs       7) selftest"
    echo "  2) stop       5) rebuild    8) open in browser"
    echo "  3) restart    6) status     9) quit"
    read -r -p "> " choice
    case "$choice" in
      1|start) cmd_start ;;
      2|stop) cmd_stop ;;
      3|restart) cmd_restart ;;
      4|logs) cmd_logs ;;
      5|rebuild) cmd_rebuild ;;
      6|status) cmd_status ;;
      7|selftest) cmd_selftest ;;
      8|open) cmd_open ;;
      9|quit|q|exit) break ;;
      *) echo "unrecognized choice: $choice" ;;
    esac
  done
}

case "${1:-}" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  restart) cmd_restart ;;
  status) cmd_status ;;
  logs) cmd_logs ;;
  rebuild) cmd_rebuild ;;
  selftest) cmd_selftest ;;
  open) cmd_open ;;
  help|-h|--help) usage ;;
  "") interactive_menu ;;
  *) echo "unknown command: $1"; usage; exit 1 ;;
esac
