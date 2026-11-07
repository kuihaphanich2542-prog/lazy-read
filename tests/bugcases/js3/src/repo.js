'use strict';
const rows = { 1: { id: 1, name: ' ada ' }, 2: { id: 2 } };
async function fetchRow(id) {
  return rows[id];
}
module.exports = { fetchRow };
