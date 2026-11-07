'use strict';
const svc = require('../services/userService');
function handleList(req) {
  const users = svc.listUsers();
  return { status: 200, body: users };
}
function handleGet(req) {
  const u = svc.getUser(Number(req.params.id));
  return u ? { status: 200, body: u } : { status: 404 };
}
module.exports = { handleList, handleGet };
