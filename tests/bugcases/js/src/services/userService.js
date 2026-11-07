'use strict';
const { formatUser } = require('../utils/format');
const DB = [
  { id: 1, createdAt: '2024-01-02', profile: { name: 'Ada Lovelace' } },
  { id: 2, createdAt: '2024-03-04', profile: { name: 'Alan Turing' } },
  { id: 3, createdAt: '2024-05-06' },
];
function listUsers() {
  return DB.map((u) => formatUser(u));
}
function getUser(id) {
  const u = DB.find((x) => x.id === id);
  return u ? formatUser(u) : null;
}
module.exports = { listUsers, getUser };
