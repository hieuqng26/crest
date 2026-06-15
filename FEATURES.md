Datasets page
- [x] "All", "Upload", "Live Query" filters should be grouped into a dropdown (default to "All")
- [x] Redesign individual dataset's page when click "View": some components are not well aligned, the data's text size is too small
- [x] Add ability to bulk delete

Algorithm Catalog
- [x] Rename to Model Catalog
- [x] Reclassify some models in the catalog: GradientBoosting should be Ensemble, Ridge should be Regression
- [x] Add a few more commonly used models: Lasso, ElasticNet, SVM, RandomForest, etc

Saved Configurations
- [x] deleted configuration still exists
- [x] add ability to edit each configuration
- [x] Bulk delete saved configurations
- [x] Remove New Configuration button in Saved Configurations page

New Calibration Run page:
- [x] Each dataset box under Datasets section : there should be ability to view all columns
- [x] Remove Resulting Schema section

All Jobs page:
- [x] a rerun should not spawn a new run id, instead overwrite the existing run

Individual Calibration's page:
- [x] Cancel gets error: "sqlalchemy.orm.exc.DetachedInstanceError: Instance <CalibrationRun at 0xffff52141850> is not bound to a Session"
- [x] Redesign Overview page: information are presented in a way that is messy and hard to read
- [x] show model's fitted coefficients (if applicable), best hyperparameters (if using grid search or random search)
- [x] Diagnostics tab: feel like it's a placeholder (static) now
- [x] Redesign Diagnostics page: think about how we might show different info, use different layout, charts for different model types
- [x] Forecast is disabled even if the run succeeds

[x] All Datetime should show format DD/MM/YYYY HH:MM:SS in timezone (add the date format and timezone (like SG, VN, ID, MY) this as system variable)

[x] Format all python scripts according industry standard python formatting. All imports are placed at the top

