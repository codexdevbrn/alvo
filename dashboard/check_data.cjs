const fs = require('fs');
const data = JSON.parse(fs.readFileSync('c:/Users/bruno/OneDrive/Área de Trabalho/alvo/dashboard/src/data/summary.json', 'utf8'));

const monthly2025Indices = new Set();
data.monthly.forEach((m, i) => {
    if (m.year === 2025) monthly2025Indices.add(i);
});

console.log('2025 Monthly Indices:', monthly2025Indices);

const clientsIn2025 = new Set();
const rowsIn2025 = data.rows.filter(r => monthly2025Indices.has(r[0]));
rowsIn2025.forEach(r => clientsIn2025.add(r[2]));

console.log('Total rows in 2025:', rowsIn2025.length);
console.log('Total clients in 2025:', clientsIn2025.size);

// Get first 10 client names in 2025
const clientNames2025 = Array.from(clientsIn2025).slice(0, 10).map(id => data.maps.c[id]);
console.log('Sample clients in 2025:', clientNames2025);

const totalRev2025 = rowsIn2025.reduce((acc, r) => acc + r[6], 0);
console.log('Total Revenue 2025 from rows:', totalRev2025);
