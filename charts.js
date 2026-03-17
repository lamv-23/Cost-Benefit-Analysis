/**
 * Chart rendering for CBA Dashboard
 * Uses Chart.js 4.x
 */
const Charts = (() => {

    // Colour palette — professional, accessible
    const COLORS = {
        tts:         '#003d6b',
        reliability: '#0060a9',
        voc:         '#2196F3',
        safety:      '#e35205',
        env:         '#0a7b3e',
        active:      '#8e44ad',
        cost:        '#c4262e',
        benefit:     '#0a7b3e',
        net:         '#003d6b',
        neutral:     '#78909c',
        gridLine:    '#e0e0e0',
        cumPos:      'rgba(10,123,62,0.15)',
        cumNeg:      'rgba(196,38,46,0.15)',
    };

    const TYPE_LABELS = {
        tts: 'Travel Time Savings',
        reliability: 'Reliability',
        voc: 'Vehicle Operating Costs',
        safety: 'Safety',
        env: 'Environmental',
        active: 'Active Transport'
    };

    const TYPE_COLORS = [
        COLORS.tts, COLORS.reliability, COLORS.voc,
        COLORS.safety, COLORS.env, COLORS.active
    ];

    // Chart instances
    let chartPie = null;
    let chartWaterfall = null;
    let chartCashflow = null;
    let chartCumulative = null;
    let chartSensDiscount = null;
    let chartSwitching = null;

    // Common options
    const FONT = { family: "'Segoe UI', -apple-system, sans-serif" };

    function defaultOpts(title) {
        return {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                title: { display: false },
                legend: { labels: { font: { ...FONT, size: 11 }, boxWidth: 12, padding: 10 } },
                datalabels: { display: false }
            },
            scales: {}
        };
    }

    // =========================================================================
    // BENEFIT COMPOSITION PIE
    // =========================================================================
    function renderPie(r) {
        const ctx = document.getElementById('chartBenefitPie').getContext('2d');
        const types = ['tts', 'reliability', 'voc', 'safety', 'env', 'active'];
        const data = types.map(t => Math.max(0, r.pvByType[t]));
        const labels = types.map(t => TYPE_LABELS[t]);
        const hasData = data.some(v => v > 0);

        if (chartPie) chartPie.destroy();
        chartPie = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels,
                datasets: [{
                    data: hasData ? data : [1],
                    backgroundColor: hasData ? TYPE_COLORS : ['#e0e0e0'],
                    borderWidth: 2,
                    borderColor: '#fff'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '45%',
                plugins: {
                    legend: {
                        position: 'right',
                        labels: { font: { ...FONT, size: 11 }, boxWidth: 12, padding: 8, generateLabels(chart) {
                            const ds = chart.data.datasets[0];
                            return chart.data.labels.map((l, i) => ({
                                text: `${l}: $${ds.data[i].toFixed(1)}M`,
                                fillStyle: ds.backgroundColor[i],
                                strokeStyle: '#fff',
                                lineWidth: 1,
                                hidden: false,
                                index: i
                            }));
                        }}
                    },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `${ctx.label}: $${ctx.parsed.toFixed(1)}M`
                        }
                    },
                    datalabels: {
                        display: hasData,
                        color: '#fff',
                        font: { weight: 'bold', size: 11 },
                        formatter: (v, ctx) => {
                            const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                            const pct = total > 0 ? (v / total * 100) : 0;
                            return pct >= 5 ? pct.toFixed(0) + '%' : '';
                        }
                    }
                }
            },
            plugins: [ChartDataLabels]
        });
    }

    // =========================================================================
    // NPV WATERFALL
    // =========================================================================
    function renderWaterfall(r) {
        const ctx = document.getElementById('chartWaterfall').getContext('2d');
        const types = ['tts', 'reliability', 'voc', 'safety', 'env', 'active'];
        const labels = types.map(t => TYPE_LABELS[t]).concat(['Total Benefits', 'Total Costs', 'NPV']);
        const pvValues = types.map(t => r.pvByType[t]);
        const totalBen = pvValues.reduce((a, b) => a + b, 0);

        // Build waterfall data: floating bars
        const barData = [];
        const bgColors = [];
        let running = 0;

        for (let i = 0; i < pvValues.length; i++) {
            barData.push([running, running + pvValues[i]]);
            bgColors.push(TYPE_COLORS[i]);
            running += pvValues[i];
        }
        // Total benefits
        barData.push([0, totalBen]);
        bgColors.push(COLORS.benefit);
        // Total costs (negative direction from total benefits)
        barData.push([totalBen, totalBen - r.pvCosts]);
        bgColors.push(COLORS.cost);
        // NPV
        barData.push([0, r.npv]);
        bgColors.push(r.npv >= 0 ? COLORS.benefit : COLORS.cost);

        if (chartWaterfall) chartWaterfall.destroy();
        chartWaterfall = new Chart(ctx, {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    data: barData,
                    backgroundColor: bgColors,
                    borderColor: bgColors.map(c => c),
                    borderWidth: 1,
                    borderSkipped: false
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => {
                                const v = ctx.raw;
                                const val = Array.isArray(v) ? (v[1] - v[0]) : v;
                                return `$${val.toFixed(1)}M`;
                            }
                        }
                    },
                    datalabels: {
                        display: true,
                        anchor: 'end',
                        align: 'top',
                        color: '#333',
                        font: { size: 10, weight: 'bold', ...FONT },
                        formatter: (v) => {
                            const val = Array.isArray(v) ? (v[1] - v[0]) : v;
                            return '$' + val.toFixed(0) + 'M';
                        }
                    }
                },
                scales: {
                    x: {
                        ticks: { font: { size: 9, ...FONT }, maxRotation: 45, minRotation: 30 },
                        grid: { display: false }
                    },
                    y: {
                        title: { display: true, text: '$M (PV)', font: { size: 11, ...FONT } },
                        grid: { color: COLORS.gridLine },
                        ticks: { font: { size: 10, ...FONT } }
                    }
                }
            },
            plugins: [ChartDataLabels]
        });
    }

    // =========================================================================
    // ANNUAL CASHFLOW
    // =========================================================================
    function renderCashflow(r) {
        const ctx = document.getElementById('chartCashflow').getContext('2d');
        const labels = Array.from({ length: r.totalYears }, (_, i) => `Y${i + 1}`);

        if (chartCashflow) chartCashflow.destroy();
        chartCashflow = new Chart(ctx, {
            type: 'bar',
            data: {
                labels,
                datasets: [
                    {
                        label: 'Benefits',
                        data: r.annualBenefits,
                        backgroundColor: 'rgba(10,123,62,0.7)',
                        borderColor: COLORS.benefit,
                        borderWidth: 1,
                        order: 2
                    },
                    {
                        label: 'Costs',
                        data: r.annualCosts.map(c => -c),
                        backgroundColor: 'rgba(196,38,46,0.7)',
                        borderColor: COLORS.cost,
                        borderWidth: 1,
                        order: 2
                    },
                    {
                        label: 'Net',
                        data: r.annualNet,
                        type: 'line',
                        borderColor: COLORS.net,
                        backgroundColor: 'transparent',
                        borderWidth: 2,
                        pointRadius: 0,
                        tension: 0.3,
                        order: 1
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { position: 'top', labels: { font: { ...FONT, size: 11 }, boxWidth: 12 } },
                    tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: $${ctx.parsed.y.toFixed(1)}M` } },
                    datalabels: { display: false }
                },
                scales: {
                    x: {
                        stacked: true,
                        ticks: { font: { size: 9, ...FONT }, maxTicksLimit: 15 },
                        grid: { display: false }
                    },
                    y: {
                        title: { display: true, text: '$M (undiscounted)', font: { size: 11, ...FONT } },
                        grid: { color: COLORS.gridLine },
                        ticks: { font: { size: 10, ...FONT } }
                    }
                }
            }
        });
    }

    // =========================================================================
    // CUMULATIVE DISCOUNTED NET BENEFITS
    // =========================================================================
    function renderCumulative(r) {
        const ctx = document.getElementById('chartCumulative').getContext('2d');
        const labels = Array.from({ length: r.totalYears }, (_, i) => `Y${i + 1}`);

        if (chartCumulative) chartCumulative.destroy();
        chartCumulative = new Chart(ctx, {
            type: 'line',
            data: {
                labels,
                datasets: [{
                    label: 'Cumulative NPV',
                    data: r.cumulativeDiscNet,
                    borderColor: COLORS.net,
                    backgroundColor: (ctx) => {
                        if (!ctx.chart.chartArea) return COLORS.cumPos;
                        const { top, bottom } = ctx.chart.chartArea;
                        const gradient = ctx.chart.ctx.createLinearGradient(0, top, 0, bottom);
                        gradient.addColorStop(0, COLORS.cumPos);
                        gradient.addColorStop(0.5, 'rgba(0,0,0,0)');
                        gradient.addColorStop(1, COLORS.cumNeg);
                        return gradient;
                    },
                    fill: true,
                    borderWidth: 2.5,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    tension: 0.3
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: (ctx) => `Cumulative NPV: $${ctx.parsed.y.toFixed(1)}M` } },
                    datalabels: { display: false },
                    annotation: undefined
                },
                scales: {
                    x: {
                        ticks: { font: { size: 9, ...FONT }, maxTicksLimit: 15 },
                        grid: { display: false }
                    },
                    y: {
                        title: { display: true, text: '$M (PV)', font: { size: 11, ...FONT } },
                        grid: { color: COLORS.gridLine },
                        ticks: { font: { size: 10, ...FONT } }
                    }
                }
            }
        });
    }

    // =========================================================================
    // DISCOUNT RATE SENSITIVITY
    // =========================================================================
    function renderSensDiscount(r) {
        const ctx = document.getElementById('chartSensDiscount').getContext('2d');
        const rates = Object.keys(r.sensitivityDR).map(Number);
        const bcrs = rates.map(rate => r.sensitivityDR[rate].bcr);

        if (chartSensDiscount) chartSensDiscount.destroy();
        chartSensDiscount = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: rates.map(r => r + '%'),
                datasets: [{
                    label: 'BCR',
                    data: bcrs,
                    backgroundColor: bcrs.map(b => b >= 1 ? 'rgba(10,123,62,0.75)' : 'rgba(196,38,46,0.75)'),
                    borderColor: bcrs.map(b => b >= 1 ? COLORS.benefit : COLORS.cost),
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: (ctx) => `BCR: ${ctx.parsed.y.toFixed(2)}` } },
                    datalabels: {
                        display: true,
                        anchor: 'end',
                        align: 'top',
                        color: '#333',
                        font: { size: 11, weight: 'bold', ...FONT },
                        formatter: (v) => v.toFixed(2)
                    }
                },
                scales: {
                    x: {
                        title: { display: true, text: 'Discount Rate', font: { size: 11, ...FONT } },
                        grid: { display: false },
                        ticks: { font: { size: 11, ...FONT } }
                    },
                    y: {
                        title: { display: true, text: 'BCR', font: { size: 11, ...FONT } },
                        grid: { color: COLORS.gridLine },
                        ticks: { font: { size: 10, ...FONT } },
                        suggestedMin: 0
                    }
                }
            },
            plugins: [ChartDataLabels]
        });
    }

    // =========================================================================
    // SWITCHING VALUES
    // =========================================================================
    function renderSwitching(r) {
        const ctx = document.getElementById('chartSwitching').getContext('2d');
        const keys = ['totalBenefits', 'totalCosts', 'tts', 'voc', 'safety', 'env'];
        const labels = ['Total Benefits', 'Total Costs', 'Travel Time', 'VOC', 'Safety', 'Environmental'];
        const values = keys.map(k => r.switchingValues[k] || 0);

        if (chartSwitching) chartSwitching.destroy();
        chartSwitching = new Chart(ctx, {
            type: 'bar',
            data: {
                labels,
                datasets: [{
                    label: '% Change for BCR=1',
                    data: values,
                    backgroundColor: values.map(v => v < 0 ? 'rgba(196,38,46,0.7)' : 'rgba(10,123,62,0.7)'),
                    borderColor: values.map(v => v < 0 ? COLORS.cost : COLORS.benefit),
                    borderWidth: 1
                }]
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: (ctx) => `${ctx.parsed.x >= 0 ? '+' : ''}${ctx.parsed.x.toFixed(1)}%` } },
                    datalabels: {
                        display: true,
                        anchor: (ctx) => ctx.dataset.data[ctx.dataIndex] >= 0 ? 'end' : 'start',
                        align: (ctx) => ctx.dataset.data[ctx.dataIndex] >= 0 ? 'right' : 'left',
                        color: '#333',
                        font: { size: 10, weight: 'bold', ...FONT },
                        formatter: (v) => `${v >= 0 ? '+' : ''}${v.toFixed(0)}%`
                    }
                },
                scales: {
                    x: {
                        title: { display: true, text: '% Change Required', font: { size: 11, ...FONT } },
                        grid: { color: COLORS.gridLine },
                        ticks: { font: { size: 10, ...FONT }, callback: (v) => v + '%' }
                    },
                    y: {
                        grid: { display: false },
                        ticks: { font: { size: 10, ...FONT } }
                    }
                }
            },
            plugins: [ChartDataLabels]
        });
    }

    // =========================================================================
    // UPDATE ALL
    // =========================================================================
    function updateAll(r) {
        renderPie(r);
        renderWaterfall(r);
        renderCashflow(r);
        renderCumulative(r);
        renderSensDiscount(r);
        renderSwitching(r);
    }

    return { updateAll, COLORS, TYPE_LABELS };
})();
