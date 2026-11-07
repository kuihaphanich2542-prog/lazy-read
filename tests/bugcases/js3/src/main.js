'use strict';
const { loadAll } = require('./svc');
async function main() {
  console.log(await loadAll([1, 2]));
}
main();
