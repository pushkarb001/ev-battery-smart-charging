# Short literature review: battery modelling and smart EV charging

This note summarises the background behind the modelling choices in this project. It is not a complete survey.

## 1. Equivalent circuit battery models

Equivalent circuit models (ECMs) describe a cell with an open-circuit voltage source, a series resistance and one or more RC elements. They are the standard choice for battery management systems and system-level simulation because they are fast and their parameters can be identified from simple tests.

- NASA's technical memorandum on battery model characterisation describes first-order ECMs, their parameter identification and their use for model-based SOC estimation, and compares them with electrochemical models.
  [NASA TM-20205008059](https://ntrs.nasa.gov/api/citations/20205008059/downloads/NASA-TM-20205008059.pdf)
- A 2025 comparative study fits a 2-RC ECM to discharge data of 12 cells from the NASA, CALCE, Oxford and HNEI datasets (via the Battery Archive) and compares eight optimisation methods for parameter identification.
  [arXiv 2512.02606](https://arxiv.org/pdf/2512.02606)
- Electro-thermal ECMs of complete EV packs can also be identified from drive-cycle CAN data instead of laboratory tests.
  [Batteries 11(9), 319](https://www.mdpi.com/2313-0105/11/9/319)
- For physics-based (electrochemical) models, PyBaMM is an open-source Python framework developed at the University of Oxford.
  [Sulzer et al., J. Open Research Software 9(1), 2021](https://doi.org/10.5334/jors.309)

**Choice in this project:** a 1-RC ECM. It is accurate enough for energy and loss calculations over hours of charging, and its main weakness (a single relaxation time constant) is shown explicitly in the validation plot.

## 2. Smart charging with PV and variable tariffs

Smart charging shifts the charging power in time, using information about prices, local generation or grid limits. Common objectives are low cost, high PV self-consumption and low peak load.

- A review of smart charging with PV production and household consumption covers rule-based, optimisation-based and stochastic approaches, mainly for minimising cost under time-of-use tariffs.
  [ResearchGate review](https://www.researchgate.net/publication/340153867_Smart_charging_of_electric_vehicles_considering_photovoltaic_power_production_and_electricity_consumption_A_review)
- A two-stage robust optimisation framework integrates PV-battery storage, EV charging and demand response in a smart home, minimising cost under time-of-use and real-time prices while accounting for PV uncertainty.
  [Journal of Energy Storage, 2025](https://www.sciencedirect.com/science/article/abs/pii/S2352152X2404845X)
- A study of a scalable PV and storage based charging station sets the charging current with an optimisation that uses the load, the tariff and user information; the cited feasibility study for Danish home charging ranks time-of-use and real-time pricing strategies among the most feasible.
  [Transportation Research Procedia, 2023](https://www.sciencedirect.com/science/article/pii/S2352146523008815)
- At fleet level, optimisation of electric bus charging adds peak demand charges, V2G and battery degradation costs.
  [arXiv 2509.05940](https://arxiv.org/pdf/2509.05940)

**Choice in this project:** deterministic linear programming over one day with perfect forecasts. This gives the upper bound of what smart charging can achieve; robust or stochastic formulations (as in the references above) would be the next step to handle forecast errors.

## 3. Open points for future work

- Replace the synthetic cell data with a public dataset (e.g. CALCE or NASA) and add a temperature-dependent resistance.
- Add a minimum charging power and charger efficiency curve.
- Use forecasts with errors and a receding-horizon (model predictive) controller.
- Extend to bidirectional charging (vehicle-to-home) and include a battery ageing cost.
