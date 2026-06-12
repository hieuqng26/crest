# Known Issues

## ISSUE-001 — Large file upload and view performance

**Status:** Open  
**Area:** `api/datasets/routes.py` — `upload_dataset` and `get_dataset_rows`

### Problem

Two related bottlenecks exist when handling large dataset files (e.g. >100 MB):

1. **Upload latency** — `POST /api/datasets/upload` reads the entire file into memory, parses it with pandas (for schema extraction), then uploads the raw bytes to MinIO in one blocking call. For a large file this blocks the Flask worker for the full duration of the upload + MinIO write.

2. **View / pagination latency** — `GET /api/datasets/<id>/rows` downloads the entire file from MinIO, re-parses it into a pandas DataFrame, then slices the requested page. Even a request for rows 0–50 of a 10M-row file downloads and parses the whole thing first. Memory use scales with file size.

### Root cause

Both operations load the full file into memory. Pagination is applied *after* the full download, not at storage level.

### Proposed fixes (for future implementation)

**Upload:**
- Stream the upload to MinIO using multipart/chunked upload rather than buffering all bytes in memory first (`minio.put_object` with a stream and unknown length, or `fput_object` via a temp file).
- Extract schema from a header-only sample (e.g. `pd.read_csv(..., nrows=100)`) instead of reading the full file.

**View / pagination:**
- Store a pre-processed Parquet copy of the dataset in MinIO alongside the original. Parquet supports column pruning and row-group skipping, making page reads much cheaper.
- Alternatively, load large CSV/Excel files into a temporary MSSQL staging table on first view (async Celery task), then serve rows via SQL with `OFFSET / FETCH` — making all pagination O(page size) rather than O(file size).
- As a quick interim fix: cap accepted file size at a reasonable limit (e.g. 50 MB) and return a 413 with a clear message until the proper fix is in place.

### Files to change

- `services/server/project/api/datasets/routes.py` — `upload_dataset`, `get_dataset_rows`
- `services/server/project/core/storage.py` — add streaming upload helper
- Possibly a new Celery task for async dataset ingestion
