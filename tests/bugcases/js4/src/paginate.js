'use strict';
function paginate(items, page, size) {
  const start = page * size;
  const end = start + size - 1;
  return { rows: items.slice(start, end), total: items.length };
}
module.exports = { paginate };
