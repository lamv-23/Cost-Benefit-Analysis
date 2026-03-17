/**
 * CBA Calculation Engine
 * Parameters based on TfNSW Economic Parameter Values (January 2025)
 * All monetary values in June 2024 prices (AUD)
 */
const CBA = (() => {

    // =========================================================================
    // TfNSW ECONOMIC PARAMETER VALUES (Jan 2025, June 2024 prices)
    // =========================================================================
    const PARAMS = {
        // Value of Travel Time Savings ($/person-hour)
        // Source: TfNSW EPV Table 2.1
        vtts: {
            urban: { commute: 19.76, business: 54.87, other: 9.35 },
            rural: { commute: 17.78, business: 49.38, other: 8.42 }
        },

        // Vehicle Operating Costs ($/vehicle-km, resource cost)
        // Source: TfNSW EPV Table 3.1 & Technical Note on VOC (2022)
        voc: {
            urban: {
                car:   { 40: 0.268, 50: 0.241, 60: 0.224, 70: 0.215, 80: 0.212, 90: 0.215, 100: 0.224 },
                lgv:   { 40: 0.323, 50: 0.296, 60: 0.281, 70: 0.273, 80: 0.271, 90: 0.276, 100: 0.287 },
                rigid: { 40: 0.602, 50: 0.553, 60: 0.523, 70: 0.508, 80: 0.505, 90: 0.513, 100: 0.534 },
                artic: { 40: 0.836, 50: 0.768, 60: 0.726, 70: 0.705, 80: 0.700, 90: 0.711, 100: 0.740 }
            },
            rural: {
                car:   { 60: 0.210, 80: 0.198, 100: 0.209, 110: 0.221 },
                lgv:   { 60: 0.265, 80: 0.255, 100: 0.268, 110: 0.282 },
                rigid: { 60: 0.493, 80: 0.475, 100: 0.502, 110: 0.526 },
                artic: { 60: 0.685, 80: 0.660, 100: 0.697, 110: 0.731 }
            }
        },

        // Crash Costs ($/crash, all casualty and damage costs)
        // Source: TfNSW EPV Table 4.1
        crashCosts: {
            fatal:    9462000,
            serious:   471000,
            moderate:   28200,
            minor:      13100,
            pdo:        11500
        },

        // Value of Statistical Life: $8.1M (source: TfNSW / Office of Best Practice Regulation)
        vsl: 8100000,

        // Environmental Externalities
        // CO2 social cost per tonne — NSW carbon values per TPG24-29
        // Uses central value growing over time; base year value shown
        carbonPerTonne: 123,

        // Air pollution externality ($/veh-km) — Source: TfNSW EPV Table 6.1
        airPollution: {
            urban: { car: 0.032, lgv: 0.045, rigid: 0.179, artic: 0.228 },
            rural: { car: 0.005, lgv: 0.007, rigid: 0.028, artic: 0.036 }
        },

        // Noise externality ($/veh-km) — Source: TfNSW EPV Table 6.2
        noise: {
            urban: { car: 0.005, lgv: 0.005, rigid: 0.037, artic: 0.037 },
            rural: { car: 0.001, lgv: 0.001, rigid: 0.006, artic: 0.006 }
        },

        // Health benefits of active transport ($/person-km)
        // Source: TfNSW EPV Table 7.1
        healthBenefits: {
            walking: 3.17,
            cycling: 1.60
        },

        // Travel time reliability ratio (reliability benefit as proportion of VTTS)
        // Source: TfNSW EPV Section 2.3
        reliabilityRatio: 0.9,

        // Working days per year (standard)
        workingDaysPerYear: 253,
        daysPerYear: 365,

        // Default discount rates for sensitivity
        discountRates: [4, 7, 10],

        // Traffic composition defaults (urban, %)
        // Source: TfNSW EPV Table 2.5
        trafficComposition: {
            urban: { car: 0.84, lgv: 0.08, rigid: 0.05, artic: 0.03 },
            rural: { car: 0.75, lgv: 0.10, rigid: 0.08, artic: 0.07 }
        }
    };

    // =========================================================================
    // HELPER FUNCTIONS
    // =========================================================================

    function val(id) {
        const el = document.getElementById(id);
        if (!el) return 0;
        return parseFloat(el.value) || 0;
    }

    function discountFactor(rate, year) {
        return 1 / Math.pow(1 + rate / 100, year);
    }

    function interpolateVOC(vocTable, speed) {
        const speeds = Object.keys(vocTable).map(Number).sort((a, b) => a - b);
        if (speed <= speeds[0]) return vocTable[speeds[0]];
        if (speed >= speeds[speeds.length - 1]) return vocTable[speeds[speeds.length - 1]];
        for (let i = 0; i < speeds.length - 1; i++) {
            if (speed >= speeds[i] && speed <= speeds[i + 1]) {
                const ratio = (speed - speeds[i]) / (speeds[i + 1] - speeds[i]);
                return vocTable[speeds[i]] + ratio * (vocTable[speeds[i + 1]] - vocTable[speeds[i]]);
            }
        }
        return vocTable[speeds[0]];
    }

    function formatM(value) {
        if (Math.abs(value) >= 1000) return '$' + (value / 1000).toFixed(1) + 'B';
        return '$' + value.toFixed(1) + 'M';
    }

    // =========================================================================
    // MAIN CALCULATION
    // =========================================================================

    let lastResults = null;

    function calculate() {
        const context = document.getElementById('projectContext').value;
        const evalPeriod = val('evaluationPeriod');
        const constYears = val('constructionYears');
        const dr = val('discountRate');
        const aadt = val('aadtBase');
        const growth = val('trafficGrowth') / 100;
        const tripLen = val('avgTripLength');
        const occupancy = val('avgOccupancy');
        const pctCommute = val('pctCommute') / 100;
        const pctBusiness = val('pctBusiness') / 100;
        const pctOther = 1 - pctCommute - pctBusiness;
        const pctHeavy = val('pctHeavyVehicles') / 100;
        const speedBase = val('speedBase');
        const speedProject = val('speedProject');

        // --- COSTS ---
        const capPlanning = val('capitalPlanning');
        const capLand = val('capitalLand');
        const capConstruction = val('capitalConstruction');
        const contingencyPct = val('capitalContingency') / 100;
        const totalCapitalUndiscounted = (capPlanning + capLand + capConstruction) * (1 + contingencyPct);
        const opexMaint = val('opexMaintenance');
        const opexOp = val('opexOperating');
        const residual = val('residualValue');

        // Spread capital evenly over construction years
        const annualCapital = totalCapitalUndiscounted / constYears;

        // --- ANNUAL BENEFITS (first year of operation) ---
        const vttsSet = PARAMS.vtts[context];
        const comp = PARAMS.trafficComposition[context];

        // Travel time savings
        const timeBaseHr = tripLen / speedBase;
        const timeProjectHr = tripLen / speedProject;
        const timeSavingHr = Math.max(0, timeBaseHr - timeProjectHr);

        const dailyPersonTrips = aadt * occupancy;
        const vttsWeighted = vttsSet.commute * pctCommute +
                             vttsSet.business * pctBusiness +
                             vttsSet.other * Math.max(0, pctOther);

        const annualTTSBenefit = dailyPersonTrips * timeSavingHr * vttsWeighted * PARAMS.daysPerYear / 1e6;

        // Reliability benefits
        const annualReliability = annualTTSBenefit * PARAMS.reliabilityRatio * 0.3;

        // Vehicle operating cost savings
        const vocBase = interpolateVOC(PARAMS.voc[context].car, speedBase);
        const vocProject = interpolateVOC(PARAMS.voc[context].car, speedProject);
        const vocSavingCar = Math.max(0, vocBase - vocProject);

        const vocBaseHeavy = interpolateVOC(PARAMS.voc[context].rigid, speedBase);
        const vocProjectHeavy = interpolateVOC(PARAMS.voc[context].rigid, speedProject);
        const vocSavingHeavy = Math.max(0, vocBaseHeavy - vocProjectHeavy);

        const annualVOCBenefit = (
            aadt * (1 - pctHeavy) * tripLen * vocSavingCar +
            aadt * pctHeavy * tripLen * vocSavingHeavy
        ) * PARAMS.daysPerYear / 1e6;

        // Safety benefits
        const annualSafety = (
            val('crashFatal') * PARAMS.crashCosts.fatal +
            val('crashSerious') * PARAMS.crashCosts.serious +
            val('crashModerate') * PARAMS.crashCosts.moderate +
            val('crashMinor') * PARAMS.crashCosts.minor +
            val('crashPDO') * PARAMS.crashCosts.pdo
        ) / 1e6;

        // Environmental benefits
        const annualCO2 = val('emissionReduction') * PARAMS.carbonPerTonne / 1e6;
        const annualAirPollution = val('airPollutionReduction') / 1e3;
        const annualNoise = val('noiseReduction') / 1e3;
        const annualEnvironmental = annualCO2 + annualAirPollution + annualNoise;

        // Active transport health benefits
        const annualWalkHealth = val('walkKmPerDay') * PARAMS.healthBenefits.walking * PARAMS.daysPerYear / 1e6;
        const annualCycleHealth = val('cycleKmPerDay') * PARAMS.healthBenefits.cycling * PARAMS.daysPerYear / 1e6;
        const annualActiveTransport = annualWalkHealth + annualCycleHealth;

        const totalFirstYearBenefit = annualTTSBenefit + annualReliability + annualVOCBenefit +
                                       annualSafety + annualEnvironmental + annualActiveTransport;

        // --- YEAR-BY-YEAR CASHFLOW ---
        const totalYears = constYears + evalPeriod;
        const annualCosts = [];
        const annualBenefits = [];
        const annualBenefitsByType = { tts: [], reliability: [], voc: [], safety: [], env: [], active: [] };
        const annualNet = [];
        const discountedCosts = [];
        const discountedBenefits = [];
        const discountedNet = [];
        const cumulativeDiscNet = [];

        let pvBenefits = 0;
        let pvCosts = 0;
        let cumDiscNet = 0;
        let paybackYear = null;

        for (let y = 0; y < totalYears; y++) {
            const df = discountFactor(dr, y);
            let cost = 0;
            let benefit = 0;
            let benefitTTS = 0, benefitRel = 0, benefitVOC = 0, benefitSafety = 0, benefitEnv = 0, benefitActive = 0;

            if (y < constYears) {
                // Construction phase
                cost = annualCapital;
            } else {
                // Operating phase
                const opYear = y - constYears;
                const growthFactor = Math.pow(1 + growth, opYear);
                cost = opexMaint + opexOp;

                benefitTTS = annualTTSBenefit * growthFactor;
                benefitRel = annualReliability * growthFactor;
                benefitVOC = annualVOCBenefit * growthFactor;
                benefitSafety = annualSafety;
                benefitEnv = annualEnvironmental;
                benefitActive = annualActiveTransport;

                benefit = benefitTTS + benefitRel + benefitVOC + benefitSafety + benefitEnv + benefitActive;

                // Residual value in final year
                if (y === totalYears - 1) {
                    benefit += residual;
                }
            }

            annualCosts.push(cost);
            annualBenefits.push(benefit);
            annualBenefitsByType.tts.push(benefitTTS);
            annualBenefitsByType.reliability.push(benefitRel);
            annualBenefitsByType.voc.push(benefitVOC);
            annualBenefitsByType.safety.push(benefitSafety);
            annualBenefitsByType.env.push(benefitEnv);
            annualBenefitsByType.active.push(benefitActive);

            const net = benefit - cost;
            annualNet.push(net);
            discountedCosts.push(cost * df);
            discountedBenefits.push(benefit * df);
            discountedNet.push(net * df);

            pvCosts += cost * df;
            pvBenefits += benefit * df;
            cumDiscNet += net * df;
            cumulativeDiscNet.push(cumDiscNet);

            if (paybackYear === null && cumDiscNet >= 0 && y >= constYears) {
                paybackYear = y + 1;
            }
        }

        const npv = pvBenefits - pvCosts;
        const bcr = pvCosts > 0 ? pvBenefits / pvCosts : 0;

        // First Year Rate of Return
        const fyrr = totalCapitalUndiscounted > 0 ? (totalFirstYearBenefit / totalCapitalUndiscounted) * 100 : 0;

        // --- PV BENEFIT BREAKDOWN ---
        const pvByType = {};
        const typeNames = ['tts', 'reliability', 'voc', 'safety', 'env', 'active'];
        for (const t of typeNames) {
            pvByType[t] = 0;
            for (let y = 0; y < totalYears; y++) {
                pvByType[t] += annualBenefitsByType[t][y] * discountFactor(dr, y);
            }
        }

        // --- SENSITIVITY: DISCOUNT RATES ---
        const sensitivityDR = {};
        for (const r of [3, 4, 5, 7, 10, 12]) {
            let sPVB = 0, sPVC = 0;
            for (let y = 0; y < totalYears; y++) {
                const df = discountFactor(r, y);
                sPVB += annualBenefits[y] * df;
                sPVC += annualCosts[y] * df;
            }
            sensitivityDR[r] = {
                pvb: sPVB,
                pvc: sPVC,
                npv: sPVB - sPVC,
                bcr: sPVC > 0 ? sPVB / sPVC : 0
            };
        }

        // --- SWITCHING VALUES ---
        // What % change in each parameter would make BCR = 1.0?
        const switchingValues = {};
        if (pvBenefits > 0 && pvCosts > 0) {
            // Benefits need to decrease by:
            const benefitSwitch = ((pvBenefits - pvCosts) / pvBenefits) * 100;
            switchingValues.totalBenefits = -benefitSwitch;
            // Costs need to increase by:
            const costSwitch = ((pvBenefits - pvCosts) / pvCosts) * 100;
            switchingValues.totalCosts = costSwitch;

            // Per benefit type
            for (const t of typeNames) {
                if (pvByType[t] > 0) {
                    const sv = ((pvBenefits - pvCosts) / pvByType[t]) * 100;
                    switchingValues[t] = -sv;
                }
            }
        }

        // --- SCENARIO SENSITIVITY ---
        const scenarios = {};
        const scenarioFactors = { 'Low (-20%)': 0.8, 'Central': 1.0, 'High (+20%)': 1.2 };
        for (const [label, factor] of Object.entries(scenarioFactors)) {
            let sPVB = 0, sPVC = 0;
            for (let y = 0; y < totalYears; y++) {
                const df = discountFactor(dr, y);
                sPVB += annualBenefits[y] * factor * df;
                sPVC += annualCosts[y] * df;
            }
            scenarios[label] = { pvb: sPVB, pvc: sPVC, npv: sPVB - sPVC, bcr: sPVC > 0 ? sPVB / sPVC : 0 };
        }

        lastResults = {
            npv, bcr, pvBenefits, pvCosts, fyrr, paybackYear,
            totalCapitalUndiscounted,
            annualCosts, annualBenefits, annualNet,
            discountedCosts, discountedBenefits, discountedNet,
            cumulativeDiscNet,
            pvByType, sensitivityDR, switchingValues, scenarios,
            constYears, evalPeriod, totalYears, dr,
            annualBenefitsByType,
            firstYearBenefits: {
                tts: annualTTSBenefit, reliability: annualReliability,
                voc: annualVOCBenefit, safety: annualSafety,
                env: annualEnvironmental, active: annualActiveTransport,
                total: totalFirstYearBenefit
            }
        };

        updateKPIs();
        if (typeof Charts !== 'undefined') Charts.updateAll(lastResults);
        updateSensitivityTable();

        return lastResults;
    }

    // =========================================================================
    // UI UPDATES
    // =========================================================================

    function updateKPIs() {
        const r = lastResults;
        if (!r) return;

        const npvEl = document.getElementById('kpiNPV');
        npvEl.textContent = formatM(r.npv);
        npvEl.className = 'kpi-value ' + (r.npv >= 0 ? 'positive' : 'negative');

        const bcrEl = document.getElementById('kpiBCR');
        bcrEl.textContent = r.bcr.toFixed(2);
        bcrEl.className = 'kpi-value ' + (r.bcr >= 1 ? 'positive' : 'negative');

        document.getElementById('kpiPVB').textContent = formatM(r.pvBenefits);
        document.getElementById('kpiPVC').textContent = formatM(r.pvCosts);
        document.getElementById('kpiFYRR').textContent = r.fyrr.toFixed(1) + '%';
        document.getElementById('kpiPayback').textContent = r.paybackYear ? r.paybackYear + ' years' : 'N/A';
    }

    function updateSensitivityTable() {
        const r = lastResults;
        if (!r) return;
        const wrap = document.getElementById('sensitivityTable');

        let html = '<table><tr><th>Scenario</th><th>PV Benefits ($M)</th><th>PV Costs ($M)</th><th>NPV ($M)</th><th>BCR</th></tr>';

        // Discount rate scenarios
        for (const [rate, vals] of Object.entries(r.sensitivityDR)) {
            const bcrClass = vals.bcr >= 1 ? 'bcr-pass' : 'bcr-fail';
            const highlight = parseFloat(rate) === r.dr ? ' style="background:#e8f0fe;font-weight:700"' : '';
            html += `<tr${highlight}>
                <td>Discount Rate ${rate}%</td>
                <td>${vals.pvb.toFixed(1)}</td>
                <td>${vals.pvc.toFixed(1)}</td>
                <td>${vals.npv.toFixed(1)}</td>
                <td class="${bcrClass}">${vals.bcr.toFixed(2)}</td>
            </tr>`;
        }

        // Demand scenarios
        for (const [label, vals] of Object.entries(r.scenarios)) {
            const bcrClass = vals.bcr >= 1 ? 'bcr-pass' : 'bcr-fail';
            const highlight = label === 'Central' ? ' style="background:#e8f0fe;font-weight:700"' : '';
            html += `<tr${highlight}>
                <td>Demand ${label}</td>
                <td>${vals.pvb.toFixed(1)}</td>
                <td>${vals.pvc.toFixed(1)}</td>
                <td>${vals.npv.toFixed(1)}</td>
                <td class="${bcrClass}">${vals.bcr.toFixed(2)}</td>
            </tr>`;
        }

        html += '</table>';
        wrap.innerHTML = html;
    }

    // =========================================================================
    // CSV EXPORT
    // =========================================================================

    function exportCSV() {
        const r = lastResults;
        if (!r) { alert('Run calculation first'); return; }

        let csv = 'Transport CBA Dashboard Export\n';
        csv += 'Project,' + (document.getElementById('projectName').value) + '\n';
        csv += 'Discount Rate,' + r.dr + '%\n';
        csv += 'NPV ($M),' + r.npv.toFixed(2) + '\n';
        csv += 'BCR,' + r.bcr.toFixed(3) + '\n';
        csv += 'PV Benefits ($M),' + r.pvBenefits.toFixed(2) + '\n';
        csv += 'PV Costs ($M),' + r.pvCosts.toFixed(2) + '\n\n';

        csv += 'PV Benefits by Category\n';
        csv += 'Travel Time Savings,' + r.pvByType.tts.toFixed(2) + '\n';
        csv += 'Reliability,' + r.pvByType.reliability.toFixed(2) + '\n';
        csv += 'Vehicle Operating Costs,' + r.pvByType.voc.toFixed(2) + '\n';
        csv += 'Safety,' + r.pvByType.safety.toFixed(2) + '\n';
        csv += 'Environmental,' + r.pvByType.env.toFixed(2) + '\n';
        csv += 'Active Transport,' + r.pvByType.active.toFixed(2) + '\n\n';

        csv += 'Year,Undiscounted Cost ($M),Undiscounted Benefit ($M),Undiscounted Net ($M),Discounted Cost ($M),Discounted Benefit ($M),Discounted Net ($M),Cumulative Disc Net ($M)\n';
        for (let y = 0; y < r.totalYears; y++) {
            csv += `${y + 1},${r.annualCosts[y].toFixed(3)},${r.annualBenefits[y].toFixed(3)},${r.annualNet[y].toFixed(3)},${r.discountedCosts[y].toFixed(3)},${r.discountedBenefits[y].toFixed(3)},${r.discountedNet[y].toFixed(3)},${r.cumulativeDiscNet[y].toFixed(3)}\n`;
        }

        const blob = new Blob([csv], { type: 'text/csv' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'cba-results.csv';
        a.click();
        URL.revokeObjectURL(url);
    }

    // =========================================================================
    // PUBLIC API
    // =========================================================================

    return {
        PARAMS,
        calculate,
        exportCSV,
        getResults: () => lastResults,
        formatM
    };

})();
