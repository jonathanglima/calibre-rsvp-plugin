#!/usr/bin/env bash
# Add books to the Calibre library *while it is being served*, handling the
# library lock for you: stop the content server, import + convert + tag, then
# bring the server back up.
#
#   ./rsvp-add.sh book.epub                 # one file
#   ./rsvp-add.sh ~/incoming-epubs/         # a whole directory (recurses)
#
# Prefers the systemd user service (calibre-server). If that isn't active, it
# stops whatever holds the port BY PID (never `pkill`-by-string, which can match
# the calling shell) and relaunches calibre-server directly afterwards.
set -euo pipefail

LIB="${RSVP_LIB:-$HOME/CalibreLibrary}"
PORT="${CALIBRE_PORT:-8080}"
SERVICE="${CALIBRE_SERVICE:-calibre-server}"
HERE="$(cd "$(dirname "$0")" && pwd)"

[ "$#" -ge 1 ] || { echo "usage: $0 <file.epub | directory> ..."; exit 1; }

server_pid() {
  ss -ltnHp "sport = :$PORT" 2>/dev/null | grep -oE 'pid=[0-9]+' | grep -oE '[0-9]+' | head -1
}

restart_mode=none
if systemctl --user is-active --quiet "$SERVICE" 2>/dev/null; then
  restart_mode=systemd
  echo "Stopping $SERVICE (releasing the library lock)..."
  systemctl --user stop "$SERVICE"
elif [ -n "$(server_pid)" ]; then
  restart_mode=manual
  pid="$(server_pid)"
  echo "Stopping calibre-server (pid $pid)..."
  kill "$pid" 2>/dev/null || true
fi
# wait for the port to actually free before touching the library
for _ in $(seq 1 200); do [ -z "$(server_pid)" ] && break; done

RSVP_LIB="$LIB" "$HERE/rsvp-import.sh" "$@"

case "$restart_mode" in
  systemd) echo "Starting $SERVICE..."; systemctl --user start "$SERVICE" ;;
  manual)  echo "Relaunching calibre-server..."
           nohup calibre-server --port "$PORT" "$LIB" >/tmp/calibre-server.log 2>&1 & disown ;;
  none)    echo "(server was not running; left it stopped)" ;;
esac
echo "Done."
