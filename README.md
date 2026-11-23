# Raw data snapshots (private)

Offline backups of the UFCalendar landing folder (`/Volumes/mma/raw/landing/ufcalendar`), made by the
`landing-snapshot` Databricks job. This branch has no shared history with `main`.

- UFCalendar terms forbid redistributing the raw dataset. Keep this repo private, and **delete this
  branch before making the repo public** (`git push origin --delete data-snapshots`).
- Restore: unzip, then upload the `ufcalendar/` folder back to the volume (or point `--output-dir` at it).
- Check integrity: `sha256sum -c snapshots/SHA256SUMS`.

| Snapshot | Files | Size | Contents |
|---|---|---|---|
| `ufcalendar_20261123T082306Z.zip` | 21,038 | 22.5 MB | Full history for UFC, PFL, OKTAGON, RIZIN (1,263 events, 13,090 bouts, 5,322 fighters), manifest and run logs |
