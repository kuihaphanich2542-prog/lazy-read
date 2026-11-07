'use strict';
const users = require('./routes/users');
function dispatch(req) {
  if (req.path === '/users') return users.handleList(req);
  return { status: 404 };
}
console.log(JSON.stringify(dispatch({ path: '/users' })));
