'use strict';
const { fetchRow } = require('./repo');
async function loadName(id) {
  const row = await fetchRow(id);
  return row.name.trim();
}
async function loadAll(ids) {
  const out = [];
  for (const id of ids) out.push(await loadName(id));
  return out;
}
module.exports = { loadAll };
