#!/usr/bin/env bash
#
# Pull a backup of the structures app from the Raspberry Pi.
#
# Run this from the machine you want the backup ON (your home PC), not
# on the Pi itself. Requires SSH access to the Pi - on your home
# network that works out of the box.
#
#   chmod +x backup_from_pi.sh
#   ./backup_from_pi.sh
#
# The database is snapshotted with VACUUM INTO before transfer. Copying
# a live SQLite file directly can produce an archive that looks fine
# and fails on restore, which is the worst kind of backup.
#
# Photos sync incrementally: they are never modified once uploaded, so
# after the first run only new files move. That is why this stays fast
# no matter how large the media folder grows, and why it never needs
# splitting into volumes.

set -euo pipefail

PI_HOST="${PI_HOST:-gpires@raspberrypi.local}"
PI_APP_DIR="${PI_APP_DIR:-/home/gpires/structures-app}"
BACKUP_ROOT="${BACKUP_ROOT:-$HOME/pi-backup/structures}"

STAMP="$(date +%Y-%m-%d_%H%M)"
DB_DIR="$BACKUP_ROOT/db"
MEDIA_DIR="$BACKUP_ROOT/media"

mkdir -p "$DB_DIR" "$MEDIA_DIR"

echo "==> Snapshotting the database on the Pi"
ssh "$PI_HOST" "cd '$PI_APP_DIR' && \
    rm -f /tmp/structures_snapshot.sqlite3 && \
    sqlite3 data/db.sqlite3 \"VACUUM INTO '/tmp/structures_snapshot.sqlite3'\""

echo "==> Fetching the snapshot"
scp "$PI_HOST:/tmp/structures_snapshot.sqlite3" \
    "$DB_DIR/structures_db_$STAMP.sqlite3"
ssh "$PI_HOST" "rm -f /tmp/structures_snapshot.sqlite3"

echo "==> Syncing photos (only new files transfer)"
rsync -a --info=progress2 \
    "$PI_HOST:$PI_APP_DIR/media/" "$MEDIA_DIR/"

echo "==> Pruning database snapshots older than 30 days"
find "$DB_DIR" -name 'structures_db_*.sqlite3' -mtime +30 -delete

DB_COUNT="$(find "$DB_DIR" -name '*.sqlite3' | wc -l | tr -d ' ')"
PHOTO_COUNT="$(find "$MEDIA_DIR" -type f | wc -l | tr -d ' ')"
TOTAL_SIZE="$(du -sh "$BACKUP_ROOT" | cut -f1)"

echo
echo "Backup complete"
echo "  snapshots kept   $DB_COUNT"
echo "  photos held      $PHOTO_COUNT"
echo "  total size       $TOTAL_SIZE"
echo "  location         $BACKUP_ROOT"
echo
echo "Note: photos are never deleted here even if removed on the Pi."
echo "That is deliberate - an accidental deletion on site should not"
echo "propagate into the backup. Prune by hand if it ever matters."
