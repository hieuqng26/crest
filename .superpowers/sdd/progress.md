# SDD Progress: Redesign Segmentation — Inline in New Calibration

Branch: feature/auth-rbac-rebuild
Merge base: c58c139 (fix(migrations): merge auth_rebuild and segmentation heads)

## Tasks
- [ ] Task 1: DB model changes + Alembic migration
- [ ] Task 2: Backend APIs + Celery task refactor (datasets sectors endpoint, calibration API, task logic, remove old segmentation API)
- [ ] Task 3: Frontend (CalibrateNew.vue redesign, remove segmentation config page, CalibrateRun.vue updates, datasetsAPI.js)

## Completed
- Task 1: complete (DB model + Alembic migration v4w6x8y0z2a4, review clean)
- Task 2: complete (datasets sectors endpoint, calibration inline seg API, celery refactor, seg_configs blueprint removed, review clean)
- Task 3: complete (CalibrateNew.vue rewrite, CalibrateRun.vue fix, OverviewTab seg info, router/menu cleanup, deleted segmentationConfigsAPI.js + SegmentationConfigs.vue, review clean)
