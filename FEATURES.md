- Add sector, subsector, country:
    - Add columns to demo data
    - For each sector user can choose to split the portfolio by subsector or country: typically there are 4-5 subsectors within a sector, if more than that, we model the main ones, then group the rest to "Others" subsector. Similarly, if splitting by countries, user can either model largest 5 countries (in terms of total exposure), group the rest to "Others", or group countries by regions, model 4-5 main regions, group the rest to "Others"
    - Each subsector/country group is then calibrated with a model
    - Remove ability to merge datasets, it is funky, we assume the input data is already merged: merge historical mev with historical financial data by date and country. The forecast data currently only has MEVs, but we should add: client_id, country, sector, subsector, base year, total assets, total long-term debts, total short-term debts
    - Forecasting: perform forecasting using the model corresponding to sample's subsector/country

- Test and verify all models
- Add real data for mev and financial (refinitive)
- Add model for panel data
- Add customized models (with optimization)
- Add outlier detection pipeline
- Verify ECL and KMV core code
- Add client segmentation analysis
- Develop PD model by logistic regression
- Create staging ETL: transform bank's raw data, merge files, ...

---

- [x] Results table in Forecast job and Backtesting's prediction table in Calibration job: show the row number "x to y" corresponding to the selected page
- [x] Results table in Forecast: doesn't need the box on top of the datatable ("PREDICTIONS ... xxx rows")
- [x] Rename sidebar items: Models' Configurations -> Model Configurations, Calibration's New Run -> New Calibration, All Jobs -> Calibration Jobs, Forecast's New Forecast Run -> New Forecast, All Jobs -> Forecast Jobs. Then group MODELS and CALIBRATION modules together, call it MODELS

---

- [x] Add a column scenario to demo_macro_forecast.csv: this column is required. Forecast result should contain this column, which will be consumed by the Credit Risk analysis job, and then IFRS 9 ECL and PD/LGD
- [x] Make the Forecast's All Jobs page and Credit Risk's Analysis Jobs page similar to Calibration's All Jobs page: Add "Select" button (for bulk deleting), remove the small "Forecast" text on top of "Forecast Jobs", add a filter button. The "View", "Rerun", "Delete" are grouped into a vertical 3 dots. Add ability to cancel the job as well. The run id in "CALIBRATION MODEL" column of the jobs table should be linked to the corresponding calibration jobs
- [x] When View a specific Forecast job: Overview should be similar to Credit Risk's Analysis Jobs
- [x] When View a specific Credit Risk analysis job: add result tab (similar to Forecast's)
- [x] Calibration job: Backtesting's Prediction table should show the whole table (not just top 100), with ability to download

---

Calibration:
- [x] The current forecast for each calibration run is done on validation set. This should not be a forecast but rather a backtesting/diagnosis.

Forecast
- [x] Create another module for "Forecast". For the forecast, user needs to register another forecast dataset of independent variables. User will choose the calibrated model and the forecast dataset, then launch a forecast run. The forecast runs' results will be the inputs to credit risk analysis jobs.

Credit Risk:
- [x] New Analysis page: Calibration run should allow more than 1 calibrations/target variables. It should let user choose the target variables available from all successful calibration, then when user pick a specific calibration id if there are more than 1 runs for a selected target variable
- [x] Analysis jobs: dont redirect to IFRS 9 ECL on clicking. Instead, add ability to set active, view, rerun, delete. And the table should show Finished date, which target variables (and corresponding calibration id, if possible link the id to the one Calibration's All Jobs page)
- [x] IFRS 9 ECL and PD/LGD: should load result from active analysis job.
- [x] IFRS 9 ECL: remove the reload button and analysis run dropdown

---

- [x] Target and features variables should be set during calibration, not as part of model configuration
- [x] Add more plots for Diagnosis of regression model

---

- [x] data split, scaler, hyperparameter search should be part of model configurations instead of being set in calibration
- [x] Confirm if Forecast is currently static. If so, connect it to the workflow
- [x] In All Jobs page, remove DURATION column, instead showing STARTED and FINISHED

---

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
- [x] add ability to edit each configuration (fix NULL model_config_id error on save)
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

