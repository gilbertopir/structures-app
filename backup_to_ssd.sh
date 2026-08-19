#!/usr/bin/env bash
#
# Back up the structures app to the external SSD.
#
#   ./backup_to_ssd.sh
#
# Run it on the Pi with the SSD plugged in. Safe to run while the app
# is being used on site - nothing is locked and nothing is stopped.

set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/structures-app}"
DEST="${DEST:-/media/gpires/SSDMicro/structures-backup}"
KEEP_DAYS="${KEEP_DAYS:-60}"

if [ ! -d "$(dirname "$DEST")" ]; then
    echo "SSD not found at $(dirname "$DEST") — is it plugged in?" >&2
    exit 1
fi

cd "$APP_DIR"
mkdir -p "$DEST/media"

STAMP="$(date +%F_%H%M)"

echo "==> Snapshotting the database"
# VACUUM INTO rather than copying db.sqlite3 directly: a plain copy
# taken while the app is writing can look fine and fail on restore.
rm -f /tmp/structures_snap.sqlite3
sqlite3 data/db.sqlite3 "VACUUM INTO '/tmp/structures_snap.sqlite3'"
cp /tmp/structures_snap.sqlite3 "$DEST/structures_db_$STAMP.sqlite3"
rm -f /tmp/structures_snap.sqlite3

echo "==> Syncing photos"
# -rlt rather than -a: the SSD is NTFS and cannot store Linux ownership,
# so -a fails on chown. Modification times are kept, which is what makes
# later runs incremental.
sudo rsync -rlt --info=progress2 media/ "$DEST/media/"

echo "==> Pruning snapshots older than $KEEP_DAYS days"
find "$DEST" -maxdepth 1 -name 'structures_db_*.sqlite3' \
     -mtime +"$KEEP_DAYS" -delete

sync

PHOTOS_LIVE="$(find media -type f | wc -l | tr -d ' ')"
PHOTOS_BACKED="$(find "$DEST/media" -type f | wc -l | tr -d ' ')"
SNAPSHOTS="$(find "$DEST" -maxdepth 1 -name '*.sqlite3' | wc -l | tr -d ' ')"

echo
echo "Backup complete"
echo "  photos on the Pi     $PHOTOS_LIVE"
echo "  photos on the SSD    $PHOTOS_BACKED"
echo "  snapshots kept       $SNAPSHOTS"
echo "  location             $DEST"

if [ "$PHOTOS_LIVE" != "$PHOTOS_BACKED" ]; then
    echo
    echo "WARNING: photo counts differ. The backup keeps files that have"
    echo "been deleted on the Pi, so a higher number here is expected."
    echo "A lower number is not — check the rsync output above."
fi
