# TODO
- [ ] Redesign Job History table
- [ ] Backtesting plots: interactive, add coefs (with p-value and statistical tests), qq plots
- [ ] Stepper for workflow progress tracking, including step after credit analysis is done
- [ ] Add more audit logs
- [ ] Test and verify all models. If the error occurs during job run, we should have clear message of what goes wrong (input data is invalid, model is not appropriate, etc.)
- [ ] Add model for panel data
- [ ] Add customized models (with optimization)
- [ ] Add outlier detection pipeline
- [ ] Add feature selection pipeline
- [ ] Verify ECL and KMV core code
- [ ] Add client segmentation analysis
- [ ] Develop PD model by logistic regression
- [ ] Create staging ETL: transform bank's raw data, merge files, ...
- [ ] Cleanup unused env variables
- [ ] Email when training jobs complete
- [ ] Dont store json in database tables

# COMPLETED
- Workflow details:
    - [x] SegmentModelsPanel: Move log inside the same collapsible box (Use PrimeVue's Panel component as it has collapsible function) with Run Details (Run Details on the left 40% of the box, Log on right with 60% width). When the job is running, make the run details & log visible, don't load or show the segment models table. When job is finished, collapse the run details & log box, show the segment models table. Add a column Sector in Segment Models table.
    - [x] Forecast tab: remove SCENARIO filter. Add the log in a collapsible panel below the forecast data table. Show the log only when the job is running.
    - [x] Credit Results tab: remove SCENARIO filter and the information display like EXPOSURE etc. Similar to Forecast tab, add the log.
- Financial Forecast:
    - [x] The plots in Financial Forecast have jumps
    - [x] Add multi-select dropdown for the target variables. If only one is chosen, show the plot in full width
    - [x] Make the plots interactive: on hovering, able to disable the scenarios when clicking on legend items
    - [x] Dont index all series to 100 at base year by default. Give user the option to switch it on if they want. Disable by default
- [x] Some pages are loading too slow: Heatmap, Financial Forecast, Job History, Job View

- Job History: 
    - [x] Add Delete, Multi-delete, Rerun, Cancel action buttons. "Type" should be MANUAL or AUTO, not Workflow, Training, Forecast,  or Analysis. Add ability to activate a job so Analysis pages will load

- [x] Financial Forecast page: add multi-select dropdown for which target variables to show (only show target variables of the active job, not some derived ones like cogs/revenue)
- [x] Modelling workflow:
    - [x] I want to make the model setup a bit more "automated" for manual. First, user don't need to choose training dataset, the backend will pull the latest data from financial data table. 
    - [x] Second, users can choose to run multiple targets at once, but we need to think carefully how we should design this: we need a default model configuration applied to all targets, but also need to offer capability to customize if user wants to. 
    - [x] Third, the job will also run forecast and analysis, pulling latest data from corresponding tables.
    - [x] Fourth, the job history will now have another level, which is Target, on top of the segments. Individual job's view should also have diagnosis & backtesting, forecast, credit analysis results.
    - [x] I dont like the breakdown of target and analysis for each job in Job History. Just treat the whole workflow as 1 process. In individual job view, I want to see 4 tabs: 
        - Overview: currently Training
        - Diagnosis & Backtesting: combine Diagnosis and Backtesting tab in old version (redesign to align with current design theme), filter by target, sector, segment
        - Forecast: display forecast results in data table, filter by target, sector, segment
        - Credit Results: display credit results in data table
        - Remove the process indicator 1->2->3

- [x] Restructure:
    The current workflow is not quite intuitive and requires a lot of mouse clicking, e.g. select data, config, model, etc. I'm thinking of restructure the modules to make the workflow smoother. There are 2 main types of users: one wants to draw insights from the data and take actions, and another focuses on the technical side and needs to make sure the models run correctly. Dashboard, Datasets and System modules can stay the same. We will restructure the rest into: Model, Analysis, Jobs. 
    Model should have New Model & Model Results. New Model has 2 mode: auto mode and manual mode. Auto mode can be used for experimenting, or high-level work, while manual mode is built purposefully for people with technical expertise. Take inspirations from Vertex AI for the model build and train. The Model Results section just shows model evaluation (diagnosis and backtesting), and model properties when user selects a trained model.
    Analysis: this section presents the results forecasted by the model with insightful visualizations, for example: 
        - Heatmap: changes in financial ratio (e.g COGS/Revenue, Revenue Change) by sectors, for each forecasted years. User can deep dive into a sector, which shows heatmap by selected companies
        - Financial Forecast: show charts on model forecast for each financial items
        - PD/LGD: same
        - ECL: same
        - Transition: same
    Jobs section: this stores the history of model runs. When user inspects a model run, they can have option to customize a specific segment model and rerun that segment
- [x] Revise data and model:
    - [x] Modify @services/server/project/data/test_data/demo_macro_forecast.csv :remove columns sector,subsector,base_year,total_assets,total_longterm_debts,total_shortterm_debts,country
    - [x] When performing forecast job, we just use the MEVs the model required. That means each country/subsector model with generate 1 dataset of forecasts.
    - [x] Create a new demo_financial_portfolio, with columns date,scenario,client_id,country,sector,subsector,base_year,total_assets,total_longterm_debts,total_shortterm_debts. base_year just put 2026 for all.
    - [x] When performing the credit analysis, we would need to merge the demo_financial_portfolio with the demo_credit_portfolio by client_id and date, then merge with the corresponding forecast (right sector and subsector/country) by date. We then proceed with the KMV, ECL.
    - [x] Frontend: segment picker in New Forecast Run form; financial portfolio dataset picker (required) in New Analysis form; financial_portfolio kind added to Datasets upload.

- [x] Create realistic demo data:
    - [x] I want you to create more realistic demo datasets. First, for @services/server/project/data/test_data/financials_macro_merged.csv , it should contains 10 sectors, each has 10 countries, and 4-6 subsectors. Per sector, per country/subsector, there should be around 300-500 samples, cover years from 1990 to 2026.
    - [x] Next, I want you to create a test to run the following workflow. Use @services/server/project/data/test_data/financials_macro_merged.csv for calibration, use model elasticnet (default configuration). Run 3 calibration jobs for total_assets, total_longterm_debts, total_shorterm_debts, and features inflation_rate, notional_gdp, unemployment_rate, coal_price, oil_price. For forecast jobs, run 3 calibration models on @services/server/project/data/test_data/demo_macro_forecast.csv . Lastly, for credit jobs, use @services/server/project/data/test_data/demo_credit_portfolio.csv and @services/server/project/data/test_data/demo_financial_portfolio.csv , with total_assets, total_longterm_debts, total_shorterm_debts are forecasted with 3 calibration models above. Test for all sectors, use subsector split, max segments is 5.
    - [x] Then look at the fit, I want the fit is relatively good (R2 at least 20%, ideally 50% and above)
    - [x] Need to make sure end-to-end is producing correct results
    
- [x] Add a shared component for data table that will be used across the application (unless we need a very customized one) for example in the dataset views, backtesting, forecast results. The table should clean, easy to read. It should have filters for each column. For categorical columns with less than 30 unique values, it should have dropdown (with search). It should also have sorting function for each column. Most importantly, it should has pagination and able to load large data seemlessly
- [x] Add ability to give the calibration a name
- [x] Redesign UI for every page

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

