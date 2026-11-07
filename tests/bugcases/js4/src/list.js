'use strict';
function last(a, n) { return a.slice(-n); }
function copy(a) { return a.slice(); }
function drop(a, n) { return a.slice(n); }
module.exports = { last, copy, drop };
