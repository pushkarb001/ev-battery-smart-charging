# Data

By default the study uses **synthetic** cell test data that `run.py` generates and saves to `results/data/`. No download is needed.

## Using real laboratory data

1. Download cell test data, for example from the [Battery Archive](https://www.batteryarchive.org/), which collects public datasets (NASA, CALCE, Oxford, HNEI and others) in a common format.
2. Prepare three tests of the **same cell** and export each to CSV with these columns:

   | column | unit | note |
   |---|---|---|
   | `time_s` | s | starts at 0 |
   | `current_a` | A | **> 0 = discharge**, < 0 = charge |
   | `voltage_v` | V | terminal voltage |

   - `ocv.csv`: full low-rate discharge (C/20 or slower) from 100 % SOC
   - `pulse.csv`: pulse test (e.g. HPPC) used for fitting
   - `dynamic.csv`: driving-like profile used only for validation (e.g. FUDS, DST, US06 tests)

3. Put the files in `data/raw/` and set in the config:

   ```yaml
   battery_identification:
     data_source: csv
     csv:
       ocv_test: data/raw/ocv.csv
       pulse_test: data/raw/pulse.csv
       validation_test: data/raw/dynamic.csv
       soc0_ocv: 1.00          # SOC at the start of each test
       soc0_pulse: 0.95
       soc0_validation: 0.90
   ```

4. Adjust `pack.n_series` and `pack.n_parallel` to the cell capacity of your data.

`data/raw/` is excluded from git (see `.gitignore`) so large datasets are not uploaded. Check each dataset's licence before redistributing it.
