/**
 * Application initialisation and parameter reference tables
 */
(function () {
    'use strict';

    // =========================================================================
    // RENDER PARAMETER REFERENCE TABLES
    // =========================================================================
    function renderParamTables() {
        const P = CBA.PARAMS;
        const container = document.getElementById('paramTables');
        let html = '';

        // --- VTTS Table ---
        html += `<table>
            <caption>Value of Travel Time Savings ($/person-hour, June 2024 prices)</caption>
            <tr><th>Trip Purpose</th><th>Urban</th><th>Rural</th></tr>
            <tr><td>Commute</td><td class="val">$${P.vtts.urban.commute.toFixed(2)}</td><td class="val">$${P.vtts.rural.commute.toFixed(2)}</td></tr>
            <tr><td>Business</td><td class="val">$${P.vtts.urban.business.toFixed(2)}</td><td class="val">$${P.vtts.rural.business.toFixed(2)}</td></tr>
            <tr><td>Other / Private</td><td class="val">$${P.vtts.urban.other.toFixed(2)}</td><td class="val">$${P.vtts.rural.other.toFixed(2)}</td></tr>
        </table>`;

        // --- VOC Table (Urban) ---
        html += `<table>
            <caption>Vehicle Operating Costs — Urban ($/vehicle-km, resource cost, June 2024 prices)</caption>
            <tr><th>Speed (km/h)</th><th>Car</th><th>LGV</th><th>Rigid Truck</th><th>Articulated Truck</th></tr>`;
        for (const speed of [40, 50, 60, 70, 80, 90, 100]) {
            html += `<tr>
                <td>${speed}</td>
                <td class="val">${P.voc.urban.car[speed]?.toFixed(3) || '–'}</td>
                <td class="val">${P.voc.urban.lgv[speed]?.toFixed(3) || '–'}</td>
                <td class="val">${P.voc.urban.rigid[speed]?.toFixed(3) || '–'}</td>
                <td class="val">${P.voc.urban.artic[speed]?.toFixed(3) || '–'}</td>
            </tr>`;
        }
        html += '</table>';

        // --- VOC Table (Rural) ---
        html += `<table>
            <caption>Vehicle Operating Costs — Rural ($/vehicle-km, resource cost, June 2024 prices)</caption>
            <tr><th>Speed (km/h)</th><th>Car</th><th>LGV</th><th>Rigid Truck</th><th>Articulated Truck</th></tr>`;
        for (const speed of [60, 80, 100, 110]) {
            html += `<tr>
                <td>${speed}</td>
                <td class="val">${P.voc.rural.car[speed]?.toFixed(3) || '–'}</td>
                <td class="val">${P.voc.rural.lgv[speed]?.toFixed(3) || '–'}</td>
                <td class="val">${P.voc.rural.rigid[speed]?.toFixed(3) || '–'}</td>
                <td class="val">${P.voc.rural.artic[speed]?.toFixed(3) || '–'}</td>
            </tr>`;
        }
        html += '</table>';

        // --- Crash Cost Table ---
        html += `<table>
            <caption>Crash Costs ($/crash, June 2024 prices)</caption>
            <tr><th>Severity</th><th>Cost per Crash</th></tr>
            <tr><td>Fatal</td><td class="val">$${(P.crashCosts.fatal / 1e6).toFixed(3)}M</td></tr>
            <tr><td>Serious Injury</td><td class="val">$${(P.crashCosts.serious / 1e3).toFixed(0)}K</td></tr>
            <tr><td>Moderate Injury</td><td class="val">$${(P.crashCosts.moderate / 1e3).toFixed(1)}K</td></tr>
            <tr><td>Minor Injury</td><td class="val">$${(P.crashCosts.minor / 1e3).toFixed(1)}K</td></tr>
            <tr><td>Property Damage Only</td><td class="val">$${(P.crashCosts.pdo / 1e3).toFixed(1)}K</td></tr>
        </table>`;

        // --- Environmental Externalities ---
        html += `<table>
            <caption>Environmental Externalities (June 2024 prices)</caption>
            <tr><th>Parameter</th><th>Urban</th><th>Rural</th></tr>
            <tr><td>CO₂ Social Cost ($/tonne)</td><td class="val" colspan="2">$${P.carbonPerTonne}</td></tr>
            <tr><td>Air Pollution — Car ($/veh-km)</td><td class="val">$${P.airPollution.urban.car.toFixed(3)}</td><td class="val">$${P.airPollution.rural.car.toFixed(3)}</td></tr>
            <tr><td>Air Pollution — Rigid Truck ($/veh-km)</td><td class="val">$${P.airPollution.urban.rigid.toFixed(3)}</td><td class="val">$${P.airPollution.rural.rigid.toFixed(3)}</td></tr>
            <tr><td>Noise — Car ($/veh-km)</td><td class="val">$${P.noise.urban.car.toFixed(3)}</td><td class="val">$${P.noise.rural.car.toFixed(3)}</td></tr>
            <tr><td>Noise — Heavy Vehicle ($/veh-km)</td><td class="val">$${P.noise.urban.rigid.toFixed(3)}</td><td class="val">$${P.noise.rural.rigid.toFixed(3)}</td></tr>
        </table>`;

        // --- Health Benefits ---
        html += `<table>
            <caption>Active Transport Health Benefits ($/person-km, June 2024 prices)</caption>
            <tr><th>Mode</th><th>Health Benefit</th></tr>
            <tr><td>Walking</td><td class="val">$${P.healthBenefits.walking.toFixed(2)}</td></tr>
            <tr><td>Cycling</td><td class="val">$${P.healthBenefits.cycling.toFixed(2)}</td></tr>
        </table>`;

        // --- Other Parameters ---
        html += `<table>
            <caption>Other Key Parameters</caption>
            <tr><th>Parameter</th><th>Value</th></tr>
            <tr><td>Value of Statistical Life (VSL)</td><td class="val">$${(P.vsl / 1e6).toFixed(1)}M</td></tr>
            <tr><td>Reliability Ratio (proportion of VTTS)</td><td class="val">${P.reliabilityRatio}</td></tr>
            <tr><td>Central Discount Rate</td><td class="val">7%</td></tr>
            <tr><td>Low Discount Rate (sensitivity)</td><td class="val">4%</td></tr>
            <tr><td>High Discount Rate (sensitivity)</td><td class="val">10%</td></tr>
            <tr><td>Working Days per Year</td><td class="val">${P.workingDaysPerYear}</td></tr>
        </table>`;

        // --- Traffic Composition ---
        html += `<table>
            <caption>Default Traffic Composition (%)</caption>
            <tr><th>Vehicle Type</th><th>Urban</th><th>Rural</th></tr>
            <tr><td>Car</td><td class="val">${(P.trafficComposition.urban.car * 100).toFixed(0)}%</td><td class="val">${(P.trafficComposition.rural.car * 100).toFixed(0)}%</td></tr>
            <tr><td>Light Commercial</td><td class="val">${(P.trafficComposition.urban.lgv * 100).toFixed(0)}%</td><td class="val">${(P.trafficComposition.rural.lgv * 100).toFixed(0)}%</td></tr>
            <tr><td>Rigid Truck</td><td class="val">${(P.trafficComposition.urban.rigid * 100).toFixed(0)}%</td><td class="val">${(P.trafficComposition.rural.rigid * 100).toFixed(0)}%</td></tr>
            <tr><td>Articulated Truck</td><td class="val">${(P.trafficComposition.urban.artic * 100).toFixed(0)}%</td><td class="val">${(P.trafficComposition.rural.artic * 100).toFixed(0)}%</td></tr>
        </table>`;

        container.innerHTML = html;
    }

    // =========================================================================
    // VALIDATE TRIP PURPOSE SPLITS
    // =========================================================================
    function validateTripSplits() {
        const pctCommute = parseFloat(document.getElementById('pctCommute').value) || 0;
        const pctBusiness = parseFloat(document.getElementById('pctBusiness').value) || 0;
        const total = pctCommute + pctBusiness;
        if (total > 100) {
            document.getElementById('pctBusiness').style.borderColor = '#c4262e';
            document.getElementById('pctCommute').style.borderColor = '#c4262e';
        } else {
            document.getElementById('pctBusiness').style.borderColor = '';
            document.getElementById('pctCommute').style.borderColor = '';
        }
    }

    // =========================================================================
    // INIT
    // =========================================================================
    document.addEventListener('DOMContentLoaded', () => {
        renderParamTables();

        // Add validation listeners
        document.getElementById('pctCommute').addEventListener('input', validateTripSplits);
        document.getElementById('pctBusiness').addEventListener('input', validateTripSplits);

        // Initial calculation
        CBA.calculate();
    });
})();
